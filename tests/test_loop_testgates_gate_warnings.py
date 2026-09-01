"""Gate warnings on non-finished outcomes (#480).

The affected-tests and test-integrity gates already run — and record their
report on the artifact — REGARDLESS of the loop's exit outcome; only the
bounded fix-turn is gated on a clean finish. But a FAILED report never
carried a ``TaskResult.warnings`` entry when the outcome wasn't
``_EXIT_FINISHED`` (colleague#480 / run ``cc5d1f1a2c5f``): the operator saw
zero fix turns and an empty ``warnings`` list, and never learned the branch
was broken.

This module asserts the fix at the loop level via ``run()`` with a scripted
``complete`` that never calls ``finish`` (forcing budget exhaustion,
``_EXIT_BUDGET`` / ``INCOMPLETE``):

* a failing affected-tests report on a non-finished outcome carries a
  ``{'kind': 'affected-tests-failed', ...}`` warning naming the selection;
* the test-integrity gate's identical pattern (``loop_testgates.py``:197)
  gets the analogous ``test-integrity-flagged`` warning;
* a passing/disabled gate on the same outcome shape is byte-identical (no
  such warning);
* a CLEAN finish (``_EXIT_FINISHED``) is unaffected either way — the
  existing fix-turn behaviour owns that path, never this warning.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from colleague.contract import INCOMPLETE, OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run

needs_pytest = pytest.mark.skipif(
    shutil.which("pytest") is None, reason="pytest not on PATH for the subprocess gate"
)


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _write(path: str, content: str) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall("w", "write_file", {"path": path, "content": content})]
    )


def _finish(summary: str) -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _seed_lazy_chain_repo(repo: Path) -> None:
    """A repo where tests/test_via_hub.py reaches pkg/impl.py ONLY via a depth-3
    lazy chain, and the test PASSES iff pkg.impl.thing == 1 (test_loop_affected_
    tests_gate.py's fixture, reused verbatim)."""
    (repo / "conftest.py").write_text("", encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text(
        "def register():\n    from pkg.cmd import run\n    return run\n", encoding="utf-8"
    )
    (repo / "pkg" / "cmd.py").write_text(
        "from pkg.impl import thing\n\n\ndef run():\n    return thing\n", encoding="utf-8"
    )
    (repo / "pkg" / "impl.py").write_text("thing = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_via_hub.py").write_text(
        "from pkg import register\n\n\ndef test_it():\n    assert register()() == 1\n",
        encoding="utf-8",
    )


def _warning(result, kind: str) -> dict | None:
    return next((w for w in result.warnings if w.get("kind") == kind), None)


@needs_pytest
def test_affected_tests_failed_warns_on_budget_exhausted(tmp_path: Path) -> None:
    """A budget-exhausted run whose affected-tests gate reports failed carries the
    warning naming the selection (#480 AC1)."""
    _seed_lazy_chain_repo(tmp_path)
    result = run(
        # No `finish` call — the model just keeps editing until the budget runs out.
        scripted([_write("pkg/impl.py", "thing = 0\n")]),
        Task.new(str(tmp_path), "edit impl"),
        max_steps=2,
        context=ContextControls(affectedtests=True, affectedtests_fix_retries=0),
    )
    assert result.status == INCOMPLETE
    report = result.affected_tests_report
    assert report is not None and report.status == "failed"
    warning = _warning(result, "affected-tests-failed")
    assert warning is not None, "a failed report on a non-finished outcome must warn"
    assert "tests/test_via_hub.py" in warning["selection"]
    # printed once — the gate's stderr surface fires exactly once too, since no
    # fix-turn retry loop runs on a non-finished outcome.
    assert sum(1 for w in result.warnings if w.get("kind") == "affected-tests-failed") == 1


@needs_pytest
def test_affected_tests_passing_on_budget_exhausted_carries_no_warning(tmp_path: Path) -> None:
    """A passing gate on the same non-finished outcome is byte-identical (no
    ``affected-tests-failed`` warning)."""
    _seed_lazy_chain_repo(tmp_path)
    result = run(
        scripted([_write("unrelated.py", "y = 1\n")]),
        Task.new(str(tmp_path), "write unrelated"),
        max_steps=2,
        context=ContextControls(affectedtests=True, affectedtests_fix_retries=0),
    )
    assert result.status == INCOMPLETE
    assert result.affected_tests_report is None  # nothing affected → strict no-op
    assert _warning(result, "affected-tests-failed") is None


@needs_pytest
def test_affected_tests_disabled_on_budget_exhausted_carries_no_warning(tmp_path: Path) -> None:
    """The gate disabled entirely on the same non-finished outcome is untouched."""
    _seed_lazy_chain_repo(tmp_path)
    result = run(
        scripted([_write("pkg/impl.py", "thing = 0\n")]),
        Task.new(str(tmp_path), "edit impl"),
        max_steps=2,
    )
    assert result.status == INCOMPLETE
    assert result.affected_tests_report is None
    assert _warning(result, "affected-tests-failed") is None


@needs_pytest
def test_affected_tests_fix_turn_behaviour_unchanged_on_clean_finish(tmp_path: Path) -> None:
    """``_EXIT_FINISHED`` behaviour (fix turns) is unchanged: a clean finish never
    gets the new warning, whether or not the report still fails afterwards."""
    _seed_lazy_chain_repo(tmp_path)
    result = run(
        scripted(
            [
                _write("pkg/impl.py", "thing = 0\n"),
                _finish("changed impl"),
            ]
        ),
        Task.new(str(tmp_path), "edit impl"),
        max_steps=5,
        context=ContextControls(affectedtests=True, affectedtests_fix_retries=0),
    )
    assert result.status == OK
    report = result.affected_tests_report
    assert report is not None and report.status == "failed"
    assert _warning(result, "affected-tests-failed") is None


# --- test-integrity gate: the identical pattern (loop_testgates.py:197) -----

_MIRROR_TEST = 'import exc\n\n\ndef test_x():\n    raise exc.response_error("boom")\n'
_MIRROR_IMPL = 'import exc\n\n\ndef handle():\n    raise exc.response_error("boom")\n'


def test_test_integrity_flagged_warns_on_budget_exhausted(tmp_path: Path) -> None:
    """The test-integrity gate's identical silent-failure shape gets the analogous
    ``test-integrity-flagged`` warning on a non-finished outcome (#480 AC2)."""
    result = run(
        scripted(
            [
                _write("test_thing.py", _MIRROR_TEST),
                _write("thing.py", _MIRROR_IMPL),
                # No `finish` — the model keeps writing until the budget runs out.
                _write("other.py", "x = 1\n"),
            ]
        ),
        Task.new(str(tmp_path), "write a test and an impl"),
        max_steps=3,
    )
    assert result.status == INCOMPLETE
    report = result.test_integrity_report
    assert report is not None and report.findings
    warning = _warning(result, "test-integrity-flagged")
    assert warning is not None
    assert "response_error" in warning["symbols"]
    assert sum(1 for w in result.warnings if w.get("kind") == "test-integrity-flagged") == 1


def test_test_integrity_disabled_on_budget_exhausted_carries_no_warning(tmp_path: Path) -> None:
    result = run(
        scripted(
            [
                _write("test_thing.py", _MIRROR_TEST),
                _write("thing.py", _MIRROR_IMPL),
            ]
        ),
        Task.new(str(tmp_path), "write a test and an impl"),
        max_steps=2,
        context=ContextControls(testintegrity=False),
    )
    assert result.status == INCOMPLETE
    assert result.test_integrity_report is None
    assert _warning(result, "test-integrity-flagged") is None


def test_test_integrity_fix_turn_behaviour_unchanged_on_clean_finish(tmp_path: Path) -> None:
    """A clean finish never gets the new warning — the existing bounded
    re-examine-turn behaviour owns that path untouched."""
    result = run(
        scripted(
            [
                _write("test_thing.py", _MIRROR_TEST),
                _write("thing.py", _MIRROR_IMPL),
                _finish("wrote a test and impl"),
            ]
        ),
        Task.new(str(tmp_path), "write a test and an impl"),
        max_steps=6,
    )
    assert result.status == OK
    report = result.test_integrity_report
    assert report is not None and report.findings
    assert _warning(result, "test-integrity-flagged") is None

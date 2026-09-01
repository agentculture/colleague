"""Wire the importability-check gate into pre-finish on EVERY outcome (#482/t6, h4).

Row 67 (docs/live-testing.md, run cc5d1f1a2c5f) shipped a branch that did not
import on a BUDGET-EXHAUSTED (``INCOMPLETE``) outcome: a hallucinated
``from colleague.hooks import ... Policy`` (no ``Policy`` in that module) AND,
once removed, a lost ``ToolCall`` re-export breaking a downstream importer
(``colleague/engines/vllm_transport.py``). The affected-tests gate already ran
and reported ``failed`` — but the harness told no one, because a non-finished
outcome got neither a fix-turn nor (pre-#480) a warning.

This file proves the NEW ``colleague.importcheck`` gate (#482, module built in
t3) is actually wired into ``_run_pre_finish_gates`` and fires on every exit
shape alike — finished, budget-exhausted, and stalled — using a fixture that
reproduces the REAL cc5d1f1a2c5f defect pair (not synthetic stubs): a module
importing a nonexistent symbol, and a second, downstream module importing a
name whose re-export was dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.contract import INCOMPLETE, OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run


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


def _warning(result, kind: str) -> dict | None:
    return next((w for w in result.warnings if w.get("kind") == kind), None)


# ── the row-67 fixture: the REAL cc5d1f1a2c5f defect pair, not a stub ──
#
# ``module_a.py`` mirrors the hallucinated ``from colleague.hooks import
# HookConfig, Policy`` — ``Policy`` never existed in that module.
# ``module_b.py`` mirrors ``colleague/engines/vllm_transport.py``: a
# DOWNSTREAM importer broken by a lost ``ToolCall`` re-export.

_HOOKS_LIKE = "class HookConfig:\n    pass\n"  # Policy is NOT defined here
_MODULE_A = "from pkg.hooks_like import HookConfig, Policy\n"  # hallucinated symbol
_LOOP_LIKE = "class _ToolCall:\n    pass\n"  # ToolCall re-export lost
_MODULE_B = "from pkg.loop_like import ToolCall\n"  # downstream importer, broken


def _seed_row67_fixture_calls() -> list[ModelResponse]:
    return [
        _write("pkg/__init__.py", ""),
        _write("pkg/hooks_like.py", _HOOKS_LIKE),
        _write("pkg/module_a.py", _MODULE_A),
        _write("pkg/loop_like.py", _LOOP_LIKE),
        _write("pkg/module_b.py", _MODULE_B),
    ]


def test_row67_fixture_fails_on_budget_exhausted(tmp_path: Path) -> None:
    """The row-67 defect pair on a BUDGET-EXHAUSTED outcome (#482 AC2 / t6):
    the gate runs, reports failed, names BOTH modules and their ImportErrors,
    and the warning lands on ``TaskResult.warnings`` even though the loop
    never finished."""
    result = run(
        # No `finish` call — the model keeps writing until the budget runs out.
        scripted(_seed_row67_fixture_calls()),
        Task.new(str(tmp_path), "port hooks + loop into pkg"),
        max_steps=len(_seed_row67_fixture_calls()),
    )
    assert result.status == INCOMPLETE

    report = result.importcheck_report
    assert report is not None
    assert report.status == "failed"
    modules = {f.module for f in report.findings}
    assert "pkg.module_a" in modules
    assert "pkg.module_b" in modules
    errors = " ".join(f.error for f in report.findings)
    assert "Policy" in errors
    assert "ToolCall" in errors

    warning = _warning(result, "import-check-failed")
    assert warning is not None, "a failed import-check on ANY outcome must warn (h4)"
    warned_modules = {f["module"] for f in warning["findings"]}
    assert warned_modules == {"pkg.module_a", "pkg.module_b"}
    warned_errors = " ".join(f["error"] for f in warning["findings"])
    assert "Policy" in warned_errors
    assert "ToolCall" in warned_errors
    assert warning["count"] == 2


def test_row67_fixture_fails_on_finished(tmp_path: Path) -> None:
    """The SAME defect pair, but the model calls ``finish`` (a clean
    ``_EXIT_FINISHED`` outcome, ``status == OK``) — the gate still runs and
    still warns, because import-check has no bounded fix-turn to hide behind
    (t6 AC1: finished and budget-exhausted alike)."""
    calls = _seed_row67_fixture_calls() + [_finish("ported hooks + loop into pkg")]
    result = run(
        scripted(calls),
        Task.new(str(tmp_path), "port hooks + loop into pkg"),
        max_steps=len(calls),
    )
    assert result.status == OK

    report = result.importcheck_report
    assert report is not None
    assert report.status == "failed"
    modules = {f.module for f in report.findings}
    assert modules == {"pkg.module_a", "pkg.module_b"}

    warning = _warning(result, "import-check-failed")
    assert warning is not None, "a failed import-check on a clean finish must ALSO warn"
    assert warning["count"] == 2


def test_row67_fixture_fails_on_stalled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The SAME defect pair, but the loop exits via the step-stall watchdog
    (#400, ``_EXIT_STALLED``) rather than budget exhaustion or a finish — the
    gate still runs over the files written before the stall (t6 AC1)."""
    import time

    from colleague import stallguard

    monkeypatch.setenv("COLLEAGUE_MAX_STEP_STALL", "0.3")
    seed = _seed_row67_fixture_calls()
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = state["i"]
        state["i"] += 1
        if i < len(seed):
            return seed[i]
        # Every fixture file is already written; now stall forever.
        while True:
            time.sleep(0.02)
            stallguard.check()

    result = run(
        complete,
        Task.new(str(tmp_path), "port hooks + loop into pkg"),
        max_steps=len(seed) + 5,
    )
    assert result.status == INCOMPLETE
    assert any(w.get("kind") == "step-stall" for w in result.warnings)

    report = result.importcheck_report
    assert report is not None
    assert report.status == "failed"
    modules = {f.module for f in report.findings}
    assert modules == {"pkg.module_a", "pkg.module_b"}

    warning = _warning(result, "import-check-failed")
    assert warning is not None
    assert warning["count"] == 2


def test_clean_import_records_passed_report_without_warning(tmp_path: Path) -> None:
    """A passing import-check still records ``importcheck_report`` (mirroring
    ``lint_report``/``coherence_report`` — a clean run is visible on the
    artifact), but carries no ``import-check-failed`` warning."""
    calls = [
        _write("pkg/__init__.py", ""),
        _write("pkg/ok.py", "value = 42\n"),
        _finish("wrote a clean module"),
    ]
    result = run(
        scripted(calls),
        Task.new(str(tmp_path), "write a clean module"),
        max_steps=len(calls),
    )
    assert result.status == OK
    report = result.importcheck_report
    assert report is not None
    assert report.status == "passed"
    assert _warning(result, "import-check-failed") is None


def test_off_knob_carries_no_report_and_no_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``COLLEAGUE_IMPORT_CHECK=0`` is a strict no-op: no report, no warning —
    byte-identical to a pre-t6 artifact."""
    monkeypatch.setenv("COLLEAGUE_IMPORT_CHECK", "0")
    result = run(
        scripted(_seed_row67_fixture_calls()),
        Task.new(str(tmp_path), "port hooks + loop into pkg"),
        max_steps=len(_seed_row67_fixture_calls()),
        context=ContextControls(),
    )
    assert result.status == INCOMPLETE
    assert result.importcheck_report is None
    assert _warning(result, "import-check-failed") is None


def test_aborted_run_carries_no_report_and_no_warning(tmp_path: Path) -> None:
    """The gate is skipped entirely on an aborted run — best-effort wrapped,
    same guard shape as the other pre-finish gates. An aborted run raises
    ``WorkAborted`` carrying the populated partial result (#37)."""
    from colleague.loop_wire import WorkAborted

    def raising(_messages: list[dict]) -> ModelResponse:
        raise RuntimeError("engine blew up")

    task = Task.new(str(tmp_path), "port hooks + loop into pkg")
    with pytest.raises(WorkAborted) as excinfo:
        run(raising, task, max_steps=3)
    result = excinfo.value.result
    assert result.importcheck_report is None
    assert _warning(result, "import-check-failed") is None

"""Affected-tests gate wired into the loop (#213, task t8) — the regression proof.

Reproduces the #210/t2 shape at the LOOP level: a scoped edit to a module breaks
a sibling test that reaches it ONLY via a depth-3 *lazy* import chain
(``test_via_hub → pkg → (lazy) pkg.cmd → pkg.impl``). The changed-files-scoped
gates (lint #200, test-integrity #203) never run that sibling test; the
affected-tests gate does, so the regression is surfaced before handoff.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from colleague.affectedtests import select_affected_tests
from colleague.contract import OK, Task
from colleague.lint import run_lint_gate
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run
from colleague.testintegrity import detect_mirror

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
    lazy chain, and the test PASSES iff pkg.impl.thing == 1."""
    (repo / "conftest.py").write_text("", encoding="utf-8")  # put repo root on sys.path
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


def test_disabled_is_strict_noop(tmp_path: Path) -> None:
    """Default run() (no ContextControls.affectedtests) never touches the report."""
    _seed_lazy_chain_repo(tmp_path)
    result = run(
        scripted([_write("pkg/impl.py", "thing = 0\n"), _finish("done")]),
        Task.new(str(tmp_path), "edit impl"),
        max_steps=5,
    )
    assert result.status == OK
    assert result.affected_tests_report is None
    assert "affected_tests_report" not in result.to_dict()


def test_noop_when_nothing_affected(tmp_path: Path) -> None:
    """Gate enabled but the changed file has no affected test → report None."""
    _seed_lazy_chain_repo(tmp_path)
    result = run(
        scripted([_write("unrelated.py", "y = 2\n"), _finish("done")]),
        Task.new(str(tmp_path), "write unrelated"),
        max_steps=5,
        context=ContextControls(affectedtests=True),
    )
    assert result.affected_tests_report is None


@needs_pytest
def test_transitive_regression_is_surfaced(tmp_path: Path) -> None:
    """THE #210/t2 PROOF: a scoped edit to pkg/impl.py breaks tests/test_via_hub.py
    (reachable only via the depth-3 lazy chain); the gate selects + fails it."""
    _seed_lazy_chain_repo(tmp_path)
    # The model edits ONLY impl.py — it never runs tests/test_via_hub.py.
    result = run(
        scripted([_write("pkg/impl.py", "thing = 0\n"), _finish("changed impl")]),
        Task.new(str(tmp_path), "edit impl"),
        max_steps=5,
        context=ContextControls(affectedtests=True, affectedtests_fix_retries=0),
    )
    report = result.affected_tests_report
    assert report is not None, "the gate must run when impl.py changed"
    assert (
        "tests/test_via_hub.py" in report.selected
    ), "the transitive sibling test must be selected"
    assert report.status == "failed"
    assert report.failed and report.failed >= 1
    # The gate is non-blocking: the work item still finished OK with its own summary.
    assert result.status == OK
    assert result.summary == "changed impl"
    assert result.to_dict()["affected_tests_report"]["status"] == "failed"


def test_changed_files_scoped_gates_never_see_the_sibling(tmp_path: Path) -> None:
    """The gap #213 closes: with ONLY pkg/impl.py changed, neither the lint gate nor
    the test-integrity gate looks at tests/test_via_hub.py — but the affected-tests
    selection does (it is the only cross-file gate)."""
    _seed_lazy_chain_repo(tmp_path)
    (tmp_path / "pkg" / "impl.py").write_text("thing = 0\n", encoding="utf-8")
    changed = ["pkg/impl.py"]

    # affected-tests: selects the cross-file sibling.
    selected, _, _ = select_affected_tests(tmp_path, changed, depth=3)
    assert "tests/test_via_hub.py" in selected

    # lint gate: scoped to the changed .py files only (no test execution, no sibling).
    lint = run_lint_gate(str(tmp_path), changed)
    assert lint is None  # no linter configured here → strict no-op

    # test-integrity: scans only the changed files for a mirror signature.
    ti = detect_mirror(str(tmp_path), changed)
    assert not any("test_via_hub" in (f.test_file or "") for f in ti.findings)

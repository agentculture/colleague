"""The PR a run just opened is one glance away (#169).

``Ledger.pr_url`` is reconciled verbatim from ``TaskResult.pr_url`` (never
synthesized), the Last-run panel gains a PR row ONLY when one exists, and the
post-run session line appends it. A local-only run renders exactly the
pre-#169 output — pinned.
"""

from __future__ import annotations

from pathlib import Path

from colleague.cli._commands.session import SessionIO, _Session
from colleague.cockpit_run import Ledger, RunState, observed_ledger, reconcile
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult


def _make_session(repo: Path, work_result: TaskResult) -> tuple[_Session, list[str]]:
    logged: list[str] = []

    def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
        return (work_result, repo / "a.json")

    s = _Session(
        repo=repo,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(model="m"),
        json_mode=False,
        view="markdown",
        io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
        work_fn=_work_fn,
    )
    original_log = s._log

    def _spy_log(text: str) -> None:
        logged.append(str(text))
        original_log(text)

    s._log = _spy_log  # type: ignore[method-assign]
    return s, logged


def _last_run_panel(s: _Session):
    return next(p for p in s.state.panels if "Last run" in p.title)


def test_reconcile_carries_the_real_pr_url() -> None:
    result = TaskResult(
        task_id="x", status=OK, summary="done", branch="colleague/x", pr_url="https://pr/1"
    )
    led = reconcile(result)
    assert led.pr_url == "https://pr/1"
    assert led.publish_state == "pr"


def test_reconcile_local_only_run_has_no_pr_url() -> None:
    led = reconcile(TaskResult(task_id="x", status=OK, summary="done", branch="colleague/x"))
    assert led.pr_url is None
    assert led.publish_state == "local"


def test_observed_ledger_never_claims_a_pr() -> None:
    assert observed_ledger(RunState()).pr_url is None


def test_ledger_default_keeps_old_constructor_shape() -> None:
    led = Ledger(files_changed=1, commands_run=2, commits=None, publish_state="")
    assert led.pr_url is None


def test_last_run_panel_shows_pr_only_when_present(tmp_path: Path) -> None:
    result = TaskResult(
        task_id="x", status=OK, summary="done", branch="colleague/x", pr_url="https://pr/2"
    )
    s, _ = _make_session(tmp_path, result)
    s._run_work(Task.new(str(tmp_path), "do it"), None)
    panel = _last_run_panel(s)
    pr_item = next(i for i in panel.items if i.id == "last.pr")
    assert pr_item.status == "https://pr/2"


def test_last_run_panel_local_only_renders_exactly_four_items(tmp_path: Path) -> None:
    result = TaskResult(task_id="x", status=OK, summary="done", branch="colleague/x")
    s, _ = _make_session(tmp_path, result)
    s._run_work(Task.new(str(tmp_path), "do it"), None)
    panel = _last_run_panel(s)
    assert [i.id for i in panel.items] == [
        "last.files",
        "last.commands",
        "last.commits",
        "last.publish",
    ]


def test_post_run_line_appends_the_pr_link(tmp_path: Path) -> None:
    result = TaskResult(task_id="x", status=OK, summary="done", pr_url="https://pr/3")
    s, logged = _make_session(tmp_path, result)
    s._run_work(Task.new(str(tmp_path), "do it"), None)
    assert any("PR: https://pr/3" in line for line in logged)


def test_post_run_line_local_only_is_unchanged(tmp_path: Path) -> None:
    result = TaskResult(task_id="x", status=OK, summary="done", branch="colleague/x")
    s, logged = _make_session(tmp_path, result)
    s._run_work(Task.new(str(tmp_path), "do it"), None)
    line = next(li for li in logged if li.startswith("ok:"))
    assert "PR:" not in line
    assert line == "ok: done [(none)] → colleague/x"

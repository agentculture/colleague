"""Integration tests for session mode selection (t3).

Drive the session through scripted ``input_fn`` (no TTY) and direct method calls
to prove: mode state + cycling, the ``/mode`` slash, mode-aware routing (auto is
byte-identical, pinned modes override the classifier, explore/review take the
read-only path), CockpitState.mode visibility, and that a palette pick is never
reclassified. Written test-first against the t3 acceptance criteria.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from colleague.cli._commands._session_input import CYCLE_MODE
from colleague.cli._commands.session import _act_mode, _Session, run_session
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.session_modes import DEFAULT_MODE

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingWork:
    """A stub ``_work_fn`` recording every dispatch (task text, open_pr, role)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        repo: Path,
        engine_name: str,
        task: Task,
        open_pr: bool,
        base: str,
        config: EngineConfig,
        allow_dirty: bool = False,
        command_name: str | None = None,
        tui: bool | None = None,
        tui_events: str | None = None,
        progress_sink: object = None,
    ) -> tuple[TaskResult, Path]:
        self.calls.append(
            {
                "instruction": task.instruction,
                "open_pr": open_pr,
                "role": getattr(config, "role", None),
                "command_name": command_name,
            }
        )
        return TaskResult(task_id=task.id, status=OK, summary="done"), repo / "art.json"


class _RecordingPlan:
    """A stub ``_plan_fn`` recording every planning request."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, *, repo: Path, engine_name: str, request: str, config: EngineConfig) -> str:
        self.requests.append(request)
        return f"planned: {request}"


def _make_args(tmp_path: Path) -> Any:
    import argparse

    return argparse.Namespace(
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )


def _make_session(tmp_path: Path, *, view: str = "markdown", **kw: Any) -> _Session:
    return _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
        json_mode=False,
        view=view,
        out=kw.get("out", lambda *a, **k: None),
        err=kw.get("err", lambda *a, **k: None),
        work_fn=kw.get("work_fn", lambda **k: (TaskResult(task_id="t", status=OK), tmp_path)),
        plan_fn=kw.get("plan_fn", lambda **k: "planned"),
        user_home=tmp_path,  # hermetic: never scan the real ~/.colleague
    )


# ---------------------------------------------------------------------------
# Mode state + cycling (shift-tab) — c1/h1, c4/h10
# ---------------------------------------------------------------------------


def test_default_mode_is_auto(tmp_path: Path) -> None:
    sess = _make_session(tmp_path)
    assert sess.mode == DEFAULT_MODE == "auto"
    assert sess.state.mode == "auto"


def test_cycle_mode_advances_and_wraps(tmp_path: Path) -> None:
    sess = _make_session(tmp_path)
    seen = [sess.mode]
    for _ in range(5):
        sess._cycle_mode()
        seen.append(sess.mode)
    assert seen == ["auto", "work", "plan", "explore", "review", "auto"]
    # The cockpit state mirrors the live mode after each cycle.
    assert sess.state.mode == "auto"


def test_cycle_mode_does_not_stack_feed_lines(tmp_path: Path) -> None:
    """Shift-tab cycling must NOT append a ``mode → …`` line per press (issue #251).

    The active mode is shown in place by the status-line affordance, so a feed
    log would only stack one line per shift-tab and leave every prior mode on
    screen. The conversation feed therefore gains nothing from cycling; the
    affordance carries the change instead.
    """
    sess = _make_session(tmp_path)
    before = list(sess.state.conversation)
    for _ in range(5):  # a full wrap: auto → … → review → auto
        sess._cycle_mode()
    assert sess.state.conversation == before  # no feed lines added by cycling
    assert not any("mode →" in line.text for line in sess.state.conversation)
    # …but the in-place affordance reflects the landed mode (back to auto here).
    assert "[auto]" in sess.state.status.message


def test_run_loop_handles_cycle_mode_sentinel(tmp_path: Path) -> None:
    """A CYCLE_MODE sentinel from the reader advances the mode and re-prompts —
    it is never treated as a submitted line or a quit."""
    sess = _make_session(tmp_path, view="ansi")
    feed = [CYCLE_MODE, CYCLE_MODE, None]  # cycle twice, then EOF
    sess._read_live_ansi = lambda: feed.pop(0)  # type: ignore[method-assign]
    rc = sess.run(input_fn=None)
    assert rc == 0
    assert sess.mode == "plan"  # auto -> work -> plan


# ---------------------------------------------------------------------------
# /mode slash command — c11/h5
# ---------------------------------------------------------------------------


def test_act_mode_no_arg_cycles(tmp_path: Path) -> None:
    sess = _make_session(tmp_path)
    assert _act_mode(sess, []) == "mode → work"
    assert sess.mode == "work"


def test_act_mode_sets_explicitly(tmp_path: Path) -> None:
    sess = _make_session(tmp_path)
    assert _act_mode(sess, ["explore"]) == "mode → explore"
    assert sess.mode == "explore"


def test_act_mode_invalid_raises_and_leaves_mode_unchanged(tmp_path: Path) -> None:
    sess = _make_session(tmp_path)
    with pytest.raises(ValueError) as exc:
        _act_mode(sess, ["bogus"])
    msg = str(exc.value)
    for m in ("auto", "work", "plan", "explore", "review"):
        assert m in msg  # the hint lists every valid mode
    assert sess.mode == "auto"  # unchanged on error


def test_mode_in_help_and_slash_catalog() -> None:
    from colleague.cli._commands.session import _HELP_TEXT, _SLASH_COMMANDS

    assert any(s.name == "mode" for s in _SLASH_COMMANDS)
    assert "/mode" in _HELP_TEXT


def test_mode_slash_via_session_sets_and_routes(tmp_path: Path) -> None:
    work, plan = _RecordingWork(), _RecordingPlan()
    args = _make_args(tmp_path)
    # Set plan mode, then a NON-planning free text — it must still route to plan.
    run_session(
        args,
        input_fn=iter(["/mode plan", "add a helper function", "q"]),
        out=lambda *a, **k: None,
        _work_fn=work,
        _plan_fn=plan,
        _color=False,
    )
    assert plan.requests == ["add a helper function"]
    assert work.calls == []  # nothing routed to work while pinned to plan


# ---------------------------------------------------------------------------
# Mode-aware routing — c12/h6 (auto byte-identical; pinned overrides classifier)
# ---------------------------------------------------------------------------


def test_auto_mode_routes_planning_text_to_plan(tmp_path: Path) -> None:
    """auto mode = the classifier verbatim: a planning phrase routes to plan."""
    work, plan = _RecordingWork(), _RecordingPlan()
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["plan this feature out", "q"]),
        out=lambda *a, **k: None,
        _work_fn=work,
        _plan_fn=plan,
        _color=False,
    )
    assert plan.requests == ["plan this feature out"]
    assert work.calls == []


def test_auto_mode_routes_plain_task_to_work(tmp_path: Path) -> None:
    work, plan = _RecordingWork(), _RecordingPlan()
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["add a CONTRIBUTING.md file", "q"]),
        out=lambda *a, **k: None,
        _work_fn=work,
        _plan_fn=plan,
        _color=False,
    )
    assert len(work.calls) == 1
    assert plan.requests == []


def test_pinned_work_mode_overrides_classifier(tmp_path: Path) -> None:
    """In work mode a planning-phrased input is NOT reclassified to plan."""
    work, plan = _RecordingWork(), _RecordingPlan()
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["/mode work", "plan this out for me", "q"]),
        out=lambda *a, **k: None,
        _work_fn=work,
        _plan_fn=plan,
        _color=False,
    )
    assert len(work.calls) == 1
    assert plan.requests == []


def test_palette_number_never_reclassified_by_mode(tmp_path: Path) -> None:
    """A bare number selects a work template regardless of the active mode."""
    cmds = tmp_path / ".colleague" / "commands"
    cmds.mkdir(parents=True)
    (cmds / "setup.md").write_text("Set up the project.\n")
    work, plan = _RecordingWork(), _RecordingPlan()
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["/mode plan", "1", "q"]),
        out=lambda *a, **k: None,
        _work_fn=work,
        _plan_fn=plan,
        _color=False,
    )
    assert len(work.calls) == 1  # the template ran as work
    assert work.calls[0]["command_name"] == "setup"
    assert plan.requests == []  # plan mode did NOT capture the palette pick


# ---------------------------------------------------------------------------
# explore / review take the read-only path — c13/h7 (wiring; proofs in t4)
# ---------------------------------------------------------------------------


def test_explore_mode_dispatches_explorer_role_no_pr(tmp_path: Path) -> None:
    work = _RecordingWork()
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["/mode explore", "how does the loop work", "q"]),
        out=lambda *a, **k: None,
        _work_fn=work,
        _color=False,
    )
    assert len(work.calls) == 1
    assert work.calls[0]["role"] == "explorer"
    assert work.calls[0]["open_pr"] is False


def test_review_mode_dispatches_reviewer_role_with_diff(tmp_path: Path) -> None:
    work = _RecordingWork()
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["/mode review", "focus on error handling", "q"]),
        out=lambda *a, **k: None,
        _work_fn=work,
        _color=False,
    )
    assert len(work.calls) == 1
    call = work.calls[0]
    assert call["role"] == "reviewer"
    assert call["open_pr"] is False
    # The reviewer is handed the diff context (sourced operator-side).
    assert "main...HEAD" in call["instruction"]
    assert "focus on error handling".split()[0] in call["instruction"].lower()


# ---------------------------------------------------------------------------
# Visibility — c9/h3 (the mode shows in the rendered cockpit + the affordance)
# ---------------------------------------------------------------------------


def test_markdown_frame_shows_mode_and_affordance(tmp_path: Path) -> None:
    sess = _make_session(tmp_path, view="markdown")
    frame = sess._frame()
    assert "auto" in frame  # the active mode
    assert "shift-tab to cycle" in frame  # the affordance


def test_mode_change_visible_in_frame(tmp_path: Path) -> None:
    sess = _make_session(tmp_path, view="markdown")
    sess._cycle_mode()  # auto -> work
    frame = sess._frame()
    assert "[work]" in frame  # the active mode is marked in the affordance line

"""Talking-to-one-teammate (task t6): the senses front door on the session.

Pins the front-door contract on the interactive session: a free-text WORK line
first consults the deterministic front door. On a non-repo turn senses answers
DIRECTLY — a ``senses:`` line, NO cortex work item (work_fn never called), no
branch, no eidetic. On a repo-touching turn the senses ack renders BEFORE the
``→ work:`` routing line (ack-first, h2), a ``cortex ▸ working…`` hand-off line
is shown (c11), and the work item dispatches. Unarmed / --cortex-only / staged
media are strict no-ops (byte-identical): no front door, no senses line.
"""

from __future__ import annotations

from pathlib import Path

from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, SensesRecord, TaskResult
from colleague.frontdoor import CORTEX, SENSES_DIRECT, FrontDoorOutcome


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))


def _senses_config() -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _session(tmp_path: Path, *, view: str = "ansi", config=None, cortex_only: bool = False):
    out, err = _CollectingOut(), _CollectingOut()
    result = TaskResult(task_id="t", status=OK, summary="s")
    calls: list[dict] = []

    def _fake_work(**kwargs: object):
        calls.append(dict(kwargs))
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config if config is not None else _senses_config(),
        json_mode=False,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(cortex_only=cortex_only),
    )
    return sess, calls


def _lines(sess) -> list[str]:
    return [line.text for line in sess.state.conversation]


def _senses_direct_outcome(answer: str = "I'm senses, colleague's front lobe.") -> FrontDoorOutcome:
    return FrontDoorOutcome(
        route=SENSES_DIRECT,
        dispatch=False,
        answered_directly=True,
        answer=answer,
        degraded=False,
        record=SensesRecord(point="senses-frontdoor:senses_direct"),
        chat_entry={"kind": "talk", "message": "what are you?", "answer": answer, "at": 0.0},
    )


def _cortex_outcome() -> FrontDoorOutcome:
    return FrontDoorOutcome(
        route=CORTEX,
        dispatch=True,
        answered_directly=False,
        record=SensesRecord(point="senses-frontdoor:cortex"),
    )


# --- senses-direct: answered without a cortex work item ----------------------


def test_senses_direct_answers_and_runs_no_work_item(tmp_path: Path, monkeypatch) -> None:
    sess, calls = _session(tmp_path)
    monkeypatch.setattr(session_mod, "run_frontdoor", lambda *a, **k: _senses_direct_outcome())
    sess._work_line("what are you?")
    lines = _lines(sess)
    assert any("senses: I'm senses, colleague's front lobe." in ln for ln in lines)
    assert calls == []  # the cortex work loop never ran — no branch, no eidetic


def test_senses_direct_threads_history_for_continuity(tmp_path: Path, monkeypatch) -> None:
    sess, _calls = _session(tmp_path)
    monkeypatch.setattr(session_mod, "run_frontdoor", lambda *a, **k: _senses_direct_outcome())
    sess._work_line("what are you?")
    roles = [h["role"] for h in sess._history]
    assert "operator" in roles and "senses" in roles


def test_senses_direct_does_not_grow_senses_chat_buffer(tmp_path: Path, monkeypatch) -> None:
    # Bug 3: a senses-direct turn produces NO work item / TaskResult, so it must
    # NOT accumulate onto the per-work-item `_senses_chat` buffer (reset per work
    # line, folded into a work item's artifact) — that would leak unbounded over a
    # senses-only conversation. `_history` is the continuity mechanism instead, and
    # it DOES accumulate.
    sess, calls = _session(tmp_path)
    monkeypatch.setattr(session_mod, "run_frontdoor", lambda *a, **k: _senses_direct_outcome())
    sess._work_line("what are you?")
    sess._work_line("who are you?")
    sess._work_line("hello")
    assert calls == []  # no cortex work item ever dispatched
    assert len(sess._senses_chat) == 0
    roles = [h["role"] for h in sess._history]
    assert roles.count("operator") == 3
    assert roles.count("senses") == 3


# --- cortex route: ack precedes the routing line, hand-off is visible --------


def test_cortex_route_acks_before_routing_line_and_dispatches(tmp_path: Path, monkeypatch) -> None:
    sess, calls = _session(tmp_path)
    monkeypatch.setattr(session_mod, "run_frontdoor", lambda *a, **k: _cortex_outcome())
    # Intake degrades (no real senses endpoint) → the FIXED ack notice renders;
    # what matters for h2 is that the ack line precedes the "→ work:" line.
    monkeypatch.setattr(session_mod, "run_senses_intake", lambda *a, **k: (None, None))
    sess._work_line("fix the bug in loop.py")
    lines = _lines(sess)
    assert calls, "cortex work item should have dispatched"
    ack_idx = next(i for i, ln in enumerate(lines) if ln.startswith("senses:"))
    work_idx = next(i for i, ln in enumerate(lines) if "→ work:" in ln)
    assert ack_idx < work_idx  # ack-first (h2)
    assert any("cortex ▸ working" in ln for ln in lines)  # visible hand-off (c11)


# --- byte-identical no-ops ---------------------------------------------------


def test_unarmed_session_has_no_front_door(tmp_path: Path, monkeypatch) -> None:
    config = EngineConfig.resolve(model="cortex-model")  # senses stays None
    sess, calls = _session(tmp_path, config=config)
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return _senses_direct_outcome()

    monkeypatch.setattr(session_mod, "run_frontdoor", _boom)
    sess._work_line("hi")
    assert called["n"] == 0  # _run_frontdoor short-circuits before run_frontdoor
    assert calls, "an unarmed session still dispatches to cortex"
    assert not any(ln.startswith("senses:") for ln in _lines(sess))


def test_unarmed_talk_lane_never_consults_frontdoor(tmp_path: Path, monkeypatch) -> None:
    # Default path: senses unarmed (config.senses None) + a typed mid-run talk
    # line — the line parks to cortex via flight guidance, and the senses front
    # door is NEVER consulted (the talk lane has no front door on the default
    # path).
    config = EngineConfig.resolve(model="cortex-model")  # senses stays None
    sess, _calls = _session(tmp_path, config=config)
    frontdoor_calls = {"n": 0}

    def _boom(*a, **k):
        frontdoor_calls["n"] += 1
        return _senses_direct_outcome()

    monkeypatch.setattr(session_mod, "run_frontdoor", _boom)
    sess._talk_active = True
    sess._talk_task_id = "tid"
    sess._talk_senses("focus on the tests")
    assert frontdoor_calls["n"] == 0  # the front door is never consulted


def test_run_frontdoor_is_noop_when_cortex_only(tmp_path: Path) -> None:
    sess, _calls = _session(tmp_path, cortex_only=True)
    assert sess._run_frontdoor("what are you?") is None


def test_run_frontdoor_is_noop_with_staged_attachments(tmp_path: Path) -> None:
    sess, _calls = _session(tmp_path)
    sess._staged_attachments = [{"path": "/x.png", "media_type": "image/png"}]
    assert sess._run_frontdoor("what are you?") is None


def test_run_frontdoor_is_noop_when_senses_engine_unresolvable(tmp_path: Path, monkeypatch) -> None:
    # Senses armed (config present), not --cortex-only, no staged media — but the
    # engine cannot be resolved, so _senses_engine() returns None and _run_frontdoor
    # degrades to None (the caller then dispatches to cortex, byte-identical).
    sess, _calls = _session(tmp_path)
    monkeypatch.setattr(sess, "_senses_engine", lambda: None)
    assert sess._run_frontdoor("what are you?") is None


def test_run_frontdoor_cortex_route_short_circuits_before_engine_load(
    tmp_path: Path, monkeypatch
) -> None:
    # Bug 4: the CORTEX route is the common case and never consults senses, so
    # _run_frontdoor must classify FIRST and never resolve/load the senses engine
    # for it — the route is still recorded even when the engine can't load.
    sess, _calls = _session(tmp_path)

    def _boom():
        raise AssertionError("_senses_engine must not be called on the CORTEX route")

    monkeypatch.setattr(sess, "_senses_engine", _boom)
    outcome = sess._run_frontdoor("fix the bug in loop.py")
    assert outcome is not None
    assert outcome.route == CORTEX
    assert outcome.dispatch is True
    assert outcome.record is not None
    assert outcome.record.point.endswith(":cortex")


# --- mode-pinned routes flow through _route_free_text (S3776 extraction) ------
# `explore`/`review`/`plan` pin the verb (route_for), so a free-text work line in
# those modes dispatches the read-only / plan verb and NEVER consults the senses
# front door — proving the extracted helper preserves the pre-refactor routing.


def _mode_route_session(tmp_path: Path, monkeypatch, mode: str):
    sess, calls = _session(tmp_path)
    sess.mode = mode
    recorded: list[str] = []
    monkeypatch.setattr(sess, "_run_plan", lambda text: recorded.append(f"plan:{text}"))
    monkeypatch.setattr(sess, "_run_explore", lambda text: recorded.append(f"explore:{text}"))
    monkeypatch.setattr(sess, "_run_review", lambda text: recorded.append(f"review:{text}"))

    def _boom_frontdoor(*a, **k):
        raise AssertionError("the front door must not be consulted on a non-work route")

    monkeypatch.setattr(session_mod, "run_frontdoor", _boom_frontdoor)
    return sess, calls, recorded


def test_plan_mode_routes_through_route_free_text(tmp_path: Path, monkeypatch) -> None:
    sess, calls, recorded = _mode_route_session(tmp_path, monkeypatch, "plan")
    sess._work_line("design a new feature")
    assert recorded == ["plan:design a new feature"]
    assert calls == []  # no cortex work item dispatched


def test_explore_mode_routes_through_route_free_text(tmp_path: Path, monkeypatch) -> None:
    sess, calls, recorded = _mode_route_session(tmp_path, monkeypatch, "explore")
    sess._work_line("look around the repo")
    assert recorded == ["explore:look around the repo"]
    assert calls == []


def test_review_mode_routes_through_route_free_text(tmp_path: Path, monkeypatch) -> None:
    sess, calls, recorded = _mode_route_session(tmp_path, monkeypatch, "review")
    sess._work_line("review the diff")
    assert recorded == ["review:review the diff"]
    assert calls == []

"""The named simulation scenarios — one per primary TUI surface, plus a full ride.

Each :func:`Scenario` bundles a :class:`~tools.tui_sim.filmstrip.Filmstrip` (which
serializes to a ``.cast`` + storyboards) with an optional ``(state, events)``
snapshot for the scenario's *key* moment (e.g. the frame where a popup is
visible) so the runner can also emit a snapshot quad and diagnose it.

Scenarios
---------
* ``first-contact``   — palette + slash autocomplete (Surface 1)
* ``drive-cockpit``   — live drive: tool steps + spinner (Surface 2)
* ``skill-suggested`` — the ``boost`` popup overlay (Surface 3)
* ``failed-step``     — the error popup on a failed tool step (Surface 3)
* ``full-ride``       — end-to-end: palette → config → drive → popup → quit

Everything is built from colleague's pure render seams, so re-running is
deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from colleague.tui.events import Dismiss, Event, SkillSuggested, UserInput
from colleague.tui.from_work import work_step
from colleague.tui.state import CockpitState

from . import session_sim as ss
from .cockpit_sim import drive_state, first_state_with_visible_popup, fold, ticks
from .filmstrip import DEFAULT_WIDTH, Filmstrip


@dataclass
class Scenario:
    """A named flow: its filmstrip plus an optional key-moment snapshot."""

    name: str
    title: str
    filmstrip: Filmstrip
    snapshot: Optional[Tuple[CockpitState, List[Event]]] = None


# ---------------------------------------------------------------------------
# Surface 1 — palette + slash autocomplete
# ---------------------------------------------------------------------------


def _first_contact(repo: Path) -> Scenario:
    session = ss.build_session(repo, engine="mock")
    frames = [ss.idle_frame(session)]
    frames += ss.type_slash_command(session, "help")  # / → /h → … → /help
    result_frame, _ = ss.submit_slash(session, "/help")
    frames.append(result_frame)
    title = "First contact — palette + slash autocomplete"
    fs = Filmstrip("first-contact", title, frames)
    return Scenario("first-contact", title, fs, snapshot=(session.state, []))


# ---------------------------------------------------------------------------
# Surface 2 — drive cockpit
# ---------------------------------------------------------------------------


def _drive_cockpit(repo: Path) -> Scenario:
    session = ss.build_session(repo, engine="mock")
    start = drive_state(session.state, engine="mock")
    timed = [
        (UserInput("Add a retry-on-overflow guard to the drive loop"), 1000),
        *ticks(2, 140),
        (work_step("read_file", "colleague/loop.py"), 650),
        *ticks(1, 150),
        (work_step("read_file", "colleague/context.py"), 650),
        *ticks(2, 140),
        (work_step("write_file", "colleague/loop.py"), 750),
        *ticks(2, 140),
        (work_step("run_command", "pytest -q tests/test_loop.py"), 850),
        *ticks(1, 150),
        (work_step("finish", "retry-on-overflow guard added"), 700),
        (
            UserInput(
                "done: retry-on-overflow guard added "
                "[colleague/loop.py] -> colleague/7f3a2c-add-retry-guard"
            ),
            2600,
        ),
    ]
    frames, states, events = fold(start, timed)
    title = "Drive cockpit — tool steps + spinner"
    fs = Filmstrip("drive-cockpit", title, frames)
    return Scenario("drive-cockpit", title, fs, snapshot=(states[-1], events))


# ---------------------------------------------------------------------------
# Surface 3 — popups
# ---------------------------------------------------------------------------


def _skill_suggested(repo: Path) -> Scenario:
    session = ss.build_session(repo, engine="mock")
    start = drive_state(session.state, engine="mock")
    timed = [
        *ticks(2, 150),
        (work_step("read_file", "colleague/engines/vllm_openai.py"), 650),
        *ticks(2, 160),
        (SkillSuggested("boost", reason="task_complexity_high", confidence=0.9), 2800),
        (Dismiss("popup.skill.boost"), 800),
        *ticks(2, 150),
        (work_step("write_file", "colleague/engines/vllm_openai.py"), 700),
    ]
    frames, states, events = fold(start, timed)
    k = first_state_with_visible_popup(states)
    snap = (states[k], events[:k]) if k >= 0 else (states[-1], events)
    title = "Skill suggested — the boost popup"
    fs = Filmstrip("skill-suggested", title, frames)
    return Scenario("skill-suggested", title, fs, snapshot=snap)


def _failed_step(repo: Path) -> Scenario:
    session = ss.build_session(repo, engine="mock")
    start = drive_state(session.state, engine="mock")
    timed = [
        *ticks(2, 150),
        (work_step("read_file", "colleague/policy.py"), 650),
        *ticks(1, 150),
        (work_step("run_command", "pytest -q tests/test_policy.py", ok=False), 2800),
        (Dismiss("popup.error.run_command"), 900),
    ]
    frames, states, events = fold(start, timed)
    k = first_state_with_visible_popup(states)
    snap = (states[k], events[:k]) if k >= 0 else (states[-1], events)
    title = "Failed step — the error popup"
    fs = Filmstrip("failed-step", title, frames)
    return Scenario("failed-step", title, fs, snapshot=snap)


# ---------------------------------------------------------------------------
# Full ride — every surface in one continuous recording
# ---------------------------------------------------------------------------


def _full_ride(repo: Path) -> Scenario:
    width = DEFAULT_WIDTH
    session = ss.build_session(repo, engine="vllm-openai")
    frames = [ss.idle_frame(session)]

    # Switch engine via the slash autocomplete, then type the argument.
    frames += ss.type_slash_command(session, "engine")  # "/engine"
    for buf, hold in (("/engine ", 160), ("/engine m", 160), ("/engine mock", 360)):
        frames.append((ss.compose_session_frame(session.state, buf, width=width), hold))
    confirm_frame, _ = ss.submit_slash(session, "/engine mock", hold=1500)
    frames.append(confirm_frame)

    # Hand off to a live drive on the now-mock engine.
    start = drive_state(session.state, engine="mock")
    timed = [
        (UserInput("Wire the cockpit status bar severity to drive failures"), 1000),
        *ticks(2, 140),
        (work_step("read_file", "colleague/tui/widgets/status_bar.py"), 650),
        *ticks(2, 150),
        (SkillSuggested("boost", reason="task_complexity_high", confidence=0.92), 2600),
        (Dismiss("popup.skill.boost"), 800),
        *ticks(1, 150),
        (work_step("write_file", "colleague/tui/widgets/status_bar.py"), 750),
        *ticks(2, 140),
        (work_step("run_command", "pytest -q tests/test_tui_render.py"), 850),
        *ticks(1, 150),
        (work_step("finish", "status bar severity wired to drive failures"), 700),
        (
            UserInput(
                "done: status bar severity wired to drive failures "
                "[colleague/tui/widgets/status_bar.py] -> colleague/7f3a2c-status-severity"
            ),
            2200,
        ),
    ]
    drive_frames, states, events = fold(start, timed, width=width)
    frames += drive_frames
    final = states[-1]

    # The user types /quit to end the session.
    frames.append((ss.compose_session_frame(final, "/quit", width=width), 1100))

    title = "Full ride — palette -> config -> drive -> popup -> quit"
    fs = Filmstrip("full-ride", title, frames, width=width)
    return Scenario("full-ride", title, fs, snapshot=(final, events))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BUILDERS = (
    _first_contact,
    _drive_cockpit,
    _skill_suggested,
    _failed_step,
    _full_ride,
)


def build_all(repo: Path) -> List[Scenario]:
    """Build every scenario against *repo* (deterministic; safe to call twice)."""
    return [build(repo) for build in _BUILDERS]

"""Surface 1 — the ``colleague session`` palette + slash-autocomplete.

Reproduces, frame-for-frame, what a human sees while driving the interactive
session: the command palette, the conversation panel, and the live slash popup
that filters as they type. The frame composition mirrors the live reader's
closure ``_read_live_ansi._render`` (``colleague/cli/_commands/session.py:268``)
exactly — cockpit frame → autocomplete popup (when the buffer matches) →
``colleague ❯`` + the typed buffer — so the sim never drifts from the real screen.

The palette ``CockpitState`` is taken from a *real* :class:`_Session` instance
(built against the target repo) so the command list, status line, and panels are
authoritative; only the deterministic ``width`` is overridden.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from colleague.cli._commands.session import _SLASH_COMMANDS, _Session, filter_slash
from colleague.config import EngineConfig
from colleague.tui.render.ansi import render as render_ansi
from colleague.tui.state import CockpitState
from colleague.tui.widgets.prompt_input import plain_prompt
from colleague.tui.widgets.slash_autocomplete import render_slash_autocomplete

from .filmstrip import DEFAULT_WIDTH, FrameT

#: The model the demo session advertises — the real reference-rig model name, so
#: the status line reads exactly like a live session header.
DEMO_MODEL = "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"


def _noop_work(**_kwargs):  # pragma: no cover - never invoked in a sim
    raise RuntimeError("tui_sim never runs a real work item")


def build_session(repo: Path, *, engine: str = "mock", model: str = DEMO_MODEL) -> _Session:
    """Construct a real (non-driving) :class:`_Session` for its authoritative state.

    Hermetic by construction: ``user_home`` is pinned to *repo* so command
    discovery never reads the real ``~/.colleague/commands`` — otherwise a
    contributor's personal templates would leak into the recordings and break
    byte-identical regeneration. Pointing the user-home at the repo is idempotent
    (``discover_commands`` dedupes by stem with repo precedence), so the palette is
    exactly the repo's templates on every machine.
    """
    config = EngineConfig.resolve(model=model)
    return _Session(
        repo=repo,
        engine_name=engine,
        open_pr=False,
        base="main",
        config=config,
        json_mode=False,
        view="ansi",
        out=lambda *a, **k: None,
        err=lambda *a, **k: None,
        work_fn=_noop_work,
        user_home=repo,
    )


def compose_session_frame(
    state: CockpitState, buffer: str, *, width: int = DEFAULT_WIDTH, selected: int = 0
) -> str:
    """Compose one session frame for *buffer* — mirror of ``_read_live_ansi._render``.

    Returns the cockpit frame for *state*, then (when ``buffer`` starts with ``/``
    and still matches at least one command) the autocomplete popup, then the
    prompt line with the typed buffer. The leading clear-home is added by the cast
    writer, so this returns the body only. Takes a bare ``CockpitState`` so any
    state (a palette *or* a post-work cockpit) can render a typed buffer.
    """
    parts: List[str] = [render_ansi(state, width=width, include_prompt=False)]
    matches = filter_slash(buffer[1:]) if buffer.startswith("/") else []
    if matches:
        parts.append(render_slash_autocomplete(matches, selected, width=width))
    parts.append(plain_prompt() + buffer)
    return "\n".join(parts)


def type_slash_command(
    session: _Session,
    command: str,
    *,
    width: int = DEFAULT_WIDTH,
    open_hold: int = 520,
    keystroke_hold: int = 170,
) -> List[FrameT]:
    """Frames for a human typing ``/<command>`` one keystroke at a time.

    Frame 1 is the bare ``/`` (the popup opens listing every command); each
    subsequent keystroke narrows the popup. Returns the keystroke filmstrip; the
    caller decides what happens on Enter (see :func:`submit_slash`).
    """
    frames: List[FrameT] = []
    buffer = "/"
    frames.append((compose_session_frame(session.state, buffer, width=width), open_hold))
    for ch in command:
        buffer += ch
        frames.append((compose_session_frame(session.state, buffer, width=width), keystroke_hold))
    return frames


def submit_slash(
    session: _Session, line: str, *, width: int = DEFAULT_WIDTH, hold: int = 2600
) -> Tuple[FrameT, str]:
    """Apply *line* (e.g. ``/help``) to the session and render the result frame.

    Folds the input through the real ``_Session._handle`` (echo + slash dispatch),
    so the conversation grows exactly as it would live, then renders one frame with
    an empty buffer (the popup is gone, the cursor is back at the prompt). Returns
    ``(frame, line)``.
    """
    session._handle(line)  # echoes the input, then runs the slash verb
    return (compose_session_frame(session.state, "", width=width), hold), line


def idle_frame(session: _Session, *, width: int = DEFAULT_WIDTH, hold: int = 700) -> FrameT:
    """The opening frame: palette + conversation, empty prompt, no popup."""
    return (compose_session_frame(session.state, "", width=width), hold)


# Re-exported for callers that want to introspect the catalogue.
SLASH_COMMANDS = _SLASH_COMMANDS

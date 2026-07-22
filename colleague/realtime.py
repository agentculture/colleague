"""Ears-only realtime speech client — an import-clean packaging stub (plan
task t2 of the realtime-speech arc: docs/specs/2026-07-22-realtime-speech.md,
docs/plans/2026-07-22-realtime-speech.md).

Task t2 lands ONLY the boundary sanction (below) + the ``[voice]`` extra
packaging for the sync WebSocket client; task t3 fills in the actual dial,
the ``session.update`` handshake, the base64 audio event codec, and the
receive-pump thread body. This module must stay import-clean on a BASE
install: the sync WebSocket client (``websocket-client``, imported as
``websocket``) lives ONLY in the opt-in ``[voice]`` extra and is imported
LAZILY, inside a function, never at module load — mirroring
``colleague/voice_devices.py`` exactly (sounddevice/soundfile are lazy there
the same way).

Ears-only design (spec c22/h15, plan task t3 instruction)
----------------------------------------------------------
The realtime session colleague dials is EARS-ONLY: it never sends
``response.create`` and never arms the bridge's own LLM turn (the bridge's
own model + its ``DEFAULT_SYSTEM_PROMPT``) — colleague consumes only VAD
turn-boundary and transcription events over the wire. Senses (the grounded,
tools-off mind that actually answers — see ``colleague/senses.py``) stays the
ONLY producer of a spoken reply, via the existing batch
``colleague.voice.synthesize()`` lane (task t5); the realtime socket is a
listening ear, never a second voice, and cortex remains the only repo actor.

Thread sanction rationale (recorded in ``tests/test_boundary.py``)
----------------------------------------------------------------------
Continuous audio streams need a receive-pump thread; ``colleague/realtime.py``
is sanctioned (spec c6, plan task t2) as the ONE additional module — after
``colleague/subagents.py`` and ``colleague/cli/_commands/_input_line.py`` — to
import ``threading`` directly. The discipline mirrors the input-line
precedent exactly: daemon threads only, a ``threading.Event`` stop signal, a
poll-wake read (``websocket-client``'s ``settimeout`` gives the same
wake-up-and-recheck shape ``select`` gives the input line), and a BOUNDED
``join`` so teardown never hangs on a parked blocking read (the #315 lesson —
a fake stream cannot prove this; a real socket/device does, in task t3/t4's
own tests). Every thread this module spawns — PortAudio capture/playback
callbacks (task t4), the ONE WS receive pump (task t3) — is extra-gated
behind ``[voice]`` and degrades to the turn-based lane on any failure, never
raising past this module's boundary. :func:`_bounded_join` is the one piece
of that discipline this stub already implements, so later tasks reuse it
rather than re-deriving the bounded-join shape.

This module is otherwise a STUB: no PortAudio, no WebSocket dial, no session
state yet — only the lazy-import guard and the bounded-join helper, so it
import-cleanly smoke-tests on a base install today (tests/test_realtime.py).
"""

from __future__ import annotations

import threading
from typing import Any

from colleague.cli._errors import CliError

_INSTALL_HINT = "pip install colleague[voice]"


def _import_ws() -> Any:
    """Lazily import the sync WS client, or raise a clean :class:`CliError`.

    Mirrors ``colleague/voice_devices.py``'s ``_import_audio``: the realtime
    module stays import-clean on a base install; the third-party dependency
    (``websocket-client``, imported as ``websocket``) is pulled in only when a
    realtime function actually runs — never at module load.
    """
    try:
        import websocket  # type: ignore

        return websocket
    except Exception as exc:  # noqa: BLE001 - any import failure names the extra
        raise CliError(
            1,
            f"realtime speech support is not installed ({type(exc).__name__})",
            remediation=_INSTALL_HINT,
        ) from exc


def _bounded_join(thread: threading.Thread, *, timeout: float = 1.0) -> None:
    """Join *thread* with a bounded timeout — never hangs.

    The one piece of the sanctioned thread discipline this stub already
    implements (see the module docstring): every pump/callback thread task
    t3/t4 spawns is a daemon thread stopped via a ``threading.Event`` and
    reaped through this bounded join, exactly like
    ``colleague/cli/_commands/_input_line.py``'s ``OwnedInputLine.stop``.
    Idempotent-safe: joining an already-finished thread returns immediately.
    """
    if thread.is_alive():
        thread.join(timeout=timeout)


def open_session(*_args: Any, **_kwargs: Any) -> Any:
    """Open an ears-only realtime session (placeholder — task t3 fills this in).

    Degrades cleanly rather than crashing: with the ``[voice]`` extra absent
    this raises the same :class:`CliError` every other voice function raises
    (naming ``pip install colleague[voice]``); with the extra installed it
    still raises :class:`NotImplementedError` today, since no dial exists
    yet — a caller's degrade-to-turn-based path is exercised identically
    either way until task t3 lands the real client.
    """
    _import_ws()
    raise NotImplementedError("colleague.realtime.open_session lands in task t3")

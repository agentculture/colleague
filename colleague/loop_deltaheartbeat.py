"""Wire the delta heartbeat into the production work path (#483).

``#479`` t10 shipped :func:`colleague.loop_progress.delta_heartbeat` — a
throttled, ``EngineConfig.on_delta``-shaped liveness callback that piggybacks a
flight-feed heartbeat onto delta arrival with no timer thread. What it did NOT
ship is the arming: nothing in the work path ever built one, so a bare
``colleague work`` run still went silent for the whole length of a slow
completion (the #479 "froze for 25 minutes" report). This module is that
missing half, and nothing else — it introduces no new liveness mechanism, no
new record type and no new knob (the throttle stays
``COLLEAGUE_DELTA_HEARTBEAT_INTERVAL``, read by the heartbeat itself; nothing
here re-throttles).

The composition, in two beats
----------------------------
The two things that must meet — a live ``EngineConfig`` and the run's ``_Work``
ctx — never exist at the same moment: an engine reads ``config.on_delta`` while
building/serving its completion, and ``ctx`` is built later, inside
:func:`colleague.loop.run`, which is handed no config at all. So:

1. :func:`arm` runs at ``ContextControls.from_config`` time — the ONE
   config→loop forwarding seam BOTH backends share (the all-engines rule) —
   and installs a CHAINED ``on_delta``: the caller's pre-armed sink first
   (a cockpit/session sink, unchanged and never dropped), then the heartbeat.
   The heartbeat slot is an empty cell at this point, so the chain is inert.
2. :func:`bind` runs inside :func:`colleague.loop.run` once ``ctx`` exists and
   fills that cell with ``delta_heartbeat(ctx)``. From there every arriving
   chunk gets a throttled chance to emit — through the SAME ``_emit_phase``
   phase notices already use, so a heartbeat inherits its invariants for free:
   a missing ``flight``/``progress`` is a no-op, a raising sink is suppressed,
   and NO heartbeat record ever advances ``step_count``.

Both legs of the chain are best-effort and independent: a raising cockpit sink
cannot suppress the heartbeat, and a raising heartbeat cannot cost the cockpit
a chunk. Nothing here mutates ``EngineConfig`` fields other than ``on_delta``
(the runtime-only display seam the CLI work path already assigns imperatively —
see ``colleague/cli/_commands/_work_support.py``), and a config that refuses
the assignment (a frozen/read-only view) simply arms nothing.

Honest limits — say them plainly
--------------------------------
* **The blocking path gets NO liveness, by construction.** With
  ``COLLEAGUE_STREAM=0`` and no pre-armed sink the adapter sends ONE blocking
  request and reads back an already-finished response: there is no delta to
  piggyback on. :func:`arm` therefore installs NOTHING in that case — not as an
  oversight but deliberately, because an ``on_delta`` would silently flip the
  adapter's ``streaming = config.on_delta is not None or headless`` decision
  and turn an operator's explicit blocking run into a streamed one. That hole
  is real; it is the price of a thread-free, delta-driven design, and closing
  it needs a different mechanism (not this one).
* **A fully silent stretch still gets no heartbeat.** The clock only advances
  when a chunk actually arrives (``loop_progress``'s own documented limit).
* **The mock engine gains no heartbeat on a bare run.** ``MockEngine.work``
  captures ``config.on_delta`` to build its synthetic-delta wrapper BEFORE it
  calls ``ContextControls.from_config``, so a bare mock run (which has no real
  transport latency to be silent about) sees ``None`` and streams nothing; a
  mock run with a pre-armed sink keeps delivering to it exactly as before.
  Result shape is identical on both backends — this is observability, not the
  contract — but the divergence is named here rather than implied away.
"""

from __future__ import annotations

import os
from contextlib import suppress
from typing import Any, Callable

#: The transport's own streaming opt-out, mirrored. Deliberately duplicated
#: rather than imported: ``colleague/engines/`` is the plugin layer and the
#: loop sits above it (no loop module imports an engine). The vocabulary is
#: pinned against ``vllm_transport._headless_streaming_enabled`` by a test, so
#: the two can never drift apart — a drift in either direction would either
#: force a blocking run to stream or drop liveness from a streamed one.
_STREAM_ENV_KEY = "COLLEAGUE_STREAM"
_STREAM_DISABLING_VALUES = ("", "0", "false", "no", "off")

#: Marker attributes on a chain THIS module installed: the heartbeat cell, and
#: the sink the caller had pre-armed. The cell makes re-arming one config (a
#: second run, a chained episode) REBIND that chain instead of wrapping it again
#: — unbounded nesting would leave every earlier run's heartbeat still writing
#: to its dead feed. The chain outlives the run it was armed for (the config is
#: the caller's object; nothing here restores it), so ``pre_armed_sink`` exists
#: to answer the only question anyone asks of it afterwards: what did the CALLER
#: arm, as opposed to what the loop wrapped around it.
_CHAIN_CELL_ATTR = "_colleague_delta_beat_cell"
_CHAIN_PRE_ATTR = "_colleague_delta_pre_sink"


def _headless_streaming_enabled() -> bool:
    """Whether the transport streams with no delta sink armed (#393's knob)."""
    value = os.environ.get(_STREAM_ENV_KEY)
    if value is None:
        return True
    return value.strip().lower() not in _STREAM_DISABLING_VALUES


def arm(config: Any) -> "Callable[[Any], None] | None":
    """Chain a (still unbound) heartbeat onto *config*'s ``on_delta``.

    Returns the binder :func:`colleague.loop.run` later calls with its ``ctx``,
    or ``None`` when nothing was armed — a blocking run with no pre-armed sink
    (see the module docstring's honest limits), or a config whose ``on_delta``
    cannot be assigned.
    """
    pre = getattr(config, "on_delta", None)
    if pre is None and not _headless_streaming_enabled():
        return None  # the blocking path: install nothing, change no decision
    cell = getattr(pre, _CHAIN_CELL_ATTR, None)
    if cell is None:
        cell = []
        chained = _chain(pre, cell)
        try:
            config.on_delta = chained
        except Exception:  # noqa: BLE001 - a frozen/read-only config arms nothing
            return None

    def _bind(ctx: Any) -> None:
        from colleague.loop_progress import delta_heartbeat

        cell[:] = [delta_heartbeat(ctx)]

    return _bind


def _chain(pre: "Callable[[str], None] | None", cell: list) -> "Callable[[str], None]":
    """The composed sink: pre-armed sink first, then the (late-bound) heartbeat.

    Each leg is independently best-effort — observability is never control, so
    neither a raising cockpit sink nor a raising heartbeat may kill the stream
    or rob the other leg of its chunk.
    """

    def _on_delta(chunk: str) -> None:
        if pre is not None:
            with suppress(Exception):
                pre(chunk)
        for beat in cell:
            with suppress(Exception):
                beat(chunk)

    setattr(_on_delta, _CHAIN_CELL_ATTR, cell)
    setattr(_on_delta, _CHAIN_PRE_ATTR, pre)
    return _on_delta


def pre_armed_sink(on_delta: Any) -> Any:
    """The sink the CALLER armed underneath a chain — *on_delta* itself when it
    is not one of ours, ``None`` when nothing was armed.

    The one honest way to ask "did the work path arm a display sink?" once the
    loop has wrapped it: a bare ``config.on_delta is None`` check stopped
    answering that question at #483.
    """
    if hasattr(on_delta, _CHAIN_PRE_ATTR):
        return getattr(on_delta, _CHAIN_PRE_ATTR)
    return on_delta


def bind(controls: Any, ctx: Any) -> None:
    """Bind *ctx* into the chain :func:`arm` installed; a no-op when unarmed.

    Called once per run, right after ``_Work`` is built. A direct
    :func:`colleague.loop.run` caller that passed a hand-built
    ``ContextControls`` has no binder at all and is untouched (byte-identical).
    """
    binder = getattr(controls, "delta_binder", None)
    if binder is None:
        return
    with suppress(Exception):
        binder(ctx)

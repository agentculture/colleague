"""Two enumerated effort spikes on the ACTING completion (#484, t9).

Spec ``docs/specs/2026-09-01-small-fixes-then-effort-balance.md`` (c18),
consuming the table task t5 built (:mod:`colleague.effortspikes`) at the two
points its sibling t8 (:mod:`colleague.loop_barrier`) did not:

``gate.repeat_failure``
    A pre-finish gate (affected-tests / test-integrity) whose bounded repair
    turn has ALREADY failed once. The FIRST repair keeps the seat's ordinary
    rung — unchanged behaviour, byte for byte. A REPEATED repair (the second
    and later iterations of the gate's ``while report … and retries > 0``
    loop) runs at :func:`colleague.effortspikes.resolve_spike`'s
    ``"medium"``. The deterministic signal is the LOOP ITERATION COUNT — never
    the report's content, never the model's text.

``fillline.decision``
    The fill-line's own capacity decision (compact | split |
    finish-with-handoff). Its rung is NOT owned by
    :data:`colleague.effortspikes.SPIKE_TABLE` (that row is the
    :data:`~colleague.effortspikes.FILLLINE_DELEGATED` sentinel): it is read
    from the EXISTING design-site contract
    :data:`colleague.effort.DESIGN_SITE_TABLE`\\ ``["fillline.split"]`` through
    the already-shipped builder :func:`colleague.fillline.design_seat_config`,
    so the operator override / kill-switch precedence (c32) is honoured once,
    in one place, and the two tables can never drift.

Why this module mutates instead of building a seat
--------------------------------------------------

Every other effort consumer BUILDS its own one-shot seat
(``engine.make_complete(seat, tools=[])`` — deepthink, associate, hire, the
t8 barrier). Neither point here can: both escalate a turn that must keep the
run's own TOOL SURFACE (a gate repair turn calls ``edit_file``/``run_tests``;
the fill-line declaring turn declares SPLIT by calling ``subagents`` and
FINISH-WITH-HANDOFF by calling ``finish``). That surface is the
role-curated ``offered_tools`` the engine captured when it built the acting
completion; re-deriving it here would duplicate the role/tool_set narrowing —
the one thing the allow-list seam exists to keep single.

So the rung reaches the wire the ONLY other way it can: the acting config's
optional ``reasoning_effort_seat`` attribute — the same plain attribute
:func:`colleague.engines.vllm_payload._effort_for` reads, and the same one
:func:`colleague.loop_barrier.barrier_seat_config` sets — is pushed onto the
LIVE config object the acting completion closed over, for the duration of the
escalated point, and popped back to its exact prior state (present-with-value
vs absent) afterwards. It is a stack, so nesting is safe; nothing else about
the config is touched.

Bounds and honesty
------------------

* **At most once per gate per run** and **at most once per run** for the
  fill-line — the barrier's at-most-once discipline. The already-fired marker
  is an explicit ``_Work`` cell (``_effort_spikes_fired``) because the artifact
  record shape ``(point, rung, seat)`` cannot distinguish the two gates.
* Every firing appends one
  :meth:`colleague.effortspikes.SpikeRecord.to_dict` entry to
  ``TaskResult.effort_spikes``. Absence reads as did-not-fire.
* **Unarmed** (``COLLEAGUE_EFFORT_SPIKES`` unset — the default)
  :func:`make_escalator` returns ``None``, every function here is a strict
  no-op, no attribute is ever set, and the ``effort_spikes`` key never
  appears: byte-identical to v1.74.0.

Pure stdlib; no subprocess, no thread, no socket. There is no public function
here that accepts a rung — the two values come from the two fixed tables and
nowhere else (pinned in ``tests/test_gate_escalation.py``).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, List, Optional, Tuple

from colleague import effortspikes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.loop_types import _Work

#: The spike point a repeated gate repair escalates under (rung from
#: :data:`colleague.effortspikes.SPIKE_TABLE`).
GATE_POINT = "gate.repeat_failure"

#: The spike point the fill-line decision escalates under. Its rung is
#: DELEGATED to the design-site table (see :data:`DESIGN_SITE`).
FILLLINE_POINT = "fillline.decision"

#: The design call site whose rung :data:`FILLLINE_POINT` consumes — read via
#: :func:`colleague.fillline.design_seat_config`, never re-derived here.
DESIGN_SITE = "fillline.split"

#: The plain optional attribute that carries a per-completion rung to the wire
#: (``vllm_payload._effort_for``). Named once here for the same reason
#: ``samplingwire`` names its keys once.
_SEAT_ATTR = "reasoning_effort_seat"

#: The gate repair attempt (1-based loop iteration) from which a repair counts
#: as REPEATED. The first repair is never escalated.
FIRST_REPEATED_ATTEMPT = 2


class SeatEscalator:
    """Push/pop the acting config's per-completion rung (see the module docstring).

    Holds the LIVE config object the acting completion closed over. ``push``
    records whether the attribute was present and with what value, then sets
    the escalated rung; ``pop`` restores that exact state — deleting the
    attribute again when it was absent before, so an un-escalated run is
    indistinguishable from one that never escalated.
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._saved: List[Tuple[bool, Any]] = []

    def push(self, rung: str) -> None:
        holder = getattr(self._config, "__dict__", None)
        if holder is None:  # pragma: no cover - a slotted config can never carry the attr
            return
        present = _SEAT_ATTR in holder
        self._saved.append((present, holder.get(_SEAT_ATTR)))
        # The literal-argument ``setattr`` form on purpose: the effort-boundary
        # scanner (tests/test_thinking_effort_boundary.py) must SEE this
        # assignment, which is why this module joins its sanctioned set rather
        # than slipping past it through ``__dict__``.
        setattr(self._config, "reasoning_effort_seat", rung)

    def pop(self) -> None:
        if not self._saved:
            return
        present, value = self._saved.pop()
        if present:
            setattr(self._config, "reasoning_effort_seat", value)
            return
        holder = getattr(self._config, "__dict__", None)
        if holder is not None:  # absent before -> absent again (never a None row)
            holder.pop(_SEAT_ATTR, None)

    def fillline_rung(self) -> Optional[str]:
        """The ``fillline.split`` design-site rung for THIS config, or ``None``.

        Delegates to the shipped builder
        :func:`colleague.fillline.design_seat_config` — the live consumer of
        :data:`colleague.effort.DESIGN_SITE_TABLE`\\ ``["fillline.split"]`` —
        rather than reading the table (or a literal) here, so the c32
        precedence (operator ``reasoning_effort_seats["design"]`` override >
        the table; the ``default`` kill switch unsets it) is honoured in one
        place. ``None`` under the kill switch: nothing escalates.
        """
        from colleague import fillline as _fillline

        try:
            seat = _fillline.design_seat_config(self._config)
        except Exception:  # noqa: BLE001 - an escalation never aborts a run
            return None
        return getattr(seat, _SEAT_ATTR, None)


def make_escalator(config: Any) -> Optional[SeatEscalator]:
    """Bind the escalator, or ``None`` when nothing here can ever fire.

    ``None`` — the strict no-op — whenever the ``COLLEAGUE_EFFORT_SPIKES``
    opt-in is unset (the default). Nothing is built and the acting config is
    never touched.
    """
    if not effortspikes.spikes_enabled():
        return None
    return SeatEscalator(config)


def gate_rung() -> Optional[str]:
    """The repeated-gate-failure rung, from the fixed spike table and nowhere else."""
    return effortspikes.resolve_spike(GATE_POINT)


# ---------------------------------------------------------------------------
# Firing bookkeeping (at-most-once, recorded on the artifact)
# ---------------------------------------------------------------------------


def _escalator(ctx: "_Work") -> Optional[SeatEscalator]:
    return getattr(ctx, "gate_escalation", None)


def _fired(ctx: "_Work", key: str) -> bool:
    return key in getattr(ctx, "_effort_spikes_fired", ())


def _record(ctx: "_Work", key: str, point: str, rung: str) -> None:
    ctx._effort_spikes_fired.append(key)
    ctx.result.effort_spikes.append(
        effortspikes.SpikeRecord(point=point, rung=rung, seat=ctx.seat).to_dict()
    )


# ---------------------------------------------------------------------------
# gate.repeat_failure — the REPEATED repair turn
# ---------------------------------------------------------------------------


@contextmanager
def escalated_gate_turn(ctx: "_Work", gate: str, attempt: int) -> Iterator[bool]:
    """Run the enclosed gate repair turn at the repeat-failure rung when it applies.

    Yields ``True`` when the escalation actually fired (the caller needs no
    branch; the flag is there for tests and future observability), ``False``
    otherwise — which is every one of:

    * the spike surface is unarmed (no escalator bound) — the default;
    * this is the FIRST repair of this gate (``attempt`` below
      :data:`FIRST_REPEATED_ATTEMPT`) — the ordinary rung, unchanged;
    * this gate already escalated once this run (at-most-once);
    * the table declined the point.

    *attempt* is the gate's own 1-based loop iteration count — the
    deterministic signal named in the spec. Nothing here inspects the gate's
    report, the failing tests, or any model text.

    The unit of escalation is the repair ATTEMPT: the enclosed fix-turn is
    itself a bounded mini-loop (``_TESTINTEGRITY_FIX_STEPS`` /
    ``_AFFECTEDTESTS_FIX_STEPS`` extra model turns), so the one escalated
    replan covers up to that many completions inside its single attempt —
    recorded as ONE :class:`SpikeRecord`, and only that one attempt ever
    escalates (``_fired`` gates the rung itself, so later attempts run back
    at the ordinary rung). See ``docs/features/effort-spikes.md``.
    """
    escalator = _escalator(ctx)
    key = f"gate:{gate}"
    rung = (
        gate_rung()
        if escalator is not None and attempt >= FIRST_REPEATED_ATTEMPT and not _fired(ctx, key)
        else None
    )
    if escalator is None or rung is None:
        yield False
        return
    _record(ctx, key, GATE_POINT, rung)
    escalator.push(rung)
    try:
        yield True
    finally:
        escalator.pop()


# ---------------------------------------------------------------------------
# fillline.decision — the DECLARING turn
# ---------------------------------------------------------------------------


def arm_fillline_decision(ctx: "_Work") -> bool:
    """Escalate the turn that will DECLARE the fill-line move; ``True`` if it fired.

    Called where the decision prompt is injected
    (:func:`colleague.loop_context._offer_fillline`), because that prompt is
    consumed by the loop's ordinary next completion — the fill-line has no
    completion of its own to build a seat for (the honest limit
    :func:`colleague.fillline.design_seat_config` has documented since #416
    t6). The escalation is released by :func:`disarm_fillline_decision` the
    moment the declaration is recorded, so exactly the declaring turn — not
    the compaction turn that may follow it, and no later turn — carries the
    design-site rung.

    At most once per run (the barrier's discipline), even though the fill line
    re-arms per crossing. A no-op when unarmed, already fired, or the
    kill switch unset the design rung.
    """
    escalator = _escalator(ctx)
    if escalator is None or _fired(ctx, "fillline"):
        return False
    rung = escalator.fillline_rung()
    if rung is None:
        return False
    _record(ctx, "fillline", FILLLINE_POINT, rung)
    escalator.push(rung)
    ctx._fillline_escalated.append(True)
    return True


def disarm_fillline_decision(ctx: "_Work") -> None:
    """Release the declaring turn's escalation (a no-op when none is active)."""
    escalator = _escalator(ctx)
    if escalator is None or not ctx._fillline_escalated:
        return
    ctx._fillline_escalated.clear()
    escalator.pop()

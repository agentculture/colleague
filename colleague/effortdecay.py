"""Effort decay after a spike — the FIXED offset table + opt-in + record shape.

Spec ``docs/specs/2026-09-02-effort-floor-and-decay-arms.md`` (c3/c4/c5/c6).
Companion to :mod:`colleague.effortspikes` and kept SEPARATE from it for the
same file-length reason. Pure stdlib beyond one import from
``colleague.effort`` (``validate_effort``) and one from
``colleague.effortspikes`` (``spikes_enabled``); this module imports nothing
from :mod:`colleague.config`.

The shape #484's comment argued for — *"decide → medium, then low, then none
… until the next reset"* — as a fixed table keyed by the OFFSET of an acting
turn from the most recent spike (the reset):

``offset 1``
    The first acting turn after a spike runs at ``"low"``.

``offset >= 2``
    Every later acting turn runs at ``"off"`` — until the next reset restarts
    the count.

The reset vocabulary is EXACTLY the enumerated spike points
(:data:`colleague.effortspikes.SPIKE_POINTS`): the pre-mutation barrier, a
repeated-gate-failure escalation, the fill-line declaring turn. Nothing else
resets, and nothing here inspects turn content, a tool argument or a
model-supplied value — the rung for a turn is a pure function of
``(turns since the last reset)`` over :data:`DECAY_TABLE`. This is the second
RECORDED amendment of the thinking-effort invariant (convention change (8) in
CLAUDE.md): effort is resolved *"never per turn FROM CONTENT — per enumerated
point, or per fixed OFFSET from such a point, from a fixed table."*

Armed by ``COLLEAGUE_EFFORT_DECAY=1`` **and** the spike opt-in
(``COLLEAGUE_EFFORT_SPIKES=1``) — decay without a reset trigger is
meaningless, so the module stays inert unless both are set. Unarmed (the
default) :func:`decay_enabled` is ``False``, :func:`make_decay` returns
``None``, and no attribute on any config is ever touched: byte-identical to
v1.75.x.

The rung reaches the wire through the SAME seam every other effort consumer
uses — ``loop_gateescalation.SeatEscalator.push``/``pop`` on the live acting
config, read by ``vllm_payload._effort_for`` — wrapped around exactly one
acting completion at a time (:func:`colleague.loop_gateescalation.decayed_turn`).
This module never assigns the attribute itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from colleague.effort import validate_effort
from colleague.effortspikes import SPIKE_POINTS, spikes_enabled

#: The opt-in environment key (``"1"`` arms; anything else leaves it OFF).
DECAY_ENV = "COLLEAGUE_EFFORT_DECAY"

#: The FIXED offset table — ``offset -> rung`` for the named offsets, and
#: :data:`DECAY_FLOOR` for every offset past the last named one. A closed
#: table: no code path writes to it or accepts a model-supplied value in its
#: place.
DECAY_TABLE: dict[int, str] = {1: "low"}

#: The rung every acting turn past the last named offset runs at, until the
#: next reset.
DECAY_FLOOR = "off"

#: The reset vocabulary — exactly the enumerated spike points, re-exported so
#: the drift test pins the identity rather than a copy.
RESET_POINTS = SPIKE_POINTS


#: Values of ``COLLEAGUE_EFFORT_DECAY`` that turn the decay OFF (default ON
#: since row 77's operator decision; ``0`` / ``off`` / ``false`` / ``no``).
DECAY_DISABLING_VALUES = frozenset({"0", "off", "false", "no"})


def decay_enabled() -> bool:
    """Whether the decay surface is armed: ``COLLEAGUE_EFFORT_DECAY=1`` AND spikes armed."""

    return os.environ.get(DECAY_ENV, "1").strip() not in DECAY_DISABLING_VALUES and spikes_enabled()


def rung_for_offset(offset: int) -> Optional[str]:
    """The rung an acting turn *offset* turns after a reset runs at.

    ``None`` for a non-positive offset (the reset turn itself, or no reset
    yet — the seat's own floor applies, nothing is pushed). Otherwise the
    table row, or :data:`DECAY_FLOOR` past the named offsets — re-validated
    through the closed ladder like every other rung.
    """

    if offset <= 0:
        return None
    return validate_effort(DECAY_TABLE.get(offset, DECAY_FLOOR))


@dataclass
class DecayState:
    """The per-run decay clock: the turn of the last reset + what fired since.

    ``turn`` values are the run's model-turn count (``WorkStats.model_turns``)
    at the moment of the event; a completion about to run at count ``n`` is
    turn ``n + 1``, so its offset is ``(n + 1) - last_reset``.
    """

    last_reset: Optional[int] = None
    resets: list[int] = field(default_factory=list)
    turns: dict[str, int] = field(default_factory=dict)

    def reset(self, turn: int) -> None:
        """A spike point fired at model-turn *turn*: restart the offset clock."""

        self.last_reset = turn
        self.resets.append(turn)

    def rung_for(self, next_turn: int) -> Optional[str]:
        """The rung the completion that will be model-turn *next_turn* carries, or ``None``."""

        if self.last_reset is None:
            return None
        return rung_for_offset(next_turn - self.last_reset)

    def note(self, applied: str) -> None:
        """Count an acting turn that actually ran at a decayed *rung*."""

        self.turns[applied] = self.turns.get(applied, 0) + 1

    def to_dict(self) -> dict:
        """The artifact record ``{resets: [...], turns: {rung: n}}``; ``{}`` = nothing fired."""

        if not self.resets:
            return {}
        return {"resets": list(self.resets), "turns": dict(self.turns)}


def make_decay() -> Optional[DecayState]:
    """A fresh :class:`DecayState`, or ``None`` — the strict no-op — when unarmed."""

    if not decay_enabled():
        return None
    return DecayState()

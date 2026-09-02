"""Effort-spike table + opt-in + artifact record shape (#484, t5).

Companion module to :mod:`colleague.effort` and :mod:`colleague.efforttables`
— kept SEPARATE so neither grows past its file-length-ratchet baseline
(``tests/test_file_length_ratchet.py``). Pure stdlib beyond one import from
``colleague.effort`` (``validate_effort``); this module imports nothing from
:mod:`colleague.config` — ``config`` imports the effort modules, never the
reverse (same rule as ``efforttables.py``).

This module builds ONLY the table/flag/record shape. The consumers — the
pre-mutation decision barrier and the repeated-gate-failure replan escalation
(t8), and the fill-line wiring (t9) — are sibling tasks; nothing here calls a
model or touches the loop.

Spike surface v0 (spec ``docs/specs/2026-09-01-small-fixes-then-effort-balance.md``,
c18/c8/h5) was the LEAN set of exactly three enumerated points; the
effort-floor-and-decay arc added a FOURTH, ``stall.no_write`` (below):

``barrier.pre_mutation``
    The bounded, tools-off decision barrier consulted immediately before a
    turn's first mutating tool call (t8). Rung: ``"medium"``.

``gate.repeat_failure``
    The one-time escalation to a ``"medium"`` replan turn after a gate has
    failed repeatedly (retry count as the signal, t8). Rung: ``"medium"``.

``fillline.decision``
    The fill-line's own decision point. This module does NOT carry its own
    rung for it — :data:`colleague.effort.DESIGN_SITE_TABLE`\\ ``["fillline.split"]``
    already assigns ``"xhigh"`` to that exact call site (``effort.py:110``);
    duplicating a second rung here would let the two tables drift. The entry
    in :data:`SPIKE_TABLE` is the sentinel :data:`FILLLINE_DELEGATED` — "ask
    ``colleague.effort.DESIGN_SITE_TABLE['fillline.split']`` instead of this
    table" — and :func:`resolve_spike` refuses to resolve it directly.
    Wiring the existing consumer is t9's job, not this module's.

``stall.no_write``
    The stall decision turn (effort-floor-and-decay arc, rows 74-75): after
    :data:`STALL_TURNS` acting turns with no ``write_file``/``edit_file`` call
    since the run start, the last spike, or the last file write, the loop
    interposes the same tools-off decision turn the barrier uses, at most
    :data:`STALL_MAX_FIRES` times per run. The signal is a COUNT over tool
    NAMES — an ``off``-floor run that surveys forever never reaches the
    pre-mutation barrier, so this point is the one that can reach it. Rung:
    ``"medium"``.

``start.first_turn``
    The run's FIRST acting completion (the orientation turn), tools on, at
    ``"medium"`` — keyed by position (model turn 1), never content — after
    which the decay clock starts (turn 2 ``low``, turn 3+ ``off`` when decay
    is armed). Rung: ``"medium"``.

Every point maps to a rung from the CLOSED ladder validated by
:func:`colleague.effort.validate_effort` — never a value the model supplies.
There is no tool parameter and no function here that accepts a
model-controlled rung; :func:`resolve_spike` only ever returns a value drawn
from :data:`SPIKE_TABLE` (or its per-point env override, itself re-validated
through the same closed ladder).

Armed by the opt-in ``COLLEAGUE_EFFORT_SPIKES=1``. Unarmed (the default), the
module is inert: :func:`spikes_enabled` is ``False`` and
:func:`resolve_spike` always returns ``None`` regardless of what
:data:`SPIKE_TABLE` holds — so every outgoing payload stays byte-identical to
v1.74.0. This amends the recorded thinking-effort invariant in
``docs/features/thinking-effort.md`` (line 11): effort is resolved "never per
turn FROM CONTENT — per enumerated point from a fixed table" (the spike
surface reads a fixed table keyed by POINT NAME, never by inspecting turn
content or a model-supplied value).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from colleague.effort import validate_effort

#: Sentinel value for :data:`SPIKE_TABLE`'s ``"fillline.decision"`` entry —
#: "this point's rung is DELEGATED to ``colleague.effort.DESIGN_SITE_TABLE``
#: under the ``'fillline.split'`` key, not owned here." Never a resolvable
#: rung; :func:`resolve_spike` refuses to return it.
FILLLINE_DELEGATED = "__delegates_to_design_site_table_fillline_split__"

#: The closed, enumerated spike-point vocabulary (exactly five: three from
#: #484, c18/c8/h5, plus ``stall.no_write`` and ``start.first_turn`` from the
#: effort-floor-and-decay arc).
#: This tuple — not a re-derivation elsewhere — is the single source both
#: :data:`SPIKE_TABLE` and the drift test key off of.
SPIKE_POINTS = (
    "barrier.pre_mutation",
    "gate.repeat_failure",
    "fillline.decision",
    "stall.no_write",
    "start.first_turn",
)

#: ``stall.no_write`` (effort-floor-and-decay arc, decision q-stall): the number
#: of ACTING model turns without any file-writing tool call — counted from the
#: run start, the last spike, or the last file write, whichever is latest —
#: after which the stall decision turn fires. A COUNT over tool names, never a
#: reading of turn content.
STALL_TURNS = 10

#: The per-run cap on ``stall.no_write`` firings (bounded, like every spike).
STALL_MAX_FIRES = 3

#: point -> rung (or :data:`FILLLINE_DELEGATED` for the one delegated point).
#: A FIXED table only — no code path here ever writes to it or accepts a
#: model-supplied value in its place.
SPIKE_TABLE = {
    "barrier.pre_mutation": "medium",
    "gate.repeat_failure": "medium",
    "fillline.decision": FILLLINE_DELEGATED,
    "stall.no_write": "medium",
    "start.first_turn": "medium",
}


#: Values of ``COLLEAGUE_EFFORT_SPIKES`` that turn the surface OFF. Default
#: is ON since the effort-floor-and-decay arc (row 77, operator decision):
#: unset = armed; ``0`` / ``off`` / ``false`` / ``no`` = the pre-#484 wire.
SPIKES_DISABLING_VALUES = frozenset({"0", "off", "false", "no"})


def spikes_enabled() -> bool:
    """Whether the spike surface is armed.

    ``COLLEAGUE_EFFORT_SPIKES=1`` arms it; anything else (unset, ``"0"``,
    empty, any other string) leaves it OFF. Default is OFF — in a clean env
    this is ``False``, and every sibling function in this module becomes a
    strict no-op while it is.
    """

    return os.environ.get("COLLEAGUE_EFFORT_SPIKES", "1").strip() not in SPIKES_DISABLING_VALUES


def resolve_spike(point: str) -> Optional[str]:
    """Resolve ``point``'s effective rung, or ``None`` if it does not fire.

    Returns ``None`` whenever:

    - :func:`spikes_enabled` is ``False`` (the opt-in is unset) — the module
      stays inert;
    - ``point`` is not a member of :data:`SPIKE_POINTS`;
    - ``point`` is ``"fillline.decision"`` — that point is DELEGATED to
      :data:`colleague.effort.DESIGN_SITE_TABLE`\\ ``["fillline.split"]``
      (t9's job to wire), never resolved from this table.

    Otherwise: an explicit per-point override
    ``COLLEAGUE_EFFORT_SPIKE_<POINT>`` (point name upper-cased, ``.``
    replaced with ``_``) wins over :data:`SPIKE_TABLE`'s fixed row, following
    the same env-override precedent as ``efforttables.py``'s
    ``resolve_purpose_overrides``. Both the table value and any override are
    re-validated through :func:`colleague.effort.validate_effort` — the
    closed ladder is the only vocabulary a rung can come from; there is no
    parameter path by which a model (or tool call) supplies this value.
    """

    if not spikes_enabled():
        return None
    if point not in SPIKE_POINTS or point not in SPIKE_TABLE:
        return None

    row = SPIKE_TABLE[point]
    if row == FILLLINE_DELEGATED:
        return None

    env_name = "COLLEAGUE_EFFORT_SPIKE_" + point.upper().replace(".", "_")
    override = os.environ.get(env_name, "").strip()
    if override:
        return validate_effort(override)

    return validate_effort(row)


@dataclass(frozen=True)
class SpikeRecord:
    """The artifact record shape a fired spike emits: ``(point, rung, seat)``.

    Built by t8/t9 at the moment a spike actually fires (a tools-off barrier
    completion runs, a replan escalates, or the fill-line consumer resolves
    its design-site rung) and appended to the artifact's spike-record list.
    Absence of a record for a given point on a finished run reads as
    "did-not-fire" — there is no separate off/false record; the list is
    append-only and empty by default (including whenever
    :func:`spikes_enabled` is ``False``).
    """

    point: str
    rung: str
    seat: str

    def to_dict(self) -> "dict[str, str]":
        """Render as the plain JSON-safe dict the artifact serializes."""

        return {"point": self.point, "rung": self.rung, "seat": self.seat}

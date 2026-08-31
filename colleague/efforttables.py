"""Associate sub-seat + purpose-tool thinking-effort tables (purpose-tools-associate-seat, t1).

Companion module to :mod:`colleague.effort` — kept SEPARATE so
``colleague/effort.py`` never grows past its file-length-ratchet baseline
(``tests/test_file_length_ratchet.py``). Pure stdlib beyond one import from
``colleague.effort`` (``validate_effort``/``DEFAULT_SENTINEL``); this module
imports nothing from :mod:`colleague.config` — ``config`` imports the effort
modules, never the reverse.

Two new tables (c8/c29), on top of :mod:`colleague.effort`'s
``SEAT_TABLE``/``ROLE_TABLE``/``DESIGN_SITE_TABLE``:

``ASSOCIATE_SEAT_TABLE``
    A sub-seat table consulted per ``ASSOCIATE_SEATS`` member (scout,
    compact, synthesis, digest, distill) — each with its own env name
    ``COLLEAGUE_ASSOCIATE_REASONING_EFFORT_<SEAT>`` and its own
    ``reasoning_effort_seats`` key, ``"associate.<seat>"``. Deliberately
    agrees with :data:`colleague.effort.ROLE_TABLE`'s ``scout`` row (both
    ``"off"``) — the purpose-called scout's rung is a PURPOSE_TABLE row (an
    explicit override), while a MANUAL subagent ``role="scout"`` still
    resolves through the seat machinery; ``test_effort.py`` pins that the two
    rows agree.

``PURPOSE_TABLE``
    The rung a purpose tool's spawn passes as its explicit override (no
    'effort' parameter on the tool itself — the model cannot pick a rung).
    ``PURPOSE_STEPS`` is a sibling table: each purpose's step budget (a plain
    ``int``, or ``None`` for a purpose with no distinct cap of its own —
    ``handover_to_colleague`` rides the caller's).

Both new groups thread through the SAME ``reasoning_effort_seats``
config-file/artifact key as the existing per-seat overrides (dotted
``"associate.<seat>"`` keys never collide with a plain seat name); the
purpose group gets its own top-level key, ``reasoning_effort_purposes``.
"""

from __future__ import annotations

from typing import Callable, Optional

from colleague.effort import DEFAULT_SENTINEL, validate_effort

#: Associate sub-seats (adopt-from-qwen-code's ``ASSOCIATE_SEATS`` five-tuple),
#: each defaulting to the associate seat's own table row (``off``) except the
#: detached distill child, which reasons at ``low`` (plumbing, not a rung
#: choice — see the spec's s11).
ASSOCIATE_SEAT_TABLE = {
    "scout": "off",
    "compact": "off",
    "synthesis": "off",
    "digest": "off",
    "distill": "low",
}

#: Purpose-tool default rungs (c29) — the spawn's explicit override, never a
#: model-chosen 'effort' parameter.
PURPOSE_TABLE = {
    "web_survey": "off",
    "code_survey": "off",
    "review": "low",
    "validate": "low",
    "plan": "medium",
    "handover_to_colleague": "medium",
}

#: Each purpose's own step budget; ``None`` = no distinct cap (rides the
#: caller's ``max_steps``).
PURPOSE_STEPS: "dict[str, Optional[int]]" = {
    "web_survey": 12,
    "code_survey": 12,
    "review": 16,
    "validate": 16,
    "plan": 10,
    "handover_to_colleague": None,
}


def purpose_context_override(purpose: str) -> "Optional[int]":
    """The EXPERIMENT lever for a purpose child's context budget (#458 re-scoped).

    ``COLLEAGUE_<PURPOSE>_CONTEXT_BUDGET`` (e.g.
    ``COLLEAGUE_CODE_SURVEY_CONTEXT_BUDGET=65536``) caps the ONE named
    purpose's child window — the #461 doctrine that survey work belongs in a
    16K-64K band, wired through ``ChildSpec.context_budget_tokens`` (explicit
    beats derived; the associate seat still takes ``min(child, seat)``).
    Unset, empty, non-integer or ``<= 0`` -> ``None`` = the child inherits the
    parent's budget, byte-identical to today. An env-read helper by the
    ``actingsurface.acting_add_set`` precedent: an opt-in instrument for the
    row-64b arm, NEVER a shipped default until the arm promotes it.
    """
    import os

    raw = os.environ.get(f"COLLEAGUE_{purpose.upper()}_CONTEXT_BUDGET", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def resolve_associate_seat_overrides(
    pick: "Callable[..., str]",
    file_reasoning_effort_seats: "dict[str, str]",
) -> "dict[str, str]":
    """Resolve the per-associate-sub-seat overrides (c8).

    For each :data:`ASSOCIATE_SEAT_TABLE` member, reads
    ``COLLEAGUE_ASSOCIATE_REASONING_EFFORT_<SEAT>`` env, else
    ``file_reasoning_effort_seats["associate.<seat>"]`` (the SAME dict the
    plain seat overrides live in); every raw value is ladder-validated.
    Returns only the keys that were actually set — the dotted
    ``"associate.<seat>"`` shape, merged by the caller into the same
    ``reasoning_effort_seats`` dict :func:`colleague.effort.
    resolve_reasoning_effort_overrides` already produced.
    """
    resolved: "dict[str, str]" = {}
    for seat in ASSOCIATE_SEAT_TABLE:
        dotted = f"associate.{seat}"
        raw = (
            pick(
                None,
                f"COLLEAGUE_ASSOCIATE_REASONING_EFFORT_{seat.upper()}",
                default=file_reasoning_effort_seats.get(dotted, ""),
            )
            or None
        )
        if raw is not None:
            resolved[dotted] = validate_effort(raw)
    return resolved


def resolve_purpose_overrides(
    pick: "Callable[..., str]",
    file_reasoning_effort_purposes: "dict[str, str]",
) -> "dict[str, str]":
    """Resolve the per-purpose overrides (c29).

    For each :data:`PURPOSE_TABLE` member, reads
    ``COLLEAGUE_<PURPOSE>_REASONING_EFFORT`` env, else
    ``file_reasoning_effort_purposes[<purpose>]``; every raw value is
    ladder-validated. Returns only the keys that were actually set.
    """
    resolved: "dict[str, str]" = {}
    for purpose in PURPOSE_TABLE:
        raw = (
            pick(
                None,
                f"COLLEAGUE_{purpose.upper()}_REASONING_EFFORT",
                default=file_reasoning_effort_purposes.get(purpose, ""),
            )
            or None
        )
        if raw is not None:
            resolved[purpose] = validate_effort(raw)
    return resolved


def resolve_associate_sub_seat_effort(
    *,
    kill_switch: bool = False,
    parent_override: Optional[str] = None,
    seat_override: Optional[str] = None,
    row_override: Optional[str] = None,
    seat: str,
) -> Optional[str]:
    """Resolve an associate sub-seat's effective rung.

    Precedence, highest first: ``kill_switch`` > ``parent_override`` (an
    explicit caller-supplied override) > ``seat_override`` (the
    ``"associate.<seat>"`` override) > ``row_override`` (the whole-seat
    ``reasoning_effort_seats["associate"]`` override) >
    :data:`ASSOCIATE_SEAT_TABLE` > unset (``None``). ``DEFAULT_SENTINEL`` at
    any rung short-circuits to ``None``, mirroring
    :func:`colleague.effort.resolve_effort`.
    """
    if kill_switch:
        return None
    for candidate in (parent_override, seat_override, row_override):
        if candidate is None:
            continue
        if candidate == DEFAULT_SENTINEL:
            return None
        return validate_effort(candidate)
    if seat in ASSOCIATE_SEAT_TABLE:
        return validate_effort(ASSOCIATE_SEAT_TABLE[seat])
    return None


def resolve_purpose_effort(
    *,
    kill_switch: bool = False,
    parent_override: Optional[str] = None,
    purpose_override: Optional[str] = None,
    purpose: str,
) -> Optional[str]:
    """Resolve a purpose tool's effective rung.

    Precedence, highest first: ``kill_switch`` > ``parent_override`` >
    ``purpose_override`` (``reasoning_effort_purposes[<purpose>]``) >
    :data:`PURPOSE_TABLE` > unset (``None``). ``DEFAULT_SENTINEL`` at any
    rung short-circuits to ``None``.
    """
    if kill_switch:
        return None
    for candidate in (parent_override, purpose_override):
        if candidate is None:
            continue
        if candidate == DEFAULT_SENTINEL:
            return None
        return validate_effort(candidate)
    if purpose in PURPOSE_TABLE:
        return validate_effort(PURPOSE_TABLE[purpose])
    return None

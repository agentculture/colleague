"""Three thinking-effort groups — seats, associate sub-seats, purposes (t10).

Shared by ``colleague config show`` (``colleague/cli/_commands/config.py``)
and the session ``/effort`` verb (``colleague/cli/_commands/_session_actions.py``)
so both surfaces iterate :mod:`colleague.effort`'s ``SEAT_TABLE`` AND
:mod:`colleague.efforttables`'s ``ASSOCIATE_SEAT_TABLE``/``PURPOSE_TABLE`` —
a new associate sub-seat or purpose tool shows up in both without touching
either caller. New module under the file-length ratchet
(``tests/test_file_length_ratchet.py``): keeps ``config.py`` and
``_session_actions.py`` net-zero (or shrinking) instead of growing past
their pinned baselines.

Three groups, in display/precedence order:

``seats``
    :data:`colleague.effort.SEAT_TABLE` — plain seat names (``cortex``,
    ``worker``, ...), resolved via :func:`colleague.effort.resolve_effort`.
``associate``
    :data:`colleague.efforttables.ASSOCIATE_SEAT_TABLE` — dotted
    ``"associate.<seat>"`` names, resolved via
    :func:`colleague.efforttables.resolve_associate_sub_seat_effort` (which
    also consults the whole-seat ``"associate"`` override as a fallback rung
    between an explicit ``associate.<seat>`` override and the table default).
``purposes``
    :data:`colleague.efforttables.PURPOSE_TABLE` — purpose-tool names
    (``web_survey``, ...), resolved via
    :func:`colleague.efforttables.resolve_purpose_effort`.

Every resolution honours the SAME global kill-switch
(``config.reasoning_effort == effort.DEFAULT_SENTINEL``) the plain-seat
table already does. :func:`apply_group_effort` is the single mutation path
for a switch (CLI or session) naming any of the three groups (or ``"all"``,
which still only ever means the global seat-table knob — unchanged from
before this module existed); an unrecognised name raises ``ValueError``
naming every valid one.
"""

from __future__ import annotations

from typing import Any, Optional

from colleague import efforttables
from colleague.effort import (
    DEFAULT_SENTINEL,
    SEAT_TABLE,
    apply_operator_effort,
    resolve_effort,
    validate_effort,
)

__all__ = [
    "GROUP_TITLES",
    "apply_group_effort",
    "resolved_groups",
    "render_lines",
    "valid_names",
]

#: Display title per group, in render order.
GROUP_TITLES: "tuple[tuple[str, str], ...]" = (
    ("seats", "seats"),
    ("associate", "associate.<seat>"),
    ("purposes", "purposes"),
)


def _kill_switch(cfg: Any) -> bool:
    return cfg.reasoning_effort == DEFAULT_SENTINEL


def _seat_rows(cfg: Any, kill_switch: bool) -> "list[tuple[str, Optional[str]]]":
    rows = []
    for seat in SEAT_TABLE:
        override = cfg.reasoning_effort_seats.get(seat) or (
            cfg.reasoning_effort if not kill_switch else None
        )
        rows.append(
            (seat, resolve_effort(kill_switch=kill_switch, seat_override=override, seat=seat))
        )
    return rows


def _associate_rows(cfg: Any, kill_switch: bool) -> "list[tuple[str, Optional[str]]]":
    row_override = cfg.reasoning_effort_seats.get("associate")
    rows = []
    for seat in efforttables.ASSOCIATE_SEAT_TABLE:
        dotted = f"associate.{seat}"
        rung = efforttables.resolve_associate_sub_seat_effort(
            kill_switch=kill_switch,
            seat_override=cfg.reasoning_effort_seats.get(dotted),
            row_override=row_override,
            seat=seat,
        )
        rows.append((dotted, rung))
    return rows


def _purpose_rows(cfg: Any, kill_switch: bool) -> "list[tuple[str, Optional[str]]]":
    rows = []
    for purpose in efforttables.PURPOSE_TABLE:
        rung = efforttables.resolve_purpose_effort(
            kill_switch=kill_switch,
            purpose_override=cfg.reasoning_effort_purposes.get(purpose),
            purpose=purpose,
        )
        rows.append((purpose, rung))
    return rows


def resolved_groups(cfg: Any) -> "dict[str, dict[str, Optional[str]]]":
    """The three groups' resolved rungs, keyed ``seats``/``associate``/``purposes``."""
    kill_switch = _kill_switch(cfg)
    return {
        "seats": dict(_seat_rows(cfg, kill_switch)),
        "associate": dict(_associate_rows(cfg, kill_switch)),
        "purposes": dict(_purpose_rows(cfg, kill_switch)),
    }


def render_lines(cfg: Any, *, indent: str = "  ") -> "list[str]":
    """Text lines for all three groups, one name-rung pair per line."""
    kill_switch = _kill_switch(cfg)
    lines: "list[str]" = []
    for key, title in GROUP_TITLES:
        rows = {
            "seats": _seat_rows,
            "associate": _associate_rows,
            "purposes": _purpose_rows,
        }[
            key
        ](cfg, kill_switch)
        lines.append(f"{indent}{title}:")
        for name, rung in rows:
            lines.append(f"{indent}  {name}: {rung}")
    return lines


def valid_names() -> "list[str]":
    """Every switchable name across all three groups, plus ``all``."""
    names = ["all", *SEAT_TABLE]
    names += [f"associate.{seat}" for seat in efforttables.ASSOCIATE_SEAT_TABLE]
    names += list(efforttables.PURPOSE_TABLE)
    return names


def apply_group_effort(config: Any, value: str, name: str) -> str:
    """Validate *value* and set it for *name* — a seat, ``all``, an
    ``"associate.<seat>"`` name, or a purpose name. Returns the validated
    rung. Raises ``ValueError``/``CliError`` (:func:`colleague.effort.
    validate_effort`'s contract) naming the ladder on a bad rung, or
    ``ValueError`` naming every valid group member on an unknown *name*.
    """
    if name == "all" or name in SEAT_TABLE:
        return apply_operator_effort(config, value, name)
    rung = validate_effort(value)
    if name.startswith("associate.") and name.split(".", 1)[1] in efforttables.ASSOCIATE_SEAT_TABLE:
        seats = dict(getattr(config, "reasoning_effort_seats", {}) or {})
        seats[name] = rung
        config.reasoning_effort_seats = seats
        return rung
    if name in efforttables.PURPOSE_TABLE:
        purposes = dict(getattr(config, "reasoning_effort_purposes", {}) or {})
        purposes[name] = rung
        config.reasoning_effort_purposes = purposes
        return rung
    raise ValueError(f"unknown seat '{name}'; available: {', '.join(valid_names())}")

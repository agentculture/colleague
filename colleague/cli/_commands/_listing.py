"""Pure renderers for the served-model list and the per-seat effort table.

qwen-direct (spec c25/c26, plan t6): ``colleague work --model`` / ``--effort``
with NO value print what the operator could choose instead of refusing, and
the session's ``/model`` / ``/effort`` (t3/t4) render the SAME facts through
these functions. Everything here is pure over its inputs — the callers fetch
the gateway roster/roles and pass them in — so the text and the ``--json``
dict never drift apart. The listing is information, never a routing policy:
switching a seat stays an explicit operator choice.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from colleague import effort as _effort
from colleague.effort import apply_operator_effort as apply_effort  # noqa: F401 - re-exported

#: Sentinel an argparse ``nargs="?"`` flag receives when given with no value.
LIST_SENTINEL = "?"

#: Seats the effort table renders, in display order (the acting seat first).
EFFORT_SEATS: tuple[str, ...] = ("cortex", "worker", "deepthink", "evaluator", "senses", "design")

#: Advertised roles colleague consumes only by opt-in (qwen-direct c2/c4).
_OPT_IN_ROLES: Mapping[str, str] = {
    "senses": "COLLEAGUE_SENSES_MODEL=lobes",
    "muse": "COLLEAGUE_DEEPTHINK_MODEL=lobes",
}


def acting_seat(config: object) -> str:
    """The acting seat name: ``worker`` when the worker seat is armed, else ``cortex``."""
    return "worker" if getattr(config, "worker", None) is not None else "cortex"


def _roster_lines(roster: Optional[Sequence[str]], current_model: str) -> list[str]:
    """One line per served id (``None`` roster = could not fetch; ``[]`` = nothing served)."""
    if roster is None:
        return ["roster unavailable — /v1/models did not answer (down, 401, or malformed)"]
    if not roster:
        return ["served: (nothing served)"]
    return [
        f"served: {model_id}{'  ◀ current' if model_id == current_model else ''}"
        for model_id in roster
    ]


def _role_lines(roles: Optional[Mapping[str, str]], consumed_roles: Sequence[str]) -> list[str]:
    """One ``role → model (status)`` line per advertised role."""
    out: list[str] = []
    for role, model_id in (roles or {}).items():
        if role in consumed_roles:
            status = "consumed"
        elif role in _OPT_IN_ROLES:
            status = f"not consumed — opt-in: {_OPT_IN_ROLES[role]}"
        else:
            status = "not consumed"
        out.append(f"role {role} → {model_id} ({status})")
    return out


def _effort_source(seats: Mapping[str, str], seat: str, kill_switch: bool) -> str:
    if seats.get(seat):
        return "override"
    return "kill-switch" if kill_switch else "table"


def served_model_listing(
    *,
    current_model: str,
    roster: Optional[Sequence[str]],
    roles: Optional[Mapping[str, str]],
    lobes_armed: bool,
    consumed_roles: Sequence[str] = ("cortex",),
) -> tuple[str, dict[str, Any]]:
    """Render the served-model options around *current_model*.

    *roster* is the gateway's ``/v1/models`` ids (``None`` = could not be
    fetched — unreachable/401 — distinct from ``[]`` = nothing served);
    *roles* maps lobes role name → served model id (``None`` when lobes is
    unarmed or unreachable); *consumed_roles* names the roles the current
    config actually dials (``cortex`` always; ``senses``/``muse`` only when
    opted in). Returns ``(text, payload)``; never raises.
    """
    lines = [f"current model: {current_model}"]
    payload: dict[str, Any] = {
        "current_model": current_model,
        "lobes_armed": lobes_armed,
        "served": list(roster) if roster is not None else None,
        "roles": dict(roles) if roles else {},
        "consumed_roles": list(consumed_roles),
    }
    if not lobes_armed:
        lines.append("lobes not armed — no served roster to list (set COLLEAGUE_LOBES_URL)")
        return "\n".join(lines), payload
    lines.extend(_roster_lines(roster, current_model))
    lines.extend(_role_lines(roles, consumed_roles))
    lines.append(
        "switch: --model <id> (CLI) or /model <id> (session) — an explicit choice, never automatic"
    )
    return "\n".join(lines), payload


def effort_table(config: object) -> tuple[str, dict[str, Any]]:
    """Render the per-seat thinking-effort rungs *config* would send.

    The acting seat reads :func:`colleague.effort.effort_of` (what is actually
    sent); every other seat resolves through :func:`colleague.effort.resolve_effort`
    with the config's kill-switch and per-seat overrides — the same precedence
    the seat builders use, so the table matches the wire. ``unset`` means
    "send nothing" (the pre-#416 wire). Returns ``(text, payload)``.
    """
    global_value = getattr(config, "reasoning_effort", None)
    kill_switch = global_value == _effort.DEFAULT_SENTINEL
    seats: Mapping[str, str] = getattr(config, "reasoning_effort_seats", {}) or {}
    acting = acting_seat(config)
    rows: dict[str, Optional[str]] = {}
    for seat in EFFORT_SEATS:
        if seat == acting:
            # The ACTING seat is the one place the global override applies
            # (resolve_acting_effort); read what is actually sent.
            rows[seat] = _effort.effort_of(config)
            continue
        # Non-acting seats mirror their builders exactly (deepthink.py /
        # senses.py / design.py …): kill-switch > per-seat override > seat table.
        rows[seat] = _effort.resolve_effort(
            kill_switch=kill_switch, seat_override=seats.get(seat), seat=seat
        )
    lines = [
        "reasoning effort per seat (ladder: " + "|".join(_effort.LADDER) + " | default = unset):"
    ]
    for seat, rung in rows.items():
        src = _effort_source(seats, seat, kill_switch)
        if (
            seat == acting
            and not seats.get(seat)
            and global_value not in (None, _effort.DEFAULT_SENTINEL)
        ):
            src = "global override"
        lines.append(f"  {seat:<10} {rung if rung is not None else 'unset':<7} ({src})")
    lines.append("switch: --effort <rung> (CLI, acting seat) or /effort <rung> [seat] (session)")
    payload = {
        "ladder": list(_effort.LADDER),
        "kill_switch": kill_switch,
        "seats": rows,
        "overrides": dict(seats),
    }
    return "\n".join(lines), payload


def print_listings(
    config: object,
    repo: object,
    *,
    list_models: bool,
    list_effort: bool,
    json_mode: bool,
) -> int:
    """CLI glue for ``--model`` / ``--effort`` with no value: fetch, render, print, exit 0.

    Fetching is the only impure step: the lobes gateway URL (``config.py``
    precedence), its ``/v1/models`` roster (Bearer attached) and ``/capabilities``
    roles — each degrading to ``None``, never raising.
    """
    import json as _json
    import sys

    from colleague import lobes as _lobes
    from colleague.config import resolve_lobes_gateway_url

    out: dict[str, Any] = {}
    texts: list[str] = []
    if list_models:
        gateway = resolve_lobes_gateway_url(repo)
        roster = roles = None
        if gateway:
            roster = _lobes.fetch_served_model_ids(gateway, api_key=getattr(config, "api_key", ""))
            info = _lobes.resolve_roles(gateway)
            if info is not None:
                roles = {
                    name: getattr(getattr(info, name, None), "model", "")
                    for name in ("cortex", "senses", "muse", "worker", "stt", "tts")
                    if getattr(info, name, None) is not None
                }
        consumed = ["cortex"]
        if getattr(config, "senses", None) is not None:
            consumed.append("senses")
        if getattr(config, "deepthink", None) is not None:
            consumed.append("muse")
        text, payload = served_model_listing(
            current_model=str(getattr(config, "model", "")),
            roster=roster,
            roles=roles,
            lobes_armed=bool(gateway),
            consumed_roles=consumed,
        )
        texts.append(text)
        out["models"] = payload
    if list_effort:
        text, payload = effort_table(config)
        texts.append(text)
        out["effort"] = payload
    if json_mode:
        sys.stdout.write(_json.dumps(out) + "\n")
    else:
        sys.stdout.write("\n".join(texts) + "\n")
    return 0


def register_listing_flags(p: Any) -> None:
    """Add ``--model`` / ``--effort`` (value optional) to an argparse parser."""
    p.add_argument(
        "--model",
        nargs="?",
        const=LIST_SENTINEL,
        default=None,
        help="Override the engine model name; with no value, list the served options.",
    )
    p.add_argument(
        "--effort",
        nargs="?",
        const=LIST_SENTINEL,
        default=None,
        help="Acting-seat thinking effort (off|low|medium|high|xhigh|default); no value = table.",
    )


def model_arg(args: Any) -> Optional[str]:
    """The ``--model`` value for ``EngineConfig.resolve`` (``None`` when listing)."""
    value = getattr(args, "model", None)
    return None if value == LIST_SENTINEL else value


def maybe_list_and_apply(
    args: Any, config: object, repo: object, *, json_mode: bool
) -> Optional[int]:
    """Handle the t6 flags after resolve: list (→ exit code) or apply an effort.

    Returns an exit code when a bare ``--model`` / ``--effort`` asked for a
    listing (the caller returns it without running); ``None`` otherwise, after
    applying an explicit ``--effort <rung>`` to the acting seat.
    """
    list_models = getattr(args, "model", None) == LIST_SENTINEL
    effort_flag = getattr(args, "effort", None)
    if list_models or effort_flag == LIST_SENTINEL:
        return print_listings(
            config,
            repo,
            list_models=list_models,
            list_effort=effort_flag == LIST_SENTINEL,
            json_mode=json_mode,
        )
    if effort_flag is not None:
        apply_effort(config, effort_flag, acting_seat(config))  # the acting seat, not always cortex
    return None


#: (role name, the config attribute that shows it was consumed, the opt-in knob).
OPT_IN_ROLE_ATTRS: tuple[tuple[str, str, str], ...] = (
    ("senses", "senses", "COLLEAGUE_SENSES_MODEL=lobes"),
    ("muse", "deepthink", "COLLEAGUE_DEEPTHINK_MODEL=lobes"),
)


def not_consumed_roles_from(roles: object, cfg: object) -> list[tuple[str, str, str]]:
    """Pure: advertised opt-in roles *cfg* did not consume (qwen-direct c7/h7).

    *roles* is a :class:`colleague.lobes.LobesRoles` (or ``None``); each entry
    is ``(role, served model id, opt-in knob)`` for a role the gateway
    advertises whose consuming seat on *cfg* is ``None``. Shared by
    ``config show`` and ``lobes show`` so both print the same facts.
    """
    out: list[tuple[str, str, str]] = []
    if roles is None or cfg is None:
        return out
    for role_name, attr, knob in OPT_IN_ROLE_ATTRS:
        info = getattr(roles, role_name, None)
        model = str(getattr(info, "model", "") or "")
        if info is not None and model and getattr(cfg, attr, None) is None:
            out.append((role_name, model, knob))
    return out


def append_not_consumed(
    lines: list[str],
    gateway: str,
    cfg: object,
    *,
    roles: object = None,
    repo: object = None,
    indent: str = "  ",
) -> list[str]:
    """Append one ``not consumed (opt-in)`` line per unconsumed role; return the names.

    *cfg* may be ``None`` — then the SAME ``EngineConfig.resolve`` the fronts
    use is run against *repo* so the consumption fact is real, not guessed;
    *roles* may be ``None`` — then they are fetched from *gateway*. Every
    fetch degrades to "no lines", never raises.
    """
    from colleague import lobes as _lobes
    from colleague.config import EngineConfig

    if roles is None:
        roles = _lobes.resolve_roles(gateway)
    if cfg is None:
        try:
            cfg = EngineConfig.resolve(repo_path=repo)
        except Exception:  # pragma: no cover - degrade to "no consumption facts"
            cfg = None
    found = not_consumed_roles_from(roles, cfg)
    for name, model, knob in found:
        lines.append(f"{indent}not consumed (opt-in): {name} → {model} — {knob}")
    return [name for name, _m, _k in found]

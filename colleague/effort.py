"""Per-seat thinking-effort ladder (#416).

Pure stdlib — this module imports nothing from :mod:`colleague.loop` or
:mod:`colleague.config`; ``config`` imports ``effort``, never the reverse.
The one cross-module import (``colleague.cli._errors.CliError``) is the
shared error contract, not a runtime/config dependency.

The ladder is a five-rung total order::

    LADDER = ("off", "low", "medium", "high", "xhigh")

``DEFAULT_SENTINEL = "default"`` is the **kill-switch sentinel**: wherever it
appears in the precedence chain (as a ``parent_override`` or
``seat_override``), it means "send nothing" — :func:`resolve_effort` returns
``None`` for that call, exactly as if every input had been unset. It is not a
sixth ladder rung; it never appears in :data:`LADDER` and never flows into a
chat-template payload.

Tables (v3, c36/c40) map a seat / role / design-site name to its ladder rung.
``SEAT_TABLE`` covers persistent seats (cortex, worker, deepthink, evaluator,
senses, design). ``ROLE_TABLE`` covers subagent roles when invoked as a
child; ``TOP_LEVEL_ROLE_TABLE`` overrides a handful of those roles when
invoked at the top level (currently just ``explorer``). ``DESIGN_SITE_TABLE``
covers one-shot design/planning call sites (spec/plan stages, workforce
decomposition, autosplit, fill-line split, subagent decomposition) that
reason about structure rather than write code, and default to heavier
effort than the steady-state seats.

:func:`resolve_effort` applies the c32 precedence order: ``kill_switch`` >
``parent_override`` > ``seat_override`` (env/config) > the design-site table
> the role table > the seat table > unset (``None``). The first non-``None``
input wins; ``DEFAULT_SENTINEL`` at any precedence rung short-circuits to
``None`` immediately (the kill switch fires from wherever it is set, not
only from the dedicated ``kill_switch`` flag).

:func:`to_chat_template_kwargs` renders a resolved rung into the payload
fragment a chat-completions call merges into its request: ``"off"`` becomes
``{"enable_thinking": False}`` (the vLLM/Qwen3 toggle), any other rung
becomes ``{"reasoning_effort": rung}`` sent **verbatim**, and ``None`` /
``DEFAULT_SENTINEL`` produce ``None`` (no key added at all).

Honest limit (probe 2026-08-22): on the pinned Qwen3.8 rig, ``"high"`` and
``"xhigh"`` have been observed to produce indistinguishable reasoning
behavior — the model does not appear to expose a fifth distinct rung.
Colleague sends ``"high"`` verbatim anyway rather than silently upgrading it
to ``"xhigh"`` or collapsing the ladder: the five-rung vocabulary is a
contract with the *backend*, and a future backend (or a future Qwen
revision) may yet honor the distinction.
"""

from __future__ import annotations

from typing import Callable, Optional

LADDER = ("off", "low", "medium", "high", "xhigh")

DEFAULT_SENTINEL = "default"

# Persistent-seat defaults (v3, c36/c40).
SEAT_TABLE = {
    "cortex": "medium",
    "worker": "medium",
    "deepthink": "xhigh",
    "evaluator": "medium",
    "senses": "off",
    "design": "xhigh",
}

# Subagent-role defaults when invoked as a child (v3, c36/c40).
ROLE_TABLE = {
    "writer": "medium",
    "planner": "medium",
    "reviewer": "low",
    "validator": "low",
    "explorer": "off",
}

# Role overrides that apply only when the role is invoked at the top level
# (not as a subagent child).
TOP_LEVEL_ROLE_TABLE = {
    "explorer": "low",
}

# One-shot design/planning call sites (v3, c36/c40).
DESIGN_SITE_TABLE = {
    "plan.spec_stage": "xhigh",
    "plan.plan_stage": "high",
    "plan.workforce": "xhigh",
    "autosplit": "xhigh",
    "fillline.split": "xhigh",
    "subagents.decompose": "xhigh",
}


def validate_effort(value: str) -> str:
    """Return *value* unchanged if it's a valid ladder rung or the sentinel.

    Raises :class:`colleague.cli._errors.CliError` naming the full ladder
    (plus the sentinel) otherwise.
    """

    if value == DEFAULT_SENTINEL or value in LADDER:
        return value

    from colleague.cli._errors import EXIT_USER_ERROR, CliError

    allowed = ", ".join((*LADDER, DEFAULT_SENTINEL))
    raise CliError(
        EXIT_USER_ERROR,
        f"invalid thinking-effort value {value!r} — must be one of: {allowed}",
        f"pass one of: {allowed}",
    )


def resolve_effort(
    *,
    kill_switch: bool = False,
    parent_override: Optional[str] = None,
    seat_override: Optional[str] = None,
    role: Optional[str] = None,
    seat: Optional[str] = None,
    site: Optional[str] = None,
) -> Optional[str]:
    """Resolve the effective thinking-effort rung by the c32 precedence order.

    Highest first: ``kill_switch`` > ``parent_override`` > ``seat_override`` >
    :data:`DESIGN_SITE_TABLE` (``site``) > :data:`ROLE_TABLE` (``role``) >
    :data:`SEAT_TABLE` (``seat``) > unset (``None``). ``DEFAULT_SENTINEL`` at
    any rung short-circuits to ``None`` ("send nothing"); every candidate is
    ladder-validated. :data:`TOP_LEVEL_ROLE_TABLE` is a separate lookup callers
    feed in via ``parent_override``/``seat_override`` — never consulted here.
    """
    if kill_switch:
        return None
    for candidate in (parent_override, seat_override):
        if candidate is None:
            continue
        if candidate == DEFAULT_SENTINEL:
            return None
        return validate_effort(candidate)
    if site is not None and site in DESIGN_SITE_TABLE:
        return validate_effort(DESIGN_SITE_TABLE[site])
    if role is not None and role in ROLE_TABLE:
        return validate_effort(ROLE_TABLE[role])
    if seat is not None and seat in SEAT_TABLE:
        return validate_effort(SEAT_TABLE[seat])
    return None

    for candidate in (parent_override, seat_override):
        if candidate is None:
            continue
        if candidate == DEFAULT_SENTINEL:
            return None
        return validate_effort(candidate)

    if site is not None and site in DESIGN_SITE_TABLE:
        return validate_effort(DESIGN_SITE_TABLE[site])

    if role is not None and role in ROLE_TABLE:
        return validate_effort(ROLE_TABLE[role])

    if seat is not None and seat in SEAT_TABLE:
        return validate_effort(SEAT_TABLE[seat])

    return None


def resolve_acting_effort(
    *,
    worker_armed: bool,
    seats: dict,
    global_value: Optional[str],
    role: Optional[str],
) -> Optional[str]:
    """Resolve the ACTING seat's effective thinking-effort rung (#416 t2, c26/h17).

    The acting seat is ``"worker"`` when ``worker_armed`` (three-tier's worker
    seat is resolved), else ``"cortex"`` — colleague's acting-dial rule.
    Precedence: the global kill-switch (``global_value == DEFAULT_SENTINEL``)
    > an explicit override (``seats[seat]``, else ``global_value`` unless it
    IS the sentinel) > the top-level ``--role explorer`` rule
    (:data:`TOP_LEVEL_ROLE_TABLE`, "low" — "off" stays selectable via an
    explicit override) > the seat table default ("medium" for cortex/worker
    alike). Pure function over already-resolved config state — the caller
    (``EngineConfig.reasoning_effort_effective``) supplies ``role`` because it
    is set by the CLI AFTER ``resolve()`` returns.
    """
    seat = "worker" if worker_armed else "cortex"
    override = seats.get(seat)
    if override is None and global_value not in (None, DEFAULT_SENTINEL):
        override = global_value
    if override is None and role == "explorer":
        override = TOP_LEVEL_ROLE_TABLE["explorer"]
    return resolve_effort(
        kill_switch=global_value == DEFAULT_SENTINEL, seat_override=override, seat=seat
    )


def effort_of(config: object) -> Optional[str]:
    """Read the resolved thinking-effort rung off a seat's ``EngineConfig``.

    A pure READ mirroring ``vllm_openai._effort_for``'s precedence (#416 t7):
    the ``reasoning_effort_seat`` attribute wins when PRESENT (even ``None`` =
    send nothing); otherwise the acting seat's ``reasoning_effort_effective``.
    Record sites call this instead of recomputing from the tables — it is
    exactly what the backend sent (or would send) for that call.
    """
    # Presence wins (mirrors ``vllm_openai._effort_for``): an attribute set to
    # ``None`` means "send nothing" and is recorded as such; only an ABSENT
    # attribute falls back to the acting seat.
    if "reasoning_effort_seat" in getattr(config, "__dict__", {}):
        return config.__dict__["reasoning_effort_seat"]
    return getattr(config, "reasoning_effort_effective", None)


def to_chat_template_kwargs(effort_value: Optional[str]) -> Optional[dict]:
    """Render a resolved rung into the chat-template payload fragment.

    ``None``/``DEFAULT_SENTINEL`` -> ``None`` (no key added). ``"off"`` ->
    ``{"enable_thinking": False}``. Any other rung -> ``{"reasoning_effort":
    rung}``, sent verbatim (see the module docstring's honest limit on
    ``"high"`` vs ``"xhigh"``).
    """

    if effort_value is None or effort_value == DEFAULT_SENTINEL:
        return None

    validate_effort(effort_value)

    if effort_value == "off":
        return {"enable_thinking": False}

    return {"reasoning_effort": effort_value}


def resolve_reasoning_effort_overrides(
    pick: "Callable[..., str]",
    file_reasoning_effort: Optional[str],
    file_reasoning_effort_seats: "dict[str, str]",
    file_too_long_min: Optional[str],
    default_too_long_min: int,
) -> "tuple[Optional[str], dict[str, str], int]":
    """Resolve the reasoning-effort config-file/env overrides.

    Extracted from ``EngineConfig.resolve`` (SonarCloud S3776) — a PURE
    helper: *pick* is ``config._pick`` (explicit > ``COLLEAGUE_*`` env >
    config-file > default), passed in rather than imported, so this module
    stays dependency-free of :mod:`colleague.config` (the module docstring's
    "config imports effort, never the reverse" invariant). Every raw value
    is validated via :func:`validate_effort` exactly as the inline block
    did. Returns ``(global_value_or_None, seat_overrides, too_long_min)``.
    """
    resolved_reasoning_effort = (
        pick(None, "COLLEAGUE_REASONING_EFFORT", default=file_reasoning_effort or "") or None
    )
    if resolved_reasoning_effort is not None:
        resolved_reasoning_effort = validate_effort(resolved_reasoning_effort)

    resolved_reasoning_effort_seats: "dict[str, str]" = {}
    for seat in SEAT_TABLE:
        raw = (
            pick(
                None,
                f"COLLEAGUE_{seat.upper()}_REASONING_EFFORT",
                default=file_reasoning_effort_seats.get(seat, ""),
            )
            or None
        )
        if raw is not None:
            resolved_reasoning_effort_seats[seat] = validate_effort(raw)

    resolved_too_long_min = int(
        pick(
            None,
            "COLLEAGUE_TOO_LONG_MIN",
            default=file_too_long_min or str(default_too_long_min),
        )
    )

    return resolved_reasoning_effort, resolved_reasoning_effort_seats, resolved_too_long_min


def apply_operator_effort(config: object, value: str, seat: str = "cortex") -> str:
    """Operator switch (CLI ``--effort`` / session ``/effort``): validate, then set
    *value* for *seat* (``all`` = global; ``default`` = kill-switch). Session-only;
    lives here because the rung is assigned only in sanctioned modules."""
    rung = validate_effort(value)
    if seat == "all":
        config.reasoning_effort = rung
        return rung
    seats = dict(getattr(config, "reasoning_effort_seats", {}) or {})
    seats[seat] = rung
    config.reasoning_effort_seats = seats
    return rung

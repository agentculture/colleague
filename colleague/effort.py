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

from typing import Optional

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

    Precedence (highest first): ``kill_switch`` > ``parent_override`` >
    ``seat_override`` > the design-site table (``site``) > the role table
    (``role``, :data:`ROLE_TABLE`) > the seat table (``seat``,
    :data:`SEAT_TABLE`) > unset (``None``). ``DEFAULT_SENTINEL`` at any rung
    means "send nothing" and short-circuits to ``None``. Every non-``None``
    candidate is validated against the ladder.

    :data:`TOP_LEVEL_ROLE_TABLE` is a separate lookup for callers resolving a
    role invoked at the top level (not as a subagent child) — it is not
    consulted internally by this function; a caller resolving a top-level
    role passes that table's value in via ``role`` lookup against its own
    table, or via ``parent_override``/``seat_override``.
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

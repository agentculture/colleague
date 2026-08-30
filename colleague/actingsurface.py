"""Depth-aware curation for the top-level acting seat (deviation d14 fix).

Purpose tools (:mod:`colleague.purpose_schemas`) are offered to cortex/worker
at the TOP LEVEL only (operator decisions q9/q10,
``docs/specs/2026-08-28-purpose-tools-associate-seat.md``) — never to a
spawned child. Two facts :func:`colleague.loop.resolve_role` could not
express cleanly on its own before this module existed:

1. **Depth.** :mod:`colleague.subagents` stamps a dynamic ``child_depth``
   attribute on every child :class:`~colleague.config.EngineConfig` it builds
   (``_build_child_config`` / ``_child_config_for_profile``) — ``1`` for a
   top-level child, deeper for a grandchild. A config with no such attribute
   (the top-level acting seat itself, whatever CLI/engine built it, and the
   thought->action->evaluation worker seat — ``tae_loop`` repoints the ACTING
   dial at the worker without ever setting ``config.role``) reads as depth 0.

2. **The bare top-level carve-out (deviation d14).** Before this fix,
   ``resolve_role`` returned ``None`` for a bare (``config.role`` unset,
   ``agents`` mode unarmed) top-level run, and ``curate_schemas(None)`` — the
   "no role, full raw surface" contract every other caller still relies on
   (:data:`colleague.tools.SCHEMAS` unfiltered, kept byte-identical here) —
   offered the raw ``web``/``subagent``/``subagents`` tools and NONE of the
   six purpose tools: the t5 swap in :func:`colleague.roles._writer_allowlist`
   only ever reached an EXPLICIT ``role='writer'`` work item.
   :func:`curate_for_depth` is the ONE place that substitutes
   :data:`colleague.roles.BUILTIN_ROLES`\\ ``['writer']`` — already carrying
   that swap — for a bare ``None`` at depth 0, so a bare run and an explicit
   ``--role writer`` run offer the identical curated surface. This never
   touches ``curate_schemas(None)``'s own contract: it is still called
   directly (bypassing ``resolve_role``) by several pinning tests and by
   :func:`colleague.subagents._child_requested_tools`'s bare-name lookups.

3. **The never-inheritable strip (q9 + plan t11).** At depth >= 1 (any
   spawned child, any nesting level), the resolved role's allow-list is
   stripped of the six purpose-tool names AND of the raw
   ``subagent``/``subagents`` names — including a ``writer`` child
   (``handover_to_colleague``, or a manual roleless spawn that would
   otherwise default to the bare-run writer substitution above): it keeps
   the writer allow-list's t5 swap (no ``web``/``subagent``/``subagents``)
   but never the purpose tools themselves, so a writer child can neither
   fetch the web nor delegate further — a BOUNDED writer, deliberately
   narrower than the top-level acting seat. The raw-delegation half of this
   strip is DEFENCE IN DEPTH: arm 4 (plan t11) briefly restored
   ``subagent``/``subagents`` on the acting seat and the arm matrix rejected
   that reversal on evidence, but the strip stays so a child can never hold
   the raw pair even if the seat's allow-list changes again. A read-only
   child role
   (explorer/planner/reviewer/validator/scout) never held a purpose-tool
   name in the first place (they are absent from ``_READONLY_TOOLS``/
   ``_SCOUT_TOOLS``), so the strip is a no-op for them — they keep ``web``
   unchanged.

Pure: reads :mod:`colleague.roles`/:mod:`colleague.purpose_schemas` lazily
(inside the functions) to dodge the same import cycle
:func:`colleague.loop.resolve_role` already dodges for :mod:`colleague.roles`.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Optional

#: The dynamic attribute :mod:`colleague.subagents` stamps on every child
#: ``EngineConfig`` it builds — absent (or falsy) means "the top-level acting
#: seat", never a spawned child.
CHILD_DEPTH_ATTR = "child_depth"

#: The acting-seat-scoped tool drop knob (plan t8, the surface lever's
#: instrument). A comma-separated list of tool names the TOP-LEVEL acting seat
#: (depth 0 only) must not offer or call — e.g. ``grep_search,glob``. Unlike
#: ``COLLEAGUE_TOOLS_LEGACY`` (role-blind: ``curate_schemas`` consults it for
#: EVERY role, so it strips the scout child too, 8 tools -> 6), this knob is
#: applied at the ONE seam that already knows the depth, so a spawned child
#: keeps the named tools. Unset/empty means "no drop" — every rendered surface
#: is byte-identical to today.
ACTING_DROP_ENV = "COLLEAGUE_ACTING_DROP_TOOLS"

#: The acting-seat-scoped tool ADD knob (the surface lever's arm instrument,
#: spec c3/D3). The mirror of :data:`ACTING_DROP_ENV`: a comma-separated list
#: of tool names the TOP-LEVEL acting seat (depth 0 only) should GAIN — e.g.
#: ``web``. Applied at the SAME depth-0 seam, AFTER the drop knob, and only
#: for names that exist in :data:`colleague.tools.SCHEMAS`: an unknown name is
#: ignored and recorded nowhere (the knob is an arm instrument, never a gate).
#: Unset/empty means "no add" — every rendered surface is byte-identical to
#: today.
ACTING_ADD_ENV = "COLLEAGUE_ACTING_ADD_TOOLS"

#: The built-in role a seat with NO resolved role acts as — the ONE name the
#: bare-run substitution (deviation d14) names, referenced by
#: :func:`substitute_bare_role` and nowhere else.
DEFAULT_ACTING_ROLE = "writer"


def acting_drop_set() -> tuple[str, ...]:
    """The acting seat's named drop-set, read ONCE from ``ACTING_DROP_ENV``.

    Comma-separated tool names, whitespace-tolerant, order-preserving,
    de-duplicated. Unset or blank returns ``()`` — the "no drop" sentinel
    (``narrow_role_by_tool_set``'s empty-drop no-op), so an unarmed run is
    byte-identical to today.
    """
    raw = os.environ.get(ACTING_DROP_ENV, "")
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def acting_add_set() -> tuple[str, ...]:
    """The acting seat's named add-set, read ONCE from ``ACTING_ADD_ENV``.

    Comma-separated tool names, whitespace-tolerant, order-preserving,
    de-duplicated. Unset or blank returns ``()`` — the "no add" sentinel, so
    an unarmed run is byte-identical to today. (The SCHEMAS-existence filter
    is applied at the depth-0 seam, not here: this reader is the raw knob
    value, mirroring :func:`acting_drop_set`.)
    """
    raw = os.environ.get(ACTING_ADD_ENV, "")
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def child_depth(config: Any) -> int:
    """*config*'s nesting depth: 0 for the top-level acting seat, >= 1 for a
    spawned child (stamped by :mod:`colleague.subagents`)."""
    return int(getattr(config, CHILD_DEPTH_ATTR, 0) or 0)


def is_top_level(config: Any) -> bool:
    """``True`` for the acting seat itself; ``False`` for any spawned child."""
    return child_depth(config) == 0


#: The raw delegation tools a spawned child never inherits, no matter what the
#: acting seat holds (plan t11 / arm 4, KEPT after the arm was rejected).
#: Arm 4 restored these two names on the ACTING seat
#: (:func:`colleague.roles._writer_allowlist`) and this set is what kept the
#: restoration from leaking down the whole tree. The measured matrix rejected
#: arm 4 (zero raw-pair calls in 21 runs) and the seat is purpose-only again,
#: so the strip is now redundant with the allow-list — deliberately so: it is
#: the standing, allow-list-independent guarantee that a depth >= 1 child is
#: the bounded writer, whatever the seat later holds.
CHILD_FORBIDDEN_TOOLS: tuple[str, ...] = ("subagent", "subagents")


def strip_child_forbidden_tools(role: "Optional[Any]") -> "Optional[Any]":
    """Drop every never-inheritable name from *role*'s allow-list: the six
    purpose tools (q9 — a child never holds a purpose tool, no matter which
    role/purpose named it) and :data:`CHILD_FORBIDDEN_TOOLS` (plan t11 — a
    child never holds the raw ``subagent``/``subagents`` tools either; kept as
    defence in depth now that the acting seat is purpose-only again).

    ``None`` (no role at all) passes through unchanged; a role whose
    allow-list holds none of those names is returned unchanged (never a
    needless copy).
    """
    if role is None:
        return None
    from colleague.purpose_schemas import PURPOSE_TOOL_NAMES

    forbidden = set(PURPOSE_TOOL_NAMES) | set(CHILD_FORBIDDEN_TOOLS)
    if not (set(role.tool_allowlist) & forbidden):
        return role
    narrowed = tuple(t for t in role.tool_allowlist if t not in forbidden)
    return replace(role, tool_allowlist=narrowed)


def substitute_bare_role(role: "Optional[Any]") -> Any:
    """The ONE place a bare (``None``) role becomes
    :data:`colleague.roles.BUILTIN_ROLES`\\ ``[``:data:`DEFAULT_ACTING_ROLE`\\ ``]``.

    Both :func:`curate_for_depth` branches (depth 0 and depth >= 1) and the
    prompt half (:func:`acting_role_name`, consumed by
    :meth:`colleague.engine.Engine.system_prompt`) read the substitution from
    here, so the surface and the prompt can never disagree about which role is
    acting (plan t5). A non-``None`` *role* is returned unchanged.
    """
    if role is not None:
        return role
    from colleague.roles import BUILTIN_ROLES

    return BUILTIN_ROLES[DEFAULT_ACTING_ROLE]


def acting_role_name(config: Any, repo_path: str) -> "Optional[str]":
    """The role NAME this seat ACTS AS — the prompt half of the ONE resolution
    that already produces the tool surface (plan t5).

    Runs the SAME :func:`colleague.loop.resolve_role` the engines call in
    ``work()`` to build the curated schema and the role-aware executor, and
    returns the resolved role's ``name``. Because that resolution ends in
    :func:`curate_for_depth`, the depth-0 bare-run writer substitution
    (deviation d14) is no longer a surface-only fact: a bare run
    (``config.role`` unset) reports ``"writer"`` here, so
    :meth:`colleague.engine.Engine.system_prompt` composes the writer's prompt
    fragment — and an operator overlay at ``.colleague/agents/writer.md`` —
    exactly as an explicit ``--role writer`` run does.

    Seats that deliberately carry no role fragment are untouched, because the
    name they resolve to is not a built-in role and
    :func:`colleague.roles.load_role` refuses it: the #411 agents-mode seats
    narrow to the synthetic ``"narrowed"``/tools-off purpose role before this
    seam sees them, and the tools-off evaluator seat never reaches
    ``Engine.system_prompt`` at all (:mod:`colleague.tae_loop` composes its own
    prompt). ``None`` is returned only when no role resolved at all.
    """
    from colleague.loop import resolve_role

    role = resolve_role(config, repo_path)
    if role is None:
        return None
    name = getattr(role, "name", None)
    return str(name) if name else None


def curate_for_depth(role: "Optional[Any]", config: Any) -> "Optional[Any]":
    """The ONE seam :func:`colleague.loop.resolve_role` applies last, after
    every other role-resolution branch (name lookup, the #411 agents-mode
    purpose narrowing).

    Depth 0 (the top-level acting seat — bare, ``--role writer``, an armed
    agents-mode purpose, or the thought->action->evaluation worker seat),
    *role* ``None`` (bare, unarmed): substitutes
    :data:`colleague.roles.BUILTIN_ROLES`\\ ``['writer']`` — the top-level
    acting seat's real curated surface is never the raw, unfiltered
    ``SCHEMAS`` list again (deviation d14). Depth 0 with any other resolved
    role is returned unchanged EXCEPT for the acting-seat-scoped drop knob
    (plan t8): when ``COLLEAGUE_ACTING_DROP_TOOLS`` names tools, the resolved
    role is threaded through :func:`colleague.tools.narrow_role_by_tool_set`
    with that drop-set, so the acting seat loses the named tools while a
    spawned child keeps them. The drop is applied at depth 0 ONLY — this is
    the ONE seam that already knows the depth, which is exactly why
    ``COLLEAGUE_TOOLS_LEGACY`` (role-blind, consulted for every role) was
    rejected as the instrument. The acting-seat-scoped ADD knob
    (``COLLEAGUE_ACTING_ADD_TOOLS``, the surface lever's arm instrument, spec
    c3/D3) is applied at depth 0 AFTER the drop: only names that exist in
    :data:`colleague.tools.SCHEMAS` are added (an unknown name is ignored and
    recorded nowhere), so the acting seat gains the named tools while a
    spawned child never does.

    Depth >= 1 (a spawned child): a roleless spawn is ALSO defaulted to the
    writer role first (today's byte-identical default), then every resolved
    role — including that default — has its purpose-tool names AND the raw
    ``subagent``/``subagents`` names stripped
    (:func:`strip_child_forbidden_tools`, q9 + plan t11): children never hold
    a purpose tool, and never hold the raw delegation tools — independently of
    what the acting seat's allow-list happens to carry. The drop knob does NOT
    reach a child (depth >= 1 returns before it).
    """
    if is_top_level(config):
        role = substitute_bare_role(role)
        drop = acting_drop_set()
        if drop:
            from colleague.tools import narrow_role_by_tool_set

            role = narrow_role_by_tool_set(role, drop=drop)
        add = acting_add_set()
        if add:
            from colleague.tools import SCHEMAS

            known = {s["function"]["name"] for s in SCHEMAS}
            new = tuple(n for n in add if n in known and n not in role.tool_allowlist)
            if new:
                role = replace(role, tool_allowlist=role.tool_allowlist + new)
        return role
    return strip_child_forbidden_tools(substitute_bare_role(role))

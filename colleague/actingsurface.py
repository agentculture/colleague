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

3. **The never-inheritable purpose-tool strip (q9).** At depth >= 1 (any
   spawned child, any nesting level), the resolved role's allow-list is
   stripped of the six purpose-tool names — including a ``writer`` child
   (``handover_to_colleague``, or a manual roleless spawn that would
   otherwise default to the bare-run writer substitution above): it keeps
   the writer allow-list's t5 swap (no ``web``/``subagent``/``subagents``)
   but never the purpose tools themselves, so a writer child can neither
   fetch the web nor delegate further — a BOUNDED writer, deliberately
   narrower than the top-level acting seat. A read-only child role
   (explorer/planner/reviewer/validator/scout) never held a purpose-tool
   name in the first place (they are absent from ``_READONLY_TOOLS``/
   ``_SCOUT_TOOLS``), so the strip is a no-op for them — they keep ``web``
   unchanged.

Pure: reads :mod:`colleague.roles`/:mod:`colleague.purpose_schemas` lazily
(inside the functions) to dodge the same import cycle
:func:`colleague.loop.resolve_role` already dodges for :mod:`colleague.roles`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

#: The dynamic attribute :mod:`colleague.subagents` stamps on every child
#: ``EngineConfig`` it builds — absent (or falsy) means "the top-level acting
#: seat", never a spawned child.
CHILD_DEPTH_ATTR = "child_depth"


def child_depth(config: Any) -> int:
    """*config*'s nesting depth: 0 for the top-level acting seat, >= 1 for a
    spawned child (stamped by :mod:`colleague.subagents`)."""
    return int(getattr(config, CHILD_DEPTH_ATTR, 0) or 0)


def is_top_level(config: Any) -> bool:
    """``True`` for the acting seat itself; ``False`` for any spawned child."""
    return child_depth(config) == 0


def strip_purpose_tools(role: "Optional[Any]") -> "Optional[Any]":
    """Drop every purpose-tool name from *role*'s allow-list (q9: a child
    never holds a purpose tool, no matter which role/purpose named it).

    ``None`` (no role at all) passes through unchanged; a role whose
    allow-list holds none of the six names is returned unchanged (never a
    needless copy).
    """
    if role is None:
        return None
    from colleague.purpose_schemas import PURPOSE_TOOL_NAMES

    purposes = set(PURPOSE_TOOL_NAMES)
    if not (set(role.tool_allowlist) & purposes):
        return role
    narrowed = tuple(t for t in role.tool_allowlist if t not in purposes)
    return replace(role, tool_allowlist=narrowed)


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
    role is returned unchanged.

    Depth >= 1 (a spawned child): a roleless spawn is ALSO defaulted to the
    writer role first (today's byte-identical default), then every resolved
    role — including that default — has its purpose-tool names stripped
    (:func:`strip_purpose_tools`, q9): children never hold a purpose tool.
    """
    if is_top_level(config):
        if role is None:
            from colleague.roles import BUILTIN_ROLES

            return BUILTIN_ROLES["writer"]
        return role
    if role is None:
        from colleague.roles import BUILTIN_ROLES

        role = BUILTIN_ROLES["writer"]
    return strip_purpose_tools(role)

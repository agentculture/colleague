"""Hire tools — the two typed hiring schemas and their hidden-state rule
(spec/plan ``delegation-follow-ups-a7-p3-hire``, task t10, covers c17/h8).

This module is the single source of truth for the hire tool NAMES
(:data:`HIRE_TOOL_NAMES`) and their OpenAI function schemas
(:data:`HIRE_SCHEMAS`). Modelled on :mod:`colleague.purpose_schemas`'s
``offered``/``hidden_names`` shape: the schemas live OUTSIDE
:data:`colleague.tools.SCHEMAS` and are appended by ``curate_schemas``
exactly as the purpose schemas are, and neither exposes an ``effort``,
``model``, ``engine`` or ``role`` property — the only role choice is the
CLOSED ``base_role`` enum of builtin role names (never a tool list, never a
free-form role).

The hidden rule (the byte-identical off-state, spec c17): BOTH names are
hidden unless the resolved ``config.hire`` flag is armed
(``COLLEAGUE_HIRE`` env > config.json ``hire`` > OFF —
:mod:`colleague.config` resolves it once; this module reads the RESOLVED
flag threaded down from the caller, the
``purpose_schemas._thread_effort_config`` precedent — it never re-reads the
environment). Unarmed = zero wire change.

Declaration-only: the ``hire_colleague`` handler (the bounded two-round
negotiation) lands in t12 (``colleague/hire_dispatch.py``) and the
``assign_to_colleague`` handler in t13 (``colleague/hire_assign.py``); an
armed model call before those land costs one readable
``UnknownToolError`` step, never a crashed drive.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "BUILTIN_ROLE_NAMES",
    "HIRE_SCHEMAS",
    "HIRE_TOOL_NAMES",
    "PROMPT_MAX_CHARS",
    "WHEN_MAX_CHARS",
    "hidden_names",
    "offered",
]

#: The two hire tool names, in spec order: ``hire_colleague`` mints a
#: run-scoped employee (an agreed purpose + when clause over a builtin base
#: role); ``assign_to_colleague`` hands a live hire one scoped task.
HIRE_TOOL_NAMES: tuple[str, ...] = ("hire_colleague", "assign_to_colleague")

#: The authored-prompt / when-clause caps (spec h22): over-cap is a readable
#: refusal at hire time (t12), and the schema itself declares the same caps so
#: the model sees them up front.
PROMPT_MAX_CHARS = 2000
WHEN_MAX_CHARS = 200

#: The builtin role names a hire may base on — pinned literally (sorted) so
#: this module never imports :mod:`colleague.roles` (which imports THIS module
#: for ``_writer_allowlist``); ``tests/test_hire_schemas.py`` asserts this
#: tuple equals ``sorted(roles.BUILTIN_ROLES)`` so the two can never drift.
BUILTIN_ROLE_NAMES: tuple[str, ...] = (
    "explorer",
    "planner",
    "reviewer",
    "scout",
    "validator",
    "writer",
)

_HIRE_DESC = (
    "Hire a run-scoped colleague: negotiate an agreed purpose and when clause "
    "with a candidate based on one builtin role, authoring its standing prompt; "
    "the hire lives only for this run and is assigned work separately via "
    "assign_to_colleague."
)
_ASSIGN_DESC = (
    "Assign one scoped task to a colleague you already hired with "
    "hire_colleague; the hire's digest comes back as the tool result, to read "
    "before you act on it."
)


def _schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    """One OpenAI function schema in the ``purpose_schemas`` shape."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


#: The two hire schemas, keyed by name in spec order. Appended by
#: ``curate_schemas`` exactly as the purpose schemas are — never joined into
#: ``tools.SCHEMAS``. No effort/model/engine/role property (the model cannot
#: pick a rung, a backend, or a free-form role — c24/h27 precedent).
HIRE_SCHEMAS: dict[str, dict[str, Any]] = {
    "hire_colleague": _schema(
        "hire_colleague",
        _HIRE_DESC,
        {
            "purpose": {
                "type": "string",
                "description": "What the hire is for — the agreed purpose of the employment.",
            },
            "when": {
                "type": "string",
                "maxLength": WHEN_MAX_CHARS,
                "description": "The agreed when clause: the situations you will assign it work.",
            },
            "base_role": {
                "type": "string",
                "enum": list(BUILTIN_ROLE_NAMES),
                "description": "The builtin role the hire is based on (its tool surface).",
            },
            "prompt": {
                "type": "string",
                "maxLength": PROMPT_MAX_CHARS,
                "description": (
                    "The authored standing prompt for the hire. It describes, never "
                    "grants: the tool surface stays the base role's, unchanged."
                ),
            },
        },
        ["purpose", "when", "base_role", "prompt"],
    ),
    "assign_to_colleague": _schema(
        "assign_to_colleague",
        _ASSIGN_DESC,
        {
            "agent_id": {
                "type": "string",
                "description": "The id hire_colleague returned for the live hire.",
            },
            "task": {
                "type": "string",
                "description": "The scoped task to assign.",
            },
            "acceptance": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The acceptance criteria the assignment must satisfy.",
            },
        },
        ["agent_id", "task"],
    ),
}


def hidden_names(config: Any = None) -> frozenset[str]:
    """The hire names ``curate_schemas`` must drop right now.

    BOTH names, unless the resolved ``config.hire`` flag is armed (spec c17:
    the byte-identical off-state — ``COLLEAGUE_HIRE=1`` is what puts the two
    schemas on the seat). *config* is the resolved ``EngineConfig`` threaded
    down from the caller (the ``purpose_schemas._thread_effort_config``
    precedent: read the already-resolved flag, never re-resolve the env); a
    missing/config-less caller (``None``, or an object without the attribute)
    is unarmed.
    """
    if getattr(config, "hire", False):
        return frozenset()
    return frozenset(HIRE_TOOL_NAMES)


def offered(name: str, allow: "set[str] | None", config: Any = None) -> bool:
    """``curate_schemas``'s filter: in *allow* (``None`` = full surface) and not hidden."""
    return (allow is None or name in allow) and name not in hidden_names(config)

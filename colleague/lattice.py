"""Typed change lattice + authority ceiling (t4).

Pure data + validation, stdlib only: no I/O, no subprocess, no network.

This module defines the typed surface for *what* can change in a colleague
instance and *who* may change it. The lattice is the single source of truth
for the three-tier execution model:

* **Targets** — the five writable surfaces:
    ``worker.tools``, ``worker.prompt.strategist``, ``worker.knowledge``,
    ``senses.prompt.strategist``, ``senses.knowledge``.
* **Origins** — the three actors: ``host``, ``cortex``, ``worker``.
* **Authority ceiling** — origin rules governing which origin may write
  which target.

A :class:`CapabilityCatalog` is constructed *only* from a caller-supplied
resolved tool allow-list (never from a tool executor). Validation refuses
the **whole** unit when any change selects a tool id outside the catalog.

Operator-owned surfaces (approvals, hooks, command approvals, task roles,
mode gates, handoff policy) are **not** valid targets and refuse with a
recorded reason. Unknown targets, unknown/extra keys, or forbidden keys
refuse the whole unit — never stripping invalid fields and keeping the rest.

All refusals return a structured :class:`Verdict` with a ``reason`` string,
never an exception crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Target and Origin enums
# ---------------------------------------------------------------------------


class Target(Enum):
    """The five writable surfaces in the colleague lattice.

    These are the ONLY valid targets. Operator-owned surfaces
    (approvals, hooks, command approvals, task roles, mode gates,
    handoff policy) are explicitly NOT valid targets.
    """

    WORKER_TOOLS = "worker.tools"
    WORKER_PROMPT_STRATEGIST = "worker.prompt.strategist"
    WORKER_KNOWLEDGE = "worker.knowledge"
    SENSES_PROMPT_STRATEGIST = "senses.prompt.strategist"
    SENSES_KNOWLEDGE = "senses.knowledge"


class Origin(Enum):
    """The three actors that may propose or apply changes.

    * ``host`` — the operator / runtime (may write every target).
    * ``cortex`` — the driving model (may propose every target).
    * ``worker`` — a delegated subagent (may write ONLY ``senses.knowledge``).
    """

    HOST = "host"
    CORTEX = "cortex"
    WORKER = "worker"


# ---------------------------------------------------------------------------
# Forbidden / operator-owned target strings
# ---------------------------------------------------------------------------

#: Strings that name operator-owned surfaces — never valid lattice targets.
_OPERATOR_OWNED_TARGETS = frozenset(
    {
        "approvals",
        "hooks",
        "command_approvals",
        "task_roles",
        "mode_gates",
        "handoff_policy",
    }
)

#: Any key that is executable or capability-defining is forbidden.
_FORBIDDEN_KEYS = frozenset(
    {
        "executable",
        "capability",
        "capabilities",
        "policy",
        "gate",
        "gates",
        "allowlist",
        "allow_list",
        "denylist",
        "deny_list",
        "permissions",
        "permission",
        "access",
        "trust",
        "sandbox",
        "runtime",
        "daemon",
        "server",
        "mcp",
        "socket",
    }
)


# ---------------------------------------------------------------------------
# Knowledge entry type
# ---------------------------------------------------------------------------

#: The targets whose changes carry ``knowledge_entries`` (a knowledge entry is
#: a mapping that MUST contain a non-empty ``"origin"`` string naming which
#: actor authored it; other keys are free-form).  ``tool_ids`` are valid only
#: on :attr:`Target.WORKER_TOOLS` — a field on a target it does not belong to
#: is a malformed unit and refuses whole.
_KNOWLEDGE_TARGETS = frozenset({Target.WORKER_KNOWLEDGE, Target.SENSES_KNOWLEDGE})


# ---------------------------------------------------------------------------
# ChangeUnit — the typed change record
# ---------------------------------------------------------------------------


@dataclass
class ChangeUnit:
    """A typed change unit targeting one lattice surface.

    Attributes
    ----------
    target:
        The lattice surface being changed (one of :class:`Target`).
    origin:
        The actor proposing or applying the change (one of :class:`Origin`).
    tool_ids:
        Tool identifiers this change selects (only for ``worker.tools``
        targets).  Every id must exist in the :class:`CapabilityCatalog`.
    knowledge_entries:
        Knowledge records (only for ``*.knowledge`` targets).  Each entry
        is a ``dict`` that MUST contain a non-empty ``"origin"`` string.
    extra_fields:
        Any keys on the raw change payload that are not part of the
        canonical schema.  Presence of extra fields triggers a refusal.
    """

    target: Target
    origin: Origin
    tool_ids: list[str] = field(default_factory=list)
    knowledge_entries: list[dict[str, Any]] = field(default_factory=list)
    extra_fields: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# CapabilityCatalog — caller-supplied tool allow-list
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityCatalog:
    """A capability catalog constructed ONLY from a caller-supplied tool allow-list.

    This catalog has no constructor that reads a tool executor.  The caller
    resolves the allow-list (e.g. from :data:`colleague.tools.SCHEMAS` or a
    role's ``tool_allowlist``) and passes the resulting ids here.

    Attributes
    ----------
    tool_ids:
        The resolved set of tool identifiers this catalog recognises.
    """

    tool_ids: tuple[str, ...]


# ---------------------------------------------------------------------------
# Verdict — structured refusal / acceptance result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The outcome of validating one change unit.

    Attributes
    ----------
    allowed:
        ``True`` when the change passes all lattice checks.
    reason:
        A human-readable explanation, populated **only** when ``allowed``
        is ``False`` (an allowed verdict carries an empty reason).
    """

    allowed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# LatticeError — for programmatic misuse (not validation refusals)
# ---------------------------------------------------------------------------


class LatticeError(Exception):
    """Raised for programmatic misuse of the lattice API.

    Validation refusals return a :class:`Verdict` with ``allowed=False``.
    This exception is reserved for internal invariants (e.g. a caller
    passing a non-dict where a dict is required).
    """


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_valid_target(target: Any) -> bool:
    """Return ``True`` if *target* is a valid :class:`Target` enum member."""
    return isinstance(target, Target)


def _is_operator_owned(target_str: str) -> bool:
    """Return ``True`` if *target_str* names an operator-owned surface."""
    return target_str in _OPERATOR_OWNED_TARGETS


def _has_forbidden_keys(unit: ChangeUnit) -> list[str]:
    """Return any forbidden keys found on *unit*'s extra fields."""
    if unit.extra_fields is None:
        return []
    found = []
    for key in unit.extra_fields:
        if key.lower() in _FORBIDDEN_KEYS:
            found.append(key)
    return found


def _check_tool_ids(tool_ids: list[str], catalog: CapabilityCatalog) -> list[str]:
    """Return tool ids from *tool_ids* that are not in *catalog*."""
    catalog_set = set(catalog.tool_ids)
    return [tid for tid in tool_ids if tid not in catalog_set]


def _check_knowledge_origins(entries: list[dict[str, Any]]) -> list[str]:
    """Return keys of entries missing or having empty ``"origin"``."""
    bad = []
    for i, entry in enumerate(entries):
        origin_val = entry.get("origin")
        if not isinstance(origin_val, str) or not origin_val.strip():
            bad.append(str(i))
    return bad


# ---------------------------------------------------------------------------
# Authority rules
# ---------------------------------------------------------------------------

#: The targets each origin is permitted to write.
_AUTHORITY_MAP: dict[Origin, frozenset[Target]] = {
    Origin.HOST: frozenset(Target),  # host may write every target
    Origin.CORTEX: frozenset(Target),  # cortex may propose every target
    Origin.WORKER: frozenset({Target.SENSES_KNOWLEDGE}),  # worker: senses.knowledge only
}


# ---------------------------------------------------------------------------
# Per-check helpers — each returns a refusing Verdict, or None when the check
# passes. Extracted from validate_change (SonarCloud S3776) so the entry-point
# stays a flat sequence of "check, and return on refusal" lines; each helper
# owns exactly the ordered check its docstring names below.
# ---------------------------------------------------------------------------


def _check_target_validity(unit: ChangeUnit) -> Optional[Verdict]:
    """Check 1: the target must be a known :class:`Target` enum value.

    Unknown strings are refused; a string naming an operator-owned surface
    (approvals, hooks, etc.) gets the more specific reason.
    """
    if _is_valid_target(unit.target):
        return None
    # Check if it's an operator-owned string first (more specific reason).
    if isinstance(unit.target, str) and _is_operator_owned(unit.target):
        return Verdict(
            False,
            f"refused: {unit.target!r} is an operator-owned surface "
            f"(approvals, hooks, command approvals, task roles, mode gates, "
            f"handoff policy are not valid lattice targets)",
        )
    return Verdict(
        False,
        f"refused: unknown target {unit.target!r} " f"(valid targets: {[t.value for t in Target]})",
    )


def _check_forbidden_key_refusal(unit: ChangeUnit) -> Optional[Verdict]:
    """Check 2: forbidden executable/capability-defining keys refuse the
    whole unit — the more specific refusal, checked before extra keys so
    the recorded reason names the forbidden key exactly."""
    forbidden = _has_forbidden_keys(unit)
    if not forbidden:
        return None
    return Verdict(
        False,
        f"refused: forbidden executable/capability-defining keys "
        f"{forbidden!r} on change unit (no such key is ever a valid "
        f"lattice field)",
    )


def _check_extra_key_refusal(unit: ChangeUnit) -> Optional[Verdict]:
    """Check 3: any extra fields on the unit refuse the whole unit."""
    if unit.extra_fields is None:
        return None
    extra_keys = list(unit.extra_fields.keys())
    return Verdict(
        False,
        f"refused: extra keys on change unit {extra_keys!r} "
        f"(only target, origin, tool_ids, knowledge_entries are valid)",
    )


def _check_field_target_shape(unit: ChangeUnit) -> Optional[Verdict]:
    """Check 4: a field on a target it does not belong to is a malformed
    unit — ``tool_ids`` rides only ``worker.tools``, ``knowledge_entries``
    rides only the ``*.knowledge`` targets. Refuse whole, never ignore."""
    if unit.tool_ids and unit.target is not Target.WORKER_TOOLS:
        return Verdict(
            False,
            f"refused: tool_ids are only valid on "
            f"{Target.WORKER_TOOLS.value!r}, not {unit.target.value!r}",
        )
    if unit.knowledge_entries and unit.target not in _KNOWLEDGE_TARGETS:
        return Verdict(
            False,
            f"refused: knowledge_entries are only valid on "
            f"{sorted(t.value for t in _KNOWLEDGE_TARGETS)!r}, "
            f"not {unit.target.value!r}",
        )
    return None


def _check_authority_ceiling(unit: ChangeUnit) -> Optional[Verdict]:
    """Check 5: the origin must be permitted to write the target (worker
    may only write ``senses.knowledge``)."""
    allowed_targets = _AUTHORITY_MAP.get(unit.origin, frozenset())
    if unit.target in allowed_targets:
        return None
    return Verdict(
        False,
        f"refused: origin {unit.origin.value!r} may not write "
        f"target {unit.target.value!r} "
        f"(allowed targets for {unit.origin.value}: "
        f"{[t.value for t in allowed_targets]})",
    )


def _check_tool_catalog(unit: ChangeUnit, catalog: CapabilityCatalog) -> Optional[Verdict]:
    """Check 6: every tool id must exist in the catalog."""
    if not unit.tool_ids:
        return None
    unknown_tools = _check_tool_ids(unit.tool_ids, catalog)
    if not unknown_tools:
        return None
    return Verdict(
        False,
        f"refused: tool ids not in capability catalog {unknown_tools!r} "
        f"(catalog contains: {list(catalog.tool_ids)})",
    )


def _check_knowledge_entry_origins(unit: ChangeUnit) -> Optional[Verdict]:
    """Check 7: every knowledge entry must name its origin."""
    if not unit.knowledge_entries:
        return None
    bad_indices = _check_knowledge_origins(unit.knowledge_entries)
    if not bad_indices:
        return None
    return Verdict(
        False,
        f"refused: knowledge entries at indices {bad_indices!r} "
        f"missing or empty 'origin' field "
        f"(every knowledge entry must name its origin)",
    )


# ---------------------------------------------------------------------------
# Public validation entry-point
# ---------------------------------------------------------------------------


def validate_change(unit: ChangeUnit, catalog: CapabilityCatalog) -> Verdict:
    """Validate a :class:`ChangeUnit` against the lattice rules and *catalog*.

    Returns a :class:`Verdict` with ``allowed=True`` when the change passes
    all checks, or ``allowed=False`` with a ``reason`` string explaining
    the refusal.  **Never raises** — all validation paths return a Verdict.

    Checks performed (in order; first failure wins — each below is a
    dedicated helper, named for the check it owns):

    1. **Target validity** (:func:`_check_target_validity`) — the target
       must be a known :class:`Target` enum value. Unknown strings are
       refused; a string naming an operator-owned surface (approvals,
       hooks, etc.) gets the more specific reason.
    2. **Forbidden keys** (:func:`_check_forbidden_key_refusal`) — any
       executable or capability-defining keys refuse the whole unit
       (checked before extra keys so the reason names the specific
       forbidden key).
    3. **Extra keys** (:func:`_check_extra_key_refusal`) — any other
       extra fields on the unit refuse the whole unit.
    4. **Field/target shape** (:func:`_check_field_target_shape`) —
       ``tool_ids`` only rides ``worker.tools``; ``knowledge_entries``
       only rides the ``*.knowledge`` targets.
    5. **Authority ceiling** (:func:`_check_authority_ceiling`) — the
       origin must be permitted to write the target (worker may only
       write ``senses.knowledge``).
    6. **Tool catalog** (:func:`_check_tool_catalog`) — every tool id
       must exist in the catalog.
    7. **Knowledge origins** (:func:`_check_knowledge_entry_origins`) —
       every knowledge entry must name its origin.
    """
    verdict = _check_target_validity(unit)
    if verdict is not None:
        return verdict

    verdict = _check_forbidden_key_refusal(unit)
    if verdict is not None:
        return verdict

    verdict = _check_extra_key_refusal(unit)
    if verdict is not None:
        return verdict

    verdict = _check_field_target_shape(unit)
    if verdict is not None:
        return verdict

    verdict = _check_authority_ceiling(unit)
    if verdict is not None:
        return verdict

    verdict = _check_tool_catalog(unit, catalog)
    if verdict is not None:
        return verdict

    verdict = _check_knowledge_entry_origins(unit)
    if verdict is not None:
        return verdict

    return Verdict(True)

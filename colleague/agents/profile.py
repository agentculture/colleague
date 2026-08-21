"""Model-bound agent profiles (#411, plan task t1).

A *profile* is the typed identity record for one model-bound agent seat: the
*purpose* it serves, the lobes *role* that purpose maps to, the *model* it
actually resolved to (trace data, filled from the gateway's advert), the
*tool-profile id* it carries, and its authority / lineage.

**Purpose before tools.** The profile names a ``tool_profile`` id (a plain
string); it never carries a tool list. The id is resolved to a concrete
effective tool surface by ``colleague/agents/tools.py`` (plan task t2). This
keeps the identity record free of any tool-shape coupling, so a profile
validates without any network.

**No vendor model names.** The reference topology (Talker=senses,
Worker=worker — dormant per deviation d3, Thinker/Coder=cortex, and the
reserved fast-coder Associate=associate) is named *by lobes role*, never by
model family. ``resolved_model`` is trace data filled from ``RoleInfo.model`` at
resolution time — it is never a constant in this module. A grep guard in
``tests/test_agents_profile.py`` pins that no file under ``colleague/agents/``
names a vendor model.

**Fallback, never refusal.** When a purpose's lobes role is absent or not
ready, :func:`resolve_profile` carries the purpose on the *cortex* model under
a RECORDED fallback (``fallback_from_role`` = the purpose's role). It never
refuses all work and never falls back silently.

Modelled on ``roles.Role`` (roles.py:27-57) and ``lobes.RoleInfo``
(lobes.py:154-171). Stdlib only; no imports from ``colleague/loop.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

__all__ = [
    "AgentProfile",
    "DORMANT_PURPOSES",
    "PURPOSES",
    "PURPOSE_ROLE",
    "Resolution",
    "SCHEMA_VERSION",
    "resolve_profile",
]

#: Schema version of the :class:`AgentProfile` record. Bump additively when a
#: field is added; readers refuse unknown versions (fail closed).
SCHEMA_VERSION = 1

#: The closed set of agent purposes. A purpose is *what the agent is for*,
#: resolved to a lobes role by :data:`PURPOSE_ROLE` — never to a model family.
PURPOSES = frozenset({"talker", "worker", "thinker_coder", "associate"})

#: The enumerated purpose→role map (spec q5: an enumerated table, not a
#: router). talker→senses (the tools-off front door), worker→worker (the
#: bounded-tool-loop actor seat), thinker_coder→cortex (the reasoner that holds
#: coding authority).
PURPOSE_ROLE = {
    "talker": "senses",
    "worker": "worker",
    "thinker_coder": "cortex",
    "associate": "associate",
}

#: Deviation d3 (operator, 2026-08-21): the non-coding ``worker`` purpose stays
#: DORMANT — its profile exists, the role is never bound — until a FAST CODER
#: model arrives; that agent is the ``associate`` purpose, reserved by name now
#: (lobes role ``associate``; absent on the gateway today → the same recorded
#: cortex fallback). Routine coding routes to ``associate`` when present, else
#: ``thinker_coder`` — never to ``worker``.
DORMANT_PURPOSES = frozenset({"worker"})

#: The floor role every purpose falls back to when its own role is absent or
#: not ready (spec q1: "for now cortex runs ALL roles").
_FALLBACK_ROLE = "cortex"


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving one purpose to a served model.

    ``model_role`` is the lobes role the purpose actually resolved to (its own
    role when ready, else the floor). ``resolved_model`` is the served model id
    (trace data from ``RoleInfo.model``). ``fallback_from_role`` names the role
    the purpose was carried *from* when it fell back to the floor — ``None``
    when the purpose ran on its own ready role.
    """

    model_role: str
    resolved_model: str
    fallback_from_role: Optional[str] = None


@dataclass(frozen=True)
class AgentProfile:
    """The typed identity record for one model-bound agent seat.

    Attributes
    ----------
    agent_id:
        Stable id for this agent instance (the lineage root for its records).
    purpose:
        One of :data:`PURPOSES` — what the agent is for.
    model_role:
        The lobes role the purpose resolved to (its own role when ready, else
        the floor). A role name, never a model family.
    resolved_model:
        The served model id (trace data, filled from ``RoleInfo.model``).
    tool_profile:
        A tool-profile *id* (string) resolved to a concrete surface by a later
        task — never a tool list (purpose before tools).
    authority_profile:
        The authority-ceiling id for this seat (a closed enum resolved by a
        later task).
    parent_agent_id:
        The ``agent_id`` of the delegating parent, or ``None`` for a root.
    task_id:
        The task this agent belongs to.
    fallback_from_role:
        The role this purpose was carried from when it fell back to the floor
        (``None`` when it ran on its own ready role).
    schema_version:
        :data:`SCHEMA_VERSION` — readers refuse unknown versions.
    """

    agent_id: str
    purpose: str
    model_role: str
    resolved_model: str
    tool_profile: str
    authority_profile: str
    parent_agent_id: Optional[str]
    task_id: str
    fallback_from_role: Optional[str]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.purpose not in PURPOSES:
            raise ValueError(f"unknown purpose: {self.purpose!r}")

    def to_dict(self) -> dict:
        """Serialize to a plain dict (all fields; None values preserved)."""
        return {
            "agent_id": self.agent_id,
            "purpose": self.purpose,
            "model_role": self.model_role,
            "resolved_model": self.resolved_model,
            "tool_profile": self.tool_profile,
            "authority_profile": self.authority_profile,
            "parent_agent_id": self.parent_agent_id,
            "task_id": self.task_id,
            "fallback_from_role": self.fallback_from_role,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentProfile":
        """Reconstruct a profile from :meth:`to_dict` output (round-trip)."""
        return cls(
            agent_id=data["agent_id"],
            purpose=data["purpose"],
            model_role=data["model_role"],
            resolved_model=data["resolved_model"],
            tool_profile=data["tool_profile"],
            authority_profile=data["authority_profile"],
            parent_agent_id=data.get("parent_agent_id"),
            task_id=data["task_id"],
            fallback_from_role=data.get("fallback_from_role"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


def resolve_profile(purpose: str, roles) -> Resolution:
    """Resolve *purpose* to a served model against *roles* (pure, no network).

    *roles* is a ``lobes.LobesRoles`` (or a test double) exposing ``.cortex``,
    ``.senses``, ``.worker`` and (once advertised) ``.associate`` — each a
    ``RoleInfo``-like with ``.model`` and ``.ready`` (``.worker`` / ``.associate``
    may be ``None`` or simply absent when the gateway didn't advertise one).

    When the purpose's role is present and ready, it resolves to that role's
    model (no fallback). Otherwise the purpose is carried on the *cortex* model
    under a RECORDED fallback (``fallback_from_role`` = the purpose's role) —
    never a refusal, never silent.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose: {purpose!r}")
    role_name = PURPOSE_ROLE[purpose]
    role = getattr(roles, role_name, None)
    if role is not None and role.ready:
        return Resolution(model_role=role_name, resolved_model=role.model)
    floor = getattr(roles, _FALLBACK_ROLE, None)
    if floor is None:
        raise ValueError(f"no {_FALLBACK_ROLE} role available to fall back to")
    # Record the cross-role fallback only when we actually left the purpose's
    # own role (a not-ready floor is still the floor — nothing to fall back from).
    fallback = role_name if role_name != _FALLBACK_ROLE else None
    return Resolution(
        model_role=_FALLBACK_ROLE,
        resolved_model=floor.model,
        fallback_from_role=fallback,
    )

"""The Hire record, roster and prompt-never-grants role builder (plan t9).

``delegation-follow-ups-a7-p3-hire`` spec c14 / honesty h7: a *hire* is a
run-scoped employee cortex takes on — an agreed *purpose* plus a *when*
clause — realized as a runtime overlay on ONE builtin role. The overlay is
exactly the shape :func:`colleague.roles.load_role` gives an operator
``.colleague/agents/<role>.md`` file: ``replace(BUILTIN_ROLES[base],
prompt_fragment=authored)`` — the prompt is replaced, the tool allow-list is
kept. **The prompt describes, never grants**: an authored prompt that names
write/delegation/hire tools changes nothing about the surface, because the
surface is derived only from the base role's allow-list through the SAME
depth>=1 seam every spawned child passes
(:func:`colleague.actingsurface.strip_child_forbidden_tools`), minus the hire
pair itself — so a hire can never hire, and authority ⊆ hirer holds by
construction.

Discipline mirrors :mod:`colleague.agents.profile`: stdlib only at import
time; every colleague import (:mod:`colleague.roles`,
:mod:`colleague.actingsurface`, :mod:`colleague.contract`,
:mod:`colleague.config`) is lazy, inside the function that needs it; no
imports from :mod:`colleague.loop`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Optional

__all__ = [
    "HIRE_TOOL_NAMES",
    "Hire",
    "HireError",
    "MAX_PROMPT_CHARS",
    "MAX_WHEN_CHARS",
    "Roster",
    "STATUSES",
    "hired_child_surface",
    "hired_role",
    "mint_hire",
]

#: The two hire tool names. Defined here for now so t9's surface math has the
#: pair to exclude; plan task t10's ``colleague/hire_schemas.py`` will own the
#: canonical ``HIRE_TOOL_NAMES`` (schemas + hidden rule) — when it lands, this
#: constant becomes a re-export/consumer of that one, never a second source.
HIRE_TOOL_NAMES: tuple[str, ...] = ("hire_colleague", "assign_to_colleague")

#: Cap on the authored prompt fragment (spec h22: the tool schema caps the
#: prompt; over-cap is a readable refusal, never a crashed drive).
MAX_PROMPT_CHARS = 2000

#: Cap on the agreed when clause (same h22 contract).
MAX_WHEN_CHARS = 200

#: The closed status vocabulary. ``live`` = assignable this run; ``expired`` =
#: dead at the cut (decision D43 — a continuation/episode rehydrates hires as
#: expired, never as live).
STATUSES: tuple[str, ...] = ("live", "expired")


class HireError(Exception):
    """A readable hire refusal (unknown base, over-cap text, roster full).

    Callers surface ``str(exc)`` as the tool result — never a traceback.
    """


def _builtin_role_names() -> tuple[str, ...]:
    from colleague.roles import BUILTIN_ROLES

    return tuple(sorted(BUILTIN_ROLES))


@dataclass(frozen=True)
class Hire:
    """One run-scoped hired employee.

    Attributes
    ----------
    agent_id:
        Stable id for this hire within the run (the handle
        ``assign_to_colleague`` addresses).
    hirer_id:
        Id of the seat that hired (cortex on the acting seat).
    base_role:
        The builtin role the hire overlays — a
        :data:`colleague.roles.BUILTIN_ROLES` key, validated on construction.
    purpose:
        The agreed purpose (free text, negotiated).
    when:
        The agreed when clause (<= :data:`MAX_WHEN_CHARS` chars).
    prompt_fragment:
        The authored prompt overlay (<= :data:`MAX_PROMPT_CHARS` chars). It
        describes the hire's job; it never grants tools.
    prompt_digest:
        ``contract.prompt_digest_for(prompt_fragment)`` — the refs-not-
        payloads handle the ledger carries instead of the text.
    status:
        One of :data:`STATUSES`.
    task_id:
        The task the hire was minted in.
    created_step:
        The hirer's ``step_count`` at mint time.
    """

    agent_id: str
    hirer_id: str
    base_role: str
    purpose: str
    when: str
    prompt_fragment: str
    prompt_digest: Optional[str]
    status: str
    task_id: str
    created_step: int

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise HireError(
                "unknown hire status %r — must be one of: %s" % (self.status, ", ".join(STATUSES))
            )
        _validate_base_role(self.base_role)
        _validate_lengths(self.prompt_fragment, self.when)

    def to_dict(self) -> dict[str, Any]:
        """Plain-JSON dict of every field (artifact serialization shape)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hire":
        """Rebuild a :class:`Hire` from :meth:`to_dict` output.

        Unknown keys are ignored (additive readers); the same validation as
        construction applies, so a corrupt record raises :class:`HireError`.
        """
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _validate_base_role(base_role: str) -> None:
    names = _builtin_role_names()
    if base_role not in names:
        raise HireError(
            "unknown base role %r — a hire overlays a builtin role: %s"
            % (base_role, ", ".join(names))
        )


def _validate_lengths(prompt_fragment: str, when: str) -> None:
    if len(prompt_fragment) > MAX_PROMPT_CHARS:
        raise HireError(
            "authored prompt is %d chars — the cap is %d" % (len(prompt_fragment), MAX_PROMPT_CHARS)
        )
    if len(when) > MAX_WHEN_CHARS:
        raise HireError("when clause is %d chars — the cap is %d" % (len(when), MAX_WHEN_CHARS))


def mint_hire(
    *,
    agent_id: str,
    hirer_id: str,
    base_role: str,
    purpose: str,
    when: str,
    prompt_fragment: str,
    task_id: str,
    created_step: int,
) -> Hire:
    """Validate + mint one live :class:`Hire`.

    Computes ``prompt_digest`` via
    :func:`colleague.contract.prompt_digest_for` (the ONE digest function the
    whole runtime uses for composed prompt text), so the ledger's
    refs-not-payloads event and the artifact's hires block can never disagree
    about what was authored. Raises :class:`HireError` on an unknown base or
    over-cap text.
    """
    from colleague.contract import prompt_digest_for

    return Hire(
        agent_id=agent_id,
        hirer_id=hirer_id,
        base_role=base_role,
        purpose=purpose,
        when=when,
        prompt_fragment=prompt_fragment,
        prompt_digest=prompt_digest_for(prompt_fragment),
        status="live",
        task_id=task_id,
        created_step=created_step,
    )


class Roster:
    """The run-scoped set of hires, capped at
    :data:`colleague.config.MAX_SUBAGENT_FANOUT` (4).

    A 5th :meth:`add` — or a duplicate ``agent_id`` — raises a readable
    :class:`HireError` and leaves the roster unchanged.
    """

    def __init__(self) -> None:
        self._hires: dict[str, Hire] = {}

    def __len__(self) -> int:
        return len(self._hires)

    def __iter__(self):
        return iter(self._hires.values())

    def add(self, hire: Hire) -> Hire:
        """Add *hire*; refuse over-cap or duplicate ids readably."""
        from colleague.config import MAX_SUBAGENT_FANOUT

        if hire.agent_id in self._hires:
            raise HireError("already hired: %r holds a roster entry this run" % hire.agent_id)
        if len(self._hires) >= MAX_SUBAGENT_FANOUT:
            raise HireError(
                "not hired: the roster is full — at most %d hires per run" % MAX_SUBAGENT_FANOUT
            )
        self._hires[hire.agent_id] = hire
        return hire

    def get(self, agent_id: str) -> Optional[Hire]:
        """The hire registered under *agent_id*, or ``None``."""
        return self._hires.get(agent_id)


def hired_role(hire: Hire):
    """The hire's role: ``replace(BUILTIN_ROLES[base], prompt_fragment=
    authored)`` — the allow-list, skill subset, read-only flag and effort all
    stay the base's (prompt never grants, spec c14)."""
    from dataclasses import replace

    from colleague.roles import BUILTIN_ROLES

    _validate_base_role(hire.base_role)
    return replace(BUILTIN_ROLES[hire.base_role], prompt_fragment=hire.prompt_fragment)


def hired_child_surface(hire: Hire) -> tuple[str, ...]:
    """The effective tool surface a hire's assignment child renders: the base
    allow-list through the REAL depth>=1 seam
    (:func:`colleague.actingsurface.strip_child_forbidden_tools` — purpose
    tools + the raw ``subagent``/``subagents`` pair, q9 + plan t11) minus
    :data:`HIRE_TOOL_NAMES` — a hire can never hire.

    The local hire-pair subtraction is transitional: plan task t11 teaches
    ``strip_child_forbidden_tools`` the hire pair itself, after which the
    subtraction here is a no-op kept as defence in depth.
    """
    from colleague.actingsurface import strip_child_forbidden_tools

    stripped = strip_child_forbidden_tools(hired_role(hire))
    return tuple(t for t in stripped.tool_allowlist if t not in HIRE_TOOL_NAMES)

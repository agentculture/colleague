"""Purpose-specific tool profiles + the validated effective tool surface (#411, t2).

**Purpose before tools.** An agent profile names a *tool profile id*; this
module resolves that id to a concrete, validated surface. Three facts are
enumerated in ONE place here so nothing else re-derives them:

1. :data:`TOOL_PROFILES` — one :class:`ToolProfile` record per canonical tool
   (every name in :data:`colleague.tools.TOOL_NAMES` plus the opt-in
   ``deepthink``): its ``tool_class`` (``read`` / ``write`` / ``external`` /
   ``destructive``), whether it needs a separate approval, and whether a
   delegated child may inherit it. The class field RECONCILES the two
   pre-existing write classifications — ``roles._WRITE_TOOLS``
   (``write_file`` / ``edit_file`` / ``run_command``) and
   ``tae_loop.CONSEQUENTIAL_TOOLS`` (those three plus ``subagent`` /
   ``subagents``) — into a single answer: all five are class ``write``;
   ``culture`` / ``devague`` are ``external`` (they shell out to write-capable
   operator CLIs); everything else is ``read``. No tool is ``destructive``
   today — the class exists so a future primitive cannot hide in ``write``.
2. The purpose profiles — :data:`TALKER_TOOLS` (empty: the talker is the
   structurally tools-off senses), :data:`WORKER_TOOLS` (inspect / run / recall
   / delegate — NO ``write_file`` / ``edit_file``; dormant per deviation d3),
   :data:`THINKER_CODER_TOOLS` (the full base + chassis surface) and
   :data:`ASSOCIATE_TOOLS` (the reserved fast coder: the coder-class surface).
3. :func:`effective_tools` — the six-way intersection
   (available ∩ model-supported ∩ purpose ∩ policy ∩ environment ∩ approvals)
   and :func:`tool_surface_digest`, the sha256 over the SORTED names that the
   per-invocation record carries. An empty intersection REFUSES WHOLE
   (:class:`EmptyToolSurface`, the ``lattice.py`` empty-narrowing precedent);
   narrowing can only ever shrink a surface — never add a name.

Pure module: stdlib + ``colleague.tools`` (names only) + ``colleague.roles`` /
``colleague.tae_loop`` (read for the reconciliation test) — no engine, no
loop, no subprocess. Two-sided ENFORCEMENT (offered schemas + executor
allow-list) is wired by the loop task (t15); this module only computes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from colleague.tools import DEEPTHINK_SCHEMA, TOOL_NAMES

__all__ = [
    "ASSOCIATE_TOOLS",
    "EmptyToolSurface",
    "PURPOSE_TOOLS",
    "TALKER_TOOLS",
    "THINKER_CODER_TOOLS",
    "TOOL_CLASSES",
    "TOOL_PROFILES",
    "ToolProfile",
    "WORKER_TOOLS",
    "effective_tools",
    "profile_for",
    "tool_surface_digest",
    "tools_for_purpose",
]

#: The opt-in escalation tool lives OUTSIDE ``tools.SCHEMAS`` (appended only
#: when deepthink is armed) — named here from its own schema, never retyped.
DEEPTHINK_TOOL = DEEPTHINK_SCHEMA["function"]["name"]

#: Every canonical tool id this module profiles: the registry + deepthink.
CANONICAL_TOOLS: tuple[str, ...] = tuple(TOOL_NAMES) + (DEEPTHINK_TOOL,)

#: The closed tool-class vocabulary.
TOOL_CLASSES: frozenset[str] = frozenset({"read", "write", "external", "destructive"})

# The reconciled write set: roles._WRITE_TOOLS ∪ tae_loop.CONSEQUENTIAL_TOOLS.
_WRITE_CLASS = frozenset({"write_file", "edit_file", "run_command", "subagent", "subagents"})
# Shell-outs to write-capable operator CLIs (excluded from read-only roles today).
_EXTERNAL_CLASS = frozenset({"culture", "devague"})
# Needs a SEPARATE approval beyond the profile: run_command is token-gated by
# colleague/policy.py when approvals.json is present.
_APPROVAL_REQUIRED = frozenset({"run_command"})
# A delegated child may never inherit these from its parent (they spawn or
# escalate — authority stays with the parent's explicit delegation).
_NOT_INHERITABLE = frozenset({"subagent", "subagents", DEEPTHINK_TOOL})


class EmptyToolSurface(ValueError):
    """Refuse whole: the effective intersection left no tool at all."""


@dataclass(frozen=True)
class ToolProfile:
    """One canonical tool's validated profile record."""

    canonical_id: str
    tool_class: str
    required_approval: bool
    inheritable: bool

    def __post_init__(self) -> None:
        if self.tool_class not in TOOL_CLASSES:
            raise ValueError(f"unknown tool_class: {self.tool_class!r}")


def _classify(name: str) -> str:
    if name in _WRITE_CLASS:
        return "write"
    if name in _EXTERNAL_CLASS:
        return "external"
    return "read"


#: The per-tool profile records, enumerated ONCE from the registry.
TOOL_PROFILES: dict[str, ToolProfile] = {
    name: ToolProfile(
        canonical_id=name,
        tool_class=_classify(name),
        required_approval=name in _APPROVAL_REQUIRED,
        inheritable=name not in _NOT_INHERITABLE,
    )
    for name in CANONICAL_TOOLS
}


def profile_for(name: str) -> ToolProfile:
    """The :class:`ToolProfile` of a canonical tool; unknown names refuse."""
    try:
        return TOOL_PROFILES[name]
    except KeyError as exc:
        raise KeyError(f"unknown tool: {name!r}") from exc


#: The talker is the tools-off senses: NO tools, by construction.
TALKER_TOOLS: frozenset[str] = frozenset()

#: The (dormant, deviation d3) worker: inspect, run, recall, delegate — and
#: NEVER the generic code-authoring pair.
WORKER_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "view_media",
        "list_dir",
        "run_tests",
        "run_command",
        "memory",
        "subagent",
        "subagents",
        "finish",
    }
)

#: The thinker/coder: the full base + chassis surface (every registry tool).
THINKER_CODER_TOOLS: frozenset[str] = frozenset(TOOL_NAMES)

#: The reserved fast coder (deviation d3): the coder-class surface.
ASSOCIATE_TOOLS: frozenset[str] = THINKER_CODER_TOOLS

#: Purpose → tool set (keys mirror ``colleague.agents.profile.PURPOSES``).
PURPOSE_TOOLS: dict[str, frozenset[str]] = {
    "talker": TALKER_TOOLS,
    "worker": WORKER_TOOLS,
    "thinker_coder": THINKER_CODER_TOOLS,
    "associate": ASSOCIATE_TOOLS,
}


def tools_for_purpose(purpose: str) -> frozenset[str]:
    """The purpose's tool set; unknown purposes refuse."""
    try:
        return PURPOSE_TOOLS[purpose]
    except KeyError as exc:
        raise KeyError(f"unknown purpose: {purpose!r}") from exc


def effective_tools(
    available: Iterable[str],
    model_supported: Iterable[str],
    purpose_tools: Iterable[str],
    policy_tools: Iterable[str],
    env_tools: Iterable[str],
    approved_tools: Iterable[str],
) -> tuple[str, ...]:
    """The sorted six-way intersection; refuses whole when it is empty.

    Every dimension is an iterable of canonical names the caller computed
    (the registry, the model's supported set, the purpose profile, host
    policy, the environment's capabilities, the operator's approvals). The
    result can only ever be a subset of EACH input — narrowing never adds.
    """
    result = (
        frozenset(available)
        & frozenset(model_supported)
        & frozenset(purpose_tools)
        & frozenset(policy_tools)
        & frozenset(env_tools)
        & frozenset(approved_tools)
    )
    if not result:
        raise EmptyToolSurface("effective tool surface is empty — refusing whole")
    return tuple(sorted(result))


def tool_surface_digest(tools: Iterable[str]) -> str:
    """sha256 over the SORTED, newline-joined, utf-8 names — stable across processes."""
    canonical = "\n".join(sorted(set(tools))).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

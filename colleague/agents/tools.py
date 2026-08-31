"""Purpose-specific tool profiles + the validated effective tool surface (#411, t2).

**Purpose before tools.** An agent profile names a *tool profile id*; this
module resolves that id to a concrete, validated surface. Three facts are
enumerated in ONE place here so nothing else re-derives them:

1. :data:`TOOL_PROFILES` — one :class:`ToolProfile` record per canonical tool
   (:data:`colleague.tools.TOOL_NAMES` plus the opt-in ``deepthink`` and the six
   purpose tools, plan t5): its ``tool_class`` (``read`` / ``write`` / ``external``
   / ``destructive``), whether it needs a separate approval, and whether a
   delegated child may inherit it. The class field RECONCILES ``roles._WRITE_TOOLS``
   (``write_file`` / ``edit_file`` / ``run_command``) and
   ``tae_loop.CONSEQUENTIAL_TOOLS`` (those three plus ``subagent`` / ``subagents`` /
   ``handover_to_colleague``) into one answer: all six are class ``write``;
   ``culture`` / ``devague`` are ``external`` (write-capable operator CLIs);
   everything else is ``read``. No tool is ``destructive`` today — the class
   exists so a future primitive cannot hide in ``write``.
2. The purpose profiles — :data:`TALKER_TOOLS` (empty: tools-off senses),
   :data:`WORKER_TOOLS` (inspect/run/recall/delegate BY PURPOSE, no write_file/
   edit_file; dormant per deviation d3), :data:`THINKER_CODER_TOOLS` (base +
   chassis minus web/subagent/subagents, plus the six purposes) and
   :data:`ASSOCIATE_TOOLS` (the reserved fast coder: the coder-class surface).
3. :func:`effective_tools` — the six-way intersection
   (available ∩ model-supported ∩ purpose ∩ policy ∩ environment ∩ approvals)
   and :func:`tool_surface_digest`, the sha256 over the SORTED names that the
   per-invocation record carries. An empty intersection REFUSES WHOLE
   (:class:`EmptyToolSurface`); narrowing can only ever shrink, never add.

Pure module: stdlib + ``colleague.tools`` (names only) + ``colleague.roles`` /
``colleague.tae_loop`` (read for the reconciliation test) — no engine, no
loop, no subprocess. Two-sided ENFORCEMENT (offered schemas + executor
allow-list) is wired by the loop task (t15); this module only computes.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Iterable

from colleague.hire_schemas import HIRE_TOOL_NAMES
from colleague.purpose_schemas import PURPOSE_TOOL_NAMES
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
    "WRITE_CAPABLE_CLASSES",
    "assert_purpose_surface",
    "effective_tools",
    "profile_for",
    "tool_surface_digest",
    "tools_for_purpose",
]

#: The opt-in escalation tool lives OUTSIDE ``tools.SCHEMAS`` (appended only
#: when deepthink is armed) — named here from its own schema, never retyped.
DEEPTHINK_TOOL = DEEPTHINK_SCHEMA["function"]["name"]

#: Every canonical tool id this module profiles: registry + deepthink + purposes (t5).
CANONICAL_TOOLS: tuple[str, ...] = tuple(TOOL_NAMES) + (DEEPTHINK_TOOL,) + PURPOSE_TOOL_NAMES

#: The closed tool-class vocabulary.
TOOL_CLASSES: frozenset[str] = frozenset({"read", "write", "external", "destructive"})

#: Every class that can change the world: ``write`` (the repo / a spawn), ``external``
#: (a shell-out to a write-capable operator CLI) and ``destructive`` (reserved). The
#: talker purpose may hold NONE of these — :func:`assert_purpose_surface` refuses.
WRITE_CAPABLE_CLASSES: frozenset[str] = frozenset({"write", "external", "destructive"})

# roles._WRITE_TOOLS ∪ tae_loop.CONSEQUENTIAL_TOOLS + handover_to_colleague (t5, q9).
_WRITE_CLASS = frozenset(
    {"write_file", "edit_file", "run_command", "subagent", "subagents", "handover_to_colleague"}
)
# Shell-outs to write-capable operator CLIs (excluded from read-only roles today).
_EXTERNAL_CLASS = frozenset({"culture", "devague"})
# Needs a SEPARATE approval beyond the profile: run_command is token-gated by
# colleague/policy.py when approvals.json is present.
_APPROVAL_REQUIRED = frozenset({"run_command"})
# A delegated child may never inherit these (authority stays with the parent);
# the six purpose tools (t5, q9) join too: cortex/worker only, never a child.
# The hire pair (delegation-follow-ups t11, c41/h25) joins UNCONDITIONALLY —
# this is a deny-list, so listing the names while the knob is off costs
# nothing, and an armed run can never leak them down to a child.
_NOT_INHERITABLE = frozenset(
    {"subagent", "subagents", DEEPTHINK_TOOL, *PURPOSE_TOOL_NAMES, *HIRE_TOOL_NAMES}
)


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

#: The (dormant, d3) worker: inspect/run/recall/delegate BY PURPOSE (t5, replacing
#: raw subagent/subagents) — NEVER the code-authoring pair.
WORKER_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "view_media",
        "list_dir",
        "run_tests",
        "run_command",
        "memory",
        *PURPOSE_TOOL_NAMES,
        "finish",
    }
)


def _hire_pair() -> frozenset[str]:
    """The hire pair when ``COLLEAGUE_HIRE`` arms it, else empty
    (delegation-follow-ups t11, c37/h21 — knob-guarded, never ambient).

    This static module has no repo context, so only the ENV half of the
    hire resolution (``colleague.config._resolve_hire_enabled``: env >
    config.json > OFF) can be read here, at import time, with the same
    truthy parse ``_parse_bool`` applies. The actual offer/refuse gate on
    the wire stays :func:`colleague.hire_schemas.hidden_names` over the
    RESOLVED ``config.hire`` flag — this set only mirrors it for the
    agents-mode (#411) purpose surfaces. Unarmed = byte-identical.
    """
    raw = os.environ.get("COLLEAGUE_HIRE", "")
    if raw.strip().lower() in ("", "0", "false", "no", "off"):
        return frozenset()
    return frozenset(HIRE_TOOL_NAMES)


#: The thinker/coder: the registry surface minus web/subagent/subagents plus the
#: six purpose tools (plan t5, q9/q10) — cortex delegates BY PURPOSE, never raw.
#: Mirrors :func:`colleague.roles._writer_allowlist`. Arm 4 (t11) briefly
#: restored the raw pair here; the 21-run matrix measured ZERO raw-pair calls
#: (A4: 0/3), so it was rejected on evidence and this is #443's purpose-only
#: surface again (``actingsurface.strip_child_forbidden_tools`` KEPT anyway).
#: The hire pair joins ONLY when ``COLLEAGUE_HIRE`` arms it (:func:`_hire_pair`,
#: delegation-follow-ups t11) — the unarmed set is byte-identical to #443's.
THINKER_CODER_TOOLS: frozenset[str] = (
    (frozenset(TOOL_NAMES) - {"web", "subagent", "subagents"})
    | frozenset(PURPOSE_TOOL_NAMES)
    | _hire_pair()
)

#: The reserved fast coder (deviation d3): the coder-class surface.
ASSOCIATE_TOOLS: frozenset[str] = THINKER_CODER_TOOLS

#: The purposes whose surface may carry the hire pair (the coder-class seats:
#: the talker never acts, the worker is dormant).
_HIRE_BEARING_PURPOSES: frozenset[str] = frozenset({"thinker_coder", "associate"})

#: Purpose → tool set (keys mirror ``colleague.agents.profile.PURPOSES``).
PURPOSE_TOOLS: dict[str, frozenset[str]] = {
    "talker": TALKER_TOOLS,
    "worker": WORKER_TOOLS,
    "thinker_coder": THINKER_CODER_TOOLS,
    "associate": ASSOCIATE_TOOLS,
}


def tools_for_purpose(purpose: str, config: Any = None) -> frozenset[str]:
    """The purpose's tool set; unknown purposes refuse.

    ``config`` (optional) supplies the RESOLVED hire flag
    (``EngineConfig.hire`` — env > config.json > OFF). Without it the static
    env-only mirror above stands, which is why a config.json-only arming used
    to strip the pair here while the wire gate offered it (Qodo #469/3). A
    coder-class purpose with an armed config always carries the pair; every
    other purpose, and an unarmed/absent config, is byte-identical.
    """
    try:
        base = PURPOSE_TOOLS[purpose]
    except KeyError as exc:
        raise KeyError(f"unknown purpose: {purpose!r}") from exc
    if config is not None and getattr(config, "hire", False) and purpose in _HIRE_BEARING_PURPOSES:
        return base | frozenset(HIRE_TOOL_NAMES)
    return base


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


def assert_purpose_surface(purpose: str, tool_names: Iterable[str]) -> None:
    """Refuse a *purpose* + tool surface pairing that breaks a structural invariant.

    Today ONE rule, for the ``talker`` purpose (t16, spec c19/h25): the talker is
    the tools-off senses, so its surface may never hold a write-capable tool
    (:data:`WRITE_CAPABLE_CLASSES`) — including ``handover_to_colleague`` (plan
    t5). An UNKNOWN name (no profile) also refuses: fail closed, never guess.
    Every other purpose passes unchanged (narrowed by :func:`effective_tools`,
    not refused here). Pure; never touches a tool.
    """
    if purpose != "talker":
        return
    offending: list[str] = []
    unknown: list[str] = []
    for name in sorted(set(tool_names)):
        profile = TOOL_PROFILES.get(name)
        if profile is None:
            unknown.append(name)
        elif profile.tool_class in WRITE_CAPABLE_CLASSES:
            offending.append(f"{name} ({profile.tool_class})")
    if offending or unknown:
        parts = []
        if offending:
            parts.append("write-capable tool(s): " + ", ".join(offending))
        if unknown:
            parts.append("unknown tool(s): " + ", ".join(unknown))
        raise ValueError(
            "talker profile refuses " + "; ".join(parts) + " — the talker is tools-off"
        )

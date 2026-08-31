"""Seat/binding resolution for spawned children — split out of ``subagents.py``
(hard-1000-line-file-limit, task t7) to keep the launcher module under the
1000-line file-length gate.

This module owns the PURE resolution surface a spawned child's identity rides
on, before any engine ever runs: the per-child extras contract
(:class:`ChildSpec`), the delegation-bounds check (child tools/ceiling must
stay a ``⊆`` of the parent's, #411 t11), and the cross-role lobes binding
(:func:`_resolve_child_binding`, #411 t14) that decides which served model a
named ``profile``/lobes role actually dials. :class:`SubagentError` — the
clean, model-visible refusal both this module and ``colleague/subagents.py``
raise — lives here too, since the bounds check is what raises it most: both
the launcher and the batch orchestration (``colleague/subagents_batch.py``)
import it from here, never from each other, so there is no import cycle.

Nothing here touches an engine, a worktree, or ``concurrent.futures`` — that
stays in ``colleague/subagents.py`` (the ONE sanctioned thread-pool consumer,
``tests/test_boundary.py``'s ``_THREADS_ALLOWED``) and
``colleague/subagents_batch.py`` respectively. This module has no dependency
on either sibling, so it loads first and cleanly — ``subagents.py`` and
``subagents_batch.py`` both import FROM here, never the reverse.
"""

from __future__ import annotations

import dataclasses
from typing import List, Optional

from colleague.agents.profile import DORMANT_PURPOSES, PURPOSE_ROLE, PURPOSES
from colleague.agents.state.context import CONTEXT_MODES
from colleague.config import EngineConfig
from colleague.design import design_seat_config as _design_seat_config

#: The lobes roles a child ``profile`` may name DIRECTLY (a bare role name
#: instead of a purpose). Chat-capable seats only — ``stt``/``tts``/
#: ``embedder`` are not seats a child work item can run on.
BINDABLE_ROLES = frozenset({"cortex", "senses", "worker", "muse", "associate"})

#: The floor role every profile falls back to (spec q1: cortex runs ALL roles
#: for now) — mirrors ``colleague.agents.profile._FALLBACK_ROLE``.
_FALLBACK_ROLE = "cortex"


class SubagentError(Exception):
    """A subagent launch was refused — e.g. the depth or global-budget cap was exceeded."""


@dataclasses.dataclass(frozen=True)
class ChildSpec:
    """Per-child delegation extras for ONE nested child work item.

    Bundles the switches that accreted beyond the original engine/model/role
    trio — the explicit t12 budget, the t16 goal contract, and t16 lineage —
    so the launcher signatures stay under the S107 parameter ceiling (the
    ``ContextControls`` precedent). Every field defaults to ``None``: an
    empty spec is byte-identical to the pre-t12/t16 behavior."""

    max_steps: Optional[int] = None
    context_budget_tokens: Optional[int] = None
    goal: Optional[str] = None
    acceptance: Optional[List[str]] = None
    parent_task_id: Optional[str] = None
    #: Model-bound agents (#411, plan task t14): the child's *profile* — a purpose
    #: name from :data:`colleague.agents.profile.PURPOSES` (``talker`` / ``worker`` /
    #: ``thinker_coder`` / ``associate``) or a bare bindable lobes role name
    #: (:data:`BINDABLE_ROLES`). ``None`` (the default) = no profile: the child
    #: inherits the parent seat exactly as today; INERT unless ``agents`` is armed.
    profile: Optional[str] = None
    #: ``inherit`` (the default, today's behaviour) or ``clear`` (the child
    #: receives the handover summary — t10 — as its ``Task.context`` instead
    #: of the parent's transcript). Anything else is refused whole.
    context_mode: str = "inherit"
    #: The PARENT's own profile/purpose (lineage one hop up), recorded on the
    #: child's ``delegate`` event as ``from_profile``; threaded by
    #: :func:`~colleague.subagents.make_spawn` /
    #: :func:`~colleague.subagents_batch.make_batch_spawn`'s ``parent_profile``.
    parent_profile: Optional[str] = None
    #: An explicit per-child thinking-effort override (#416 t5, c28/h19) — one
    #: of :data:`colleague.effort.LADDER` or the kill-switch sentinel
    #: ``"default"``. ``None`` (the default) means "no override": the child's
    #: builder resolves its effort from the role/seat tables instead. Threaded
    #: from the ``subagent``/``subagents`` tool args (:mod:`colleague.tools`)
    #: as ``resolve_effort``'s ``parent_override`` — the HIGHEST-precedence
    #: input, above the role/seat tables.
    effort: Optional[str] = None
    #: Whether this child consumes a slot of the shared delegation budget
    #: (``MAX_SUBAGENT_FANOUT`` / ``MAX_SUBAGENT_TOTAL``). ``True`` (the
    #: default) is every manual delegation — byte-identical. ``False`` is
    #: the purpose-tool arithmetic exemption
    #: (purpose-tools-associate-seat, c34). The DEPTH cap always applies.
    charges_budget: bool = True
    #: The ONE work-item-wide web budget this child inherits (t7, c33/h32):
    #: ``COLLEAGUE_WEB_MAX_CALLS - parent.web_calls`` at spawn time, or
    #: ``None`` (the default) - today's per-executor budget, byte-identical
    #: for every manual ``subagent``/``subagents`` call.
    web_calls_remaining: Optional[int] = None
    #: The purpose-tool name (t8, q3) when spawned BY a purpose tool — exempts
    #: the armed ``⊆``-parent check for its FIXED child surface; ``None`` for
    #: a manual ``subagent``/``subagents`` delegation, which stays subject to it.
    purpose: Optional[str] = None

    def __post_init__(self) -> None:
        if self.context_mode not in CONTEXT_MODES:
            raise ValueError(
                f"unknown context_mode: {self.context_mode!r} (expected one of {CONTEXT_MODES})"
            )
        if self.profile is not None and (
            self.profile not in PURPOSES and self.profile not in BINDABLE_ROLES
        ):
            raise ValueError(
                f"unknown profile: {self.profile!r} (expected a purpose in "
                f"{sorted(PURPOSES)} or a lobes role in {sorted(BINDABLE_ROLES)})"
            )
        if self.effort is not None:
            from colleague import effort as _effort

            _effort.validate_effort(self.effort)


def decomposition_seat_config(config: EngineConfig) -> EngineConfig:
    """The 'subagents.decompose' design call-site seat (#416 t6, c14/h9): xhigh.

    Honest limit: ``colleague/subagents.py`` dispatches each child as a full
    ``Task`` through ``Engine.work`` (``make_spawn``/``make_batch_spawn``), so
    a child's OWN completion is built by the engine at the child's own
    role/seat effort (t5) — there is no separate "decide how to decompose"
    completion in this module to route through the design seat instead. This
    builder is pinned here, ready for a future dedicated
    decomposition-planning call; it is unit-tested at the builder level
    (``tests/test_design_call_site.py``), not exercised end-to-end.
    """
    return _design_seat_config(config, "subagents.decompose")


# ---------------------------------------------------------------------------
# Cross-role dial (#411, plan task t14): a child may bind a different lobes role.
# ---------------------------------------------------------------------------


def default_parent_profile(config: EngineConfig) -> Optional[str]:
    """The profile the TOP-LEVEL spawn wiring hands to ``make_spawn`` /
    ``make_batch_spawn`` as ``parent_profile``.

    Unarmed (``config.agents`` False) → ``None`` — byte-identical to today.
    Armed → an explicit ``config.agents_profile`` attribute when the loop
    wiring (t15) set one, else ``thinker_coder`` (cortex runs the acting seat
    today, spec q1). Every caller passes this so every spawn path carries the
    parent's purpose.
    """
    if not getattr(config, "agents", False):
        return None
    explicit = getattr(config, "agents_profile", None)
    return str(explicit) if explicit else "thinker_coder"


def _seat_purpose(config: EngineConfig) -> str:
    """The purpose whose tool surface THIS seat's own loop narrows itself to.

    Read back from the same place the loop's ``resolve_role`` reads it (t15):
    an explicit ``agents_profile`` attribute, else the acting default
    (``thinker_coder``, the full surface). Parent and child are therefore
    always ranked on the SAME rule.
    """
    from colleague.agents.runtime import DEFAULT_ACTING_PURPOSE

    return str(getattr(config, "agents_profile", None) or DEFAULT_ACTING_PURPOSE)


def _child_purpose(parent_config: EngineConfig, spec: ChildSpec) -> str:
    """The purpose the CHILD seat will actually run on.

    Its own when ``spec.profile`` names one; otherwise the PARENT's — a bare
    lobes role name switches the model, never the tool surface, and a spawn
    with NO profile inherits the parent's seat (the ``subagent`` tool's own
    documented contract). Never ``DEFAULT_ACTING_PURPOSE``: defaulting there
    would silently widen a narrow parent's child to the full surface.
    """
    from colleague.agents.tools import PURPOSE_TOOLS

    if spec.profile in PURPOSE_TOOLS:
        return str(spec.profile)
    return _seat_purpose(parent_config)


def _child_requested_tools(
    spec: ChildSpec,
    child_purpose: str,
    role: Optional[str],
    parent_config: Optional[EngineConfig] = None,
) -> tuple[str, ...]:
    """Requested tools for the ``⊆`` check (t8, q3): a purpose spawn's FIXED
    role-allowlist-∩-environment surface (via ``curate_schemas``, the same
    filter ``web``'s presence check applies) — else today's profile tools."""
    if spec.purpose:
        from colleague.tools import curate_schemas

        return tuple(sorted(s["function"]["name"] for s in curate_schemas(role)))
    from colleague.agents.tools import tools_for_purpose

    return tuple(sorted(tools_for_purpose(child_purpose, parent_config)))


def _delegation_bounds(
    parent_config: EngineConfig,
    spec: ChildSpec,
    *,
    instruction: str,
    depth: int,
    role: Optional[str],
) -> tuple[str, str, tuple[str, ...], "object"]:
    """``(child_purpose, child_ceiling, requested_tools, verdict)`` for one delegation."""
    from colleague.agents.delegation import DelegationRequest, validate_delegation
    from colleague.agents.runtime import seat_ceiling
    from colleague.agents.tools import tools_for_purpose

    parent_purpose = _seat_purpose(parent_config)
    child_purpose = _child_purpose(parent_config, spec)
    # The child inherits the parent's publish intent; only its ROLE can lower
    # the ceiling further, so the child's ceiling is ranked off the parent's
    # config with the CHILD's role applied.
    child_ceiling = seat_ceiling(parent_config, role)
    requested_tools = _child_requested_tools(spec, child_purpose, role)
    request = DelegationRequest(
        delegation_id="",  # validation only — nothing is recorded from here
        from_agent=spec.parent_profile or parent_purpose,
        requested_agent_profile=spec.profile or child_purpose,
        objective=instruction,
        acceptance="",
        requested_tools=requested_tools,
        authority_ceiling=child_ceiling,
        context_mode=spec.context_mode,
        depth=depth,
        purpose=spec.purpose,
    )
    verdict = validate_delegation(
        request,
        parent_effective_tools=tools_for_purpose(parent_purpose),
        parent_ceiling=seat_ceiling(parent_config, getattr(parent_config, "role", None)),
    )
    return child_purpose, child_ceiling, requested_tools, verdict


def _enforce_delegation_bounds(
    parent_config: EngineConfig,
    spec: ChildSpec,
    *,
    instruction: str,
    depth: int,
    role: Optional[str],
) -> tuple[tuple[str, ...], str]:
    """Validate ONE armed delegation against the parent's bounds — refuse whole.

    Returns the ``(requested_tools, authority_ceiling)`` the delegation was
    ranked on, for the ``delegate`` event to record (empty when unarmed).

    The enforcement half of t11 (Qodo, PR #414): ``validate_delegation`` owned
    the arithmetic — child tools ``⊆`` parent tools, child ceiling ``≤``
    parent ceiling, depth/fanout/total within the ``MAX_SUBAGENT_*`` caps,
    ``context_mode`` in the closed set — but nothing on the spawn path called
    it, so a narrow parent could hand a child a WIDER surface by naming a
    different profile (a ``worker`` seat, which holds no ``write_file`` /
    ``edit_file``, delegating a ``thinker_coder`` child that does).

    Called on EVERY armed spawn — gated on ``config.agents``, NOT on a
    declared profile: a delegation that omits ``profile`` inherits the
    parent's seat, and gating on the profile would have let the model skip the
    check by simply not naming one. Runs BEFORE the global budget charge,
    before the ``delegate`` event and before the child engine runs, so a
    refused delegation costs nothing, records nothing and spawns nothing.
    Refusal surfaces as :class:`SubagentError` — the same clean, model-visible
    refusal as the depth and budget caps. Because a non-subset REFUSES, the
    child's surface is a subset of the parent's by construction.

    Two bounds are deliberately NOT re-derived here: ``fanout``/``total`` (the
    shared ``_AgentBudget`` charges and refuses them upstream, before any work —
    and a ``charges_budget=False`` purpose child is exempt from exactly those
    two, c34) and the ``_NOT_INHERITABLE`` tool classes (nested delegation is
    explicitly permitted — a child gets its own depth-bound spawn callbacks).
    Alignment is not permission: the host's policy/approval gate still gates
    every route this allows.
    """
    if not getattr(parent_config, "agents", False):
        return (), ""  # unarmed: no purposes, no bounds — byte-identical today
    child_purpose, ceiling, requested_tools, verdict = _delegation_bounds(
        parent_config, spec, instruction=instruction, depth=depth, role=role
    )
    if not verdict.allowed:
        raise SubagentError(
            f"delegation refused: {child_purpose!r} under "
            f"{_seat_purpose(parent_config)!r} — {verdict.reason}"
        )
    return requested_tools, ceiling


@dataclasses.dataclass(frozen=True)
class _ChildBinding:
    """How ONE child's ``profile`` resolved — the trace record behind the armed
    child config and the ``SubResult.agent_id`` / ``resolved_model`` /
    ``fallback_from_role`` fields.

    ``role_info`` is the lobes ``RoleInfo`` the child dials (``None`` when the
    gateway was absent/unreachable — the child then stays on the parent's
    main endpoint). ``gateway_url`` is the gateway the roles came from.
    """

    profile: str
    requested_role: str
    model_role: str
    resolved_model: str
    fallback_from_role: Optional[str]
    role_info: object
    gateway_url: Optional[str]


def _requested_role(profile: str) -> str:
    """The lobes role a profile names: a purpose maps through the enumerated
    :data:`~colleague.agents.profile.PURPOSE_ROLE` table; a bare role name is
    itself."""
    return PURPOSE_ROLE[profile] if profile in PURPOSES else profile


def _resolve_child_binding(parent_config: EngineConfig, spec: ChildSpec) -> Optional[_ChildBinding]:
    """Resolve ``spec.profile`` against the lobes gateway — ``None`` when unarmed.

    Armed (``parent_config.agents`` True) AND ``spec.profile`` set, the roles
    come from :func:`colleague.lobes.resolve_roles` over the parent's
    ``lobes_gateway_url``; the requested role binds when present AND ready,
    else the child is carried on the cortex model under a RECORDED fallback
    (``fallback_from_role`` = the requested role — the
    :func:`colleague.agents.profile.resolve_profile` doctrine: fallback, never
    refusal, never silent). Two further rules:

    - **d3 dormancy**: a DORMANT purpose (``worker``) is NEVER bound even when
      its role is ready — it resolves to the cortex floor, fallback recorded.
    - **no gateway** (unarmed lobes, or unreachable): the child degrades to
      the parent's MAIN model/endpoint with the fallback recorded; a
      ``thinker_coder``/``cortex`` profile on the main seat records no
      fallback (it IS the floor).

    Pure except for the one GET :func:`colleague.lobes.resolve_roles` issues
    (which never raises — it degrades to ``None``).
    """
    profile = spec.profile
    if not getattr(parent_config, "agents", False) or profile is None:
        return None
    # Lazy import: keeps the unarmed import graph of this module byte-identical
    # (lobes pulls urllib) and lets tests monkeypatch the gateway resolver.
    from colleague import lobes as _lobes

    requested = _requested_role(profile)
    gateway = getattr(parent_config, "lobes_gateway_url", None)
    roles = _lobes.resolve_roles(gateway) if gateway else None
    if roles is None:
        # Gateway absent/unreachable: the parent's main seat IS the floor.
        return _ChildBinding(
            profile=profile,
            requested_role=requested,
            model_role=_FALLBACK_ROLE,
            resolved_model=parent_config.model,
            fallback_from_role=(requested if requested != _FALLBACK_ROLE else None),
            role_info=None,
            gateway_url=None,
        )
    role = getattr(roles, requested, None)
    dormant = profile in DORMANT_PURPOSES or requested in DORMANT_PURPOSES
    if role is not None and getattr(role, "ready", False) and not dormant:
        return _ChildBinding(
            profile=profile,
            requested_role=requested,
            model_role=requested,
            resolved_model=role.model,
            fallback_from_role=None,
            role_info=role,
            gateway_url=gateway,
        )
    floor = getattr(roles, _FALLBACK_ROLE)
    return _ChildBinding(
        profile=profile,
        requested_role=requested,
        model_role=_FALLBACK_ROLE,
        resolved_model=floor.model,
        fallback_from_role=(requested if requested != _FALLBACK_ROLE else None),
        role_info=floor,
        gateway_url=gateway,
    )


def _delegate_event_data(
    child_task_id: str,
    spec: ChildSpec,
    binding: "_ChildBinding",
    agent_id: Optional[str],
    bounds: tuple[tuple[str, ...], str] = ((), ""),
    resolved_effort: Optional[str] = None,
) -> dict:
    """The ``delegate`` ledger event payload for an armed child (#411 t14).

    ``resolved_effort`` (#416 t5, c28/h19) is the CHILD's resolved thinking-
    effort rung (the same value ``_child_config_for_profile`` set as the
    child config's ``reasoning_effort_seat``) — recorded beside
    ``effort_override`` (``True`` when ``spec.effort`` named an explicit
    per-child override, the highest-precedence input) so a ledger replay can
    audit not just the tools/ceiling a delegation was ranked on but the
    effort it actually ran with.
    """
    return {
        "id": child_task_id,
        "delegation_id": child_task_id,
        "child_ref": f"sub/{child_task_id}",
        "profile": binding.profile,
        "context_mode": spec.context_mode,
        "from_profile": spec.parent_profile,
        "agent_id": agent_id,
        "model_role": binding.model_role,
        "resolved_model": binding.resolved_model,
        "fallback_from_role": binding.fallback_from_role,
        # What the t11 bounds check ranked this delegation on, so a ledger
        # replay can audit the decision instead of taking it on trust.
        "requested_tools": list(bounds[0]),
        "authority_ceiling": bounds[1],
        "effort": resolved_effort,
        "effort_override": spec.effort is not None,
    }

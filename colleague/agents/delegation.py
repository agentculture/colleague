"""Delegation envelope + lifecycle events + handoff semantics (#411, task t11).

A *delegation* is the typed, ledgered act of handing a scoped piece of work to
another model-bound agent. This module is the CONTRACT for that act — it
computes and records; it does NOT spawn. The spawn wiring lives in
:mod:`colleague.subagents` (``run_subagent``), threaded through
:func:`open_delegation` / :func:`close_delegation` so the ``delegate`` /
``return`` events bracket the child's life on the task ledger (t4).

**No spawning here.** Nothing in this module loads an engine, starts a child
work item, or opens a socket — pure stdlib over the append-only task ledger,
the same "compute, don't act" seam as :mod:`colleague.agents.tools`.

**Authority ceilings are a small closed enum, ordered.**
:data:`AUTHORITY_CEILINGS` = ``read_only`` < ``repo_patch_no_publish`` <
``repo_patch_publish``. A child may never be granted a ceiling above its
parent's — :func:`ceiling_rank` makes the ordering total and
:func:`validate_delegation` enforces it (tools subset, ceiling order,
depth/fanout/total within ``MAX_SUBAGENT_*``); host policy still gates every
route, never substituted for by this module.

**Refuse whole.** :func:`validate_delegation` returns a :class:`DelegationVerdict`
(the :mod:`colleague.agents.messages` refuse-whole shape) and never raises: a
refused delegation records/spawns nothing.

**Ledger-only handoff.** :func:`handoff` transfers plan-node ownership by
appending a ``plan_node`` event — the ledger, and nothing else."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from colleague.agents.state.ledger import LedgerEvent, TaskLedger
from colleague.config import MAX_SUBAGENT_DEPTH, MAX_SUBAGENT_FANOUT, MAX_SUBAGENT_TOTAL

__all__ = [
    "AUTHORITY_CEILINGS",
    "CONTEXT_MODES",
    "DelegationHandle",
    "DelegationRequest",
    "DelegationVerdict",
    "ceiling_rank",
    "close_delegation",
    "handoff",
    "open_delegation",
    "validate_delegation",
]

#: The closed, ordered set of authority ceilings. A child's ceiling may never
#: exceed its parent's; the ordering is total (see :func:`ceiling_rank`).
AUTHORITY_CEILINGS: tuple[str, ...] = (
    "read_only",
    "repo_patch_no_publish",
    "repo_patch_publish",
)

#: The closed set of context modes a delegation may request (t10): ``inherit``
#: (the parent's windowed transcript) or ``clear`` (a handover summary only).
CONTEXT_MODES: tuple[str, ...] = ("inherit", "clear")


@dataclass(frozen=True)
class DelegationVerdict:
    """The outcome of validating one :class:`DelegationRequest` — refuse-whole
    (mirrors :class:`colleague.agents.messages.MessageVerdict`): ``allowed=True``
    with ``reason=None`` (clean), or ``allowed=False`` with a short ``reason``
    (nothing recorded, nothing spawns).
    """

    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class DelegationRequest:
    """The typed envelope for one delegation.

    ``requested_tools`` is the child's requested tool surface (a subset of the
    parent's effective tools); ``authority_ceiling`` is the child's requested
    ceiling (one of :data:`AUTHORITY_CEILINGS`, never above the parent's);
    ``depth`` / ``fanout`` / ``total`` are the delegation's position against the
    ``MAX_SUBAGENT_*`` caps (the child's nesting depth, the batch width it would
    open, and the agents it would charge against the shared budget).
    ``evidence_refs`` / ``context_refs`` / ``return_contract`` carry refs, never
    payloads. ``context_mode`` is one of :data:`CONTEXT_MODES`.

    ``effort`` (#416 t5, c28/h19) is the child's RESOLVED thinking-effort
    rung (one of :data:`colleague.effort.LADDER`, or ``None`` when unset);
    ``effort_override`` is ``True`` when that rung came from an explicit
    per-child override rather than the role/seat tables. Both are recorded
    on the ``delegate`` event by :func:`open_delegation`, purely as trace
    data — this module computes/records, it never resolves the rung itself.

    ``purpose`` (q3/t8) names a fixed purpose tool when set: its
    ``requested_tools`` is then exempt from the ``⊆`` check below. A manual
    subagent delegation always leaves this ``None``.
    """

    delegation_id: str
    from_agent: str
    requested_agent_profile: str
    objective: str
    acceptance: str
    evidence_refs: tuple[str, ...] = ()
    context_refs: tuple[str, ...] = ()
    requested_tools: tuple[str, ...] = ()
    authority_ceiling: str = "read_only"
    return_contract: str = ""
    context_mode: str = "inherit"
    depth: int = 1
    fanout: int = 1
    total: int = 1
    effort: str | None = None
    effort_override: bool = False
    purpose: str | None = None


@dataclass(frozen=True)
class DelegationHandle:
    """The open side of a delegation, returned by :func:`open_delegation`.

    ``delegation_id`` keys the matching ``return`` event; ``child_ref`` is the
    ``sub/<child_id>`` name the snapshot's open loop carries; ``seq`` is the
    ledger-assigned sequence of the ``delegate`` event (the spawn's anchor);
    ``ledger`` is the task ledger the ``delegate`` event was appended to, so
    :func:`close_delegation` can append the matching ``return`` without the
    caller re-supplying it.
    """

    delegation_id: str
    child_ref: str
    seq: int
    ledger: TaskLedger


def ceiling_rank(ceiling: str) -> int:
    """The total order of an authority ceiling; unknown ceilings refuse.

    ``read_only`` (0) < ``repo_patch_no_publish`` (1) < ``repo_patch_publish``
    (2). A ceiling outside the closed enum raises :class:`ValueError` — the
    ordering is only defined for the enumerated set.
    """
    try:
        return AUTHORITY_CEILINGS.index(ceiling)
    except ValueError as exc:
        raise ValueError(
            f"unknown authority ceiling {ceiling!r} (expected one of {AUTHORITY_CEILINGS})"
        ) from exc


def validate_delegation(
    req: DelegationRequest,
    *,
    parent_effective_tools: Iterable[str],
    parent_ceiling: str,
) -> DelegationVerdict:
    """Validate one :class:`DelegationRequest` against its parent's bounds.

    Refuses whole (a :class:`DelegationVerdict` with ``allowed=False``) when ANY
    bound is crossed — never raises on a bad request:

    - ``requested_tools`` is not a subset of the parent's effective tools
      (skipped when ``req.purpose`` is set — q3 exemption);
    - ``authority_ceiling`` ranks above the parent's ceiling;
    - ``depth`` / ``fanout`` / ``total`` exceed ``MAX_SUBAGENT_DEPTH`` /
      ``MAX_SUBAGENT_FANOUT`` / ``MAX_SUBAGENT_TOTAL``;
    - ``context_mode`` is outside :data:`CONTEXT_MODES`.

    Host policy still gates every route: this is the delegation's own
    arithmetic only, not a substitute for the approval/policy layer.
    """
    parent_tools = frozenset(parent_effective_tools)
    if req.purpose is None and not frozenset(req.requested_tools) <= parent_tools:
        extra = sorted(set(req.requested_tools) - parent_tools)
        return DelegationVerdict(
            allowed=False,
            reason=f"requested_tools not a subset of the parent's effective tools: {extra}",
        )
    if ceiling_rank(req.authority_ceiling) > ceiling_rank(parent_ceiling):
        return DelegationVerdict(
            allowed=False,
            reason=(
                f"authority_ceiling {req.authority_ceiling!r} exceeds the parent's "
                f"{parent_ceiling!r}"
            ),
        )
    if req.depth > MAX_SUBAGENT_DEPTH:
        return DelegationVerdict(
            allowed=False,
            reason=f"depth {req.depth} exceeds MAX_SUBAGENT_DEPTH ({MAX_SUBAGENT_DEPTH})",
        )
    if req.fanout > MAX_SUBAGENT_FANOUT:
        return DelegationVerdict(
            allowed=False,
            reason=f"fanout {req.fanout} exceeds MAX_SUBAGENT_FANOUT ({MAX_SUBAGENT_FANOUT})",
        )
    if req.total > MAX_SUBAGENT_TOTAL:
        return DelegationVerdict(
            allowed=False,
            reason=f"total {req.total} exceeds MAX_SUBAGENT_TOTAL ({MAX_SUBAGENT_TOTAL})",
        )
    if req.context_mode not in CONTEXT_MODES:
        return DelegationVerdict(
            allowed=False,
            reason=f"context_mode {req.context_mode!r} not in {CONTEXT_MODES}",
        )
    return DelegationVerdict(allowed=True)


def open_delegation(ledger: TaskLedger, req: DelegationRequest) -> DelegationHandle:
    """Append the ``delegate`` event BEFORE the spawn and return a handle.

    The event's ``child_ref`` is ``sub/<delegation_id>`` — the name
    :func:`colleague.agents.state.ledger.derive_snapshot` carries on the open
    loop for a delegate without a matching ``return``. The returned
    :class:`DelegationHandle` anchors the spawn; :func:`close_delegation`
    consumes it.
    """
    child_ref = f"sub/{req.delegation_id}"
    event = ledger.append(
        "delegate",
        {
            "id": req.delegation_id,
            "child_ref": child_ref,
            "from_agent": req.from_agent,
            "requested_agent_profile": req.requested_agent_profile,
            "objective": req.objective,
            "acceptance": req.acceptance,
            "evidence_refs": list(req.evidence_refs),
            "context_refs": list(req.context_refs),
            "requested_tools": list(req.requested_tools),
            "authority_ceiling": req.authority_ceiling,
            "return_contract": req.return_contract,
            "context_mode": req.context_mode,
            "effort": req.effort,
            "effort_override": req.effort_override,
        },
    )
    return DelegationHandle(
        delegation_id=req.delegation_id,
        child_ref=child_ref,
        seq=event.seq,
        ledger=ledger,
    )


def close_delegation(handle: DelegationHandle, result: Any) -> LedgerEvent:
    """Append the ``return`` event that closes the delegation *handle* opened.

    ``result`` is the child's ``SubResult`` (duck-typed: only ``.task_id`` is
    read, so no engine/contract import is needed). The ``return`` event's
    ``id`` matches the ``delegate`` event's ``id`` (the ``delegation_id``), so
    :func:`derive_snapshot` marks the delegation returned and drops it from the
    open loops.
    """
    return handle.ledger.append(
        "return",
        {
            "id": handle.delegation_id,
            "child_ref": handle.child_ref,
            "ref": getattr(result, "task_id", ""),
        },
    )


def handoff(ledger: TaskLedger, plan_node: str | Mapping[str, Any], to_agent: str) -> LedgerEvent:
    """Transfer plan-node ownership to *to_agent* — on the ledger only.

    Appends a ``plan_node`` event (keyed by the node's ``id``) whose latest
    ``owner`` is *to_agent*; :func:`derive_snapshot`'s last-wins replay then
    shows the node owned by the new agent. No spawn, no engine, no side effect
    beyond the ledger line.
    """
    if isinstance(plan_node, Mapping):
        node_id = str(plan_node.get("id", ""))
        data: dict[str, Any] = dict(plan_node)
        data["id"] = node_id
    else:
        node_id = str(plan_node)
        data = {"id": node_id}
    data["owner"] = to_agent
    return ledger.append("plan_node", data)

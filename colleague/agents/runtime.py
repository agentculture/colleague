"""Per-invocation agent identity + the ONE agent seat builder (#411, plan task t9).

Two things live here, and nothing else:

1. :class:`InvocationRecord` — the per-invocation identity + context manifest
   (spec c13 / h12): who ran (``agent_id``, purpose, the lobes ``model_role``
   it resolved to, the served ``resolved_model``, the RECORDED
   ``fallback_from_role`` when a purpose was carried on the cortex floor),
   what it was offered (``tool_surface_digest`` — the t2 sha256 over the
   sorted effective names), what it saw (``ledger_digest`` + the
   reconstruction manifest's nucleus / working-set / retrieved-memory /
   peer-message refs), how big the send was (``token_estimate`` +
   ``token_estimate_source`` in {tokenize, chars}), whether the turn was
   truncated, and its lineage (``parent_agent_id`` / ``delegation_id`` /
   ledger-owned ``seq``).

   **``token_estimate`` is NEVER written into
   :class:`colleague.contract.Usage`.** Usage is the work-item's exact token
   accounting, summed from the model's reported usage across the loop's
   calls; the estimate is a pre-send sizing figure (chars/4 or the
   ``/tokenize`` probe) that belongs on the invocation record and the
   artifact only. :func:`append_invocation` enforces this by construction —
   the ledger event it appends carries the identity + manifest fields and
   deliberately omits ``token_estimate``.

2. :func:`agent_engine_config` — the ONE agent seat builder. It generalizes
   ``tae_loop.seat_engine_config`` (tae_loop.py:214-232) to a profile +
   lobes roles: a ``dataclasses.replace`` of the parent config switching
   ``model`` to the role's served id, ``base_url`` to
   :func:`colleague.lobes.resolve_role_base_url` (the role's own advertised
   endpoint when dialable, else the gateway origin), ``api_key`` under the
   #348 same-origin hygiene rule (inherited only toward the parent's own
   origin — a cross-origin role gets ``None``, never the parent's Bearer),
   and ``context_budget_tokens`` to the role's OWN advertised context
   (cortex 1,048,576 per the 2026-08-21 re-probe; worker 65,536 when ready —
   the bigger sliding window is intended). ``refresh_seat`` and ``on_delta``
   are cleared so an agent seat never inherits the parent's stale-pin
   refresh or streaming sink. ``tae_loop.seat_engine_config``,
   ``deepthink_engine_config`` and ``senses_engine_config`` are NOT rewritten
   here — a follow-up task may fold them onto this builder.

Invocation records are appended to the task ledger (t4) as ``invocation``
events: :func:`append_invocation` is the one writer, and the record's
``ledger_digest`` is the digest of the ledger state AFTER the append (what
``derive_snapshot`` replays), so a record always names the state it ran
under.

Pure stdlib + the sibling agent modules + ``colleague.lobes`` /
``colleague.context`` / ``colleague.config``. No imports from
``colleague/loop.py``; no subprocess, no threads, no network.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, cast
from urllib.parse import urlsplit

from colleague.agents.profile import AgentProfile
from colleague.agents.state.ledger import LedgerEvent, TaskLedger
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.lobes import resolve_role_base_url

__all__ = [
    "TOKEN_ESTIMATE_SOURCES",
    "InvocationRecord",
    "agent_engine_config",
    "append_invocation",
    "estimate_tokens",
]

#: The closed vocabulary of ``token_estimate_source`` labels. ``tokenize`` —
#: the engine's exact counter (``vllm_openai._make_count_tokens`` via the
#: ``/tokenize`` endpoint); ``chars`` — the zero-dependency
#: :func:`colleague.context.count_tokens_chars` heuristic.
TOKEN_ESTIMATE_SOURCES: tuple[str, ...] = ("tokenize", "chars")

#: The only URL schemes a role endpoint may be dialed directly (mirrors
#: ``lobes._ALLOWED_SCHEMES`` — the same SSRF guard).
_ALLOWED_SCHEMES = frozenset({"http", "https"})


# ---------------------------------------------------------------------------
# InvocationRecord — identity + context manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvocationRecord:
    """One model invocation's identity + context manifest (spec c13 / h12).

    ``model_role`` is the lobes role the purpose actually resolved to (its
    own role when ready, else the cortex floor); ``resolved_model`` is the
    served model id (trace data, never a constant); ``fallback_from_role``
    names the role the purpose was carried *from* when it fell back —
    ``None`` when it ran on its own ready role. The manifest fields
    (``ledger_digest``, ``nucleus_refs``, ``working_set_refs``,
    ``retrieved_memory_refs``, ``peer_message_refs``) mirror the t10
    reconstruction manifest: refs and digests, never payloads.

    ``token_estimate`` is a pre-send sizing figure labelled by
    ``token_estimate_source`` (one of :data:`TOKEN_ESTIMATE_SOURCES`); it is
    NEVER written into :class:`colleague.contract.Usage` (exact accounting
    only) and never into the ledger event (see :func:`append_invocation`).
    ``seq`` is ledger-owned: 0 until :func:`append_invocation` appends the
    record and returns it with the ledger-assigned seq.
    """

    agent_id: str
    purpose: str
    model_role: str
    resolved_model: str
    fallback_from_role: Optional[str]
    tool_surface_digest: str
    ledger_digest: str
    nucleus_refs: tuple[str, ...] = ()
    working_set_refs: tuple[str, ...] = ()
    retrieved_memory_refs: tuple[str, ...] = ()
    peer_message_refs: tuple[str, ...] = ()
    token_estimate: int = 0
    token_estimate_source: str = "chars"
    truncated: bool = False
    parent_agent_id: Optional[str] = None
    delegation_id: Optional[str] = None
    seq: int = 0

    def __post_init__(self) -> None:
        if self.token_estimate_source not in TOKEN_ESTIMATE_SOURCES:
            raise ValueError(
                f"unknown token_estimate_source: {self.token_estimate_source!r} "
                f"(expected one of {TOKEN_ESTIMATE_SOURCES})"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (all fields; None values preserved)."""
        return {
            "agent_id": self.agent_id,
            "purpose": self.purpose,
            "model_role": self.model_role,
            "resolved_model": self.resolved_model,
            "fallback_from_role": self.fallback_from_role,
            "tool_surface_digest": self.tool_surface_digest,
            "ledger_digest": self.ledger_digest,
            "nucleus_refs": list(self.nucleus_refs),
            "working_set_refs": list(self.working_set_refs),
            "retrieved_memory_refs": list(self.retrieved_memory_refs),
            "peer_message_refs": list(self.peer_message_refs),
            "token_estimate": self.token_estimate,
            "token_estimate_source": self.token_estimate_source,
            "truncated": self.truncated,
            "parent_agent_id": self.parent_agent_id,
            "delegation_id": self.delegation_id,
            "seq": self.seq,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InvocationRecord":
        """Reconstruct a record from :meth:`to_dict` output (round-trip)."""
        return cls(
            agent_id=str(data["agent_id"]),
            purpose=str(data["purpose"]),
            model_role=str(data["model_role"]),
            resolved_model=str(data["resolved_model"]),
            fallback_from_role=data.get("fallback_from_role"),
            tool_surface_digest=str(data["tool_surface_digest"]),
            ledger_digest=str(data["ledger_digest"]),
            nucleus_refs=tuple(str(x) for x in data.get("nucleus_refs") or ()),
            working_set_refs=tuple(str(x) for x in data.get("working_set_refs") or ()),
            retrieved_memory_refs=tuple(str(x) for x in data.get("retrieved_memory_refs") or ()),
            peer_message_refs=tuple(str(x) for x in data.get("peer_message_refs") or ()),
            token_estimate=int(data.get("token_estimate", 0) or 0),
            token_estimate_source=str(data.get("token_estimate_source", "chars")),
            truncated=bool(data.get("truncated", False)),
            parent_agent_id=data.get("parent_agent_id"),
            delegation_id=data.get("delegation_id"),
            seq=int(data.get("seq", 0) or 0),
        )


# ---------------------------------------------------------------------------
# The ONE agent seat builder
# ---------------------------------------------------------------------------


def _same_origin(a: str, b: str) -> bool:
    """True when *a* and *b* share scheme + host + port (case-insensitive
    netloc) — the #348 credential-hygiene predicate (mirrors
    ``colleague.config._same_origin``)."""
    sa, sb = urlsplit(a), urlsplit(b)
    return (sa.scheme.lower(), sa.netloc.lower()) == (sb.scheme.lower(), sb.netloc.lower())


def _role_base_url(role: Any, gateway_url: Optional[str], fallback: str) -> str:
    """The role's dial target: :func:`resolve_role_base_url` when the gateway
    origin is known, else the role's own endpoint when it is dialable, else
    *fallback* (the parent's base_url — the honest no-gateway case)."""
    if gateway_url:
        return resolve_role_base_url(role, gateway_url)
    endpoint = (getattr(role, "endpoint", "") or "").strip()
    if endpoint and urlsplit(endpoint).scheme in _ALLOWED_SCHEMES:
        return endpoint
    return fallback


def _role_api_key(role_base_url: str, parent: EngineConfig) -> Optional[str]:
    """The role's api_key under the #348 same-origin hygiene rule.

    The parent's key is inherited ONLY toward the parent's own origin; a
    cross-origin role gets ``None`` — the parent's Bearer token is never
    forwarded to a host a wire payload advertised.
    """
    if _same_origin(role_base_url, parent.base_url):
        return parent.api_key
    return None


def agent_engine_config(config: EngineConfig, profile: AgentProfile, roles: Any) -> EngineConfig:
    """Build the :class:`EngineConfig` one agent seat runs against.

    The ONE builder (plan t9): a ``dataclasses.replace`` of *config* with
    ``model`` = the role's served id (the profile's ``resolved_model`` when
    the role is not advertised — the recorded-fallback case), ``base_url`` =
    :func:`colleague.lobes.resolve_role_base_url` (the role's own advertised
    endpoint when dialable, else the gateway origin), ``api_key`` = the
    parent's key only when the role's dial target shares the parent's origin
    (#348 hygiene — ``None`` cross-origin, never the parent's), and
    ``context_budget_tokens`` = the role's OWN advertised context (the bigger
    sliding window is intended: cortex 1,048,576 per the 2026-08-21
    re-probe; worker 65,536 when ready). ``refresh_seat`` and ``on_delta``
    are cleared so the seat never inherits the parent's stale-pin refresh or
    streaming sink; every other knob inherits unchanged.

    *roles* is a ``lobes.LobesRoles`` (or a test double) exposing the role
    named by ``profile.model_role`` as a ``RoleInfo``-like (``.model``,
    ``.endpoint``, ``.context``); an absent role degrades to the profile's
    own trace data, never a refusal.
    """
    role = getattr(roles, profile.model_role, None)
    model = role.model if role is not None else profile.resolved_model
    gateway_url = getattr(config, "lobes_gateway_url", None)
    base_url = _role_base_url(role, gateway_url, config.base_url)
    seat_context = int(getattr(role, "context", 0) or 0) if role is not None else 0
    return cast(
        EngineConfig,
        dataclasses.replace(
            config,
            model=model,
            base_url=base_url,
            api_key=_role_api_key(base_url, config),
            context_budget_tokens=seat_context or config.context_budget_tokens,
            refresh_seat=None,
            on_delta=None,
        ),
    )


# ---------------------------------------------------------------------------
# Token estimate — the engine's exact counter when available, else chars
# ---------------------------------------------------------------------------


def estimate_tokens(
    engine: Any, config: EngineConfig, messages: Sequence[Mapping[str, Any]]
) -> tuple[int, str]:
    """Count *messages* for one invocation, labelling the source.

    Uses the engine's exact counter when available —
    ``engine.make_count_tokens(config)`` (the ``vllm_openai._make_count_tokens``
    seam: the ``/tokenize`` endpoint, degrading to the char heuristic
    internally) — and falls back to
    :func:`colleague.context.count_tokens_chars` when the engine exposes no
    such seam or the counter fails. Returns ``(estimate, source)`` with
    ``source`` in :data:`TOKEN_ESTIMATE_SOURCES`: ``"tokenize"`` when the
    engine's counter answered, ``"chars"`` otherwise. Never raises.
    """
    make = getattr(engine, "make_count_tokens", None)
    if callable(make):
        try:
            return int(make(config)(list(messages))), "tokenize"
        except Exception:  # noqa: BLE001 - a failing counter degrades to chars
            pass
    return count_tokens_chars(list(messages)), "chars"


# ---------------------------------------------------------------------------
# The ledger writer — 'invocation' events (t4)
# ---------------------------------------------------------------------------


def append_invocation(ledger: TaskLedger, record: InvocationRecord) -> InvocationRecord:
    """Append *record* to the task ledger as an ``invocation`` event.

    The event carries the identity + manifest fields (refs and digests, never
    payloads) and DELIBERATELY omits ``token_estimate`` — the estimate is a
    pre-send sizing figure that belongs on the record/artifact, never in the
    ledger, and never in Usage. Returns a NEW record (the input is frozen)
    with the ledger-assigned ``seq`` and the ``ledger_digest`` of the state
    AFTER the append — what ``derive_snapshot`` replays — so the record
    always names the ledger state it ran under.
    """
    data: dict[str, Any] = {
        "agent_id": record.agent_id,
        "purpose": record.purpose,
        "model_role": record.model_role,
        "resolved_model": record.resolved_model,
        "fallback_from_role": record.fallback_from_role,
        "tool_surface_digest": record.tool_surface_digest,
        "nucleus_refs": list(record.nucleus_refs),
        "working_set_refs": list(record.working_set_refs),
        "retrieved_memory_refs": list(record.retrieved_memory_refs),
        "peer_message_refs": list(record.peer_message_refs),
        "truncated": record.truncated,
        "parent_agent_id": record.parent_agent_id,
        "delegation_id": record.delegation_id,
    }
    event: LedgerEvent = ledger.append("invocation", data)
    snapshot = ledger.derive()
    return dataclasses.replace(record, seq=event.seq, ledger_digest=snapshot.state_digest)

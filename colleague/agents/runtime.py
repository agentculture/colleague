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
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, cast
from urllib.parse import urlsplit

from colleague.agents.profile import PURPOSE_ROLE, AgentProfile
from colleague.agents.state.ledger import LedgerEvent, TaskLedger
from colleague.agents.tools import tool_surface_digest
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.lobes import resolve_role_base_url

__all__ = [
    "TOKEN_ESTIMATE_SOURCES",
    "InvocationRecord",
    "agent_engine_config",
    "append_invocation",
    "estimate_tokens",
    "seat_ceiling",
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
    reasoning_effort: Optional[str] = None

    def __post_init__(self) -> None:
        if self.token_estimate_source not in TOKEN_ESTIMATE_SOURCES:
            raise ValueError(
                f"unknown token_estimate_source: {self.token_estimate_source!r} "
                f"(expected one of {TOKEN_ESTIMATE_SOURCES})"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (all fields; None values preserved).

        ``reasoning_effort`` is the ONE exception: it is omitted entirely
        when unset (#416 t7, c29/h20) — an unarmed/unset-effort run's
        records stay byte-identical to before this field existed, and
        :func:`append_invocation`'s ledger event follows the same
        omit-when-``None`` rule.
        """
        d: dict[str, Any] = {
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
        if self.reasoning_effort is not None:
            d["reasoning_effort"] = self.reasoning_effort
        return d

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
            reasoning_effort=data.get("reasoning_effort"),
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
    seat = cast(
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
    # The seat's PURPOSE rides along explicitly. ``agents_profile`` is a dynamic
    # attribute, so ``dataclasses.replace`` drops it — and the purpose is what
    # ``loop.resolve_role`` narrows the seat's tool surface by, and what
    # ``subagents._seat_purpose`` ranks a delegation's bounds against. A seat
    # built without it silently widens to the full ``thinker_coder`` surface,
    # which is exactly the delegation hole the t11 enforcement closes; the
    # pending fold of ``subagents._child_config_for_profile`` onto this builder
    # (#412) must therefore keep carrying it.
    setattr(seat, "agents_profile", profile.purpose)
    # Per-seat thinking effort (#416 t4): the agent seat carries the rung of
    # the seat its PURPOSE names (talker→senses, thinker_coder→cortex,
    # worker→worker) via the plain ``reasoning_effort_seat`` attribute that
    # ``vllm_openai._effort_for`` honors ahead of the acting seat's resolved
    # rung. A purpose with no seat-table row (associate) resolves to None —
    # unset, byte-identical.
    from colleague import effort

    _seat_name = PURPOSE_ROLE.get(profile.purpose)
    setattr(
        seat,
        "reasoning_effort_seat",
        effort.resolve_effort(
            kill_switch=(config.reasoning_effort == "default"),
            seat_override=config.reasoning_effort_seats.get(_seat_name) if _seat_name else None,
            seat=_seat_name,
        ),
    )
    return seat


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
        with suppress(Exception):  # a failing counter degrades to chars
            return int(make(config)(list(messages))), "tokenize"
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
    if record.reasoning_effort is not None:
        data["reasoning_effort"] = record.reasoning_effort
    event: LedgerEvent = ledger.append("invocation", data)
    snapshot = ledger.derive()
    return cast(
        InvocationRecord,
        dataclasses.replace(record, seq=event.seq, ledger_digest=snapshot.state_digest),
    )


# ---------------------------------------------------------------------------
# The per-work-item runtime the loop wires (#411, plan task t15 — bodies live
# HERE; colleague/loop.py carries only the seam calls)
# ---------------------------------------------------------------------------

#: Schema version of the ``TaskResult.agents`` block this runtime folds.
AGENTS_BLOCK_VERSION = 1

#: The acting seat's default purpose when the operator names none.
DEFAULT_ACTING_PURPOSE = "thinker_coder"


def seat_ceiling(config: EngineConfig, role: Optional[str] = None) -> str:
    """One seat's authority ceiling on the closed ``AUTHORITY_CEILINGS`` enum.

    THE single definition of a seat's ceiling — the acting seat reads it here
    and :mod:`colleague.subagents` reads it here when it validates a
    delegation against its parent's bounds (t11's ``validate_delegation``), so
    parent and child are never ranked on two different rules.

    ``read_only`` when *role* is a built-in read-only role (its curated surface
    withholds every write tool — :func:`colleague.roles.is_read_only`);
    otherwise ``repo_patch_no_publish`` under ``--no-pr`` and
    ``repo_patch_publish`` when the seat may publish. Host policy/approvals
    still gate every route — a ceiling is the delegation's own arithmetic, not
    a permission.
    """
    from colleague.roles import is_read_only

    if is_read_only(role):
        return "read_only"
    if getattr(config, "no_pr", False):
        return "repo_patch_no_publish"
    return "repo_patch_publish"


def _closed_authority(config: EngineConfig) -> str:
    """The acting seat's ceiling (kept as the loop-facing name)."""
    return seat_ceiling(config, getattr(config, "role", None))


class AgentsRun:
    """The bound agents-mode runtime for ONE work item (the loop's seam target).

    Built by :func:`make_agents_run` from the resolved :class:`EngineConfig`
    (``None`` when the mode is unarmed — every seam call is then a strict
    no-op and the loop is byte-identical). Owns: the task ledger at the
    OPERATOR repo (``task.flight_repo_path or task.repo_path``, the flight
    plane precedent), the acting seat's :class:`AgentProfile` (purpose
    ``config.agents_profile`` or :data:`DEFAULT_ACTING_PURPOSE`, resolved BY
    ROLE NAME from lobes with the recorded cortex fallback), the effective
    tool surface + its digest, the invocation records, mid-run operator
    inputs, and the final ``TaskResult.agents`` fold. Every method degrades
    (never raises past the seam) so an agents-mode bookkeeping failure can
    never lose the work item.
    """

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.purpose: str = getattr(config, "agents_profile", None) or DEFAULT_ACTING_PURPOSE
        self.ledger: Optional[TaskLedger] = None
        self.ledger_path: Optional[str] = None
        self.profile: Optional[AgentProfile] = None
        self.effective_tools: tuple[str, ...] = ()
        self.tool_digest: str = ""
        self.invocations: list[InvocationRecord] = []
        self.messages: list[dict[str, Any]] = []
        self.fallbacks: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self._began = False

    # -- begin -------------------------------------------------------------

    def begin(
        self, task: Any, *, model: str = "", role_tools: Optional[Sequence[str]] = None
    ) -> None:
        """Open the ledger, resolve the acting profile, seed the immutable request.

        Idempotent. A ledger that already carries events (a continued run) is
        NOT re-seeded with the operator request — the ledger is the
        continuity, not this call.
        """
        if self._began:
            return
        self._began = True
        try:
            self._begin(task, model=model, role_tools=role_tools)
        except Exception as exc:  # noqa: BLE001 - bookkeeping never loses the work item
            self.warnings.append(
                {"kind": "agents-begin-failed", "detail": f"{type(exc).__name__}: {exc}"}
            )

    def _begin(self, task: Any, *, model: str, role_tools: Optional[Sequence[str]]) -> None:
        from colleague.agents.state.ledger import ledger_path
        from colleague.agents.tools import tools_for_purpose

        root = getattr(task, "flight_repo_path", None) or task.repo_path
        path = ledger_path(root, task.id)
        self.ledger_path = str(path)
        self.ledger = TaskLedger(path)
        # Visible to every spawn closure / senses call that captured this config.
        setattr(self.config, "agents_ledger_path", self.ledger_path)

        model_role, resolved_model, fallback = self._resolve_identity(model)
        self.profile = AgentProfile(
            agent_id=f"{self.purpose}-{task.id}",
            purpose=self.purpose,
            model_role=model_role,
            resolved_model=resolved_model,
            tool_profile=self.purpose,
            authority_profile=_closed_authority(self.config),
            parent_agent_id=None,
            task_id=task.id,
            fallback_from_role=fallback,
        )
        if fallback:
            self.fallbacks.append(
                {"purpose": self.purpose, "from_role": fallback, "resolved_model": resolved_model}
            )
        purpose_tools = tools_for_purpose(self.purpose)
        offered = set(role_tools) if role_tools is not None else set(purpose_tools)
        self.effective_tools = tuple(sorted(offered & set(purpose_tools)))
        self.tool_digest = tool_surface_digest(self.effective_tools)

        self._seed_ledger(task, path)

    def _resolve_identity(self, model: str) -> tuple[str, str, Optional[str]]:
        """(model_role, resolved_model, fallback_from_role) for the acting purpose."""
        from colleague.agents.profile import PURPOSE_ROLE, resolve_profile

        roles = self._roles()
        fallback: Optional[str] = None
        model_role = PURPOSE_ROLE.get(self.purpose, "cortex")
        resolved_model = model or self.config.model
        if roles is not None:
            with suppress(Exception):  # no usable roles: the main seat is the floor
                res = resolve_profile(self.purpose, roles)
                model_role, resolved_model, fallback = (
                    res.model_role,
                    res.resolved_model,
                    res.fallback_from_role,
                )
        elif model_role != "cortex":
            fallback = model_role
            model_role = "cortex"
        return model_role, resolved_model, fallback

    def _seed_ledger(self, task: Any, path: Any) -> None:
        """Seed the immutable request + constraints + acceptance ONCE.

        Never re-seeded on a continued ledger — the ledger is the continuity.
        """
        from colleague.agents.state.ledger import read_ledger

        if self.ledger is None:
            return
        try:
            already = bool(read_ledger(path).events)
        except Exception:  # noqa: BLE001 - unreadable/absent = seed fresh
            already = False
        if already:
            return
        self.ledger.append(
            "operator_request",
            {
                "text": task.instruction,
                "context": getattr(task, "context", "") or "",
                "no_pr": bool(getattr(self.config, "no_pr", False)),
                "mode": getattr(self.config, "mode", None),
                "role": getattr(self.config, "role", None),
                "profile": self.purpose,
            },
        )
        for c in getattr(task, "constraints", None) or []:
            self.ledger.append("constraint", {"text": c})
        for a in getattr(task, "acceptance", None) or []:
            self.ledger.append("acceptance", {"text": a})

    def _roles(self) -> Any:
        gateway = getattr(self.config, "lobes_gateway_url", None)
        if not gateway:
            return None
        try:
            from colleague import lobes as _lobes

            return _lobes.resolve_roles(gateway)
        except Exception:  # noqa: BLE001 - unreachable gateway: main seat is the floor
            return None

    # -- prompt material ----------------------------------------------------

    def system_addendum(self) -> str:
        """Guidance table + the STATIC nucleus, appended ONCE to the system prompt.

        Static by design (cache-friendly): the request, constraints, acceptance
        and authority never change mid-run; dynamic state lives on the ledger.
        """
        from colleague.agents.guidance import build_guidance_text
        from colleague.agents.state.context import build_nucleus

        parts = [build_guidance_text()]
        if self.ledger is not None:
            with_suppress = None
            try:
                read = self.ledger.read() if hasattr(self.ledger, "read") else None
                events = getattr(read, "events", None)
                snapshot = self.ledger.derive()
                with_suppress = build_nucleus(snapshot, events)
            except Exception:  # noqa: BLE001 - nucleus is advisory
                with_suppress = None
            if with_suppress:
                parts.append(str(with_suppress.get("content", "")))
        return "\n\n".join(p for p in parts if p)

    # -- per-invocation --------------------------------------------------------

    def record_invocation(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        truncated: bool = False,
        count_tokens: Any = None,
    ) -> Optional[InvocationRecord]:
        """Append ONE invocation record (identity + manifest) for a model call."""
        if self.ledger is None or self.profile is None:
            return None
        try:
            if callable(count_tokens):
                estimate, source = int(count_tokens(list(messages))), "tokenize"
            else:
                estimate, source = count_tokens_chars(list(messages)), "chars"
        except Exception:  # noqa: BLE001
            estimate, source = count_tokens_chars(list(messages)), "chars"
        try:
            from colleague import effort as _effort

            record = InvocationRecord(
                agent_id=self.profile.agent_id,
                purpose=self.profile.purpose,
                model_role=self.profile.model_role,
                resolved_model=self.profile.resolved_model,
                fallback_from_role=self.profile.fallback_from_role,
                tool_surface_digest=self.tool_digest,
                ledger_digest="",
                token_estimate=estimate,
                token_estimate_source=source,
                truncated=truncated,
                # Read off the seat's EngineConfig at record time (#416 t7,
                # c29/h20) — NEVER recomputed from SEAT_TABLE/ROLE_TABLE.
                reasoning_effort=_effort.effort_of(self.config),
            )
            record = append_invocation(self.ledger, record)
        except Exception as exc:  # noqa: BLE001 - bookkeeping never loses the turn
            self.warnings.append(
                {"kind": "agents-record-failed", "detail": f"{type(exc).__name__}: {exc}"}
            )
            return None
        self.invocations.append(record)
        return record

    def operator_input(self, text: str, *, via: str) -> None:
        """Ledger a mid-run operator input (flight guidance, talk, guide_cortex)."""
        if self.ledger is None or not text:
            return
        try:
            self.ledger.append("operator_input", {"text": text, "via": via})
        except Exception as exc:  # noqa: BLE001
            self.warnings.append({"kind": "agents-operator-input-failed", "detail": str(exc)})

    # -- end -------------------------------------------------------------------

    def block(self) -> dict[str, Any]:
        """The ``TaskResult.agents`` block (schema :data:`AGENTS_BLOCK_VERSION`)."""
        digest = None
        if self.ledger is not None:
            try:
                digest = self.ledger.derive().state_digest
            except Exception:  # noqa: BLE001
                digest = None
        from colleague.agents.artifact_block import build_agents_block

        return build_agents_block(
            list(self.invocations),
            list(self.messages),
            fallbacks=list(self.fallbacks),
            ledger_path=self.ledger_path,
            ledger_digest=digest,
        )

    def end(self, result: Any) -> None:
        """Fold changed paths + the block onto *result* (every exit path; never raises)."""
        if self.ledger is not None:
            for path in getattr(result, "changed_files", None) or []:
                try:
                    self.ledger.append("changed_path", {"path": path})
                except Exception:  # noqa: BLE001
                    break
        with suppress(Exception):  # the fold is best-effort
            block = self.block()
            if self.warnings:
                block["warnings"] = list(self.warnings)
            if getattr(result, "agents", None) is None:
                result.agents = block


def make_agents_run(config: Any) -> Optional[AgentsRun]:
    """Bind the agents runtime for *config* — ``None`` (a strict no-op) when unarmed."""
    if not getattr(config, "agents", False):
        return None
    return AgentsRun(config)

"""Talker = senses: identity + invocation records at the senses call sites (#411, t16).

The **talker** purpose (``colleague.agents.profile.PURPOSE_ROLE["talker"]`` →
the ``senses`` role) is the structurally tools-off front door. This module is
the pure helper :mod:`colleague.senses` / :mod:`colleague.senses_loop` call at
every senses completion so that, when model-bound agents are ARMED, each
completion leaves a per-invocation :class:`~colleague.agents.runtime.
InvocationRecord` (purpose ``talker``, model_role ``senses``, the digest of the
EMPTY tool surface — :data:`colleague.agents.tools.TALKER_TOOLS`) on the task
ledger, and a ``guide_cortex`` move lands as an ``operator_input`` event (it
carries the operator's own words into the run — spec c19/c21/h25).

Arming rule (read, never resolved here): ``config.agents`` truthy AND
``config.agents_ledger_path`` set (the armed loop, t15, sets the path on the
:class:`~colleague.config.EngineConfig`; the senses seat inherits it through
``senses_engine_config``). Unarmed, or no ledger path → every helper is a
strict no-op and :func:`recording_complete` returns the caller's own callable
UNCHANGED (byte-identical wire + artifact). A headless / cortex-only run has
no senses config at all, so it never reaches these seams.

What this module can NEVER do: it appends only ``invocation`` and
``operator_input`` events — never ``delegate`` / ``return`` / ``message`` —
and it imports neither :mod:`colleague.agents.delegation` nor
:mod:`colleague.agents.messages`; a talker reply / clarify / narrate is
display-only and is not ledgered at all (it carries no authority). Every
helper suppresses its own failures: a broken ledger never breaks a senses
call. Pure stdlib + the sibling agent modules; no subprocess, no threads, no
network, no import of ``colleague/loop.py``.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from colleague.agents.profile import PURPOSE_ROLE
from colleague.agents.runtime import InvocationRecord, append_invocation, estimate_tokens
from colleague.agents.state.ledger import LedgerEvent, TaskLedger
from colleague.agents.tools import TALKER_TOOLS, tool_surface_digest

__all__ = [
    "GUIDE_CORTEX_VIA",
    "MAX_OPERATOR_INPUT_CHARS",
    "TALKER_PURPOSE",
    "TALKER_ROLE",
    "TALKER_TOOL_SURFACE_DIGEST",
    "record_operator_input",
    "record_talker_invocation",
    "recording_complete",
    "talker_ledger_path",
]

#: The purpose every senses completion is recorded under.
TALKER_PURPOSE = "talker"

#: The lobes role the talker purpose resolves to (``senses``) — read from the
#: enumerated table, never retyped.
TALKER_ROLE = PURPOSE_ROLE[TALKER_PURPOSE]

#: The digest of the talker's EMPTY tool surface — the same sha256 every
#: record carries, computed once.
TALKER_TOOL_SURFACE_DIGEST = tool_surface_digest(TALKER_TOOLS)

#: The ``via`` label an ``operator_input`` event carries when a senses
#: ``guide_cortex`` move brought the operator's words into the run.
GUIDE_CORTEX_VIA = "senses.guide_cortex"

#: Cap on the operator-input text an event carries (the ledger refuses a line
#: over ``MAX_EVENT_BYTES``; the operator's words are short by construction —
#: a longer guidance is cut here with ``truncated: true`` recorded).
MAX_OPERATOR_INPUT_CHARS = 2048


def talker_ledger_path(config: Any) -> Optional[str]:
    """The task-ledger path when the talker records, else ``None`` (unarmed).

    Armed iff ``config.agents`` is truthy AND ``config.agents_ledger_path`` is a
    non-empty string. Both are read with ``getattr`` so a config double (a
    ``SimpleNamespace`` in the senses-loop tests) or a pre-t15 config without
    the path attribute reads as unarmed.
    """
    if not getattr(config, "agents", False):
        return None
    path = getattr(config, "agents_ledger_path", None)
    if not path:
        return None
    return str(path)


def _ledger_for(path: str) -> TaskLedger:
    return TaskLedger(path)


def record_talker_invocation(
    config: Any,
    messages: Sequence[Mapping[str, Any]],
    *,
    engine: Any = None,
    truncated: bool = False,
) -> Optional[InvocationRecord]:
    """Append ONE ``invocation`` event (purpose ``talker``) for *messages*.

    Returns the ledger-assigned :class:`InvocationRecord`, or ``None`` when
    unarmed or when recording failed (suppressed — a broken ledger never
    breaks the senses call). ``model_role`` is :data:`TALKER_ROLE`,
    ``resolved_model`` the senses seat's served id (``config.model``),
    ``tool_surface_digest`` :data:`TALKER_TOOL_SURFACE_DIGEST` (the empty set),
    ``token_estimate`` from :func:`colleague.agents.runtime.estimate_tokens`
    (the engine's exact counter when it exposes one, else chars — the source
    is labelled), ``agent_id`` ``talker-<ledger task id>``.
    """
    path = talker_ledger_path(config)
    if path is None:
        return None
    try:
        ledger = _ledger_for(path)
        estimate, source = estimate_tokens(engine, config, messages)
        record = InvocationRecord(
            agent_id=f"{TALKER_PURPOSE}-{ledger.task_id}",
            purpose=TALKER_PURPOSE,
            model_role=TALKER_ROLE,
            resolved_model=str(getattr(config, "model", "") or ""),
            fallback_from_role=None,
            tool_surface_digest=TALKER_TOOL_SURFACE_DIGEST,
            ledger_digest=ledger.derive().state_digest,
            token_estimate=estimate,
            token_estimate_source=source,
            truncated=bool(truncated),
        )
        return append_invocation(ledger, record)
    except Exception:  # noqa: BLE001 - recording never breaks a senses call
        return None


def recording_complete(
    complete: Callable[[list[dict[str, Any]]], Any],
    config: Any,
    *,
    engine: Any = None,
    truncation_marker: Optional[str] = None,
) -> Callable[[list[dict[str, Any]]], Any]:
    """Wrap a bound tools-off ``complete`` so each call records a talker invocation.

    Unarmed (see :func:`talker_ledger_path`) returns *complete* ITSELF — the
    identity, so the call site is byte-identical. Armed, the returned callable
    appends one ``invocation`` event per completion (before the send, so the
    record names the ledger state it ran under; a failed send still leaves
    its record — an invocation was attempted) and then calls through
    unchanged. ``truncated`` is ``True`` when *truncation_marker* (the senses
    ``_TRUNCATION_NOTE``) appears in any message content.
    """
    if talker_ledger_path(config) is None:
        return complete

    def recording(messages: list[dict[str, Any]]) -> Any:
        truncated = bool(truncation_marker) and any(
            truncation_marker in str(m.get("content") or "") for m in messages
        )
        record_talker_invocation(config, messages, engine=engine, truncated=truncated)
        return complete(messages)

    return recording


def record_operator_input(
    config: Any, text: str, *, via: str = GUIDE_CORTEX_VIA, source: Optional[str] = None
) -> Optional[LedgerEvent]:
    """Append ONE ``operator_input`` event carrying *text* (capped) + ``via``.

    The ONLY non-``invocation`` event the talker ever writes: a ``guide_cortex``
    move carries the operator's instruction into the run, so it is an
    operator input — never a ``delegate`` / ``handoff`` authority. Returns the
    event, or ``None`` when unarmed, when *text* is blank, or when the append
    failed (suppressed).
    """
    path = talker_ledger_path(config)
    body = str(text or "").strip()
    if path is None or not body:
        return None
    data: dict[str, Any] = {"via": via}
    if len(body) > MAX_OPERATOR_INPUT_CHARS:
        data["truncated"] = True
        body = body[:MAX_OPERATOR_INPUT_CHARS]
    data["text"] = body
    if source:
        data["source"] = str(source)
    try:
        return _ledger_for(path).append("operator_input", data)
    except Exception:  # noqa: BLE001 - recording never breaks a senses move
        return None

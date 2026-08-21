"""Typed agent messages + the per-task message budget (#411, task t3).

Agents exchange typed, attributable messages — ``delegate`` / ``ask`` /
``inform`` / ``challenge`` / ``handoff`` / ``return`` — as in-process records
destined for the task ledger (t4). There is NO transport here: no socket, no
subprocess, no thread, no model wire. A message is data; whatever a peer model
wrote into ``content`` (including tool-call-shaped markup) is inert text that
the ledger stores and the reconstruction layer (t10) renders as a labelled
peer block — never parsed as an action.

The refuse/degrade shape mirrors :class:`colleague.senses_moves.MoveResult`:
a small frozen verdict record with ``allowed`` / ``reason`` — validation
REFUSES the whole message (unknown type, or a missing from/to whole) and the
budget REFUSES at the cap, both without raising.

The per-task :class:`MessageBudget` mirrors :class:`colleague.subagents.
_AgentBudget` (subagents.py:246-289): one shared counter per task, charged
atomically (lock-guarded), refusing at the cap so a scripted ask/challenge
ping-pong can never run unbounded. The cap is the constant
:data:`colleague.config.MAX_AGENT_MESSAGES` — a config constant, never
model-chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from colleague.config import MAX_AGENT_MESSAGES

# ---------------------------------------------------------------------------
# The closed message vocabulary — enumerated in exactly ONE place.
# ---------------------------------------------------------------------------

#: Hand a scoped piece of work to another agent (a ledgered delegation).
MSG_DELEGATE = "delegate"
#: Ask another agent a question and request a reply.
MSG_ASK = "ask"
#: Inform another agent of a fact or state (no reply requested by default).
MSG_INFORM = "inform"
#: Challenge another agent's recorded claim (both sides stay on the ledger).
MSG_CHALLENGE = "challenge"
#: Transfer ownership of a plan node to another agent.
MSG_HANDOFF = "handoff"
#: Return a completed delegation to the delegating agent.
MSG_RETURN = "return"

#: The complete, ONLY-valid set of agent message types. Anything else is
#: refused whole by :func:`validate_message`.
MESSAGE_TYPES: "frozenset[str]" = frozenset(
    {MSG_DELEGATE, MSG_ASK, MSG_INFORM, MSG_CHALLENGE, MSG_HANDOFF, MSG_RETURN}
)

#: The exact refusal reason :class:`MessageBudget` reports at the cap.
BUDGET_EXHAUSTED_REASON = "message budget exhausted"


@dataclass(frozen=True)
class MessageVerdict:
    """The record of one validation/charge attempt — refuse/degrade-shaped.

    Mirrors :class:`colleague.senses_moves.MoveResult`: exactly one outcome
    holds — ``allowed=True`` with ``reason=None`` (clean), or
    ``allowed=False`` with a short human-readable ``reason`` (refused whole;
    nothing was recorded or charged).
    """

    allowed: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class AgentMessage:
    """One typed, attributable agent-to-agent message (in-process record).

    ``evidence_refs`` are references to evidence (artifact step index, file
    path, message id) — never large payloads. ``requested_response`` names the
    message type the sender expects back (e.g. an ``ask`` requesting a
    ``return``); it is ``None`` when no response is requested. ``seq`` is the
    ledger-owned sequence number assigned when the message is appended (t4);
    it is ``0`` on a freshly built, not-yet-ledgered message.

    The record carries NO rationale / chain-of-thought field — a peer's
    reasoning is not a first-class message payload (honesty condition: the
    nucleus never contains chain-of-thought), and :meth:`to_dict` emits none.
    """

    message_id: str
    task_id: str
    from_agent: str
    to_agent: str
    type: str
    subject: str
    content: str
    evidence_refs: Tuple[str, ...] = ()
    requested_response: Optional[str] = None
    seq: int = 0

    def to_dict(self) -> "dict[str, Any]":
        """Serialize to a plain dict for the task ledger (t4).

        Emits exactly the dataclass fields — no rationale / chain-of-thought
        key, ever.
        """
        return {
            "message_id": self.message_id,
            "task_id": self.task_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "type": self.type,
            "subject": self.subject,
            "content": self.content,
            "evidence_refs": list(self.evidence_refs),
            "requested_response": self.requested_response,
            "seq": self.seq,
        }

    @classmethod
    def from_dict(cls, d: "dict[str, Any]") -> "AgentMessage":
        """Rebuild an :class:`AgentMessage` from :meth:`to_dict` output.

        Refuses whole (returns nothing, raises ``ValueError``) on an unknown
        type or a missing from/to whole — the same closed-vocabulary rule
        :func:`validate_message` applies.
        """
        verdict = validate_message(
            type=d.get("type"),
            from_agent=d.get("from_agent"),
            to_agent=d.get("to_agent"),
        )
        if not verdict.allowed:
            raise ValueError(verdict.reason)
        return cls(
            message_id=d["message_id"],
            task_id=d["task_id"],
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            type=d["type"],
            subject=d.get("subject", ""),
            content=d.get("content", ""),
            evidence_refs=tuple(d.get("evidence_refs", ())),
            requested_response=d.get("requested_response"),
            seq=d.get("seq", 0),
        )


def validate_message(
    *,
    type: Any,
    from_agent: Any,
    to_agent: Any,
) -> MessageVerdict:
    """Validate a message's closed-vocabulary fields; refuse the whole.

    A message is allowed only when BOTH hold:

    - ``type`` is one of :data:`MESSAGE_TYPES` (the closed vocabulary — an
      unknown type is a hallucination, refused whole, never coerced);
    - the from/to whole is present: ``from_agent`` and ``to_agent`` are both
      non-empty strings (a message with no sender or no recipient is
      unattributable and refused whole).

    Returns a :class:`MessageVerdict`; never raises.
    """
    if type not in MESSAGE_TYPES:
        return MessageVerdict(
            allowed=False,
            reason=f"unknown message type {type!r}; refused whole",
        )
    if not isinstance(from_agent, str) or not from_agent.strip():
        return MessageVerdict(
            allowed=False,
            reason="missing from_agent; refused whole",
        )
    if not isinstance(to_agent, str) or not to_agent.strip():
        return MessageVerdict(
            allowed=False,
            reason="missing to_agent; refused whole",
        )
    return MessageVerdict(allowed=True)


class MessageBudget:
    """A per-task agent-message counter shared across ONE task.

    Mirrors :class:`colleague.subagents._AgentBudget` (subagents.py:246-289):
    every message an agent sends on the task charges this budget exactly once
    before it is recorded, so the TOTAL number of messages on one task is
    bounded by ``limit`` (default :data:`MAX_AGENT_MESSAGES`) — the structural
    termination guarantee that a scripted ask/challenge ping-pong never runs
    unbounded.

    Charging is atomic in the sense that matters here: the check-and-increment
    is ONE indivisible operation on an in-process record (messages are
    single-threaded ledger data — no transport, no socket, no thread), and it
    checks BEFORE incrementing so ``count`` never exceeds ``limit`` even
    across repeated refused attempts: the (limit+1)-th charge refuses without
    bumping the count, so ``count`` is exactly the number of messages actually
    allowed.

    The budget is created ONCE per task and threaded to every sender. It
    REFUSES — it never raises: :meth:`charge` returns a
    :class:`MessageVerdict` with ``allowed=False`` and the reason
    :data:`BUDGET_EXHAUSTED_REASON` at the cap, so exhaustion is recorded
    honestly on the ledger and ``TaskResult.warnings`` (t4/t15).
    """

    def __init__(self, limit: int = MAX_AGENT_MESSAGES) -> None:
        self.limit = limit
        self.count = 0

    def charge(self) -> MessageVerdict:
        """Account for one more message; refuse at the cap (zero work done).

        Checks BEFORE incrementing so ``count`` never exceeds ``limit`` even
        across repeated refused attempts: the (limit+1)-th charge refuses
        without bumping the count, so ``count`` is exactly the number of
        messages that were actually allowed.
        """
        if self.count >= self.limit:
            return MessageVerdict(allowed=False, reason=BUDGET_EXHAUSTED_REASON)
        self.count += 1
        return MessageVerdict(allowed=True)

    def remaining(self) -> int:
        """A snapshot of how many more messages may be sent (best-effort)."""
        return max(0, self.limit - self.count)


def new_message_budget(limit: int = MAX_AGENT_MESSAGES) -> MessageBudget:
    """Create ONE shared per-task message budget (default cap
    :data:`MAX_AGENT_MESSAGES`)."""
    return MessageBudget(limit)

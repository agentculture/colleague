"""Append-only evaluation ledger for the thought-action-evaluation mode (#397, t11).

Pure stdlib, no I/O, no subprocess, no network — same discipline as
:mod:`colleague.configevents` and :mod:`colleague.thought`.

This module owns the append-only chain of entries that records one episode of
the thought -> action -> evaluation -> reroute -> execution -> outcome cycle.
Each entry carries a ``seq`` (assigned by the ledger, never by the caller),
a ``kind`` (one of six fixed values), a ``thought_id`` (the chain key),
an optional ``action_id``, a short ``detail`` line, a ``seat`` attribution,
and a ``model`` id.

The ledger is a SEPARATE surface from config_events / EpisodeConfigLifecycle.
Configuration and intention answer different questions.

Design invariants
------------------
- **Append-only.** :class:`EvaluationLedger` exposes exactly ``append`` +
  ``entries`` (plus read-only helpers) — no edit/remove/clear API exists to
  rewrite history once an entry lands.
- **seq is ledger-owned.** :meth:`append` assigns ``seq`` itself (the ledger
  is the sole authority on ordering); a hand-built ``LedgerEntry`` may set
  it directly for tests that build a sequence without going through a
  ledger.
- **Kind and seat are closed.** ``kind`` must be one of the six fixed values;
  ``seat`` must be one of the four fixed values. Unknown values refuse the
  whole entry.

Versioning
----------
:data:`LEDGER_SCHEMA_VERSION` is the current schema version. A raw payload
MAY omit ``version`` (defaults to the current version); if present it MUST
match :data:`LEDGER_SCHEMA_VERSION` exactly, or the whole ledger refuses to
load it.

Left for later tasks
--------------------
* ``t13`` — the control loop that drives the thought-action-evaluation cycle.
  Nothing here decides when entries are appended.
* ``t12`` — arming/config. This module is contract-only and is not wired
  into :mod:`colleague.loop`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional, Sequence

# ---------------------------------------------------------------------------
# Kind and seat vocabularies
# ---------------------------------------------------------------------------

#: A thought step — the front seat's committed decision artifact.
KIND_THOUGHT = "thought"
#: An action step — the worker seat's proposed action bound to a thought.
KIND_ACTION = "action"
#: An evaluation step — the evaluator seat's fidelity judgment.
KIND_EVALUATION = "evaluation"
#: A reroute step — where the run goes after evaluation (rethink/replan).
KIND_REROUTE = "reroute"
#: An execution step — the host seat's execution of the action.
KIND_EXECUTION = "execution"
#: An outcome step — the observed result of the execution.
KIND_OUTCOME = "outcome"

#: Every valid :class:`LedgerEntry` ``kind`` value, in the fixed reading order
#: used throughout this module and the docs.
KINDS: tuple[str, ...] = (
    KIND_THOUGHT,
    KIND_ACTION,
    KIND_EVALUATION,
    KIND_REROUTE,
    KIND_EXECUTION,
    KIND_OUTCOME,
)

#: The only valid seat values.
SEAT_FRONT = "front"
SEAT_WORKER = "worker"
SEAT_EVALUATOR = "evaluator"
SEAT_HOST = "host"

#: Every valid :class:`LedgerEntry` ``seat`` value.
SEATS: tuple[str, ...] = (SEAT_FRONT, SEAT_WORKER, SEAT_EVALUATOR, SEAT_HOST)

#: The current ledger schema version. A raw payload MAY omit ``version``; if
#: present it MUST equal this exactly.
LEDGER_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# LedgerEntry — one step in the append-only chain
# ---------------------------------------------------------------------------


@dataclass
class LedgerEntry:
    """One step in the evaluation ledger.

    Fields
    ------
    kind:
        One of :data:`KINDS`. Not validated by the dataclass itself
        (validation lives on :meth:`EvaluationLedger.append`); a hand-built
        ``LedgerEntry`` with an unrecognised kind is still a valid dataclass
        instance (e.g. for a test asserting the digest changes under an
        arbitrary payload).
    thought_id:
        The ``thought_id`` this step is bound to — the chain key that lets a
        reader reconstruct which thought produced which action, verdict, and
        outcome.
    action_id:
        The ``action_id`` of the action this step is bound to, or ``None``
        for thought/evaluation/outcome entries that do not carry an action.
    detail:
        A short human-readable line describing this step.
    seat:
        The seat that produced this entry — one of :data:`SEATS`.
    model:
        The actual contributing model id, may be empty for host entries.
    seq:
        A monotonically increasing position in the ledger.
        :meth:`EvaluationLedger.append` assigns this itself; a hand-built
        ``LedgerEntry`` may set it directly for tests.
    """

    kind: str
    thought_id: str
    action_id: Optional[str] = None
    detail: str = ""
    seat: str = ""
    model: str = ""
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize this entry to a plain dict."""
        d: dict[str, Any] = {
            "kind": self.kind,
            "thought_id": self.thought_id,
            "detail": self.detail,
            "seat": self.seat,
            "model": self.model,
            "seq": self.seq,
        }
        if self.action_id is not None:
            d["action_id"] = self.action_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LedgerEntry":
        """Coerce an already-validated entry-shaped mapping into a
        :class:`LedgerEntry`. Callers that read untrusted input should run
        :meth:`EvaluationLedger.append` first — this constructor does not
        re-validate; it is the artifact-readback half of the round-trip."""
        return cls(
            kind=str(data.get("kind", "")),
            thought_id=str(data.get("thought_id", "")),
            action_id=(str(data["action_id"]) if data.get("action_id") is not None else None),
            detail=str(data.get("detail", "")),
            seat=str(data.get("seat", "")),
            model=str(data.get("model", "")),
            seq=int(data.get("seq", 0) or 0),
        )

    def canonical(self) -> str:
        """A deterministic, order-independent-of-construction string encoding.

        Used by :func:`ledger_digest` for hashing: ``json.dumps`` with
        sorted keys and no incidental whitespace, so two ``LedgerEntry``
        instances with equal field values ALWAYS produce byte-identical
        canonical strings regardless of the keyword-argument order they were
        constructed with.
        """
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# EvaluationLedger — the append-only chain
# ---------------------------------------------------------------------------


class EvaluationLedger:
    """An append-only sequence of :class:`LedgerEntry` records.

    Exposes exactly two operations on the sequence itself: :meth:`append`
    (add one new entry, assigning its ``seq``) and :meth:`entries` (read the
    full ordered sequence back as a defensive copy). There is no
    mutate/remove/clear API — once an entry is appended it is a permanent
    part of the ledger's history.
    """

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def append(
        self,
        kind: str,
        *,
        thought_id: str,
        action_id: Optional[str] = None,
        detail: str = "",
        seat: str = "",
        model: str = "",
    ) -> LedgerEntry:
        """Append one new entry, assigning it the next sequence number.

        Raises ``ValueError`` for a ``kind`` outside :data:`KINDS` or a
        ``seat`` outside :data:`SEATS` — the ledger is the sanctioned
        construction path and refuses to record a kind or seat that has no
        defined meaning. Returns the appended :class:`LedgerEntry` (with its
        assigned ``seq``) for convenience.
        """
        if kind not in KINDS:
            raise ValueError(f"unknown ledger kind: {kind!r} (expected one of {KINDS})")
        if seat and seat not in SEATS:
            raise ValueError(f"unknown ledger seat: {seat!r} (expected one of {SEATS})")
        entry = LedgerEntry(
            kind=kind,
            thought_id=str(thought_id),
            action_id=action_id,
            detail=str(detail),
            seat=str(seat),
            model=str(model),
            seq=len(self._entries),
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> list[LedgerEntry]:
        """The full ordered entry sequence, as a defensive copy.

        Mutating the returned list never affects the ledger itself — the
        ledger's own internal list is the only durable copy, and it is only
        ever grown via :meth:`append`.
        """
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full ledger to a plain dict.

        The output is suitable for JSON round-tripping and is accepted by
        :func:`from_dict` to produce an equal :class:`EvaluationLedger`.
        """
        return {
            "version": LEDGER_SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in self._entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationLedger":
        """Coerce an already-validated ledger-shaped mapping into an
        :class:`EvaluationLedger`. Callers that read untrusted input should
        validate the structure first — this constructor does not re-validate;
        it is the artifact-readback half of the round-trip."""
        version = int(data.get("version", LEDGER_SCHEMA_VERSION))
        if version != LEDGER_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported ledger schema version {version!r} "
                f"(expected {LEDGER_SCHEMA_VERSION})"
            )
        ledger = cls()
        for entry_data in data.get("entries", []):
            entry = LedgerEntry.from_dict(entry_data)
            ledger._entries.append(entry)
        return ledger

    def digest(self) -> str:
        """Convenience: :func:`ledger_digest` over this ledger's own entries."""
        return ledger_digest(self.entries())


def ledger_digest(entries: Sequence[LedgerEntry]) -> str:
    """A deterministic sha256 hex digest over the REPLAYED entry sequence alone.

    No ambient state — wall clock, environment, process id, a ledger
    instance's identity, anything not IN ``entries`` — enters this
    computation; the signature accepts exactly the one sequence argument.
    Two independently-built entry lists with equal entries, in the same
    order, ALWAYS produce the identical digest (see
    :meth:`LedgerEntry.canonical` for the per-entry determinism this relies
    on); changing any single entry's kind/thought_id/action_id/detail/seat/
    model/seq, adding, removing, or reordering an entry, all change the
    digest.
    """
    canonical_seq = "[" + ",".join(entry.canonical() for entry in entries) + "]"
    return hashlib.sha256(canonical_seq.encode("utf-8")).hexdigest()

"""Append-only config event stream + effective-config digest (plan task t7).

Part of the three-tier execution arc (docs/plans/2026-08-05-three-tier-execution.md,
covers c9/h9). A cortex configurator (t11, not built this wave) will PROPOSE,
VERIFY, APPLY, and occasionally REFUSE or REVERT changes to a worker/senses
episode's config; this module owns the audit trail those moves land on and
the deterministic digest that makes "what config produced this run" a
reproducible question rather than a trust-me claim.

Design invariants
------------------
- **Append-only.** :class:`ConfigEventStream` exposes exactly ``append`` +
  ``replay`` (plus read-only helpers) — no edit/remove/clear API exists to
  rewrite history once an event lands.
- **The T8 trap.** ``"baseline"`` is an ordinary :data:`EVENT_KINDS` member,
  not a constructor field or other out-of-band seed. A starting config that
  never became an explicit ``baseline`` event is invisible to
  :func:`effective_digest` — because the digest is a pure function of the
  REPLAYED event sequence alone (see that function's docstring), any config
  state that isn't IN the sequence can never be reproduced from, or verified
  against, the digest. This is deliberate: it forces every seeded starting
  point through the same append path as every later move, so "what was the
  config when this ran" always has one honest answer — replay the stream.
- **No liveness from "armed" alone.** :func:`liveness_advanced` reads TRUE
  only when a progress counter (proposed/refused/verified/applied/reverted)
  or the caller-supplied ``boundaries_observed`` input actually advanced.
  Being merely configured/seeded (a lone ``baseline`` event, or an empty
  stream) is not progress — the function's signature has no "armed" flag to
  even ask the question the wrong way.

This module is pure stdlib (dataclasses, hashlib, json) — no I/O, no
subprocess, no network, matching colleague/lattice.py's own "pure data"
stance. ``target``/``origin`` are free-form strings here (not tied to
colleague.lattice.Target/Origin) so this stream stays usable by any future
producer; when the t11 configurator lands, it is expected to populate them
from ``colleague.lattice.Target.value`` / ``Origin.value``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Event kinds
# ---------------------------------------------------------------------------

#: A starting config, seeded before any proposal — deliberately a first-class
#: event kind (the T8 trap guard), never an invisible constructor default.
EVENT_KIND_BASELINE = "baseline"
EVENT_KIND_PROPOSED = "proposed"
EVENT_KIND_REFUSED = "refused"
EVENT_KIND_VERIFIED = "verified"
EVENT_KIND_APPLIED = "applied"
EVENT_KIND_REVERTED = "reverted"
#: A configurator review that never usefully reached the cortex model (no
#: dial resolvable, a dead endpoint, a request error) — the #363
#: armed-is-not-alive lesson applied to this producer: visible on the stream
#: (and therefore the artifact/feed), never silent. Deliberately distinct
#: from ``"refused"`` — a refusal means cortex answered but the answer (or
#: one entry in it) was invalid; ``"degraded"`` means the review never
#: usefully happened at all. A healthy ``{"changes": []}`` reply (nothing to
#: change this window) appends NEITHER kind — it is not a degradation.
EVENT_KIND_DEGRADED = "degraded"

#: Every valid :class:`ConfigEvent` ``kind`` value, in the fixed reading order
#: used throughout this module and the docs — importable so a caller/test can
#: assert exhaustiveness without hand-listing the seven strings again.
#: ``"degraded"`` is appended at the END (never re-ordered into the middle)
#: so existing digests/ordering pins over the first six kinds stay stable.
EVENT_KINDS: tuple[str, ...] = (
    EVENT_KIND_BASELINE,
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    EVENT_KIND_VERIFIED,
    EVENT_KIND_APPLIED,
    EVENT_KIND_REVERTED,
    EVENT_KIND_DEGRADED,
)

#: The kinds that count as "progress" for :func:`liveness_advanced` —
#: deliberately EXCLUDES "baseline". Seeding a starting config is not
#: progress; only an actual proposed/refused/verified/applied/reverted move
#: is (the armed-alone trap this module is named for in the plan's
#: acceptance criteria).
_PROGRESS_KINDS: tuple[str, ...] = (
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    EVENT_KIND_VERIFIED,
    EVENT_KIND_APPLIED,
    EVENT_KIND_REVERTED,
)


@dataclass
class ConfigEvent:
    """One entry in the append-only config event stream.

    Fields
    ------
    kind:
        One of :data:`EVENT_KINDS`. Not validated by the dataclass itself
        (validation lives on :meth:`ConfigEventStream.append`, which is the
        sanctioned construction path); a hand-built ``ConfigEvent`` with an
        unrecognised kind is still a valid dataclass instance (e.g. for a
        test asserting the digest changes under an arbitrary payload).
    target:
        The lattice surface (or other config target) this event concerns —
        a free-form string, e.g. ``"worker.tools"``. Empty when not
        applicable to this event.
    origin:
        The actor that produced this event — a free-form string, e.g.
        ``"host"`` / ``"cortex"`` / ``"worker"``. Empty when not applicable.
    reason:
        Human-readable explanation, populated for a ``"refused"`` event
        (why the change was refused); empty for every other kind by
        convention, though nothing enforces that here.
    seq:
        A monotonically increasing position in the stream.
        :meth:`ConfigEventStream.append` assigns this itself (the stream is
        the sole authority on ordering); a hand-built ``ConfigEvent`` may
        set it directly for tests that build a sequence without going
        through a stream.
    """

    kind: str
    target: str = ""
    origin: str = ""
    reason: str = ""
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "origin": self.origin,
            "reason": self.reason,
            "seq": self.seq,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfigEvent":
        return cls(
            kind=str(data.get("kind", "")),
            target=str(data.get("target", "")),
            origin=str(data.get("origin", "")),
            reason=str(data.get("reason", "")),
            seq=int(data.get("seq", 0) or 0),
        )

    def canonical(self) -> str:
        """A deterministic, order-independent-of-construction string encoding.

        Used by :func:`effective_digest` for hashing: ``json.dumps`` with
        sorted keys and no incidental whitespace, so two ``ConfigEvent``
        instances with equal field values ALWAYS produce byte-identical
        canonical strings regardless of the keyword-argument order they were
        constructed with.
        """
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


class ConfigEventStream:
    """An append-only sequence of :class:`ConfigEvent` records.

    Exposes exactly two operations on the sequence itself: :meth:`append`
    (add one new event, assigning its ``seq``) and :meth:`replay` (read the
    full ordered sequence back as a defensive copy). There is no
    mutate/remove/clear API — once an event is appended it is a permanent
    part of the stream's history, and the only way to "undo" a config move
    is to append a new event describing the undo (e.g. a ``"reverted"``
    event), never to erase the record of what happened.
    """

    def __init__(self) -> None:
        self._events: list[ConfigEvent] = []

    def append(
        self, kind: str, *, target: str = "", origin: str = "", reason: str = ""
    ) -> ConfigEvent:
        """Append one new event, assigning it the next sequence number.

        Raises ``ValueError`` for a ``kind`` outside :data:`EVENT_KINDS` —
        the stream is the sanctioned construction path and refuses to record
        a kind that has no defined meaning. Returns the appended
        :class:`ConfigEvent` (with its assigned ``seq``) for convenience.
        """
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown config event kind: {kind!r} (expected one of {EVENT_KINDS})")
        event = ConfigEvent(
            kind=kind, target=target, origin=origin, reason=reason, seq=len(self._events)
        )
        self._events.append(event)
        return event

    def replay(self) -> list[ConfigEvent]:
        """The full ordered event sequence, as a defensive copy.

        Mutating the returned list never affects the stream itself — the
        stream's own internal list is the only durable copy, and it is only
        ever grown via :meth:`append`.
        """
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def digest(self) -> str:
        """Convenience: :func:`effective_digest` over this stream's own replay."""
        return effective_digest(self.replay())


def effective_digest(events: Sequence[ConfigEvent]) -> str:
    """A deterministic sha256 hex digest over the REPLAYED event sequence alone.

    No ambient state — wall clock, environment, process id, a stream
    instance's identity, anything not IN ``events`` — enters this
    computation; the signature accepts exactly the one sequence argument.
    Two independently-built event lists with equal events, in the same
    order, ALWAYS produce the identical digest (see
    :meth:`ConfigEvent.canonical` for the per-event determinism this relies
    on); changing any single event's kind/target/origin/reason/seq, adding,
    removing, or reordering an event, all change the digest.

    This is the T8-trap guard from the other direction: since nothing
    outside ``events`` can influence the result, a config state that never
    became an explicit event in the sequence (e.g. a seeded "baseline" that
    was only ever a constructor default) can never be reconstructed from —
    or verified against — this digest. The only way to make a starting
    config count is to append it as a ``"baseline"`` :class:`ConfigEvent`.
    """
    canonical_seq = "[" + ",".join(event.canonical() for event in events) + "]"
    return hashlib.sha256(canonical_seq.encode("utf-8")).hexdigest()


def counts_by_kind(events: Sequence[ConfigEvent]) -> dict[str, int]:
    """A ``{kind: count}`` tally derived purely from ``events`` — every kind
    in :data:`EVENT_KINDS` is present in the result (0 when absent from
    ``events``), so a caller never needs a presence check before indexing."""
    counts: dict[str, int] = dict.fromkeys(EVENT_KINDS, 0)
    for event in events:
        counts[event.kind] = counts.get(event.kind, 0) + 1
    return counts


def liveness_advanced(events: Sequence[ConfigEvent], *, boundaries_observed: int = 0) -> bool:
    """True only when a PROGRESS counter has actually advanced.

    "Progress" means at least one ``proposed``/``refused``/``verified``/
    ``applied``/``reverted`` event is present in ``events`` (deliberately
    excluding ``baseline`` — seeding a starting config is not progress), OR
    ``boundaries_observed`` (a caller-supplied count of some other observed
    progress signal, e.g. episode boundaries crossed) is greater than zero.

    An empty stream, or a stream holding only ``baseline`` events, reads
    FALSE — the "armed-alone" trap this function exists to close: a run that
    is merely configured/seeded must never report as live. There is
    deliberately no "armed" (or similarly-named) parameter on this
    function's signature — the only inputs are the replayed event sequence
    and an explicit progress count; a caller cannot even ask this function
    to treat "configured" as "live".
    """
    counts = counts_by_kind(events)
    progressed = sum(counts.get(kind, 0) for kind in _PROGRESS_KINDS)
    return progressed > 0 or boundaries_observed > 0

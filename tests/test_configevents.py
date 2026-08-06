"""Tests for colleague.configevents (plan task t7, covers c9/h9).

The append-only config event stream + deterministic digest that will back
the three-tier configurator's audit trail. This module is exercised in
isolation here — nothing in this test file drives the loop or touches
lattice.py/chain.py (those stay owned by other tasks this wave).

Coverage:
- ``ConfigEvent``: dataclass shape, canonical serialization, round-trip.
- ``ConfigEventStream``: append-only (no mutate/remove API), replay ordering,
  defensive copies.
- ``effective_digest``: deterministic sha256 over the REPLAYED sequence
  alone — identical event lists reproduce the digest, any single differing
  event changes it, and — the T8 trap — a seeded starting config must be an
  explicit ``baseline`` event or it never enters the digest at all.
- Liveness: counters derived purely from the stream, and a liveness
  predicate that is true ONLY when a progress counter (or an externally
  supplied ``boundaries_observed`` count) advanced — never from an "armed"
  flag, because the API has no such parameter to pass.
"""

from __future__ import annotations

import hashlib
import inspect
import json

import pytest

from colleague import configevents as ce

# ---------------------------------------------------------------------------
# ConfigEvent: shape, canonical serialization, round-trip.
# ---------------------------------------------------------------------------


def test_event_kinds_include_baseline_as_a_real_kind() -> None:
    """BASELINE IS AN EVENT KIND — the T8 trap guard: a seeded starting
    config must be representable as an ordinary stream event, not a
    constructor-only field invisible to replay."""
    assert ce.EVENT_KIND_BASELINE in ce.EVENT_KINDS
    assert set(ce.EVENT_KINDS) == {
        "baseline",
        "proposed",
        "refused",
        "verified",
        "applied",
        "reverted",
        "degraded",
    }


def test_event_kinds_include_degraded_appended_at_the_end() -> None:
    """``EVENT_KIND_DEGRADED`` (a configurator review that never usefully
    reached the cortex model) is a real event kind, appended at the END of
    :data:`EVENT_KINDS` — never re-ordered into the middle, so digests/
    ordering pins over the original six kinds stay stable."""
    assert ce.EVENT_KIND_DEGRADED in ce.EVENT_KINDS
    assert ce.EVENT_KINDS[-1] == ce.EVENT_KIND_DEGRADED
    assert ce.EVENT_KINDS.index(ce.EVENT_KIND_DEGRADED) == len(ce.EVENT_KINDS) - 1


def test_stream_accepts_degraded_kind() -> None:
    """A degraded review event round-trips through the sanctioned append
    path exactly like every other recognised kind (contract coercion via
    ``colleague.contract`` needs nothing further -- it validates a kind
    string against no allow-list of its own)."""
    stream = ce.ConfigEventStream()
    event = stream.append(ce.EVENT_KIND_DEGRADED, reason="no cortex dial resolvable")
    assert event.kind == "degraded"
    assert [e.kind for e in stream.replay()] == ["degraded"]


def test_config_event_defaults() -> None:
    event = ce.ConfigEvent(kind=ce.EVENT_KIND_PROPOSED)
    assert event.kind == "proposed"
    assert event.target == ""
    assert event.origin == ""
    assert event.reason == ""
    assert event.seq == 0


def test_config_event_to_dict_key_set() -> None:
    event = ce.ConfigEvent(
        kind="refused", target="worker.tools", origin="cortex", reason="outside ceiling", seq=3
    )
    assert set(event.to_dict().keys()) == {"kind", "target", "origin", "reason", "seq"}


def test_config_event_round_trips_through_from_dict() -> None:
    original = ce.ConfigEvent(
        kind="applied", target="senses.knowledge", origin="worker", reason="", seq=7
    )
    restored = ce.ConfigEvent.from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored == original


def test_config_event_canonical_is_deterministic_and_order_independent_of_construction() -> None:
    """Two events built with the same field values (regardless of kwarg order)
    produce byte-identical canonical serializations."""
    a = ce.ConfigEvent(kind="proposed", target="t", origin="o", reason="r", seq=1)
    b = ce.ConfigEvent(seq=1, reason="r", origin="o", target="t", kind="proposed")
    assert a.canonical() == b.canonical()


def test_config_event_canonical_changes_when_any_field_differs() -> None:
    base = ce.ConfigEvent(kind="proposed", target="t", origin="o", reason="", seq=1)
    variants = [
        ce.ConfigEvent(kind="refused", target="t", origin="o", reason="", seq=1),
        ce.ConfigEvent(kind="proposed", target="other", origin="o", reason="", seq=1),
        ce.ConfigEvent(kind="proposed", target="t", origin="other", reason="", seq=1),
        ce.ConfigEvent(kind="proposed", target="t", origin="o", reason="nope", seq=1),
        ce.ConfigEvent(kind="proposed", target="t", origin="o", reason="", seq=2),
    ]
    base_canonical = base.canonical()
    for variant in variants:
        assert variant.canonical() != base_canonical


# ---------------------------------------------------------------------------
# ConfigEventStream: append-only, replay-only.
# ---------------------------------------------------------------------------


def test_stream_starts_empty() -> None:
    stream = ce.ConfigEventStream()
    assert stream.replay() == []
    assert len(stream) == 0


def test_stream_append_assigns_monotonically_increasing_seq() -> None:
    stream = ce.ConfigEventStream()
    e0 = stream.append(ce.EVENT_KIND_BASELINE, target="worker.tools", origin="host")
    e1 = stream.append(ce.EVENT_KIND_PROPOSED, target="worker.tools", origin="cortex")
    e2 = stream.append(ce.EVENT_KIND_APPLIED, target="worker.tools", origin="host")
    assert [e0.seq, e1.seq, e2.seq] == [0, 1, 2]
    assert [e.seq for e in stream.replay()] == [0, 1, 2]


def test_stream_append_rejects_unknown_kind() -> None:
    stream = ce.ConfigEventStream()
    with pytest.raises(ValueError):
        stream.append("not-a-real-kind")


def test_stream_replay_preserves_append_order() -> None:
    stream = ce.ConfigEventStream()
    stream.append(ce.EVENT_KIND_BASELINE, target="a")
    stream.append(ce.EVENT_KIND_PROPOSED, target="b")
    stream.append(ce.EVENT_KIND_REFUSED, target="c", reason="ceiling")
    kinds = [e.kind for e in stream.replay()]
    assert kinds == ["baseline", "proposed", "refused"]


def test_stream_replay_returns_a_defensive_copy() -> None:
    stream = ce.ConfigEventStream()
    stream.append(ce.EVENT_KIND_BASELINE)
    snapshot = stream.replay()
    snapshot.append(ce.ConfigEvent(kind="proposed"))  # mutate the returned list
    assert len(stream.replay()) == 1  # the stream itself is untouched


def test_stream_has_no_mutation_or_removal_api() -> None:
    """Append-only, replay-only (design contract): the class exposes no way
    to edit or delete a previously-appended event."""
    stream = ce.ConfigEventStream()
    for forbidden in ("remove", "pop", "clear", "delete", "__delitem__", "__setitem__", "insert"):
        assert not hasattr(stream, forbidden), f"ConfigEventStream must not expose {forbidden!r}"


# ---------------------------------------------------------------------------
# effective_digest: deterministic sha256 over the replayed sequence alone.
# ---------------------------------------------------------------------------


def test_digest_of_empty_sequence_is_deterministic() -> None:
    first_digest = ce.effective_digest([])
    second_digest = ce.effective_digest([])
    assert first_digest == second_digest


def test_digest_is_a_sha256_hex_string() -> None:
    digest = ce.effective_digest([ce.ConfigEvent(kind="baseline", seq=0)])
    assert isinstance(digest, str)
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex


def test_identical_event_lists_reproduce_the_digest() -> None:
    """Two INDEPENDENTLY built streams that append the same events, in the
    same order, produce the identical digest — the digest is a pure function
    of the replayed sequence, nothing else."""
    stream_a = ce.ConfigEventStream()
    stream_a.append(ce.EVENT_KIND_BASELINE, target="worker.tools", origin="host")
    stream_a.append(ce.EVENT_KIND_PROPOSED, target="worker.tools", origin="cortex")

    stream_b = ce.ConfigEventStream()
    stream_b.append(ce.EVENT_KIND_BASELINE, target="worker.tools", origin="host")
    stream_b.append(ce.EVENT_KIND_PROPOSED, target="worker.tools", origin="cortex")

    assert ce.effective_digest(stream_a.replay()) == ce.effective_digest(stream_b.replay())


def test_digest_changes_when_any_event_differs() -> None:
    base_events = [
        ce.ConfigEvent(kind="baseline", target="worker.tools", origin="host", seq=0),
        ce.ConfigEvent(kind="proposed", target="worker.tools", origin="cortex", seq=1),
    ]
    base_digest = ce.effective_digest(base_events)

    # A different reason on an otherwise-identical refused event.
    changed_reason = list(base_events) + [
        ce.ConfigEvent(kind="refused", target="worker.tools", origin="cortex", reason="a", seq=2)
    ]
    changed_reason_2 = list(base_events) + [
        ce.ConfigEvent(kind="refused", target="worker.tools", origin="cortex", reason="b", seq=2)
    ]
    assert ce.effective_digest(changed_reason) != ce.effective_digest(changed_reason_2)
    assert ce.effective_digest(changed_reason) != base_digest

    # A different sequence order changes the digest too.
    reordered = [base_events[1], base_events[0]]
    assert ce.effective_digest(reordered) != ce.effective_digest(base_events)

    # Dropping the baseline event changes the digest — proves baseline
    # participates (the T8 trap: nothing outside the sequence can matter, so
    # if baseline didn't count, dropping it would be a no-op — it isn't).
    without_baseline = base_events[1:]
    assert ce.effective_digest(without_baseline) != base_digest


def test_digest_takes_no_ambient_state_only_the_events_argument() -> None:
    """The T8 trap, structurally: effective_digest's signature accepts
    exactly the events sequence — there is no hidden seed/context parameter
    a caller could use to smuggle in a baseline invisible to replay."""
    params = list(inspect.signature(ce.effective_digest).parameters)
    assert params == ["events"]


def test_baseline_must_be_an_explicit_event_to_affect_the_digest() -> None:
    """The T8 trap, end to end: a stream seeded with a baseline event and one
    with NO baseline event (but otherwise identical activity) produce
    DIFFERENT digests — replaying the bare event list is the only way to
    reproduce a digest, so a starting config that never became a stream
    event can never be reconstructed from (or verified against) the digest."""
    seeded = ce.ConfigEventStream()
    seeded.append(ce.EVENT_KIND_BASELINE, target="worker.tools", origin="host")
    seeded.append(ce.EVENT_KIND_APPLIED, target="worker.tools", origin="host")

    unseeded = ce.ConfigEventStream()
    unseeded.append(ce.EVENT_KIND_APPLIED, target="worker.tools", origin="host")

    assert ce.effective_digest(seeded.replay()) != ce.effective_digest(unseeded.replay())
    # And replaying the seeded stream's OWN sequence alone (no other input)
    # reproduces its own digest, byte for byte, every time.
    first_replay_digest = ce.effective_digest(seeded.replay())
    second_replay_digest = ce.effective_digest(seeded.replay())
    assert first_replay_digest == second_replay_digest


def test_digest_matches_manual_sha256_over_canonical_join() -> None:
    """Pins the exact digest algorithm so a future refactor can't silently
    change it: sha256 over the canonical per-event strings joined as a JSON
    array."""
    events = [
        ce.ConfigEvent(kind="baseline", target="a", origin="host", seq=0),
        ce.ConfigEvent(kind="applied", target="a", origin="host", seq=1),
    ]
    expected = hashlib.sha256(
        ("[" + ",".join(e.canonical() for e in events) + "]").encode("utf-8")
    ).hexdigest()
    assert ce.effective_digest(events) == expected


# ---------------------------------------------------------------------------
# Liveness: counters + a predicate that never accepts an "armed" flag.
# ---------------------------------------------------------------------------


def test_counts_by_kind_tallies_every_event() -> None:
    events = [
        ce.ConfigEvent(kind="baseline", seq=0),
        ce.ConfigEvent(kind="proposed", seq=1),
        ce.ConfigEvent(kind="proposed", seq=2),
        ce.ConfigEvent(kind="refused", seq=3),
        ce.ConfigEvent(kind="applied", seq=4),
    ]
    counts = ce.counts_by_kind(events)
    assert counts["baseline"] == 1
    assert counts["proposed"] == 2
    assert counts["refused"] == 1
    assert counts["applied"] == 1
    assert counts["verified"] == 0
    assert counts["reverted"] == 0


def test_counts_by_kind_of_empty_sequence_is_all_zero() -> None:
    counts = ce.counts_by_kind([])
    assert set(counts) == set(ce.EVENT_KINDS)
    assert all(v == 0 for v in counts.values())


def test_liveness_false_on_a_totally_empty_stream() -> None:
    assert ce.liveness_advanced([]) is False


def test_liveness_false_on_baseline_only_the_armed_alone_trap() -> None:
    """The T8 trap's liveness counterpart: a stream that has been SEEDED
    (baseline recorded) but has seen no proposed/refused/verified/applied/
    reverted activity must NOT read as live — 'armed' is not 'advanced'."""
    events = [ce.ConfigEvent(kind="baseline", target="worker.tools", origin="host", seq=0)]
    assert ce.liveness_advanced(events) is False


@pytest.mark.parametrize("kind", ["proposed", "refused", "verified", "applied", "reverted"])
def test_liveness_true_when_any_progress_kind_is_present(kind: str) -> None:
    events = [
        ce.ConfigEvent(kind="baseline", seq=0),
        ce.ConfigEvent(kind=kind, seq=1),
    ]
    assert ce.liveness_advanced(events) is True


def test_liveness_true_from_boundaries_observed_alone() -> None:
    """``boundaries_observed`` is an accepted INPUT count (e.g. episode
    boundaries crossed with no config activity) — a caller-supplied progress
    signal, distinct from anything derivable from the event list itself."""
    assert ce.liveness_advanced([], boundaries_observed=1) is True
    assert ce.liveness_advanced([], boundaries_observed=0) is False


def test_liveness_signature_has_no_armed_parameter() -> None:
    """The API simply must not accept an 'armed'-style flag — checked
    structurally, not just by convention."""
    params = inspect.signature(ce.liveness_advanced).parameters
    assert "armed" not in params
    assert "is_armed" not in params
    assert "configured" not in params


def test_liveness_rejects_an_armed_kwarg_outright() -> None:
    with pytest.raises(TypeError):
        ce.liveness_advanced([], armed=True)  # type: ignore[call-arg]

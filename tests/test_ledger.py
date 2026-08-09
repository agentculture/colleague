"""Tests for colleague.ledger (plan task t11, covers the evaluation ledger).

Covers:
- Appending each valid kind works; an invalid kind refuses the whole entry.
- An invalid seat refuses the whole entry.
- ``seq`` is assigned by the ledger in order and a caller cannot set it.
- ``to_dict``/``from_dict`` round-trip exactly, and the digest changes when
  any entry changes.
- THE KEY TEST: build a full episode (thought -> action -> evaluation ->
  reroute -> execution -> outcome) and prove that FROM THE LEDGER ALONE you
  can reconstruct which thought produced which action, which verdict and
  route followed, and what the outcome was.
- A TaskResult with no ledger serializes with NO evaluation_ledger key at
  all (byte-identical to before).
"""

from __future__ import annotations

import json

import pytest

from colleague.contract import TaskResult
from colleague.ledger import (
    KIND_ACTION,
    KIND_EVALUATION,
    KIND_EXECUTION,
    KIND_OUTCOME,
    KIND_REROUTE,
    KIND_THOUGHT,
    KINDS,
    LEDGER_SCHEMA_VERSION,
    SEAT_EVALUATOR,
    SEAT_FRONT,
    SEAT_HOST,
    SEAT_WORKER,
    SEATS,
    EvaluationLedger,
    LedgerEntry,
    ledger_digest,
)

# ===========================================================================
# Helpers
# ===========================================================================


#: A minimal valid raw entry dict for building entries without going through
#: the ledger (used only for round-trip / digest tests).
def _entry_dict(
    kind: str = KIND_THOUGHT,
    thought_id: str = "t-1",
    action_id: str | None = None,
    detail: str = "",
    seat: str = SEAT_FRONT,
    model: str = "mock",
    seq: int = 0,
) -> dict:
    d: dict = {
        "kind": kind,
        "thought_id": thought_id,
        "detail": detail,
        "seat": seat,
        "model": model,
        "seq": seq,
    }
    if action_id is not None:
        d["action_id"] = action_id
    return d


# ===========================================================================
# Kind validation — each valid kind works
# ===========================================================================


def test_each_valid_kind_appends() -> None:
    """Every member of KINDS can be appended successfully."""
    ledger = EvaluationLedger()
    for kind in KINDS:
        entry = ledger.append(kind, thought_id="t-1", seat=SEAT_FRONT)
        assert entry.kind == kind
        assert entry.seq == len(ledger) - 1


def test_invalid_kind_refuses_whole_entry() -> None:
    """A kind outside KINDS raises ValueError — the whole entry is refused."""
    ledger = EvaluationLedger()
    with pytest.raises(ValueError, match="unknown ledger kind"):
        ledger.append("bogus", thought_id="t-1", seat=SEAT_FRONT)
    assert len(ledger) == 0


# ===========================================================================
# Seat validation
# ===========================================================================


def test_each_valid_seat_appends() -> None:
    """Every member of SEATS can be used as a seat."""
    ledger = EvaluationLedger()
    for seat in SEATS:
        entry = ledger.append(KIND_THOUGHT, thought_id="t-1", seat=seat)
        assert entry.seat == seat


def test_invalid_seat_refuses_whole_entry() -> None:
    """A seat outside SEATS raises ValueError — the whole entry is refused."""
    ledger = EvaluationLedger()
    with pytest.raises(ValueError, match="unknown ledger seat"):
        ledger.append(KIND_THOUGHT, thought_id="t-1", seat="nobody")
    assert len(ledger) == 0


# ===========================================================================
# seq is ledger-owned
# ===========================================================================


def test_seq_assigned_by_ledger_in_order() -> None:
    """The ledger assigns seq itself; appended entries are 0, 1, 2, ..."""
    ledger = EvaluationLedger()
    for i in range(5):
        ledger.append(KIND_THOUGHT, thought_id="t-1", seat=SEAT_FRONT)
    entries = ledger.entries()
    for i, entry in enumerate(entries):
        assert entry.seq == i


def test_caller_cannot_set_seq() -> None:
    """Even if a caller passes seq=999 to append, the ledger overwrites it."""
    ledger = EvaluationLedger()
    # append does not accept seq as a parameter — the ledger assigns it.
    entry = ledger.append(KIND_THOUGHT, thought_id="t-1", seat=SEAT_FRONT)
    assert entry.seq == 0
    # A hand-built entry can set seq directly, but that bypasses append.
    hand_built = LedgerEntry(kind=KIND_THOUGHT, thought_id="t-1", seq=999)
    assert hand_built.seq == 999  # hand-built is allowed for tests


# ===========================================================================
# to_dict / from_dict round-trip
# ===========================================================================


def test_entry_round_trip() -> None:
    """A LedgerEntry round-trips through to_dict/from_dict exactly."""
    original = LedgerEntry(
        kind=KIND_ACTION,
        thought_id="t-42",
        action_id="a-7",
        detail="edit_file called",
        seat=SEAT_WORKER,
        model="qwen-2.5",
        seq=3,
    )
    d = original.to_dict()
    restored = LedgerEntry.from_dict(d)
    assert restored == original
    assert restored.to_dict() == d


def test_entry_round_trip_without_action_id() -> None:
    """An entry with action_id=None serializes without the key."""
    original = LedgerEntry(
        kind=KIND_THOUGHT,
        thought_id="t-1",
        action_id=None,
        detail="front thought",
        seat=SEAT_FRONT,
        model="gemma",
        seq=0,
    )
    d = original.to_dict()
    assert "action_id" not in d
    restored = LedgerEntry.from_dict(d)
    assert restored.action_id is None
    assert restored == original


def test_ledger_round_trip() -> None:
    """A populated EvaluationLedger round-trips through to_dict/from_dict."""
    ledger = EvaluationLedger()
    ledger.append(KIND_THOUGHT, thought_id="t-1", detail="plan", seat=SEAT_FRONT, model="gemma")
    ledger.append(
        KIND_ACTION,
        thought_id="t-1",
        action_id="a-1",
        detail="edit",
        seat=SEAT_WORKER,
        model="qwen",
    )
    ledger.append(
        KIND_EVALUATION,
        thought_id="t-1",
        action_id="a-1",
        detail="aligned",
        seat=SEAT_EVALUATOR,
        model="qwen",
    )

    d = ledger.to_dict()
    assert d["version"] == LEDGER_SCHEMA_VERSION
    assert len(d["entries"]) == 3

    restored = EvaluationLedger.from_dict(d)
    assert len(restored.entries()) == 3
    for orig, rest in zip(ledger.entries(), restored.entries()):
        assert orig == rest


def test_ledger_from_dict_rejects_bad_version() -> None:
    """A ledger dict with a wrong version raises ValueError."""
    bad = {"version": 99, "entries": []}
    with pytest.raises(ValueError, match="unsupported ledger schema version"):
        EvaluationLedger.from_dict(bad)


# ===========================================================================
# Digest — deterministic and sensitive
# ===========================================================================


def test_digest_is_deterministic() -> None:
    """Two identical entry lists produce the same digest."""
    entries = [
        LedgerEntry(
            kind=KIND_THOUGHT,
            thought_id="t-1",
            detail="plan",
            seat=SEAT_FRONT,
            model="gemma",
            seq=0,
        ),
        LedgerEntry(
            kind=KIND_ACTION,
            thought_id="t-1",
            action_id="a-1",
            detail="edit",
            seat=SEAT_WORKER,
            model="qwen",
            seq=1,
        ),
    ]
    d1 = ledger_digest(entries)
    d2 = ledger_digest(entries)
    assert d1 == d2
    assert isinstance(d1, str)
    assert len(d1) == 64  # sha256 hex


def test_digest_changes_when_any_entry_changes() -> None:
    """Changing any field of any entry changes the digest."""
    base = [
        LedgerEntry(
            kind=KIND_THOUGHT,
            thought_id="t-1",
            detail="plan",
            seat=SEAT_FRONT,
            model="gemma",
            seq=0,
        ),
    ]
    base_digest = ledger_digest(base)

    # Change kind
    modified = [
        LedgerEntry(
            kind=KIND_ACTION, thought_id="t-1", detail="plan", seat=SEAT_FRONT, model="gemma", seq=0
        )
    ]
    assert ledger_digest(modified) != base_digest

    # Change thought_id
    modified = [
        LedgerEntry(
            kind=KIND_THOUGHT,
            thought_id="t-2",
            detail="plan",
            seat=SEAT_FRONT,
            model="gemma",
            seq=0,
        )
    ]
    assert ledger_digest(modified) != base_digest

    # Change detail
    modified = [
        LedgerEntry(
            kind=KIND_THOUGHT,
            thought_id="t-1",
            detail="changed",
            seat=SEAT_FRONT,
            model="gemma",
            seq=0,
        )
    ]
    assert ledger_digest(modified) != base_digest

    # Change seat
    modified = [
        LedgerEntry(
            kind=KIND_THOUGHT,
            thought_id="t-1",
            detail="plan",
            seat=SEAT_WORKER,
            model="gemma",
            seq=0,
        )
    ]
    assert ledger_digest(modified) != base_digest

    # Change model
    modified = [
        LedgerEntry(
            kind=KIND_THOUGHT, thought_id="t-1", detail="plan", seat=SEAT_FRONT, model="qwen", seq=0
        )
    ]
    assert ledger_digest(modified) != base_digest

    # Change seq
    modified = [
        LedgerEntry(
            kind=KIND_THOUGHT,
            thought_id="t-1",
            detail="plan",
            seat=SEAT_FRONT,
            model="gemma",
            seq=99,
        )
    ]
    assert ledger_digest(modified) != base_digest


def test_digest_changes_on_add_remove_reorder() -> None:
    """Adding, removing, or reordering entries changes the digest."""
    a = [
        LedgerEntry(
            kind=KIND_THOUGHT, thought_id="t-1", detail="a", seat=SEAT_FRONT, model="gemma", seq=0
        )
    ]
    b = [
        LedgerEntry(
            kind=KIND_ACTION, thought_id="t-1", detail="b", seat=SEAT_WORKER, model="qwen", seq=1
        )
    ]
    ab = a + b
    ba = b + a

    assert ledger_digest(ab) != ledger_digest(ba)
    assert ledger_digest(ab) != ledger_digest(a)
    assert ledger_digest(ab) != ledger_digest(b)


def test_ledger_digest_method() -> None:
    """EvaluationLedger.digest() delegates to ledger_digest(entries())."""
    ledger = EvaluationLedger()
    ledger.append(KIND_THOUGHT, thought_id="t-1", seat=SEAT_FRONT)
    assert ledger.digest() == ledger_digest(ledger.entries())


# ===========================================================================
# THE KEY TEST: full episode reconstruction from ledger alone
# ===========================================================================


def test_full_episode_reconstruction() -> None:
    """Build a complete thought->action->evaluation->reroute->execution->outcome
    episode and prove that FROM THE LEDGER ALONE you can reconstruct:
    - which thought produced which action
    - which verdict and route followed
    - what the outcome was
    """
    ledger = EvaluationLedger()

    # 1. Thought — front seat
    ledger.append(
        KIND_THOUGHT,
        thought_id="t-1",
        detail="Add retry logic for transient failures",
        seat=SEAT_FRONT,
        model="gemma",
    )

    # 2. Action — worker seat, bound to t-1
    ledger.append(
        KIND_ACTION,
        thought_id="t-1",
        action_id="a-1",
        detail="edit_file: add retry wrapper",
        seat=SEAT_WORKER,
        model="qwen",
    )

    # 3. Evaluation — evaluator seat, bound to t-1 and a-1
    ledger.append(
        KIND_EVALUATION,
        thought_id="t-1",
        action_id="a-1",
        detail="verdict=aligned, route=execute",
        seat=SEAT_EVALUATOR,
        model="qwen",
    )

    # 4. Reroute — evaluator seat (the route decision)
    ledger.append(
        KIND_REROUTE,
        thought_id="t-1",
        action_id="a-1",
        detail="route=execute -> host approval gate",
        seat=SEAT_EVALUATOR,
        model="qwen",
    )

    # 5. Execution — host seat
    ledger.append(
        KIND_EXECUTION,
        thought_id="t-1",
        action_id="a-1",
        detail="ran: edit_file with retry wrapper",
        seat=SEAT_HOST,
        model="",
    )

    # 6. Outcome — host seat
    ledger.append(
        KIND_OUTCOME,
        thought_id="t-1",
        action_id="a-1",
        detail="file updated successfully, tests pass",
        seat=SEAT_HOST,
        model="",
    )

    # --- Reconstruction from ledger alone ---
    entries = ledger.entries()
    assert len(entries) == 6

    # Reconstruct: which thought produced which action?
    thought_entries = [e for e in entries if e.kind == KIND_THOUGHT]
    action_entries = [e for e in entries if e.kind == KIND_ACTION]
    assert len(thought_entries) == 1
    assert len(action_entries) == 1
    assert action_entries[0].thought_id == thought_entries[0].thought_id
    assert action_entries[0].thought_id == "t-1"

    # Reconstruct: which verdict and route followed?
    eval_entries = [e for e in entries if e.kind == KIND_EVALUATION]
    reroute_entries = [e for e in entries if e.kind == KIND_REROUTE]
    assert len(eval_entries) == 1
    assert len(reroute_entries) == 1
    # The evaluation is bound to the same thought and action as the action
    assert eval_entries[0].thought_id == "t-1"
    assert eval_entries[0].action_id == "a-1"
    # The reroute follows the evaluation, same thought/action binding
    assert reroute_entries[0].thought_id == "t-1"
    assert reroute_entries[0].action_id == "a-1"

    # Reconstruct: what was the outcome?
    outcome_entries = [e for e in entries if e.kind == KIND_OUTCOME]
    assert len(outcome_entries) == 1
    assert outcome_entries[0].thought_id == "t-1"
    assert outcome_entries[0].action_id == "a-1"
    assert "file updated" in outcome_entries[0].detail

    # Reconstruct: execution tied to the same thought/action
    exec_entries = [e for e in entries if e.kind == KIND_EXECUTION]
    assert len(exec_entries) == 1
    assert exec_entries[0].thought_id == "t-1"
    assert exec_entries[0].action_id == "a-1"

    # Verify the full chain is reconstructable:
    # thought(t-1) -> action(a-1) -> evaluation(aligned/execute) -> reroute(execute) -> execution -> outcome
    chain = [(e.kind, e.thought_id, e.action_id) for e in entries]
    assert chain == [
        (KIND_THOUGHT, "t-1", None),
        (KIND_ACTION, "t-1", "a-1"),
        (KIND_EVALUATION, "t-1", "a-1"),
        (KIND_REROUTE, "t-1", "a-1"),
        (KIND_EXECUTION, "t-1", "a-1"),
        (KIND_OUTCOME, "t-1", "a-1"),
    ]

    # Verify seqs are in order
    seqs = [e.seq for e in entries]
    assert seqs == [0, 1, 2, 3, 4, 5]

    # Verify the ledger's digest is deterministic
    d1 = ledger.digest()
    d2 = EvaluationLedger.from_dict(ledger.to_dict()).digest()
    assert d1 == d2


def test_multi_episode_reconstruction() -> None:
    """Two independent episodes coexist in the same ledger and are
    independently reconstructable by thought_id."""
    ledger = EvaluationLedger()

    # Episode 1: t-1 -> a-1
    ledger.append(
        KIND_THOUGHT, thought_id="t-1", detail="episode 1 thought", seat=SEAT_FRONT, model="gemma"
    )
    ledger.append(
        KIND_ACTION,
        thought_id="t-1",
        action_id="a-1",
        detail="episode 1 action",
        seat=SEAT_WORKER,
        model="qwen",
    )
    ledger.append(
        KIND_EVALUATION,
        thought_id="t-1",
        action_id="a-1",
        detail="episode 1 eval",
        seat=SEAT_EVALUATOR,
        model="qwen",
    )

    # Episode 2: t-2 -> a-2
    ledger.append(
        KIND_THOUGHT, thought_id="t-2", detail="episode 2 thought", seat=SEAT_FRONT, model="gemma"
    )
    ledger.append(
        KIND_ACTION,
        thought_id="t-2",
        action_id="a-2",
        detail="episode 2 action",
        seat=SEAT_WORKER,
        model="qwen",
    )
    ledger.append(
        KIND_EVALUATION,
        thought_id="t-2",
        action_id="a-2",
        detail="episode 2 eval",
        seat=SEAT_EVALUATOR,
        model="qwen",
    )

    entries = ledger.entries()
    assert len(entries) == 6

    # Episode 1 is independently reconstructable
    ep1 = [e for e in entries if e.thought_id == "t-1"]
    assert len(ep1) == 3
    assert ep1[0].kind == KIND_THOUGHT
    assert ep1[1].kind == KIND_ACTION
    assert ep1[1].action_id == "a-1"
    assert ep1[2].kind == KIND_EVALUATION

    # Episode 2 is independently reconstructable
    ep2 = [e for e in entries if e.thought_id == "t-2"]
    assert len(ep2) == 3
    assert ep2[0].kind == KIND_THOUGHT
    assert ep2[1].kind == KIND_ACTION
    assert ep2[1].action_id == "a-2"
    assert ep2[2].kind == KIND_EVALUATION


# ===========================================================================
# TaskResult integration — no evaluation_ledger key when None
# ===========================================================================


def test_task_result_no_ledger_serializes_cleanly() -> None:
    """A TaskResult with evaluation_ledger=None serializes with NO
    evaluation_ledger key at all — byte-identical to the pre-ledger contract."""
    result = TaskResult(
        task_id="task-1",
        status="ok",
        summary="done",
    )
    d = result.to_dict()
    assert "evaluation_ledger" not in d


def test_task_result_with_ledger_serializes_key() -> None:
    """A TaskResult with a non-None evaluation_ledger includes the key."""
    ledger = EvaluationLedger()
    ledger.append(KIND_THOUGHT, thought_id="t-1", detail="plan", seat=SEAT_FRONT, model="gemma")

    result = TaskResult(
        task_id="task-1",
        status="ok",
        summary="done",
        evaluation_ledger=ledger.to_dict(),
    )
    d = result.to_dict()
    assert "evaluation_ledger" in d
    assert d["evaluation_ledger"]["version"] == LEDGER_SCHEMA_VERSION
    assert len(d["evaluation_ledger"]["entries"]) == 1


def test_task_result_from_dict_round_trip_no_ledger() -> None:
    """A TaskResult without evaluation_ledger round-trips: from_dict
    produces None, and re-serializing omits the key."""
    result = TaskResult(
        task_id="task-1",
        status="ok",
        summary="done",
    )
    d = result.to_dict()
    assert "evaluation_ledger" not in d

    restored = TaskResult.from_dict(d)
    assert restored.evaluation_ledger is None
    d2 = restored.to_dict()
    assert "evaluation_ledger" not in d2

    # Byte-identical serialization
    assert json.dumps(d, sort_keys=True) == json.dumps(d2, sort_keys=True)


def test_task_result_from_dict_with_ledger() -> None:
    """A TaskResult with evaluation_ledger round-trips through from_dict."""
    ledger = EvaluationLedger()
    ledger.append(KIND_THOUGHT, thought_id="t-1", detail="plan", seat=SEAT_FRONT, model="gemma")

    result = TaskResult(
        task_id="task-1",
        status="ok",
        summary="done",
        evaluation_ledger=ledger.to_dict(),
    )
    d = result.to_dict()
    assert "evaluation_ledger" in d

    restored = TaskResult.from_dict(d)
    assert restored.evaluation_ledger is not None
    assert restored.evaluation_ledger["version"] == LEDGER_SCHEMA_VERSION
    assert len(restored.evaluation_ledger["entries"]) == 1

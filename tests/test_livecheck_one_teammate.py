"""Tests for the "one teammate" livecheck proof (task t8).

Covers, with NO network / live rig required, the pure classifier
``classify_one_teammate_check`` mirroring the honest-SKIP discipline of the
neighbouring ``classify_*_check`` functions in ``colleague/livecheck.py``:

- senses unreachable always SKIPs, regardless of the other evidence (the
  reference-rig reality today — never a fabricated PASS)
- a non-repo turn that spawned a git branch and/or an eidetic record FAILs —
  exactly the pain the "one teammate" front door is meant to remove
- cortex answering a turn senses should have handled directly FAILs
- senses answering directly, with no branch and no record, PASSes
"""

from __future__ import annotations

from colleague.livecheck import classify_one_teammate_check

# ---------------------------------------------------------------------------
# classify_one_teammate_check
# ---------------------------------------------------------------------------


class TestClassifyOneTeammateCheckUnreachable:
    def test_senses_unreachable_skips(self) -> None:
        status, detail = classify_one_teammate_check(
            senses_reachable=False,
            answered_by="senses",
            branch_created=False,
            record_created=False,
        )
        assert status == "skipped"
        assert "unreachable" in detail or "unarmed" in detail

    def test_senses_unreachable_skips_regardless_of_other_fields(self) -> None:
        """Even a shape that would otherwise FAIL (a branch spawned, cortex
        answered) still SKIPs when senses itself was never reachable — never
        a fabricated PASS, and the unreachable reason always wins first."""
        status, detail = classify_one_teammate_check(
            senses_reachable=False,
            answered_by="cortex",
            branch_created=True,
            record_created=True,
        )
        assert status == "skipped"
        assert "unreachable" in detail or "unarmed" in detail


class TestClassifyOneTeammateCheckSideEffects:
    def test_branch_created_fails(self) -> None:
        status, detail = classify_one_teammate_check(
            senses_reachable=True,
            answered_by="senses",
            branch_created=True,
            record_created=False,
        )
        assert status == "failed"
        assert "branch" in detail.lower()

    def test_record_created_fails(self) -> None:
        status, detail = classify_one_teammate_check(
            senses_reachable=True,
            answered_by="senses",
            branch_created=False,
            record_created=True,
        )
        assert status == "failed"
        assert "record" in detail.lower()

    def test_both_branch_and_record_created_fails_and_names_both(self) -> None:
        status, detail = classify_one_teammate_check(
            senses_reachable=True,
            answered_by="senses",
            branch_created=True,
            record_created=True,
        )
        assert status == "failed"
        assert "branch" in detail.lower()
        assert "record" in detail.lower()


class TestClassifyOneTeammateCheckWrongAnswerer:
    def test_cortex_answered_fails(self) -> None:
        status, detail = classify_one_teammate_check(
            senses_reachable=True,
            answered_by="cortex",
            branch_created=False,
            record_created=False,
        )
        assert status == "failed"
        assert "cortex" in detail.lower()

    def test_no_answerer_fails(self) -> None:
        status, detail = classify_one_teammate_check(
            senses_reachable=True,
            answered_by=None,
            branch_created=False,
            record_created=False,
        )
        assert status == "failed"


class TestClassifyOneTeammateCheckPasses:
    def test_senses_answered_no_side_effects_passes(self) -> None:
        status, detail = classify_one_teammate_check(
            senses_reachable=True,
            answered_by="senses",
            branch_created=False,
            record_created=False,
        )
        assert status == "passed"
        assert "senses" in detail.lower()
        assert "no cortex work item" in detail.lower()

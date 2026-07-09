"""Livecheck classifiers for the pilotable-runs arc (#307-#311).

Pure ``(inputs) -> (status, detail)`` graders for the two crux live proofs — the
#310 flight-reachability fact and the #308 liveness fact — with the same
honest-SKIP / never-fabricate-a-pass discipline as the sibling classifiers.
"""

from colleague.livecheck import (
    classify_flight_liveness_check,
    classify_flight_reachable_check,
)


class TestFlightReachable:
    def test_reachable_and_survives_passes(self):
        status, _ = classify_flight_reachable_check(True, True)
        assert status == "passed"

    def test_not_reachable_fails(self):
        status, detail = classify_flight_reachable_check(False, True)
        assert status == "failed"
        assert "reachable-in-operator-repo" in detail

    def test_did_not_survive_cleanup_fails(self):
        status, detail = classify_flight_reachable_check(True, False)
        assert status == "failed"
        assert "survived-cleanup" in detail


class TestFlightLiveness:
    def test_no_marker_skips(self):
        status, _ = classify_flight_liveness_check(False, "")
        assert status == "skipped"

    def test_grounded_status_passes(self):
        status, _ = classify_flight_liveness_check(True, "cortex started, ~90s elapsed, step 0/40")
        assert status == "passed"

    def test_still_dont_know_fails(self):
        """A liveness marker existed but the status was still ungrounded — a real
        regression, never silently passed."""
        status, _ = classify_flight_liveness_check(True, "I don't know.")
        assert status == "failed"

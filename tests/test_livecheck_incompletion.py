"""Live-proof classifier for the honest-incompletion contract (#313).

Grades whether a real run's artifact matched the contract: a no-deliverable run
comes back non-ok with a full incompletion {reason, recommendation}; a delivering
run carries none. Never a fabricated pass; SKIP when there is nothing to grade.
"""

from colleague.livecheck import classify_honest_incompletion_check


class TestClassifyHonestIncompletion:
    def test_no_status_skips(self):
        status, _ = classify_honest_incompletion_check("", None, expected_incomplete=True)
        assert status == "skipped"

    def test_incomplete_with_full_record_passes(self):
        status, msg = classify_honest_incompletion_check(
            "incomplete",
            {"reason": "write-no-changes", "recommendation": "re-scope or take over"},
            expected_incomplete=True,
        )
        assert status == "passed"
        assert "write-no-changes" in msg

    def test_silent_incomplete_fails(self):
        """Non-ok but no incompletion record — the exact failure the feature closes."""
        status, _ = classify_honest_incompletion_check("incomplete", None, expected_incomplete=True)
        assert status == "failed"

    def test_record_missing_recommendation_fails(self):
        status, _ = classify_honest_incompletion_check(
            "incomplete", {"reason": "write-no-changes"}, expected_incomplete=True
        )
        assert status == "failed"

    def test_expected_incomplete_but_ok_fails(self):
        status, _ = classify_honest_incompletion_check("ok", None, expected_incomplete=True)
        assert status == "failed"

    def test_delivering_run_with_no_record_passes(self):
        status, _ = classify_honest_incompletion_check("ok", None, expected_incomplete=False)
        assert status == "passed"

    def test_delivering_run_wrongly_flagged_fails(self):
        status, _ = classify_honest_incompletion_check(
            "incomplete",
            {"reason": "write-no-changes", "recommendation": "x"},
            expected_incomplete=False,
        )
        assert status == "failed"

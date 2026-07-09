"""The at-home arc's live-proof grader (``classify_at_home_check``).

Pure-evidence grading, mirroring the sibling livecheck classifier tests: every
verdict must be derivable from the supplied evidence alone, SKIP is the honest
answer whenever the proof could not run, and a fabricated PASS is the one
unforgivable outcome (the grader must never infer success it wasn't shown).
"""

from colleague.livecheck import classify_at_home_check


class TestGlobalArmingLeg:
    def test_passes_when_both_verbs_agree_armed_with_env_dark(self):
        status, reason = classify_at_home_check(
            "global-arming",
            env_armed=False,
            user_config_present=True,
            config_show_armed=True,
            lobes_show_armed=True,
        )
        assert status == "passed"
        assert "zero env vars" in reason

    def test_skips_when_env_rung_was_lit(self):
        status, reason = classify_at_home_check(
            "global-arming",
            env_armed=True,
            user_config_present=True,
            config_show_armed=True,
            lobes_show_armed=True,
        )
        assert status == "skipped"
        assert "env rung" in reason

    def test_skips_without_a_user_config_to_prove_with(self):
        status, _ = classify_at_home_check(
            "global-arming",
            env_armed=False,
            user_config_present=False,
        )
        assert status == "skipped"

    def test_fails_on_introspection_drift(self):
        status, reason = classify_at_home_check(
            "global-arming",
            env_armed=False,
            user_config_present=True,
            config_show_armed=True,
            lobes_show_armed=False,
        )
        assert status == "failed"
        assert "drift" in reason

    def test_fails_when_user_default_is_shadowed(self):
        status, reason = classify_at_home_check(
            "global-arming",
            env_armed=False,
            user_config_present=True,
            config_show_armed=False,
            lobes_show_armed=False,
        )
        assert status == "failed"
        assert "did not arm" in reason


class TestInputLineLeg:
    def test_skips_when_owned_line_never_armed(self):
        status, reason = classify_at_home_check("input-line", armed=False)
        assert status == "skipped"
        assert "structural pytest" in reason

    def test_fails_when_armed_but_no_repaint(self):
        status, reason = classify_at_home_check(
            "input-line", armed=True, repaint_seen=False, output="", pending_text=""
        )
        assert status == "failed"
        assert "repaint" in reason

    def test_fails_when_pending_text_lost(self):
        status, reason = classify_at_home_check(
            "input-line",
            armed=True,
            repaint_seen=True,
            output="[edit_file] x\n> tell it t",
            pending_text="tell it to",
        )
        assert status == "failed"
        assert "lost" in reason

    def test_passes_when_pending_survives_the_repaint(self):
        status, _ = classify_at_home_check(
            "input-line",
            armed=True,
            repaint_seen=True,
            output="[edit_file] x\n> tell it to",
            pending_text="tell it to",
        )
        assert status == "passed"


class TestSelfKnowledgeLeg:
    IDS = ["sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"]

    def test_skips_when_mind_unreachable(self):
        status, _ = classify_at_home_check(
            "self-knowledge", reachable=False, answer="", expected_ids=self.IDS
        )
        assert status == "skipped"

    def test_fails_on_the_pre_arc_deferral(self):
        status, reason = classify_at_home_check(
            "self-knowledge",
            reachable=True,
            answer="I don't know which specific model I am using.",
            expected_ids=self.IDS,
        )
        assert status == "failed"
        assert "deferral" in reason

    def test_fails_when_a_resolved_id_is_missing(self):
        status, reason = classify_at_home_check(
            "self-knowledge",
            reachable=True,
            answer="I run a Qwen model on a local rig.",
            expected_ids=self.IDS,
        )
        assert status == "failed"
        assert "exact-match" in reason

    def test_passes_only_on_verbatim_ids(self):
        status, _ = classify_at_home_check(
            "self-knowledge",
            reachable=True,
            answer=f"cortex: {self.IDS[0]}, driving the loop.",
            expected_ids=self.IDS,
        )
        assert status == "passed"

    def test_skips_with_no_expected_ids(self):
        status, reason = classify_at_home_check(
            "self-knowledge", reachable=True, answer="hi", expected_ids=[]
        )
        assert status == "skipped"
        assert "nothing exact" in reason


def test_unknown_leg_skips_honestly():
    status, reason = classify_at_home_check("no-such-leg")
    assert status == "skipped"
    assert "no-such-leg" in reason

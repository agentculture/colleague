"""Talking-to-one livecheck classifiers (task t9 / spec h7, h11, h14).

Pure-grader tests — no live rig: :func:`classify_middle_manager_check` grades
every announcement beat (ack → proactive update → conversational answer) from
the recorded evidence alone (a ``senses`` payload + the transcript lines), and
:func:`classify_front_latency_check` grades 'quick is measured' from recorded
wall-clock senses-turn latencies. Every missing beat FAILs naming the gap; a
missing measurement SKIPs — never a fabricated pass. The live drive lives in
``tests/test_vllm_live_talking_to_one.py`` (gated on ``COLLEAGUE_VLLM_E2E``).
"""

from __future__ import annotations

from colleague.livecheck import (
    classify_front_latency_check,
    classify_middle_manager_check,
    front_latencies,
)


def _proof_senses(**over) -> dict:
    payload = {
        "mode": "split",
        "packet": {"original": "req", "interpretation": "tidy", "ack": "on it."},
        "records": [
            {"point": "senses-intake", "latency": 1.2, "degraded": False},
            {"point": "senses-update", "latency": 0.9, "degraded": False},
            {"point": "senses-speakback", "latency": 1.1, "degraded": False},
        ],
        "chat": [
            {"kind": "ack", "text": "on it.", "fixed": False, "at": 1.0},
            {"kind": "update", "text": "reading config now", "at": 2.0},
        ],
    }
    payload.update(over)
    return payload


def _proof_conversation() -> list[str]:
    return [
        "tidy the config module",
        "senses: on it.",
        "[read_file] config.py",
        "senses: reading config now",
        "ok: shaped answer [config.py]",
    ]


class TestMiddleManagerCheck:
    def test_all_beats_observed_passes(self) -> None:
        status, detail = classify_middle_manager_check(_proof_senses(), _proof_conversation())
        assert status == "passed"
        assert "ack (senses' own words)" in detail
        assert "1 rendered update(s)" in detail

    def test_fixed_notice_ack_still_passes_named_honestly(self) -> None:
        senses = _proof_senses()
        senses["chat"][0]["fixed"] = True
        status, detail = classify_middle_manager_check(senses, _proof_conversation())
        assert status == "passed"
        assert "(fixed dispatch notice)" in detail

    def test_no_senses_block_fails(self) -> None:
        status, detail = classify_middle_manager_check(None, _proof_conversation())
        assert status == "failed"
        assert "never armed" in detail

    def test_missing_ack_entry_fails(self) -> None:
        senses = _proof_senses(chat=[{"kind": "update", "text": "reading config now"}])
        status, detail = classify_middle_manager_check(senses, _proof_conversation())
        assert status == "failed"
        assert "no ack chat entry" in detail

    def test_ack_recorded_but_never_rendered_fails(self) -> None:
        conversation = [ln for ln in _proof_conversation() if ln != "senses: on it."]
        status, detail = classify_middle_manager_check(_proof_senses(), conversation)
        assert status == "failed"
        assert "never rendered" in detail

    def test_no_update_record_fails(self) -> None:
        senses = _proof_senses(
            records=[
                {"point": "senses-intake", "latency": 1.2, "degraded": False},
                {"point": "senses-speakback", "latency": 1.1, "degraded": False},
            ]
        )
        status, detail = classify_middle_manager_check(senses, _proof_conversation())
        assert status == "failed"
        assert "no proactive-update record" in detail

    def test_all_updates_degraded_or_unrendered_fails(self) -> None:
        conversation = [ln for ln in _proof_conversation() if ln != "senses: reading config now"]
        status, detail = classify_middle_manager_check(_proof_senses(), conversation)
        assert status == "failed"
        assert "none rendered" in detail

    def test_degraded_speakback_fails(self) -> None:
        senses = _proof_senses()
        senses["records"][-1]["degraded"] = True
        status, detail = classify_middle_manager_check(senses, _proof_conversation())
        assert status == "failed"
        assert "speak-back" in detail


class TestFrontLatency:
    def test_median_under_target_passes(self) -> None:
        status, detail = classify_front_latency_check([1.2, 0.9, 2.8])
        assert status == "passed"
        assert "median senses turn 1.20s" in detail

    def test_median_over_target_fails(self) -> None:
        status, detail = classify_front_latency_check([4.0, 5.0, 3.5])
        assert status == "failed"
        assert "breached" in detail

    def test_no_measurements_skips_never_fabricates(self) -> None:
        status, detail = classify_front_latency_check([])
        assert status == "skipped"
        assert "no senses-turn latencies" in detail

    def test_front_latencies_collects_numeric_record_latencies(self) -> None:
        assert front_latencies(_proof_senses()) == [1.2, 0.9, 1.1]
        assert front_latencies(None) == []
        assert front_latencies({"records": [{"point": "x", "latency": None}]}) == []

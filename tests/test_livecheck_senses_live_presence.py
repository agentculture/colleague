"""Senses live-presence arc (task t10): livecheck classifiers grade from evidence.

The classifiers turn recorded rig evidence into pass/fail/skip WITHOUT ever
fabricating a pass: the concurrent-senses-latency proof passes only when the
measured percentiles clear the target; the injection-awareness proof passes only
when the injection is reconstructable from BOTH the feed and the artifact; and the
stt/tts voice lanes SKIP honestly while the rig's speech proxy 502s (probed
2026-07-03), flipping to a real grade the day the proxy serves audio.
"""

from __future__ import annotations

from colleague.livecheck import (
    classify_injection_reached_check,
    classify_senses_latency_check,
    classify_voice_lane_check,
)

# --- concurrent senses latency (spec h9) ------------------------------------


def test_latency_passes_under_target() -> None:
    # probe 2026-07-03: 2.3s p50 under cortex load, 2.3s p95 — both under target.
    status, detail = classify_senses_latency_check(2.33, 2.33)
    assert status == "passed"
    assert "p50=2.33s" in detail


def test_latency_fails_when_p50_breaches() -> None:
    status, _ = classify_senses_latency_check(3.5, 4.0)
    assert status == "failed"


def test_latency_fails_when_p95_breaches() -> None:
    status, _ = classify_senses_latency_check(1.2, 9.0)
    assert status == "failed"


def test_latency_skips_without_measurement() -> None:
    status, detail = classify_senses_latency_check(None, None)
    assert status == "skipped"
    assert "no concurrent-latency measurement" in detail


# --- injection awareness (spec h8) ------------------------------------------


def test_injection_passes_when_in_both_surfaces() -> None:
    status, _ = classify_injection_reached_check(in_feed=True, in_artifact=True)
    assert status == "passed"


def test_injection_fails_when_missing_from_feed() -> None:
    status, detail = classify_injection_reached_check(in_feed=False, in_artifact=True)
    assert status == "failed"
    assert "feed" in detail


def test_injection_fails_when_unrecorded_in_artifact() -> None:
    status, detail = classify_injection_reached_check(in_feed=True, in_artifact=False)
    assert status == "failed"
    assert "artifact" in detail


# --- stt/tts voice lanes: honest SKIP while the gateway proxy 502s -----------


def test_voice_lane_skips_on_proxy_502() -> None:
    for kind in ("stt", "tts"):
        status, detail = classify_voice_lane_check(kind, "proxy_502")
        assert status == "skipped"
        assert "502" in detail  # names the rig-side reason, never a fabricated pass


def test_voice_lane_passes_on_ok() -> None:
    # written to flip automatically the day the proxy serves audio.
    status, _ = classify_voice_lane_check("stt", "ok")
    assert status == "passed"


def test_voice_lane_fails_on_unexpected_error() -> None:
    status, _ = classify_voice_lane_check("tts", "timeout")
    assert status == "failed"

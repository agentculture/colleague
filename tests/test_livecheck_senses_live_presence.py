"""Senses live-presence arc (task t10): livecheck classifiers grade from evidence.

The classifiers turn recorded rig evidence into pass/fail/skip WITHOUT ever
fabricating a pass: the concurrent-senses-latency proof passes only when the
measured percentiles clear the target; the injection-awareness proof passes only
when the injection is reconstructable from BOTH the feed and the artifact; and the
stt/tts voice lanes SKIP only when the gateway's live readiness probe reports the
role genuinely down/unready (lobes-cli#89, 0.38.0 — colleague#292/291 S1). Since
``ready`` is now live-probe-backed for stt/tts (a warming backend answers
503+Retry-After via ``colleague/voice.py``'s bounded retry, never a bare 502), an
unexpected failure despite a ready report is graded as a real regression
(FAILED), not silently skipped the way the old bare-502 workaround used to.
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


# --- stt/tts voice lanes: honest SKIP only when genuinely not ready ---------


def test_voice_lane_skips_on_not_ready() -> None:
    """lobes-cli#89 (0.38.0): stt/tts readiness is now LIVE-PROBED via the
    gateway's realtime bridge — a genuinely down/unready role is the only
    case this SKIPs on, and the reason names that (not a bare "502")."""
    for kind in ("stt", "tts"):
        status, detail = classify_voice_lane_check(kind, "not_ready")
        assert status == "skipped"
        assert "not ready" in detail  # names the rig-side reason, never a fabricated pass


def test_voice_lane_passes_on_ok() -> None:
    # written to flip automatically the day the proxy serves audio.
    status, _ = classify_voice_lane_check("stt", "ok")
    assert status == "passed"


def test_voice_lane_fails_on_unexpected_error() -> None:
    status, _ = classify_voice_lane_check("tts", "timeout")
    assert status == "failed"


def test_voice_lane_fails_on_bare_502_now_that_ready_is_live_probed() -> None:
    """The OLD workaround SKIPped on a bare 502; now that ``ready`` is
    live-probed (lobes-cli#89), a round-trip failure despite a ready report
    is a genuine regression and must FAIL, never SKIP a fabricated pass."""
    status, _ = classify_voice_lane_check("stt", "proxy_502")
    assert status == "failed"

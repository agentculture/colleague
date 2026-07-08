"""Per-front presence livecheck classifiers (presence-default-everywhere, t14).

Grade-from-evidence: each classifier reads the shared SensesBlock (t3) + a
front's rendered lines and decides passed/failed/skipped — never a model
self-report, never a fabricated pass.
"""

from __future__ import annotations

from colleague.livecheck import (
    PRESENCE_FRONTS,
    classify_background_presence_check,
    classify_front_presence_check,
    classify_resident_presence_check,
    classify_session_presence_check,
    classify_talk_presence_check,
    classify_work_presence_check,
)


def _loop_block() -> dict:
    """A senses-loop-lane block: loop-turn records + kind-ed chat."""
    return {
        "mode": "cortex-only",
        "records": [
            {"point": "senses-loop:dispatch_to_cortex", "degraded": False},
            {"point": "senses-loop:reply_to_operator", "degraded": False},
        ],
        "chat": [
            {"kind": "ack", "text": "on it — handing to cortex"},
            {"message": "status?", "answer": "cortex is editing foo.py"},
        ],
        "injections": [],
    }


def _beats_block() -> dict:
    """A fixed-beat-lane block: intake/update/speakback records + kind-ed chat."""
    return {
        "mode": "split",
        "records": [
            {"point": "senses-intake", "degraded": False},
            {"point": "senses-update", "degraded": False},
            {"point": "senses-speakback", "degraded": False},
        ],
        "chat": [
            {"kind": "ack", "text": "got it", "fixed": False},
            {"kind": "update", "text": "reading the config now"},
        ],
        "injections": [{"text": "focus on config", "at": 1.0, "source": "senses-loop"}],
    }


# ── skip / fail / pass ────────────────────────────────────────────────────────
def test_skips_when_front_not_exercised() -> None:
    status, detail = classify_front_presence_check(None, [], front="work")
    assert status == "skipped" and "not exercised" in detail


def test_fails_when_ack_beat_missing() -> None:
    block = _loop_block()
    block["records"] = [{"point": "senses-loop:reply_to_operator"}]
    block["chat"] = [{"message": "hi", "answer": "there"}]
    status, detail = classify_front_presence_check(block, ["senses: there"], front="work")
    assert status == "failed" and "no ack" in detail


def test_fails_when_narration_beat_missing() -> None:
    block = {
        "records": [{"point": "senses-loop:dispatch_to_cortex"}],
        "chat": [{"kind": "ack", "text": "hi"}],
    }
    status, detail = classify_front_presence_check(block, ["senses: hi"], front="work")
    assert status == "failed" and "no grounded update/reply" in detail


def test_passes_on_the_loop_lane_evidence() -> None:
    status, detail = classify_front_presence_check(_loop_block(), ["senses: on it"], front="work")
    assert status == "passed" and "ack + narration observed" in detail


def test_passes_on_the_fixed_beat_lane_evidence() -> None:
    status, detail = classify_front_presence_check(
        _beats_block(), ["senses: got it"], front="session"
    )
    assert status == "passed"
    assert "with a guidance relay" in detail  # the beats block carries an injection


def test_degraded_update_alone_is_not_a_narration_beat() -> None:
    block = {
        "records": [
            {"point": "senses-loop:dispatch_to_cortex"},
            {"point": "senses-update", "degraded": True},
        ],
        "chat": [{"kind": "ack", "text": "hi"}],
    }
    status, _ = classify_front_presence_check(block, ["senses: hi"], front="background")
    assert status == "failed"  # a degraded update never counts as a delivered narration


def test_rendered_but_no_block_fails_reconstruction() -> None:
    status, detail = classify_front_presence_check(None, ["senses: hi"], front="talk")
    assert status == "failed" and "not reconstructable" in detail


# ── all five named fronts exist and grade ─────────────────────────────────────
def test_all_named_front_wrappers_grade_the_loop_block() -> None:
    for fn in (
        classify_session_presence_check,
        classify_talk_presence_check,
        classify_background_presence_check,
        classify_resident_presence_check,
        classify_work_presence_check,
    ):
        status, _ = fn(_loop_block(), ["senses: on it"])
        assert status == "passed"


def test_presence_fronts_enumerates_all_five() -> None:
    assert PRESENCE_FRONTS == ("session", "talk", "background", "resident", "work")

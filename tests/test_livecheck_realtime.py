"""Tests for the realtime livecheck (realtime-speech arc, task t7, spec c12/h9).

Covers:
- classify_realtime_check grades from evidence alone: SKIP when the session
  never opened (naming the reason), FAIL when it opened but produced zero
  server events, PASS when it opened AND produced at least one event.
- run_realtime_check's three honest-SKIP paths (extra absent / config absent
  or unavailable / rig lane absent — the dial/handshake failing) and its
  PASS/FAIL path once a session genuinely opens.
- The session is always closed (bounded teardown) regardless of outcome.
- A synthesized-or-silence burst is sent — never a fabricated transcript
  claim; the PASS bar is the session+event handshake only.

No live rig: colleague.realtime.open_session is monkeypatched with a fake
session object; no real socket/network is touched anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.cli._errors import CliError
from colleague.livecheck import ProofResult, classify_realtime_check, run_realtime_check

# ---------------------------------------------------------------------------
# classify_realtime_check — pure classifier, no I/O
# ---------------------------------------------------------------------------


def test_classify_skips_when_not_opened_naming_the_reason() -> None:
    status, detail = classify_realtime_check(
        opened=False, event_count=0, reason="no realtime lane resolved"
    )
    assert status == "skipped"
    assert detail == "no realtime lane resolved"


def test_classify_skips_with_a_default_reason_when_none_given() -> None:
    status, detail = classify_realtime_check(opened=False, event_count=0)
    assert status == "skipped"
    assert detail


def test_classify_fails_when_opened_but_zero_events() -> None:
    status, detail = classify_realtime_check(opened=True, event_count=0)
    assert status == "failed"
    assert "zero" in detail.lower()
    assert "101 handshake" in detail


def test_classify_passes_when_opened_and_at_least_one_event() -> None:
    status, detail = classify_realtime_check(opened=True, event_count=1)
    assert status == "passed"
    assert "1 server event" in detail


def test_classify_passes_reports_the_real_event_count() -> None:
    status, detail = classify_realtime_check(opened=True, event_count=3)
    assert status == "passed"
    assert "3 server event" in detail


def test_classify_pass_never_claims_a_transcript_round_trip() -> None:
    """The PASS bar is the handshake+event wire, never a transcript claim
    (spec instruction: 'do NOT fabricate a transcript claim')."""
    status, detail = classify_realtime_check(opened=True, event_count=1)
    assert status == "passed"
    assert "does not" in detail.lower() or "does NOT" in detail
    assert "transcript" in detail.lower()


def test_classify_fail_documents_what_zero_events_does_not_mean() -> None:
    _status, detail = classify_realtime_check(opened=True, event_count=0)
    # The FAIL detail must not itself claim a transcript was expected/produced.
    assert "spoken audio" in detail.lower() or "transcript" in detail.lower()


# ---------------------------------------------------------------------------
# run_realtime_check — the three honest-SKIP paths
# ---------------------------------------------------------------------------


class _RealtimeConfigLike(SimpleNamespace):
    """A minimal stand-in for colleague.config.RealtimeConfig."""


def _fake_resolve(*, realtime):
    def _resolve(**kwargs):
        return SimpleNamespace(realtime=realtime)

    return _resolve


def test_skips_when_config_realtime_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.config as config_mod

    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=None))
    )

    result = run_realtime_check(".")

    assert isinstance(result, ProofResult)
    assert result.file == "realtime"
    assert result.status == "skipped"
    assert "no realtime lane resolved" in result.detail


def test_skips_when_config_realtime_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.config as config_mod

    unavailable = _RealtimeConfigLike(available=False, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=unavailable))
    )

    result = run_realtime_check(".")

    assert result.status == "skipped"
    assert "unavailable" in result.detail or "absent" in result.detail


def test_skips_naming_the_extra_when_voice_extra_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.config as config_mod
    import colleague.livecheck as livecheck_mod

    available = _RealtimeConfigLike(available=True, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=available))
    )

    def _raise_missing_extra(config, *, on_transcript=None, on_event=None, sample_rate=24000):
        raise CliError(
            1,
            "realtime speech support is not installed (ModuleNotFoundError)",
            remediation="pip install colleague[voice]",
        )

    monkeypatch.setattr(livecheck_mod, "open_session", _raise_missing_extra)

    result = run_realtime_check(".")

    assert result.status == "skipped"
    assert "[voice]" in result.detail
    assert "not installed" in result.detail


def test_skips_when_dial_handshake_fails_rig_lane_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """open_session degrades to None on a dial/handshake failure — the 'rig
    lane absent' case (a configured target that is not actually serving)."""
    import colleague.config as config_mod
    import colleague.livecheck as livecheck_mod

    available = _RealtimeConfigLike(available=True, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=available))
    )
    monkeypatch.setattr(
        livecheck_mod,
        "open_session",
        lambda config, *, on_transcript=None, on_event=None, sample_rate=24000: None,
    )

    result = run_realtime_check(".")

    assert result.status == "skipped"
    assert "did not open" in result.detail


def test_skips_on_any_unexpected_open_session_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A live proof degrades, it never crashes the caller — even on an
    exception open_session's own contract doesn't document."""
    import colleague.config as config_mod
    import colleague.livecheck as livecheck_mod

    available = _RealtimeConfigLike(available=True, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=available))
    )

    def _raise(config, *, on_transcript=None, on_event=None, sample_rate=24000):
        raise ValueError("unexpected")

    monkeypatch.setattr(livecheck_mod, "open_session", _raise)

    result = run_realtime_check(".")

    assert result.status == "skipped"
    assert "proof error" in result.detail


# ---------------------------------------------------------------------------
# run_realtime_check — the session genuinely opens: PASS/FAIL evidence
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, *, on_event=None, emit_events: list[dict] | None = None) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self._on_event = on_event
        # Simulate the server talking back synchronously (a real session
        # does this from its own receive-pump thread; the queue-based wait
        # in run_realtime_check doesn't care whether the producer is sync
        # or threaded).
        for event in emit_events or []:
            if self._on_event is not None:
                self._on_event(event)

    def send_audio(self, pcm16_bytes: bytes) -> bool:
        self.sent.append(pcm16_bytes)
        return True

    def close(self, *, timeout: float = 2.0) -> None:
        self.closed = True


def _fake_open_session_factory(*, session_events: list[dict] | None, dial_ok: bool = True):
    holder: dict = {}

    def _open_session(config, *, on_transcript=None, on_event=None, sample_rate=24000):
        if not dial_ok:
            return None
        session = _FakeSession(on_event=on_event, emit_events=session_events)
        holder["session"] = session
        return session

    return _open_session, holder


def test_passes_when_session_opens_and_an_event_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.config as config_mod
    import colleague.livecheck as livecheck_mod

    available = _RealtimeConfigLike(available=True, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=available))
    )
    fake_open, holder = _fake_open_session_factory(session_events=[{"type": "session.created"}])
    monkeypatch.setattr(livecheck_mod, "open_session", fake_open)

    result = run_realtime_check(".", timeout=0.2)

    assert result.status == "passed"
    assert "1 server event" in result.detail
    # A short PCM16 burst was actually sent, and the session was torn down.
    session = holder["session"]
    assert len(session.sent) == 1
    assert isinstance(session.sent[0], bytes)
    assert session.closed is True


def test_fails_when_session_opens_but_zero_events_arrive(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.config as config_mod
    import colleague.livecheck as livecheck_mod

    available = _RealtimeConfigLike(available=True, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=available))
    )
    fake_open, holder = _fake_open_session_factory(session_events=[])
    monkeypatch.setattr(livecheck_mod, "open_session", fake_open)

    # A tiny bounded timeout so this test stays instant.
    result = run_realtime_check(".", timeout=0.05)

    assert result.status == "failed"
    assert "zero" in result.detail.lower()
    assert holder["session"].closed is True


def test_session_is_closed_even_on_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.config as config_mod
    import colleague.livecheck as livecheck_mod

    available = _RealtimeConfigLike(available=True, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=available))
    )
    fake_open, holder = _fake_open_session_factory(
        session_events=[{"type": "conversation.item.input_audio_transcription.completed"}]
    )
    monkeypatch.setattr(livecheck_mod, "open_session", fake_open)

    result = run_realtime_check(".", timeout=0.2)

    assert result.status == "passed"
    assert holder["session"].closed is True


def test_multiple_events_are_all_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.config as config_mod
    import colleague.livecheck as livecheck_mod

    available = _RealtimeConfigLike(available=True, ws_url="ws://x/v1/realtime", api_key="k")
    monkeypatch.setattr(
        config_mod.EngineConfig, "resolve", staticmethod(_fake_resolve(realtime=available))
    )
    fake_open, _holder = _fake_open_session_factory(
        session_events=[{"type": "session.created"}, {"type": "session.updated"}]
    )
    monkeypatch.setattr(livecheck_mod, "open_session", fake_open)

    result = run_realtime_check(".", timeout=0.2)

    assert result.status == "passed"
    assert "2 server event" in result.detail


def test_never_sends_response_create_style_audio_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """The burst sent is silence, never claimed as speech — the file itself
    never fabricates a spoken/transcribed claim (module-level guard against a
    future regression that dresses the burst up as real audio)."""
    import colleague.livecheck as livecheck_mod

    source = Path(livecheck_mod.__file__).read_text(encoding="utf-8")
    assert "response.create" not in source

"""Realtime-speech arc (plan task t6): negative-space byte-identical proofs.

Tasks t1-t5 landed the voice lane itself (``tests/test_session_voice.py``
covers the 26 positive-path tests: offer/opt-in/toggle/transcript-routing/
teardown). This file is the NEGATIVE space the acceptance criteria name
explicitly:

1. **Off-TTY / piped / ``--json`` byte-identity.** With realtime genuinely
   AVAILABLE (armed via a monkeypatched-in ``RealtimeConfig``) but the session
   OFF a colour TTY, the rendered output must carry ZERO realtime/voice-lane
   bytes — no offer line, no state line, not one byte of difference from the
   identical session run with realtime absent. The strongest available proof:
   drive a full, scripted ``_Session.run()`` line twice — once with
   ``config.realtime`` populated, once with it ``None`` — holding every OTHER
   config knob (including senses/voice, so presence's OWN off-TTY ack/update
   lines, a DELIBERATE t7 pin-break recorded in
   ``tests/test_presence_pin_breaks.py``, land identically on both sides) and
   assert the two full captured outputs are BYTE-IDENTICAL. Modeled on this
   suite's strongest existing byte-identity idiom,
   ``tests/test_talking_to_one_boundary.py::TestSensesUnresolvedSessionByteIdentical``
   (a full ``.run()`` line, pinned conversation shape) — extended here to a
   two-sided A/B diff rather than a single fixed fixture, since the variable
   under test (``config.realtime``) has no bearing on the pre-arc fixture
   itself. No stubbing of ``run_senses_intake``/``run_senses_speakback`` is
   needed for this: ``colleague.engines.mock.MockEngine`` "never touches the
   network" and does not override ``Engine.make_complete`` (which raises by
   default), so a real, unstubbed senses intake/speak-back call on the mock
   engine deterministically degrades identically on both sides — the A/B
   diff is never contaminated by mock nondeterminism.

2. **Armed-but-not-opted-in inertness.** On a colour TTY, with realtime
   available and senses armed, an operator who never types ``/voice`` and
   never passes ``--voice`` gets exactly ONE offer line (c27: availability
   renders, it never dials) and ZERO calls into
   ``colleague.realtime.open_session`` / ``colleague.realtime.start_capture``
   — spied at the session module's import site with UNCONDITIONALLY FAILING
   stand-ins (any call raises immediately), not merely call-recording fakes,
   so a leak fails loudly rather than passing silently on an empty list this
   test forgot to assert.

3. **Extra-absent cleanliness.** In this plain (no ``[voice]``) environment:
   importing ``colleague.cli._commands.session`` / ``colleague.realtime``
   pulls in neither ``websocket`` nor ``sounddevice``/``soundfile``; and a
   colour-TTY session with realtime armed that has an operator type ``/voice``
   mid-work-item hits the REAL (unstubbed) ``realtime.open_session`` →
   ``_import_ws()`` extra-missing path, degrades to lane state ``degraded``
   with the clean install hint (``pip install colleague[voice]``) landing on
   the conversation, and the session continues cleanly afterward (no
   exception escapes, teardown is a clean no-op). ``tests/test_realtime.py``'s
   own extra-absent pins are left untouched, not duplicated here.

GOTCHA (tests/conftest.py scrubs ``COLLEAGUE_*`` env): every config here is
built directly on ``EngineConfig``/``RealtimeConfig``/``VoiceConfig``/
``SensesConfig`` objects — never resolved from env — so there is nothing to
arm via monkeypatch in the first place; the harness matches
``tests/test_session_voice.py``'s own convention.
"""

from __future__ import annotations

import sys
from pathlib import Path

from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import (
    _VOICE_OFFER_LINE,
    SensesSessionOptions,
    SessionIO,
    _Session,
)
from colleague.config import EngineConfig, RealtimeConfig, SensesConfig, VoiceConfig
from colleague.contract import OK, Task, TaskResult


class _CollectingOut:
    """Mirrors every other session test file's recording sink verbatim."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _realtime_config() -> RealtimeConfig:
    return RealtimeConfig(available=True, ws_url="ws://rig/v1/realtime", api_key="k")


def _config(*, realtime: bool) -> EngineConfig:
    """Senses + voice ALWAYS armed (held constant) — only ``realtime`` varies,
    isolating exactly its contribution to the rendered output."""
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    config.voice = VoiceConfig(
        stt_model="stt",
        tts_model="tts",
        stt_base_url="http://stt",
        tts_base_url="http://tts",
        api_key="k",
    )
    if realtime:
        config.realtime = _realtime_config()
    return config


def _fake_work(**kwargs: object):
    result = TaskResult(task_id="t", status=OK, summary="raw summary")
    repo = kwargs["repo"]
    return result, Path(str(repo)) / ".colleague" / "art.json"


def _session(
    tmp_path: Path,
    *,
    config: EngineConfig,
    view: str = "markdown",
    json_mode: bool = False,
    voice_wanted: bool = False,
    cortex_only: bool = False,
):
    out, err = _CollectingOut(), _CollectingOut()
    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config,
        json_mode=json_mode,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(cortex_only=cortex_only),
    )
    sess._voice_wanted = voice_wanted
    return sess, out, err


def _conversation_lines(sess) -> list[str]:
    return [line.text for line in sess.state.conversation]


# ---------------------------------------------------------------------------
# 1. Off-TTY / piped / --json byte-identity
# ---------------------------------------------------------------------------


def test_off_tty_full_run_byte_identical_realtime_armed_vs_absent(tmp_path: Path) -> None:
    """The strongest form: two full, scripted ``.run()`` lines — realtime
    armed vs. absent — off a colour TTY, byte-compared in full.

    Both sides run against the SAME repo path (sequentially — the fake
    ``work_fn`` never touches the filesystem, so re-using one directory is
    safe) so the rendered Context panel's ``repo (...)`` line reads identically
    on both sides; two DIFFERENT tmp dirs would leak their own basenames into
    the diff and falsely look like a realtime-arc regression."""
    sess_absent, out_absent, err_absent = _session(
        tmp_path, config=_config(realtime=False), view="markdown"
    )
    rc_absent = sess_absent.run(iter(["fix the flaky parser test"]))

    # The armed side ALSO asks for voice explicitly (--voice) — proving that
    # even an explicit opt-in makes no difference off a colour TTY, since the
    # talk lane (and therefore the voice lane it gates) requires view=='ansi'
    # regardless of the operator's stated preference.
    sess_armed, out_armed, err_armed = _session(
        tmp_path, config=_config(realtime=True), view="markdown", voice_wanted=True
    )
    rc_armed = sess_armed.run(iter(["fix the flaky parser test"]))

    assert rc_absent == rc_armed == 0
    assert out_absent.text() == out_armed.text()
    assert err_absent.text() == err_armed.text()
    # And, precisely: none of the realtime-specific lane lines reached either
    # transcript (the ``/voice (available)`` catalog entry itself is expected
    # on BOTH sides — voice/tts/stt are armed identically on both configs; only
    # ``config.realtime`` differs — so it is not asserted absent here).
    for text in (out_absent.text(), out_armed.text(), err_absent.text(), err_armed.text()):
        assert session_mod._VOICE_OFFER_LINE not in text
        assert session_mod._VOICE_UNAVAILABLE_LINE not in text
        for state_line in session_mod._VOICE_STATE_LINES.values():
            assert state_line not in text


def test_off_tty_json_mode_full_run_byte_identical_realtime_armed_vs_absent(
    tmp_path: Path,
) -> None:
    """The same A/B proof under ``json_mode=True`` (``--json`` forces
    ``view='markdown'`` — see ``_resolve_view`` — so this exercises the exact
    same gate the acceptance names explicitly by name). Same repo path on both
    sides, sequentially, for the same reason as the test above."""
    sess_absent, out_absent, err_absent = _session(
        tmp_path, config=_config(realtime=False), view="markdown", json_mode=True
    )
    sess_absent.run(iter(["fix the flaky parser test"]))

    sess_armed, out_armed, err_armed = _session(
        tmp_path, config=_config(realtime=True), view="markdown", json_mode=True, voice_wanted=True
    )
    sess_armed.run(iter(["fix the flaky parser test"]))

    assert out_absent.text() == out_armed.text()
    assert err_absent.text() == err_armed.text()


def test_off_tty_no_offer_no_state_line_direct(tmp_path: Path) -> None:
    """Direct-call companion to the full-run proof above (the established
    ``test_session_voice.py`` idiom): off-TTY, realtime available, ``--voice``
    asked for — ``_begin_talk_lane`` renders NOTHING onto the conversation."""
    sess, _out, _err = _session(
        tmp_path, config=_config(realtime=True), view="markdown", voice_wanted=True
    )
    before = list(sess.state.conversation)
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)

    assert list(sess.state.conversation) == before  # zero new lines, any lines
    assert sess._voice_state == "off"
    assert sess._talk_active is False


# ---------------------------------------------------------------------------
# 2. Armed-but-not-opted-in inertness (colour TTY)
# ---------------------------------------------------------------------------


def _loud_spy(name: str):
    def _fail(*args: object, **kwargs: object):
        raise AssertionError(
            f"colleague.realtime.{name} must NOT be called — availability alone "
            "never dials (c27); the operator neither typed /voice nor passed --voice"
        )

    return _fail


def test_armed_not_opted_in_zero_ws_dials_zero_device_opens(tmp_path: Path, monkeypatch) -> None:
    """Colour TTY, realtime available, senses armed, operator never opts in:
    a full ``.run()`` line must make ZERO calls into open_session/start_capture.

    The spies are UNCONDITIONALLY FAILING (raise on any invocation) rather than
    merely call-recording — a leaked dial fails the test loudly via the raised
    AssertionError propagating out of the session's own degrade-never-raise
    try/except (still surfacing as a test failure, never silently swallowed),
    instead of relying on an assertion this test might have forgotten to write."""
    monkeypatch.setattr(session_mod.realtime, "open_session", _loud_spy("open_session"))
    monkeypatch.setattr(session_mod.realtime, "start_capture", _loud_spy("start_capture"))

    sess, out, _err = _session(tmp_path, config=_config(realtime=True), view="ansi")
    rc = sess.run(iter(["fix the flaky parser test"]))

    assert rc == 0
    # Exactly ONE offer line — c27 renders availability, never more than once.
    offer_lines = [ln for ln in _conversation_lines(sess) if ln == _VOICE_OFFER_LINE]
    assert len(offer_lines) == 1
    assert sess._voice_state == "off"


def test_armed_not_opted_in_second_work_item_still_zero_dials_one_offer_total(
    tmp_path: Path, monkeypatch
) -> None:
    """The offer line is a ONE-TIME notice across the whole session (t5's own
    ``_voice_offer_shown`` once-flag) — a second work line must not re-offer,
    and the loud spies must survive both lines untouched."""
    monkeypatch.setattr(session_mod.realtime, "open_session", _loud_spy("open_session"))
    monkeypatch.setattr(session_mod.realtime, "start_capture", _loud_spy("start_capture"))

    sess, _out, _err = _session(tmp_path, config=_config(realtime=True), view="ansi")
    rc = sess.run(iter(["fix the flaky parser test", "fix another thing"]))

    assert rc == 0
    offer_lines = [ln for ln in _conversation_lines(sess) if ln == _VOICE_OFFER_LINE]
    assert len(offer_lines) == 1  # still exactly one, across BOTH work items


def test_armed_not_opted_in_cortex_only_zero_dials_zero_offer(tmp_path: Path, monkeypatch) -> None:
    """``--cortex-only`` disarms the talk lane (and therefore the voice lane
    it gates) entirely — not even the offer line renders."""
    monkeypatch.setattr(session_mod.realtime, "open_session", _loud_spy("open_session"))
    monkeypatch.setattr(session_mod.realtime, "start_capture", _loud_spy("start_capture"))

    sess, _out, _err = _session(
        tmp_path, config=_config(realtime=True), view="ansi", cortex_only=True
    )
    rc = sess.run(iter(["fix the flaky parser test"]))

    assert rc == 0
    assert not any(ln == _VOICE_OFFER_LINE for ln in _conversation_lines(sess))
    assert sess._voice_state == "off"


# ---------------------------------------------------------------------------
# 3. Extra-absent cleanliness (this plain, [voice]-less dev/CI environment)
# ---------------------------------------------------------------------------


def test_session_and_realtime_modules_import_clean_without_the_extra() -> None:
    """Mirrors ``tests/test_realtime.py``'s own import-cleanliness pin, checked
    again from the SESSION side: importing the session command module (which
    imports ``colleague.realtime`` at module load, per its own top-level
    ``from colleague import ... realtime ...``) must not have pulled in any of
    the third-party packages the ``[voice]`` extra alone provides."""
    assert "colleague.cli._commands.session" in sys.modules
    assert "colleague.realtime" in sys.modules
    assert "websocket" not in sys.modules
    assert "sounddevice" not in sys.modules
    assert "soundfile" not in sys.modules


def test_voice_toggle_mid_work_item_degrades_with_clean_install_hint_and_continues(
    tmp_path: Path,
) -> None:
    """Colour TTY, realtime + senses armed, operator types ``/voice`` WHILE a
    work item is running (the only path that actually dials — see
    ``_toggle_voice``'s ``self._talk_active and self._voice_gate_open()``
    guard). No seam is installed: the REAL ``colleague.realtime.open_session``
    runs, hits ``_import_ws()`` with the ``[voice]`` extra genuinely absent in
    this environment, and raises a clean ``CliError`` naming
    ``pip install colleague[voice]`` — caught inside ``_arm_voice_capture``,
    which degrades the lane and renders the hint onto the conversation. The
    session must not raise, and must continue cleanly afterward (teardown is
    an idempotent no-op since no real session/capture handle was ever set)."""
    sess, _out, _err = _session(tmp_path, config=_config(realtime=True), view="ansi")
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)  # arms the talk lane; renders the ONE offer line
    assert sess._voice_state == "off"

    msg = sess._toggle_voice()  # /voice, mid-work-item — the REAL dial path

    assert sess._voice_state == "degraded"  # never crashes, never silently "live"
    conv = "\n".join(_conversation_lines(sess))
    assert "pip install colleague[voice]" in conv  # the clean install hint, named
    assert "degraded" in conv
    assert isinstance(msg, str)  # the toggle itself returned a plain string, no raise

    # The session continues: teardown is a clean, idempotent no-op (no real
    # session/capture handle was ever assigned on the CliError branch).
    sess._end_talk_lane()
    assert sess._voice_session is None
    assert sess._voice_state == "off"

    # And the typed lane still works — an unrelated slash command dispatches
    # normally afterward, proving the session itself never wedged.
    still_alive = sess._toggle_voice()
    assert isinstance(still_alive, str)


def test_voice_flag_wanted_before_any_work_item_degrades_same_way(tmp_path: Path) -> None:
    """The ``--voice``-at-launch path (rather than a mid-run ``/voice``) hits
    the SAME real extra-absent degrade inside ``_arm_voice_capture`` via
    ``_begin_voice_lane`` — exercised through the natural ``_begin_talk_lane``
    entry point a work line takes, with no seam installed."""
    sess, _out, _err = _session(
        tmp_path, config=_config(realtime=True), view="ansi", voice_wanted=True
    )
    task = Task.new(str(tmp_path), "scan")

    sess._begin_talk_lane(task)  # --voice: dials immediately, no offer line

    assert sess._voice_state == "degraded"
    conv = "\n".join(_conversation_lines(sess))
    assert "pip install colleague[voice]" in conv
    assert not any(
        ln == _VOICE_OFFER_LINE for ln in _conversation_lines(sess)
    )  # opted in, no offer

    sess._end_talk_lane()  # clean, idempotent teardown — no crash
    assert sess._voice_session is None

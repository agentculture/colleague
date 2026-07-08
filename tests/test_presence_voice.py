"""Tests for tts narration of presence beats (presence-default-everywhere, t12).

Covers the task's four acceptance criteria:

1. Narration is STRICTLY ADDITIVE — a failed/absent synthesis (the reference
   rig's tts proxy currently 502s) never changes the rendered text (byte-
   identical, plus at most one notice); an exception from a front's narrate
   callback is swallowed by the engine so the render path is untouched even
   under a buggy front.
2. NO base-install audio dependency — the whole presence-narration path
   (colleague.presence_engine + colleague.voice.build_presence_narrator)
   works with sounddevice/soundfile forced unimportable, proving narration
   never reaches for the [voice] extra's device layer (it only talks to
   synthesize()'s pure-urllib wire client).
3. The hook lives in the presence engine — PresenceIO.narrate defaults to a
   no-op (byte-identical when unwired) and the ENGINE invokes it right after
   render, so no front needs its own "narrate after render" glue.
4. The voice live proof grades from evidence and SKIPs honestly while the
   rig's speech proxy 502s — never a fabricated pass
   (colleague.livecheck.classify_presence_narration_check /
   run_presence_narration_check).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from colleague.config import VoiceConfig
from colleague.contract import ContextPacket
from colleague.livecheck import (
    ProofResult,
    classify_presence_narration_check,
    run_presence_narration_check,
)
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses_loop import RUNG_OFF, SensesLoopDriver
from colleague.voice import build_presence_narrator

# ---------------------------------------------------------------------------
# Shared harness (mirrors tests/test_presence_engine.py's fixtures, kept
# self-contained here so this file exercises its own narrate wiring).
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning = ""
        self.prompt_tokens = 3
        self.completion_tokens = 5


def _make_complete(replies, *, default=None):
    seq = list(replies)
    idx = {"i": 0}
    default = default if default is not None else json.dumps({"move": "wait"})

    def make_complete(config, *, tools):  # noqa: ANN001
        assert tools == []

        def complete(messages):  # noqa: ANN001
            i = idx["i"]
            idx["i"] += 1
            return _FakeResp(seq[i] if i < len(seq) else default)

        return complete

    return make_complete


class _RecordingIO:
    """Same shape as test_presence_engine.py's harness, plus a narrate slot."""

    def __init__(self, pending=None, flight="step 3/40 · editing foo.py", narrate=None):
        self.dispatched: list = []
        self.guided: list = []
        self.rendered: list = []
        self.narrated: list = []
        self.reads = 0
        self._pending = list(pending or [])
        self._flight = flight
        self._narrate = narrate

    def _read(self):
        self.reads += 1
        return self._flight

    def _poll(self) -> Optional[str]:
        return self._pending.pop(0) if self._pending else None

    def _default_narrate(self, line: str) -> None:
        self.narrated.append(line)
        if self._narrate is not None:
            self._narrate(line)

    def io(self, *, narrate=None) -> PresenceIO:
        kwargs = dict(
            dispatch_to_cortex=self.dispatched.append,
            append_guidance=self.guided.append,
            read_flight=self._read,
            render=self.rendered.append,
            poll_operator_input=self._poll,
            feed_tail=lambda: self._flight,
            task_state=lambda: "step 3/40",
        )
        if narrate is not None:
            kwargs["narrate"] = narrate
        return PresenceIO(**kwargs)


def _config(budget: int = 24000):
    return SimpleNamespace(context_budget_tokens=budget)


def _engine(replies, *, io=None, senses_config="__armed__", default=None, narrate=None):
    io = io if io is not None else _RecordingIO()
    cfg = _config() if senses_config == "__armed__" else senses_config
    driver = SensesLoopDriver(
        senses_config=cfg,
        make_complete=_make_complete(replies, default=default),
        executor=build_presence_executor(io.io()),
    )
    engine = PresenceEngine(driver=driver, io=io.io(narrate=narrate))
    return engine, io


def _voice_config(**overrides) -> VoiceConfig:
    fields = dict(
        stt_model=None,
        tts_model="tts-1",
        stt_base_url="http://voice/v1",
        tts_base_url="http://voice/v1",
        api_key="k",
    )
    fields.update(overrides)
    return VoiceConfig(**fields)


# ---------------------------------------------------------------------------
# 1. Additive / degrade-clean
# ---------------------------------------------------------------------------


def test_narrate_defaults_to_a_noop_and_is_byte_identical_to_pre_arc() -> None:
    """No front wires ``narrate`` -> PresenceIO's default no-op fires; the
    rendered text is exactly what t6 already produced (byte-identical)."""
    io = _RecordingIO()
    engine, io = _engine(
        [json.dumps({"move": "dispatch_to_cortex", "instruction": "x", "ack": "on it"})],
        io=io,
    )
    engine.acknowledge(ContextPacket(original="do x"))
    assert any("on it" in line for line in io.rendered)
    # No narrate callback was ever supplied, so nothing to assert about
    # narration side effects — this just proves the engine still works.


def test_rendered_text_is_identical_whether_or_not_narration_is_wired(tmp_path: Path) -> None:
    """The core additivity pin: build the SAME turn sequence twice, once with
    a narrate hook wired (via build_presence_narrator, with synthesize forced
    to degrade to None the way the rig's 502ing tts proxy does today) and
    once with no narrate hook at all. The rendered text must be identical."""
    replies = [
        json.dumps({"move": "dispatch_to_cortex", "instruction": "x", "ack": "got it, starting"})
    ]

    # Run A: no narration at all.
    io_a = _RecordingIO()
    engine_a, io_a = _engine(list(replies), io=io_a)
    engine_a.acknowledge(ContextPacket(original="do the task"))

    # Run B: narration wired, but the tts backend degrades (returns None),
    # exactly as the reference rig's tts proxy does today.
    narrate_b = build_presence_narrator(_voice_config(), tmp_path)
    assert narrate_b is not None
    io_b = _RecordingIO(narrate=lambda line: narrate_b(line))
    engine_b, io_b = _engine(list(replies), io=io_b, narrate=io_b._default_narrate)

    import colleague.voice as voice_mod

    original_synthesize = voice_mod.synthesize
    try:
        voice_mod.synthesize = lambda *a, **k: None  # simulate the rig's 502
        engine_b.acknowledge(ContextPacket(original="do the task"))
    finally:
        voice_mod.synthesize = original_synthesize

    assert io_a.rendered == io_b.rendered  # byte-identical text either way
    # And narration was genuinely attempted on run B (proves the hook fired,
    # not merely that it was skipped/absent).
    assert io_b.narrated == ["got it, starting"]
    # A degraded synth writes no file.
    assert list(tmp_path.glob("*.wav")) == []


def test_narrate_is_invoked_with_the_same_text_right_after_render() -> None:
    """The hook lives in the engine: render() and narrate() both fire, in
    that order, carrying the identical text — no front needs its own glue."""
    events: list = []

    def render(line: str) -> None:
        events.append(("render", line))

    def narrate(line: str) -> None:
        events.append(("narrate", line))

    driver = SensesLoopDriver(
        senses_config=_config(),
        make_complete=_make_complete(
            [json.dumps({"move": "dispatch_to_cortex", "instruction": "x", "ack": "hello there"})]
        ),
        executor=build_presence_executor(
            PresenceIO(dispatch_to_cortex=lambda _i: None, append_guidance=lambda _t: None)
        ),
    )
    engine = PresenceEngine(driver=driver, io=PresenceIO(render=render, narrate=narrate))
    engine.acknowledge(ContextPacket(original="do the task"))

    narrate_events = [e for e in events if e[0] == "narrate"]
    render_events = [e for e in events if e[0] == "render"]
    assert narrate_events == [("narrate", "hello there")]
    assert any("hello there" in text for (_kind, text) in render_events)
    # render happened before narrate for the matching line.
    render_idx = next(i for i, e in enumerate(events) if e[0] == "render" and "hello there" in e[1])
    narrate_idx = next(i for i, e in enumerate(events) if e[0] == "narrate")
    assert render_idx < narrate_idx


def test_narrate_exception_is_swallowed_render_still_happens() -> None:
    """A raising narrate callback (a buggy/unreachable front-side wiring)
    must NEVER stop the text render or escape the engine."""
    io = _RecordingIO()

    def boom(_line: str) -> None:
        raise RuntimeError("tts backend exploded")

    engine, io = _engine(
        [json.dumps({"move": "dispatch_to_cortex", "instruction": "x", "ack": "still renders"})],
        io=io,
        narrate=boom,
    )
    # Must not raise.
    engine.acknowledge(ContextPacket(original="do the task"))
    assert any("still renders" in line for line in io.rendered)


def test_off_rung_never_calls_narrate() -> None:
    """A senses-unarmed (off rung) engine never drives a turn at all, so the
    narrate hook — even a hostile one — is never reached (strict no-op)."""
    io = _RecordingIO()

    def boom(_line: str) -> None:
        raise AssertionError("narrate must never be called on the off rung")

    engine, io = _engine([json.dumps({"move": "wait"})], io=io, senses_config=None, narrate=boom)
    assert engine.rung == RUNG_OFF and engine.active is False
    engine.acknowledge(ContextPacket(original="x"))
    engine.on_operator_message("anything")
    assert io.rendered == []


# ---------------------------------------------------------------------------
# 2. No base [voice] audio dependency
# ---------------------------------------------------------------------------


def test_voice_module_imports_no_audio_device_libs_at_module_level() -> None:
    """AST pin: colleague/voice.py (the narration wire client) must not
    import sounddevice/soundfile at module scope — that lazy-import
    boundary belongs solely to colleague/voice_devices.py's opt-in device
    layer."""
    src = Path(__file__).resolve().parents[1] / "colleague" / "voice.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    modules: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    forbidden = {"sounddevice", "soundfile"}
    assert not (modules & forbidden), (
        "colleague/voice.py must not import audio device libs — those live "
        f"behind the lazy [voice] extra in voice_devices.py (found: {modules & forbidden})"
    )


def test_presence_narration_works_with_sounddevice_and_soundfile_unimportable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force sounddevice/soundfile to be unimportable (the standard
    ``sys.modules[name] = None`` technique makes ``import name`` raise
    ``ImportError`` regardless of what is actually installed) and drive the
    FULL presence-narration path end to end: import colleague.presence_engine,
    build a narrate() callable via colleague.voice.build_presence_narrator,
    and run an ack turn through the engine. Narration only ever talks to
    synthesize()'s pure-urllib wire client — it must never reach for the
    [voice] extra's device layer, so this must work with the extra entirely
    absent (the base-install condition, verified separately in this repo's
    environment: sounddevice/soundfile are not installed at all)."""
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    monkeypatch.setitem(sys.modules, "soundfile", None)

    import colleague.presence_engine as presence_engine_mod  # noqa: F401 - importable
    import colleague.voice as voice_mod

    written: list = []

    def _fake_synthesize(
        text, *, tts_model, base_url, out_path, api_key="", voice=None, timeout=60.0
    ):
        Path(out_path).write_bytes(b"RIFF....WAVEfake")
        written.append(text)
        return Path(out_path)

    monkeypatch.setattr(voice_mod, "synthesize", _fake_synthesize)

    narrate = build_presence_narrator(_voice_config(), tmp_path)
    assert narrate is not None

    io = _RecordingIO(narrate=narrate)
    engine, io = _engine(
        [json.dumps({"move": "dispatch_to_cortex", "instruction": "x", "ack": "audio ready"})],
        io=io,
        narrate=io._default_narrate,
    )
    engine.acknowledge(ContextPacket(original="do the task"))

    assert written == ["audio ready"]
    assert list(tmp_path.glob("*.wav"))


# ---------------------------------------------------------------------------
# colleague.voice.build_presence_narrator — unit tests
# ---------------------------------------------------------------------------


def test_build_presence_narrator_returns_none_when_voice_config_is_none(tmp_path: Path) -> None:
    assert build_presence_narrator(None, tmp_path) is None


def test_build_presence_narrator_returns_none_without_a_tts_model(tmp_path: Path) -> None:
    assert build_presence_narrator(_voice_config(tts_model=None), tmp_path) is None


def test_build_presence_narrator_is_duck_typed_not_isinstance_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain object carrying the right attributes works too — no
    isinstance(VoiceConfig) check, matching how talk.py/appserver.py already
    consume config.voice."""
    import colleague.voice as voice_mod

    monkeypatch.setattr(
        voice_mod,
        "synthesize",
        lambda *a, **k: Path(k["out_path"]).write_bytes(b"RIFF") or Path(k["out_path"]),
    )
    fake_config = SimpleNamespace(tts_model="tts-1", tts_base_url="http://voice/v1", api_key="k")
    narrate = build_presence_narrator(fake_config, tmp_path)
    assert narrate is not None
    narrate("hi")
    assert list(tmp_path.glob("*.wav"))


def test_build_presence_narrator_writes_numbered_wavs_beside_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import colleague.voice as voice_mod

    monkeypatch.setattr(
        voice_mod,
        "synthesize",
        lambda *a, **k: Path(k["out_path"]).write_bytes(b"RIFF") or Path(k["out_path"]),
    )
    narrate = build_presence_narrator(_voice_config(), tmp_path, prefix="beat")
    assert narrate is not None
    narrate("one")
    narrate("two")
    names = sorted(p.name for p in tmp_path.glob("*.wav"))
    assert names == ["beat-0001.wav", "beat-0002.wav"]


def test_build_presence_narrator_degrades_when_synthesize_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rig's tts proxy 502s -> synthesize returns None -> narrate() must
    not raise and must write no file."""
    import colleague.voice as voice_mod

    monkeypatch.setattr(voice_mod, "synthesize", lambda *a, **k: None)
    narrate = build_presence_narrator(_voice_config(), tmp_path)
    assert narrate is not None
    narrate("this will not be synthesized")  # must not raise
    assert list(tmp_path.glob("*.wav")) == []


def test_build_presence_narrator_swallows_a_synthesize_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import colleague.voice as voice_mod

    def _boom(*a, **k):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(voice_mod, "synthesize", _boom)
    narrate = build_presence_narrator(_voice_config(), tmp_path)
    assert narrate is not None
    narrate("still must not raise")  # must not raise


# ---------------------------------------------------------------------------
# 4. livecheck: grade from evidence, SKIP honestly, never a fabricated pass
# ---------------------------------------------------------------------------


def test_classify_presence_narration_passes_when_a_real_wav_landed() -> None:
    status, detail = classify_presence_narration_check(True)
    assert status == "passed"
    assert "wav" in detail


def test_classify_presence_narration_skips_when_no_audio_landed() -> None:
    """Never a fabricated pass: no wav (the rig's tts proxy 502ing today)
    grades as an honest SKIP, not a failure."""
    status, detail = classify_presence_narration_check(False)
    assert status == "skipped"
    assert "no audio" in detail or "not ready" in detail.lower()


def test_run_presence_narration_check_skips_when_voice_unconfigured(tmp_path: Path) -> None:
    result = run_presence_narration_check(tmp_path)
    assert isinstance(result, ProofResult)
    assert result.status == "skipped"
    assert "not configured" in result.detail


def test_run_presence_narration_check_skips_honestly_when_rig_502s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the acceptance criterion directly: with voice configured but the
    tts backend degrading (simulating today's rig 502), the live proof SKIPs
    — it never reports a fabricated pass."""
    import colleague.config as config_mod
    import colleague.voice as voice_mod

    monkeypatch.setattr(voice_mod, "synthesize", lambda *a, **k: None)
    monkeypatch.setattr(
        config_mod.EngineConfig,
        "resolve",
        staticmethod(lambda **kw: SimpleNamespace(voice=_voice_config())),
    )

    result = run_presence_narration_check(tmp_path)
    assert result.status == "skipped"
    assert result.file == "presence_narration"


def test_run_presence_narration_check_passes_when_the_rig_actually_serves_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Written to flip automatically the day the rig's tts proxy is fixed."""
    import colleague.config as config_mod
    import colleague.voice as voice_mod

    def _fake_synthesize(
        text, *, tts_model, base_url, out_path, api_key="", voice=None, timeout=60.0
    ):
        Path(out_path).write_bytes(b"RIFF....WAVEfake")
        return Path(out_path)

    monkeypatch.setattr(voice_mod, "synthesize", _fake_synthesize)
    monkeypatch.setattr(
        config_mod.EngineConfig,
        "resolve",
        staticmethod(lambda **kw: SimpleNamespace(voice=_voice_config())),
    )

    result = run_presence_narration_check(tmp_path)
    assert result.status == "passed"

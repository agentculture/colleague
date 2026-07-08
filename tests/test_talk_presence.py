"""Tests for talk-attach middle-manager parity (presence-default-everywhere, t8).

``colleague talk <task-id>`` gains two beats on top of today's reactive talk
lane: an ack/context render on attach (read from the flight plane, before the
first prompt) and cadence-gated proactive updates fired between REPL turns,
both pumped through the SAME :class:`~colleague.presence_engine.PresenceEngine`
used by every other front. The senses-unarmed path must stay byte-identical to
pre-arc ``talk.py`` (:mod:`tests.test_talk_cli`) — pinned here with exact
line-list equality, not just substring checks.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import colleague.flight as flight_mod
from colleague.cli._commands.talk import _UNARMED_NOTICE, run_talk_repl
from colleague.config import EngineConfig, SensesConfig


def _config() -> EngineConfig:
    """A plain resolved config with no senses declared (rung == 'off')."""
    return EngineConfig.resolve(repo_path=Path("/nonexistent-does-not-matter"))


def _armed_config(repo: Path) -> EngineConfig:
    """A resolved config with a senses model declared (rung armed, default 'loop')."""
    base = EngineConfig.resolve(repo_path=repo)
    return dataclasses.replace(
        base,
        senses=SensesConfig(
            model="gemma", base_url="http://senses.example", api_key="", context_budget=24000
        ),
    )


def _seed_flight(tmp_path: Path, task_id: str = "tid") -> None:
    flight_mod.arm(tmp_path, task_id)
    session = flight_mod.FlightSession(repo_path=tmp_path, task_id=task_id)
    session.append_feed(step_index=0, tool="read_file", intent="reading config", stats={})
    session.append_feed(step_index=1, tool="write_file", intent="editing config.py", stats={})


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning = ""
        self.prompt_tokens = 3
        self.completion_tokens = 5


def _make_complete(replies, *, default=None):
    """Build an injectable ``make_complete`` yielding scripted JSON move replies."""
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


def _seam(replies=(), default=None):
    return (
        SimpleNamespace(context_budget_tokens=24000),
        _make_complete(replies, default=default),
        None,
    )


class TestAttachRendersAckAndContext:
    def test_ack_and_flight_context_render_before_first_prompt(self, tmp_path):
        _seed_flight(tmp_path)
        flight_mod.append_chat(
            tmp_path, "tid", {"kind": "ack", "text": "got it — cortex is on it", "at": 0}
        )
        lines: list[str] = []
        seam = _seam()

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _armed_config(tmp_path),
            input_fn=iter(["/quit"]),
            out=lines.append,
            talk_fn=lambda *a, **kw: None,
            resolve_engine_seam=lambda cfg, name: seam,
        )
        assert rc == 0
        # Ack renders first, labeled like every other senses line ...
        assert lines[0] == "senses: got it — cortex is on it"
        # ... followed by a factual (never fabricated) flight-state line.
        assert any("step 1" in line and "write_file" in line for line in lines[1:])

    def test_no_ack_yet_still_renders_flight_state_never_a_cold_prompt(self, tmp_path):
        _seed_flight(tmp_path)  # no ack chat entry written yet
        lines: list[str] = []
        seam = _seam()

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _armed_config(tmp_path),
            input_fn=iter(["/quit"]),
            out=lines.append,
            talk_fn=lambda *a, **kw: None,
            resolve_engine_seam=lambda cfg, name: seam,
        )
        assert rc == 0
        assert not any(line.startswith("senses:") for line in lines)
        assert any("step 1" in line and "write_file" in line for line in lines)

    def test_no_flight_state_at_all_renders_nothing_extra(self, tmp_path):
        # Flight armed but empty (no feed records, no chat) - never fabricate.
        flight_mod.arm(tmp_path, "tid")
        lines: list[str] = []
        seam = _seam()

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _armed_config(tmp_path),
            input_fn=iter(["/quit"]),
            out=lines.append,
            talk_fn=lambda *a, **kw: None,
            resolve_engine_seam=lambda cfg, name: seam,
        )
        assert rc == 0
        assert lines == []


class TestProactiveUpdatesBetweenTurns:
    def test_update_fires_once_then_stays_quiet_when_nothing_changed(self, tmp_path, monkeypatch):
        _seed_flight(tmp_path)  # last recorded step=1, tool=write_file
        monkeypatch.setenv("COLLEAGUE_SENSES_UPDATE_STEPS", "1")
        monkeypatch.setenv("COLLEAGUE_SENSES_UPDATE_CAP", "4")
        lines: list[str] = []
        seam = _seam(default=json.dumps({"move": "reply_to_operator", "text": "still working"}))

        def stub_talk_fn(message, **kwargs):
            return {
                "answer": "reading config",
                "relay": False,
                "relay_text": "",
                "latency": 0.1,
                "degraded": False,
                "tokens": None,
            }

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _armed_config(tmp_path),
            input_fn=iter(["hi", "there", "/quit"]),
            out=lines.append,
            talk_fn=stub_talk_fn,
            resolve_engine_seam=lambda cfg, name: seam,
        )
        assert rc == 0
        updates = [line for line in lines if "still working" in line]
        # Fires exactly once: the feed never advanced between the two REPL
        # turns, so the second boundary has nothing new to say and renders
        # NOTHING (never a fabricated repeat).
        assert len(updates) == 1

        chat = flight_mod.read_chat(tmp_path, "tid")
        assert any(rec.get("answer") == "still working" for rec in chat)

    def test_update_advances_when_the_feed_advances(self, tmp_path, monkeypatch):
        _seed_flight(tmp_path)
        monkeypatch.setenv("COLLEAGUE_SENSES_UPDATE_STEPS", "1")
        monkeypatch.setenv("COLLEAGUE_SENSES_UPDATE_CAP", "4")
        lines: list[str] = []
        seam = _seam(default=json.dumps({"move": "reply_to_operator", "text": "progressing"}))

        def stub_talk_fn(message, **kwargs):
            return None  # irrelevant to this test; presence-armed reactive path unused here

        # Feed advances between the two typed lines - a real caller would be
        # a background cortex process; we simulate it inline.
        def dispatch_and_advance(line_iter):
            for line in line_iter:
                yield line

        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")

        class _AdvancingInput:
            def __init__(self, lines):
                self._lines = list(lines)
                self._i = 0

            def __iter__(self):
                return self

            def __next__(self):
                if self._i >= len(self._lines):
                    raise StopIteration
                line = self._lines[self._i]
                self._i += 1
                if self._i == 2:
                    session.append_feed(step_index=2, tool="run_command", intent="tests", stats={})
                return line

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _armed_config(tmp_path),
            input_fn=_AdvancingInput(["hi", "there", "/quit"]),
            out=lines.append,
            talk_fn=stub_talk_fn,
            resolve_engine_seam=lambda cfg, name: seam,
        )
        assert rc == 0
        updates = [line for line in lines if "progressing" in line]
        # Fires on both turns - the feed genuinely advanced between them.
        assert len(updates) == 2


class TestPresenceOffSwitch:
    def test_env_presence_off_disables_new_beats_but_keeps_reactive_lane(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("COLLEAGUE_PRESENCE", "off")
        _seed_flight(tmp_path)
        flight_mod.append_chat(tmp_path, "tid", {"kind": "ack", "text": "should not show", "at": 0})
        lines: list[str] = []
        seam = _seam()

        def stub_talk_fn(message, **kwargs):
            return {
                "answer": "reading config",
                "relay": False,
                "relay_text": "",
                "latency": 0.1,
                "degraded": False,
                "tokens": None,
            }

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _armed_config(tmp_path),
            input_fn=iter(["hi", "/quit"]),
            out=lines.append,
            talk_fn=stub_talk_fn,
            resolve_engine_seam=lambda cfg, name: seam,
        )
        assert rc == 0
        # No ack/context/update lines - only the reactive answer, exactly as
        # if the presence lane did not exist.
        assert lines == ["senses: reading config"]


class TestUnarmedByteIdentical:
    """Senses-unarmed pins: EXACT line-list equality, not substring checks -
    proof the new attach-context + proactive-update code paths add nothing
    when there is no senses to talk to (config.senses is None -> rung 'off')."""

    def test_typed_message_flow_is_byte_identical_to_pre_arc_talk(self, tmp_path):
        _seed_flight(tmp_path)
        lines: list[str] = []
        err_lines: list[str] = []

        def stub_talk_fn(message, **kwargs):
            assert message == "how's it going?"
            return {
                "answer": "reading config",
                "relay": False,
                "relay_text": "",
                "latency": 0.5,
                "degraded": False,
                "tokens": None,
            }

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _config(),
            input_fn=iter(["how's it going?", "/quit"]),
            out=lines.append,
            err=err_lines.append,
            talk_fn=stub_talk_fn,
        )
        assert rc == 0
        assert lines == ["senses: reading config"]
        assert err_lines == []

    def test_relay_flow_is_byte_identical_to_pre_arc_talk(self, tmp_path):
        _seed_flight(tmp_path)
        lines: list[str] = []

        def stub_talk_fn(message, **kwargs):
            return {
                "answer": "ok, relaying",
                "relay": True,
                "relay_text": "focus on tests",
                "latency": 0.4,
                "degraded": False,
                "tokens": None,
            }

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _config(),
            input_fn=iter(["cortex: focus on tests", "/quit"]),
            out=lines.append,
            talk_fn=stub_talk_fn,
        )
        assert rc == 0
        assert lines == ["senses: ok, relaying", "-> cortex: focus on tests"]

    def test_unarmed_watch_and_raw_guide_flow_is_byte_identical_to_pre_arc_talk(self, tmp_path):
        _seed_flight(tmp_path)
        out_lines: list[str] = []
        err_lines: list[str] = []

        def stub_talk_fn(message, **kwargs):
            return None

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _config(),
            input_fn=iter(["what's happening?", "/quit"]),
            out=out_lines.append,
            err=err_lines.append,
            talk_fn=stub_talk_fn,
        )
        assert rc == 0
        assert out_lines == ["-> cortex: what's happening?"]
        assert err_lines == [_UNARMED_NOTICE]


def test_talk_boundary_never_fires_phase_change_off_a_tool_change(tmp_path, monkeypatch):
    # Qodo (talk phase_changed wrong): the flight feed records only real steps,
    # not the loop's empty-tool phase notices, so a tool-name change is NOT a
    # phase change. The talk boundary must always pass phase_changed=False and
    # rely on the step cadence — else it burns the update cap early.
    from types import SimpleNamespace

    from colleague.cli._commands import talk as talk_mod

    seen: list = []
    presence = SimpleNamespace(
        on_progress_boundary=lambda *, step_count, phase_changed: seen.append(
            (step_count, phase_changed)
        )
        or []
    )
    # Two boundaries with DIFFERENT tool names (would be a "phase change" under
    # the old tool-name heuristic).
    states = iter(
        [{"step_index": 1, "tool": "read_file"}, {"step_index": 2, "tool": "run_command"}]
    )
    monkeypatch.setattr(talk_mod, "_last_task_state", lambda repo, task_id: next(states))
    monkeypatch.setattr(talk_mod, "_persist_presence_turns", lambda *a, **k: None)

    state: dict = {}
    boundary = talk_mod._make_progress_boundary(presence, tmp_path, "tid", state)
    boundary()
    boundary()
    assert seen == [(1, False), (2, False)]  # never a phase-change fire off a tool change

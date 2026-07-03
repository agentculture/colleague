"""Tests for the ``colleague talk`` attach verb (t6, senses live presence + voice).

Drives the REPL core (:func:`run_talk_repl`) via dependency injection — a
scripted ``input_fn`` iterator, a captured ``out`` sink, and an injected
``talk_fn`` stub — so no live model / flight process is needed.
"""

from __future__ import annotations

from pathlib import Path

import colleague.flight as flight_mod
from colleague.cli._app import build_app
from colleague.cli._commands.talk import run_talk_repl
from colleague.config import EngineConfig
from colleague.explain import resolve as explain_resolve


def _config() -> EngineConfig:
    """A plain resolved config with no senses/voice declared (env-independent)."""
    return EngineConfig.resolve(repo_path=Path("/nonexistent-does-not-matter"))


def _seed_flight(tmp_path: Path, task_id: str = "tid") -> None:
    """Arm a flight and write a couple of feed records (the fixture the spec asks for)."""
    flight_mod.arm(tmp_path, task_id)
    session = flight_mod.FlightSession(repo_path=tmp_path, task_id=task_id)
    session.append_feed(step_index=0, tool="read_file", intent="reading config", stats={})
    session.append_feed(step_index=1, tool="write_file", intent="editing config.py", stats={})


class TestTalkAnswersSenses:
    def test_typed_message_yields_labeled_senses_answer(self, tmp_path):
        _seed_flight(tmp_path)
        lines = []

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
            talk_fn=stub_talk_fn,
        )
        assert rc == 0
        assert any("senses: reading config" in line for line in lines)

    def test_exchange_is_recorded_in_the_chat_log(self, tmp_path):
        _seed_flight(tmp_path)

        def stub_talk_fn(message, **kwargs):
            return {
                "answer": "reading config",
                "relay": False,
                "relay_text": "",
                "latency": 0.5,
                "degraded": False,
                "tokens": None,
            }

        run_talk_repl(
            tmp_path,
            "tid",
            _config(),
            input_fn=iter(["how's it going?", "/quit"]),
            out=lambda *a, **kw: None,
            talk_fn=stub_talk_fn,
        )
        records = flight_mod.read_chat(tmp_path, "tid")
        assert len(records) == 1
        assert records[0]["message"] == "how's it going?"
        assert records[0]["answer"] == "reading config"


class TestTalkRelaysInstruction:
    def test_relayed_instruction_lands_in_control_file_with_echo(self, tmp_path):
        _seed_flight(tmp_path)
        lines = []

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

        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")
        control = session.read_control()
        assert "focus on tests" in control.guidance
        assert any("-> cortex: focus on tests" in line for line in lines)


class TestTalkSensesUnarmed:
    def test_unarmed_degrades_to_watch_and_raw_guide(self, tmp_path):
        _seed_flight(tmp_path)
        lines = []

        def stub_talk_fn(message, **kwargs):
            return None

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _config(),
            input_fn=iter(["what's happening?", "please add tests", "/quit"]),
            out=lines.append,
            talk_fn=stub_talk_fn,
        )
        assert rc == 0

        # Exactly ONE unarmed notice, regardless of how many turns degrade.
        notices = [line for line in lines if "senses not armed" in line]
        assert len(notices) == 1

        # Both typed lines are relayed RAW into the control file.
        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")
        control = session.read_control()
        assert "what's happening?" in control.guidance
        assert "please add tests" in control.guidance

        # Each relay is echoed visibly.
        assert any("-> cortex: what's happening?" in line for line in lines)
        assert any("-> cortex: please add tests" in line for line in lines)

    def test_eof_ends_the_repl_cleanly(self, tmp_path):
        _seed_flight(tmp_path)

        def stub_talk_fn(message, **kwargs):
            return None

        rc = run_talk_repl(
            tmp_path,
            "tid",
            _config(),
            input_fn=iter([]),  # immediate EOF
            out=lambda *a, **kw: None,
            talk_fn=stub_talk_fn,
        )
        assert rc == 0


class TestTalkRegistration:
    def test_talk_is_a_known_host_command(self):
        app = build_app()
        assert app.get_command("talk") is not None

    def test_explain_talk_has_a_catalog_entry(self):
        markdown = explain_resolve(("talk",))
        assert "colleague talk" in markdown
        assert markdown  # non-empty

    def test_talk_registers_a_legacy_parser_subcommand(self):
        import argparse

        from colleague.cli._commands.talk import register

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        register(sub)
        args = parser.parse_args(["talk", "tid", "--repo", "."])
        assert args.task_id == "tid"
        assert args.func is not None

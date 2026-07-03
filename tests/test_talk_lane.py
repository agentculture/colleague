"""Live-presence arc (task t5): injection recording + talk-lane chat fold.

Pins the t5 contract: every APPLIED operator-to-cortex guidance injection produces
a visible feed line AND a durable ``TaskResult.senses`` record; the talk-lane chat
log is folded into the artifact at finish; a run with no live lane is byte-identical
(``senses`` stays ``None``); and recording an injection never advances ``step_count``
(the #206 invariant). Drives ``loop.run`` with a scripted fake model exactly like
``tests/test_flight_loop.py`` — a "pilot"/talk-lane client acts BETWEEN turns by
writing the per-flight control/chat files as a side effect of ``complete``.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague import flight
from colleague.contract import OK, SensesBlock, Task
from colleague.loop import ModelResponse, ToolCall, run


def _list_dir_turn() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("c", "list_dir", {"path": "."})])


def _finish_turn() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "done"})])


def _read_feed(repo: Path, task_id: str) -> list[dict]:
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        return []
    return [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]


# --- flight.py chat-log helpers ---------------------------------------------


def test_chat_append_read_roundtrip(tmp_path: Path) -> None:
    flight.append_chat(tmp_path, "abc", {"message": "hi", "answer": "yo"})
    flight.append_chat(tmp_path, "abc", {"message": "bye", "answer": "cya"})
    recs = flight.read_chat(tmp_path, "abc")
    assert [r["message"] for r in recs] == ["hi", "bye"]
    assert recs[0]["answer"] == "yo"


def test_read_chat_absent_is_empty(tmp_path: Path) -> None:
    assert flight.read_chat(tmp_path, "nope") == []


def test_read_chat_skips_malformed_and_nondict_lines(tmp_path: Path) -> None:
    cp = flight.chat_path(tmp_path, "abc")
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text('{"message":"ok"}\nNOT JSON\n[1,2,3]\n\n{"message":"ok2"}\n')
    recs = flight.read_chat(tmp_path, "abc")
    assert [r["message"] for r in recs] == ["ok", "ok2"]


def test_reap_removes_chat_file(tmp_path: Path) -> None:
    session = flight.arm(tmp_path, "abc")
    flight.append_chat(tmp_path, "abc", {"message": "hi"})
    assert flight.chat_path(tmp_path, "abc").exists()
    session.reap()
    assert not flight.chat_path(tmp_path, "abc").exists()


# --- contract: omit-when-empty + round-trip ---------------------------------


def test_senses_block_omits_empty_live_lane_keys() -> None:
    block = SensesBlock(mode="split")
    serialized = block.to_dict()
    assert "injections" not in serialized
    assert "chat" not in serialized


def test_senses_block_roundtrips_injections_and_chat() -> None:
    block = SensesBlock(
        mode="cortex-only",
        injections=[{"text": "pivot", "at": 1.5, "source": "guidance"}],
        chat=[{"message": "status?", "answer": "reading", "relay": False}],
    )
    serialized = block.to_dict()
    assert serialized["injections"] == [{"text": "pivot", "at": 1.5, "source": "guidance"}]
    assert serialized["chat"] == [{"message": "status?", "answer": "reading", "relay": False}]
    restored = SensesBlock.from_dict(serialized)
    assert restored.injections == block.injections
    assert restored.chat == block.chat


def test_senses_block_from_dict_drops_nondict_entries() -> None:
    restored = SensesBlock.from_dict(
        {"mode": "cortex-only", "injections": [{"text": "ok"}, 42, "x"], "chat": [None, {"m": 1}]}
    )
    assert restored.injections == [{"text": "ok"}]
    assert restored.chat == [{"m": 1}]


# --- loop: applied injection recorded on feed + artifact --------------------


def test_applied_guidance_recorded_on_feed_and_artifact(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan", watch=True)
    captured: dict[str, list[dict]] = {}

    def complete(_messages: list[dict]) -> ModelResponse:
        n = len(captured)
        if n == 0:
            # talk-lane client relays an instruction DURING turn 0 -> applied at the
            # boundary before turn 1.
            flight.append_guidance(tmp_path, task.id, "pivot to plan B")
            captured["turn0"] = []
            return _list_dir_turn()
        # turn 1: the injection line is now on the feed (before the finish-time reap).
        captured["feed_at_turn1"] = _read_feed(tmp_path, task.id)
        return _finish_turn()

    result = run(complete, task, max_steps=10)

    assert result.status == OK
    # Durable artifact record.
    assert result.senses is not None
    injections = result.senses.injections
    assert len(injections) == 1
    assert injections[0]["text"] == "pivot to plan B"
    assert isinstance(injections[0]["at"], float)  # wall-clock, never estimated

    # Visible feed line (captured mid-run, before the ephemeral plane is reaped).
    feed = captured["feed_at_turn1"]
    assert any(
        "[guidance applied] pivot to plan B" in (record.get("intent") or "") for record in feed
    )


def _run_two_turn_flight(tmp_path: Path, *, inject: bool) -> tuple[int, int]:
    """Run an identical list_dir->finish flight, optionally injecting guidance at
    the boundary. Returns (len(steps), step_count)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    task = Task.new(str(tmp_path), "scan", watch=True)
    turns = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turns["n"] += 1
        if turns["n"] == 1:
            if inject:
                flight.append_guidance(tmp_path, task.id, "keep going")
            return _list_dir_turn()
        return _finish_turn()

    result = run(complete, task, max_steps=10)
    if inject:
        assert result.senses is not None and len(result.senses.injections) == 1
    return len(result.steps), result.stats.step_count


def test_injection_recording_adds_no_phantom_step(tmp_path: Path) -> None:
    # #206 invariant: recording an applied injection never advances step_count or
    # adds a phantom step. The step counts of an identical run with and without the
    # injection are byte-identical — the injection recording is invisible to steps.
    baseline_steps, baseline_count = _run_two_turn_flight(tmp_path / "base", inject=False)
    injected_steps, injected_count = _run_two_turn_flight(tmp_path / "inj", inject=True)

    assert injected_steps == baseline_steps
    assert injected_count == baseline_count


# --- loop: talk-lane chat folded into the artifact at finish ----------------


def test_talk_lane_chat_folded_into_artifact_at_finish(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan", watch=True)

    def complete(_messages: list[dict]) -> ModelResponse:
        # a talk-lane client records a senses exchange DURING the run.
        flight.append_chat(
            tmp_path,
            task.id,
            {
                "message": "how's it going?",
                "answer": "reading the config",
                "relay": False,
                "latency": 1.2,
                "degraded": False,
            },
        )
        return _finish_turn()

    result = run(complete, task, max_steps=10)

    assert result.senses is not None
    assert len(result.senses.chat) == 1
    assert result.senses.chat[0]["message"] == "how's it going?"
    assert result.senses.chat[0]["answer"] == "reading the config"
    # the ephemeral chat log is reaped once folded.
    assert not flight.chat_path(tmp_path, task.id).exists()


# --- byte-identical when no live lane ---------------------------------------


def test_flight_without_live_lane_leaves_senses_none(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan", watch=True)

    def complete(_messages: list[dict]) -> ModelResponse:
        return _finish_turn()

    result = run(complete, task, max_steps=10)

    assert result.status == OK
    # No injection, no chat -> senses stays None -> artifact byte-identical to today.
    assert result.senses is None

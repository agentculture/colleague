"""Background presence (presence-default-everywhere arc, task t9).

A watched, non-session work item (a `colleague work --background` child, auto
`--watch`) with senses armed writes ack + cadence-gated proactive updates onto
the file-based flight plane at the EXISTING progress-sink boundaries, so an
attached `colleague talk` REPL renders them and the artifact records them — no
TTY, no new thread, no socket/daemon.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from colleague import flight
from colleague.cli._commands._presence_sink import (
    ack_packet_for_task,
    build_watch_presence,
    compose_presence_sink,
    fold_presence_snapshot,
    presence_progress_sink,
)
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, Task, TaskResult


class _FakeEngine:
    """An engine whose senses completions are scripted coordination moves."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self._i = 0

    def make_complete(self, config, *, tools):  # noqa: ANN001
        assert tools == []

        def complete(messages):  # noqa: ANN001
            i, self._i = self._i, self._i + 1
            content = self._replies[i] if i < len(self._replies) else json.dumps({"move": "wait"})
            return SimpleNamespace(
                content=content, reasoning="", prompt_tokens=1, completion_tokens=1
            )

        return complete

    def make_count_tokens(self, config):  # noqa: ANN001
        return None


def _armed_config() -> EngineConfig:
    config = EngineConfig()
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _task(tmp_path: Path, *, watch: bool = True, instruction: str = "build the widget") -> Task:
    return Task(id="bgrun", repo_path=str(tmp_path), instruction=instruction, watch=watch)


# ── the two gates: byte-identical unless armed AND a flight ────────────────────
def test_none_when_senses_unarmed(tmp_path: Path) -> None:
    assert (
        build_watch_presence(task=_task(tmp_path), config=EngineConfig(), engine=object()) is None
    )


def test_none_when_not_a_flight(tmp_path: Path) -> None:
    p = build_watch_presence(
        task=_task(tmp_path, watch=False), config=_armed_config(), engine=_FakeEngine([])
    )
    assert p is None


def test_built_and_active_when_armed_and_watched(tmp_path: Path) -> None:
    p = build_watch_presence(
        task=_task(tmp_path),
        config=_armed_config(),
        engine=_FakeEngine([json.dumps({"move": "wait"})]),
    )
    assert p is not None and p.active


# ── beats land on the flight plane (readable by an attach) ─────────────────────
def test_ack_and_update_land_on_the_flight_plane(tmp_path: Path) -> None:
    task = _task(tmp_path)
    engine = _FakeEngine(
        [
            json.dumps(
                {
                    "move": "dispatch_to_cortex",
                    "instruction": "x",
                    "ack": "on it — handing to cortex",
                }
            ),
            json.dumps({"move": "reply_to_operator", "text": "cortex is editing the widget"}),
        ]
    )
    presence = build_watch_presence(task=task, config=_armed_config(), engine=engine)
    assert presence is not None

    presence.acknowledge(ack_packet_for_task(task))  # the ack beat
    sink = presence_progress_sink(presence)
    sink(0, "", "thinking…", True)  # a phase-change boundary → a proactive update

    chat = flight.read_chat(Path(task.repo_path), task.id)
    texts = " ".join(str(c.get("text") or "") for c in chat)
    assert "on it — handing to cortex" in texts  # ack readable by an attach
    assert "cortex is editing the widget" in texts  # proactive update readable


def test_unattached_run_records_cost_on_the_artifact(tmp_path: Path) -> None:
    task = _task(tmp_path)
    engine = _FakeEngine([json.dumps({"move": "reply_to_operator", "text": "still working"})])
    presence = build_watch_presence(task=task, config=_armed_config(), engine=engine)
    sink = presence_progress_sink(presence)
    sink(0, "", "thinking…", True)  # fire one update

    result = TaskResult(task_id=task.id, status=OK, summary="done")
    fold_presence_snapshot(result, presence)
    # The senses cost is recorded whether or not anyone attached (cap-bounded).
    assert result.senses is not None and result.senses.records


def test_fold_records_but_not_chat_to_avoid_double_fold(tmp_path: Path) -> None:
    # render() already writes chat to the flight log (loop.py folds it at finish);
    # fold_presence_snapshot deliberately folds only records/injections, never chat.
    task = _task(tmp_path)
    engine = _FakeEngine([json.dumps({"move": "reply_to_operator", "text": "hi"})])
    presence = build_watch_presence(task=task, config=_armed_config(), engine=engine)
    presence_progress_sink(presence)(0, "", "thinking…", True)
    result = TaskResult(task_id=task.id, status=OK, summary="done")
    fold_presence_snapshot(result, presence)
    assert result.senses.chat == []  # chat is NOT double-folded here


def test_fold_is_a_no_op_when_presence_produced_nothing(tmp_path: Path) -> None:
    task = _task(tmp_path)
    presence = build_watch_presence(
        task=task, config=_armed_config(), engine=_FakeEngine([json.dumps({"move": "wait"})])
    )
    result = TaskResult(task_id=task.id, status=OK, summary="done")
    fold_presence_snapshot(result, presence)  # never drove a boundary → nothing
    assert result.senses is None  # byte-identical


def test_compose_presence_sink_fans_out_to_the_base_sink(tmp_path: Path) -> None:
    seen: list = []
    base = lambda si, tool, target, ok: seen.append((si, tool, target, ok))  # noqa: E731
    presence = build_watch_presence(
        task=_task(tmp_path),
        config=_armed_config(),
        engine=_FakeEngine([json.dumps({"move": "wait"})]),
    )
    composed = compose_presence_sink(base, presence)
    composed(1, "read_file", "a.py", True)
    assert seen == [(1, "read_file", "a.py", True)]  # the base sink still fires


# ── no new thread / socket / daemon ───────────────────────────────────────────
def test_presence_sink_module_adds_no_thread_socket_or_subprocess() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "colleague"
        / "cli"
        / "_commands"
        / "_presence_sink.py"
    )
    tree = ast.parse(src.read_text(encoding="utf-8"))
    modules: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    for banned in ("threading", "socket", "subprocess", "multiprocessing"):
        assert not any(
            m == banned or m.startswith(banned + ".") for m in modules
        ), f"background presence must add no {banned} — the flight plane is plain file I/O"

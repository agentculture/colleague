"""One-shot foreground work presence (presence-default-everywhere, task t10).

A plain `colleague work "<task>"` (senses armed, NOT --watch, NOT a session)
renders senses' ack + cadence-gated proactive updates as labeled `senses:` lines
on STDERR (via the injected render callback), so the operator watching the
terminal sees senses while cortex works — while `--json`'s stdout result stays
machine-parseable (presence never touches stdout).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from colleague.cli._commands._presence_sink import (
    ack_packet_for_task,
    build_foreground_presence,
    presence_progress_sink,
)
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import Task


class _FakeEngine:
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


def _task(tmp_path: Path, *, watch: bool = False) -> Task:
    return Task(id="oneshot", repo_path=str(tmp_path), instruction="add a docstring", watch=watch)


# ── gating: byte-identical unless armed AND a one-shot (not watched) ───────────
def test_none_when_senses_unarmed(tmp_path: Path) -> None:
    p = build_foreground_presence(
        task=_task(tmp_path), config=EngineConfig(), engine=object(), render=lambda _l: None
    )
    assert p is None


def test_none_when_watched_that_is_the_flight_path(tmp_path: Path) -> None:
    # A watched run is build_watch_presence's job — build_foreground_presence
    # must return None so the two never double up.
    p = build_foreground_presence(
        task=_task(tmp_path, watch=True),
        config=_armed_config(),
        engine=_FakeEngine([]),
        render=lambda _l: None,
    )
    assert p is None


def test_built_when_armed_and_one_shot(tmp_path: Path) -> None:
    p = build_foreground_presence(
        task=_task(tmp_path),
        config=_armed_config(),
        engine=_FakeEngine([json.dumps({"move": "wait"})]),
        render=lambda _l: None,
    )
    assert p is not None and p.active


# ── all presence output goes through the injected render callback (→ stderr) ───
def test_ack_and_update_render_only_through_the_callback(tmp_path: Path) -> None:
    rendered: list[str] = []
    engine = _FakeEngine(
        [
            json.dumps(
                {
                    "move": "dispatch_to_cortex",
                    "instruction": "x",
                    "ack": "on it — cortex is starting",
                }
            ),
            json.dumps({"move": "reply_to_operator", "text": "cortex is adding the docstring"}),
        ]
    )
    presence = build_foreground_presence(
        task=_task(tmp_path), config=_armed_config(), engine=engine, render=rendered.append
    )
    presence.acknowledge(ack_packet_for_task(_task(tmp_path)))
    presence_progress_sink(presence)(0, "", "thinking…", True)

    joined = " ".join(rendered)
    assert "on it — cortex is starting" in joined  # ack rendered
    assert "cortex is adding the docstring" in joined  # proactive update rendered
    assert all(line.startswith("senses:") for line in rendered)  # labeled lines only


def test_no_feed_no_flight_reads_for_a_one_shot(tmp_path: Path) -> None:
    # A one-shot run has no flight plane: feed/task_state IO are empty no-ops, so
    # nothing is written to .colleague/flight/.
    presence = build_foreground_presence(
        task=_task(tmp_path),
        config=_armed_config(),
        engine=_FakeEngine([json.dumps({"move": "reply_to_operator", "text": "hi"})]),
        render=lambda _l: None,
    )
    presence_progress_sink(presence)(0, "", "thinking…", True)
    assert not (tmp_path / ".colleague" / "flight").exists()


# ── the JSON contract: work.py wires render to stderr, never stdout ────────────
def test_work_wires_foreground_presence_render_to_stderr_not_stdout() -> None:
    """Structural pin: execute_work builds foreground presence with
    render=emit_diagnostic (stderr), so a --json invocation's stdout result is
    never interleaved with a senses line."""
    src = Path(__file__).resolve().parents[1] / "colleague" / "cli" / "_commands" / "work.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_foreground_presence"
    ]
    assert calls, "execute_work must call build_foreground_presence"
    render_kwargs = [kw for c in calls for kw in c.keywords if kw.arg == "render"]
    assert render_kwargs, "build_foreground_presence must be called with an explicit render="
    # The render target is emit_diagnostic (the stderr diagnostics stream),
    # NEVER emit_result / a stdout writer.
    for kw in render_kwargs:
        assert (
            isinstance(kw.value, ast.Name) and kw.value.id == "emit_diagnostic"
        ), "foreground presence must render via emit_diagnostic (stderr), never stdout"

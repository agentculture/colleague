"""The mock engine — a deterministic, networkless coder backend (R6).

It runs the *exact same* chassis as a real engine — the shared task contract and
the bounded tool-loop — but supplies a scripted ``complete`` instead of calling a
model. That makes it the CI workhorse (h6): it proves the harness end to end with
no network and no flakiness, and it is the reference against which a live engine's
result *shape* is compared (h8).
"""

from __future__ import annotations

from convertible.config import EngineConfig
from convertible.contract import Task, TaskResult
from convertible.engine import Engine
from convertible.loop import CompleteFn, ModelResponse, ToolCall, run

#: Where the mock writes its marker file (relative to the repo root).
OUTPUT_FILE = "convertible-mock.md"


def _script(task: Task) -> CompleteFn:
    """A deterministic two-turn script: write a marker file, then finish."""
    content = f"# Convertible mock engine\n\nHandled instruction:\n\n{task.instruction}\n"
    turns = [
        ModelResponse(
            tool_calls=[
                ToolCall("mock-1", "write_file", {"path": OUTPUT_FILE, "content": content})
            ],
            prompt_tokens=1,
            completion_tokens=1,
        ),
        ModelResponse(
            tool_calls=[ToolCall("mock-2", "finish", {"summary": f"mock wrote {OUTPUT_FILE}"})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
    ]
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


class MockEngine(Engine):
    """Deterministic in-process engine; never touches the network."""

    name = "mock"

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        return run(_script(task), task, max_steps=config.max_steps)

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
    # Deterministic reasoning/answer text so DriveStats' generated-size fields are
    # non-zero and engine-agnostic (the mock is the contract reference, h5): the
    # e2e shape test compares key shape, and these give the mock the same
    # reasoning_*/answer_* fields a real reasoning model produces.
    turns = [
        ModelResponse(
            content="writing the marker file",
            reasoning="mock reasoning: decide to write the marker file",
            tool_calls=[
                ToolCall("mock-1", "write_file", {"path": OUTPUT_FILE, "content": content})
            ],
            prompt_tokens=1,
            completion_tokens=1,
        ),
        ModelResponse(
            content="done",
            reasoning="mock reasoning: nothing left to do, finish",
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
        return run(
            _script(task),
            task,
            max_steps=config.max_steps,
            system_prompt=self.system_prompt(task, config),
            model=config.model,
            progress=config.progress,
            spawn=config.subagent_spawn,
            # All-engines rule: the mock exercises the SAME loop windowing path.
            # No count_tokens → the loop uses the char estimate via window_messages.
            context_budget=config.context_budget_tokens,
        )

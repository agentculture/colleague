"""The mock engine — a deterministic, networkless coder backend (R6).

It runs the *exact same* runtime as a real backend — the shared task contract and
the bounded tool-loop — but supplies a scripted ``complete`` instead of calling a
model. That makes it the CI workhorse (h6): it proves the harness end to end with
no network and no flakiness, and it is the reference against which a live backend's
result *shape* is compared (h8).
"""

from __future__ import annotations

from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.deepthink import make_deepthink_run
from colleague.engine import Engine
from colleague.loop import (
    CompleteFn,
    ContextControls,
    ModelResponse,
    ToolCall,
    resolve_role,
    run,
)
from colleague.tools import ToolExecutor

#: Where the mock writes its marker file (relative to the repo root).
OUTPUT_FILE = "colleague-mock.md"


def _script(task: Task) -> CompleteFn:
    """A deterministic two-turn script: write a marker file, then finish."""
    content = f"# Colleague mock engine\n\nHandled instruction:\n\n{task.instruction}\n"
    # Deterministic reasoning/answer text so WorkStats' generated-size fields are
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

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        # Typed-subagent role (#t4): resolve config.role and build a role-aware
        # executor identically to the live backend (all-engines rule). The mock's
        # scripted ``complete`` carries no tool schema, so the executor's
        # ``allowlist`` is the role-enforcement point here. None → unrestricted
        # (byte-identical to the pre-role path). Prompt via role-aware system_prompt.
        role = resolve_role(config, task.repo_path)
        # Dual-model deepthink (t5): the mock binds the SAME seam the live backend
        # does (all-engines rule). Its scripted turns never call the tool, but the
        # acceptance self-check escalation path fires identically — and degrades
        # to a recorded no-op, since the mock's make_complete raises (no live
        # model), exercising the c13 degradation ladder end-to-end.
        dt_run = make_deepthink_run(config, self.name)
        return run(
            _script(task),
            task,
            max_steps=config.max_steps,
            system_prompt=self.system_prompt(task, config),
            model=config.model,
            progress=config.progress,
            # The engine builds the repo-confined executor so the config-derived
            # output cap (and subagent spawn) ride the existing ``executor`` seam
            # — keeps ``run()`` from growing another parameter (all-engines rule).
            # ``allowlist=role`` makes the executor REFUSE any tool the role withholds.
            executor=ToolExecutor(
                task.repo_path,
                spawn=config.subagent_spawn,
                batch_spawn=config.subagent_batch_spawn,
                max_output_chars=config.max_output_chars,
                allowlist=role,
                deepthink=dt_run,
            ),
            # All-engines rule: the mock exercises the SAME loop windowing path and
            # arms reactive auto-split (#151) identically (dormant unless an
            # exhausted overflow fires it). No count_tokens → the loop uses the char
            # estimate via window_messages. ``from_config`` is the single source for
            # the config→controls forwarding both backends share.
            context=ContextControls.from_config(config, deepthink_run=dt_run),
        )

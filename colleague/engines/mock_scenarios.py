"""Opt-in mock engine scenarios beyond the default two-turn script (t17).

The default mock script (``colleague/engines/mock.py``'s ``_script``) returns
exactly one tool call per turn — ``write_file`` then ``finish`` — so batched
tool execution (``colleague/toolbatch_loop.py``, plan task t15) went untested
on the mock engine, the contract reference (spec c39/h28, docs/specs/
2026-08-27-adopt-from-qwen-code.md: "today mock.py:97-107 returns one call
per turn and would leave batches untested on the reference backend"). This
module adds exactly ONE opt-in scenario, selected the same way every other
mock recipe is selected — by task text, never automatically: a task whose
``instruction`` contains :data:`BATCH_TASK_MARKER` gets a batch turn instead
of the default script. Every other task text is unaffected — the default
mock script stays byte-identical (``tests/test_mock_engine.py``,
``tests/test_e2e_mock.py`` pass unchanged).

Kept in its own module — rather than growing ``mock.py`` further — so
``tests/test_file_length_ratchet.py``'s per-file baseline stays intact: a
brand-new module starts fresh, well under the ratchet's 1000-line ceiling for
new modules, while ``mock.py`` itself gains only the one-line import + a
single-line change to reach in (a net-zero hunk against its own baseline).

The constants below (``BATCH_READ_PATHS`` / ``BATCH_WRITE_PATH`` /
``BATCH_WRITE_CONTENT``) are the single source of truth for what "the batch
turn" is — ``tests/_batch_fixture.py`` imports them directly so the mock
engine and a scripted fake vllm-openai server are proven to run the
*identical* tool calls (h8: the mock stays the reference other engines are
compared against), not two independently-typed lookalikes.
"""

from __future__ import annotations

from colleague.contract import Task
from colleague.loop import ModelResponse, ToolCall

#: The task-text trigger for the batch scenario — opt-in, like every other
#: mock recipe: absent from a task's instruction, the default script runs.
BATCH_TASK_MARKER = "mock-batch:"

#: The three read-only files the batch scenario reads, in request order.
BATCH_READ_PATHS: tuple[str, ...] = ("a.txt", "b.txt", "c.txt")

#: Where the batch scenario's write call lands, and what it writes — fixed
#: values (not derived from ``task.instruction``) so a fake vllm-openai
#: server scripting the same calls produces call-for-call identical
#: ``(name, arguments)`` pairs to the mock's, not merely same-shaped ones.
BATCH_WRITE_PATH = "batch-out.txt"
BATCH_WRITE_CONTENT = "written by the batch turn\n"


def is_batch_task(task: Task) -> bool:
    """True when *task*'s instruction opts into the batch scenario."""
    return BATCH_TASK_MARKER in task.instruction


def batch_turns_or_none(task: Task) -> "list[ModelResponse] | None":
    """:func:`batch_turns` when *task* opts in, else ``None``.

    The single seam ``mock._script`` reaches through, via ``... or [default]``
    (never truthy-empty — :func:`batch_turns` always returns two turns) — kept
    here, in this module, rather than inlined at the call site, so
    ``mock.py``'s own line count never grows past its ratchet baseline.
    """
    return batch_turns(task) if is_batch_task(task) else None


def batch_turns(task: Task) -> list[ModelResponse]:
    """The batch scenario's two turns: one batched turn, then finish.

    Turn 1 carries FOUR tool calls in a single ``ModelResponse`` — three
    concurrency-safe ``read_file`` calls (``colleague/toolbatch.py``'s
    ``CONCURRENCY_SAFE_TOOLS``) followed by one mutating ``write_file`` — so
    the loop's batching path (``colleague/toolbatch_loop.py``) partitions
    them into a 3-wide parallel read batch, then a solo write batch, the
    exact shape ``tests/test_toolbatch_loop.py`` already proves against a
    fake executor. Turn 2 finishes, mirroring the default script's shape.
    """
    reads = [
        ToolCall(f"mock-batch-read-{i}", "read_file", {"path": path})
        for i, path in enumerate(BATCH_READ_PATHS, start=1)
    ]
    write = ToolCall(
        "mock-batch-write",
        "write_file",
        {"path": BATCH_WRITE_PATH, "content": BATCH_WRITE_CONTENT},
    )
    return [
        ModelResponse(
            content="reading three files, then writing the batch marker",
            reasoning="mock reasoning: batch scenario — read three files, then write one",
            tool_calls=[*reads, write],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        ),
        ModelResponse(
            content="done",
            reasoning="mock reasoning: batch scenario finished, nothing left to do",
            tool_calls=[ToolCall("mock-batch-finish", "finish", {"summary": "mock batch done"})],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        ),
    ]

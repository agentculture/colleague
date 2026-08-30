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


def batch_turns(_task: Task) -> list[ModelResponse]:
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


# ---------------------------------------------------------------------------
# t20 (decision c47) — the survey-digest scenario: a mock purpose child whose
# brief is one of the two FIXED survey briefs (``colleague/purpose_schemas.py``
# ``_brief_code_survey`` / ``_brief_web_survey``) answers with a scripted
# evidence digest in the required shape — one cited finding (path:start-end,
# or a url + anchor), a <= 5-line verbatim excerpt, and a trailing
# ``commands run:`` list — so ``tests/test_purpose_executor.py`` proves the
# parent-side renderer accepts a well-shaped digest end to end on the
# reference backend. Selected by the brief's fixed opening line, like every
# other mock recipe: any other task text keeps the default script.
# ---------------------------------------------------------------------------

#: The fixed opening lines of the two survey briefs (the templates' prefixes).
CODE_SURVEY_BRIEF_PREFIX = "Survey the code for:"
WEB_SURVEY_BRIEF_PREFIX = "Survey the web for:"

#: Scripted digests — fixed values, not derived from the task, so tests pin
#: the exact shape. The citations are illustrative, not real evidence: the
#: mock never reads anything; the SHAPE is what the parent renderer checks.
CODE_SURVEY_DIGEST = (
    "finding: colleague/loop.py:1-3 — the survey target's opening lines\n"
    "  excerpt:\n"
    "    the opening line, quoted verbatim\n"
    "commands run:\n"
    "  - read_file colleague/loop.py"
)
WEB_SURVEY_DIGEST = (
    "finding: https://example.invalid/docs#overview — the page's overview anchor\n"
    "  excerpt:\n"
    "    the quoted overview sentence, verbatim\n"
    "commands run:\n"
    "  - web fetch https://example.invalid/docs"
)


def survey_digest_or_none(task: Task) -> "str | None":
    """The scripted digest for *task*'s survey brief, or ``None`` (no survey)."""
    if task.instruction.startswith(CODE_SURVEY_BRIEF_PREFIX):
        return CODE_SURVEY_DIGEST
    if task.instruction.startswith(WEB_SURVEY_BRIEF_PREFIX):
        return WEB_SURVEY_DIGEST
    return None


def survey_turns_or_none(task: Task) -> "list[ModelResponse] | None":
    """One finish turn carrying the scripted digest, or ``None`` (no survey).

    The scout role is read-only, so the scenario is a single deliberate
    ``finish`` whose summary IS the digest — the digest is DATA the parent
    reads, never a tool the runtime calls on the parent's behalf.
    """
    digest = survey_digest_or_none(task)
    if digest is None:
        return None
    return [
        ModelResponse(
            content="reporting the survey digest",
            reasoning="mock reasoning: survey brief — answer in the evidence-digest shape",
            tool_calls=[ToolCall("mock-survey-finish", "finish", {"summary": digest})],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        )
    ]

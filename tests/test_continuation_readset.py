"""t21 — continuation carries no read-set (spec c41/h30).

The prior-read rule (``colleague/editgate.py``, t13) is enforced by a per-
``ToolExecutor`` :class:`~colleague.editmatch.ReadSet` — never persisted onto
a :class:`~colleague.contract.TaskResult`, a
:class:`~colleague.agents.state.TaskSnapshot`, or a continuation seed. A
continued run (``work --continue``) therefore starts with a FRESH read set:
files this executor (or an earlier episode) edited are NOT considered read,
so ``edit_file`` still needs its own ``read_file`` first — proved here by
driving the shared loop (:func:`colleague.loop.run`) with a scripted
``complete``, exactly the way every engine does. Three things are pinned:

1. an edit-before-read on a continued run is refused, naming the rule AND
   the continuation id; read-then-edit on the SAME continued run succeeds;
2. the continuation seed's own preamble states the rule up front, in one
   sentence, ahead of the prior state recap (a snapshot test of the render);
3. ``TaskSnapshot`` carries no read-set field at all, in the dataclass or in
   its JSON — confirming the read set is simply never in the replay state a
   continuation rehydrates from.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from colleague import editgate
from colleague.agents.state import TaskSnapshot
from colleague.artifact import artifact_dir, write
from colleague.continuation import resolve_continuation
from colleague.contract import Task, TaskResult, WorkStats
from colleague.loop import ModelResponse, ToolCall, run

ORIGINAL = "def f():\n    x = 1\n    return x\n"


def _write_prior_artifact(repo: Path, task_id: str) -> None:
    """A cut/incomplete prior work item — exactly what ``--continue`` resumes."""
    stats = WorkStats(
        request="add a helper function",
        started_at="2026-01-01T00:00:00Z",
        duration_seconds=12.0,
        model_turns=2,
        step_count=2,
        tool_counts={"write_file": 1},
        files_changed=1,
        bytes_written=100,
    )
    result = TaskResult(
        task_id=task_id,
        status="incomplete",
        summary="ran out of steps",
        changed_files=["mod.py"],
        error="step budget exhausted",
        stats=stats,
    )
    write(result, artifact_dir(repo))


def _repo(tmp_path: Path) -> Path:
    (tmp_path / ".colleague").mkdir()
    (tmp_path / "mod.py").write_text(ORIGINAL, encoding="utf-8")
    return tmp_path


def _scripted_complete(turns: list[ModelResponse]):
    """A minimal ``CompleteFn``: replays *turns* in order, holding the last."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


def _continued_task(repo: Path, task_id: str) -> tuple[str, Task]:
    _write_prior_artifact(repo, task_id)
    prior_id, seed = resolve_continuation(repo, task_id)
    return prior_id, Task.new(str(repo), seed, engine="mock")


# ---------------------------------------------------------------------------
# 1. edit-before-read on a continued run: refused, naming the rule + the id;
#    read-then-edit on the same continued run: succeeds.
# ---------------------------------------------------------------------------


def test_continued_run_edit_before_read_names_rule_and_continuation_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    prior_id, task = _continued_task(repo, "prior-edit-001")

    turns = [
        ModelResponse(
            content="editing without reading first",
            tool_calls=[
                ToolCall(
                    "c1",
                    "edit_file",
                    {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 9"},
                )
            ],
        ),
        ModelResponse(content="done", tool_calls=[ToolCall("c2", "finish", {"summary": "done"})]),
    ]
    result = run(_scripted_complete(turns), task, max_steps=5)

    edit_step = result.steps[0]
    assert edit_step.tool == "edit_file"
    assert edit_step.ok is False
    assert "prior-read rule" in edit_step.result
    assert prior_id in edit_step.result
    assert (repo / "mod.py").read_text(encoding="utf-8") == ORIGINAL  # untouched


def test_continued_run_read_then_edit_succeeds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, task = _continued_task(repo, "prior-edit-002")

    turns = [
        ModelResponse(
            content="reading first",
            tool_calls=[ToolCall("c1", "read_file", {"path": "mod.py"})],
        ),
        ModelResponse(
            content="now editing",
            tool_calls=[
                ToolCall(
                    "c2",
                    "edit_file",
                    {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 9"},
                )
            ],
        ),
        ModelResponse(content="done", tool_calls=[ToolCall("c3", "finish", {"summary": "done"})]),
    ]
    result = run(_scripted_complete(turns), task, max_steps=5)

    assert all(step.ok for step in result.steps)
    assert (repo / "mod.py").read_text(encoding="utf-8") == "def f():\n    x = 9\n    return x\n"


def test_ordinary_run_refusal_carries_no_continuation_id(tmp_path: Path) -> None:
    """A non-continued run's refusal names the rule, but no continuation id —
    ``context_note`` is ``None`` unless the task's own instruction is a
    continuation seed (t21)."""
    repo = _repo(tmp_path)
    task = Task.new(str(repo), "add one to x", engine="mock")

    turns = [
        ModelResponse(
            content="editing without reading first",
            tool_calls=[
                ToolCall(
                    "c1",
                    "edit_file",
                    {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 9"},
                )
            ],
        ),
        ModelResponse(content="done", tool_calls=[ToolCall("c2", "finish", {"summary": "done"})]),
    ]
    result = run(_scripted_complete(turns), task, max_steps=5)

    edit_step = result.steps[0]
    assert "prior-read rule" in edit_step.result
    assert "continuing work item" not in edit_step.result


# ---------------------------------------------------------------------------
# 2. the seed states the rule up front, in one sentence (snapshot of render).
# ---------------------------------------------------------------------------


def test_continuation_preamble_states_rule_up_front() -> None:
    preamble = editgate.continuation_preamble("task-123")

    assert preamble == (
        "You are CONTINUING work item task-123 that stopped early. This is a "
        "continuation of task-123: files edited earlier are NOT considered read — "
        "read_file a file (or the span) before edit_file. Prior state:\n\n"
    )
    # The rule sentence precedes "Prior state:" — stated up front, not buried
    # after the recap.
    rule_at = preamble.index("NOT considered read")
    prior_state_at = preamble.index("Prior state:")
    assert rule_at < prior_state_at


def test_resolved_seed_leads_with_the_continuation_preamble(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_prior_artifact(repo, "prior-seed-002")

    task_id, seed = resolve_continuation(repo, "prior-seed-002")

    assert seed.startswith(editgate.continuation_preamble(task_id))


# ---------------------------------------------------------------------------
# 3. TaskSnapshot carries no read-set field — the dataclass or its JSON.
# ---------------------------------------------------------------------------


def test_task_snapshot_has_no_read_set_field() -> None:
    field_names = {f.name for f in fields(TaskSnapshot)}
    read_like = {name for name in field_names if "read" in name.lower()}
    assert read_like == set(), f"TaskSnapshot carries a read-set-shaped field: {read_like}"

    snapshot = TaskSnapshot(task_id="t1")
    keys = set(snapshot.to_dict().keys())
    assert keys == field_names  # to_dict is exactly the dataclass fields, nothing folded in
    assert not any("read" in k.lower() for k in keys)

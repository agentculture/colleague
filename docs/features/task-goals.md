# Task goals — a pre-execution goal + acceptance criteria, and an advisory self-check

> Tracking: [colleague#259](https://github.com/agentculture/colleague/issues/259) ·
> spec R6 in
> [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md).

Before this feature `Task` carried only free-form `instruction` text —
acceptance criteria, when they existed at all, lived flattened into that
prose, and there was no structured record of *whether* the work met them.
Destination/announcement (`docs/features/destination.md`) is recorded only
**post-hoc** on `TaskResult`. This feature adds pre-execution, machine-readable
goal fields to the task contract, an advisory self-check that grades the
finished work against them, and task lineage across subagent trees — all
omit-when-None, so a task authored without them is byte-identical.

## The contract fields (`colleague/contract.py`, t14)

- **`Task.goal: Optional[str]`** — a one-line, human-readable statement of
  what this work item is *for*, distinct from `instruction` (which may be the
  full "do X in file Y" prose; a goal-less task carries no separate goal).
- **`Task.acceptance: Optional[list[str]]`** — machine-readable acceptance
  criteria, one short sentence each. Setting a goal without acceptance
  criteria is fine — no self-check runs without at least one criterion.
- **`TaskResult.acceptance_outcomes: Optional[list[dict]]`** — the self-check's
  per-criterion outcome records (below), or `None` when the task carried no
  acceptance criteria.
- **`SubResult.parent: Optional[str]`** — the **immediate** parent work item's
  `task_id` (lineage), or `None` when the child was not recorded with a
  parent link.

All four fields follow the established omit-when-None convention
(`to_dict()` only adds the key when the value is not `None`) — a
`Task`/`TaskResult`/`SubResult` authored without them serializes with exactly
the pre-feature key set (pinned by `tests/test_contract_goal.py` and the e2e
mock shape test).

## The prompt block + the self-check turn (`colleague/loop.py`, t15)

### The goal block

`_build_user_message` appends a **distinct** block after `instruction` /
`context` / `constraints` when the task declares them:

```python
if task.goal:
    user += f"\n\nGoal:\n{task.goal}"
if task.acceptance:
    user += (
        "\n\nAcceptance criteria (the work is done when each of these holds):\n"
        + "\n".join(f"- {c}" for c in task.acceptance)
    )
```

so `finish` has a concrete, separated target instead of re-deriving intent
from prose alone (#231). Absent fields mean this block is simply never
appended — byte-identical to before.

### The self-check turn

`_maybe_run_acceptance_selfcheck(ctx, complete, outcome, aborted)` fires
**only** when the task declared `acceptance` **and** the run reached a clean
`_EXIT_FINISHED` (an incomplete or aborted run does not spend a turn grading
itself — its honest `incomplete`/error status must stand untouched). It
appends `_ACCEPTANCE_CHECK_PROMPT` (asking for a JSON array, one object per
criterion, `{"criterion", "met", "evidence"}`, no prose, no tool calls),
completes **once**, and parses the result with `_parse_acceptance_outcomes`:

- entries are matched to the task's criteria **by position**, and the
  **criterion text is taken from the Task** (authoritative) — a model that
  paraphrases or hallucinates a different criterion can still only ever grade
  the real ones;
- a missing/malformed entry reads as `met=False` with empty evidence (the
  conservative default);
- any parse failure returns `[]` (nothing recorded) — the check is advisory
  and must never raise.

`met=False` **never flips the run's status** — outcomes land on
`result.acceptance_outcomes` for the feedback/ROI loop
(`docs/features/stats-and-feedback.md`) only. Operator judgment stays the
authority (the same convention the `devague` destination tool already
established: the backend cannot self-confirm its own arrival).

## Deviation from the plan: a single completion, not save/restore

The plan's t15 acceptance criterion described the self-check "reus[ing] the
lint fix-turn save/restore pattern" — the lint/test-integrity/affected-tests
gates all save the work item's terminal `summary`/`status` before their
model turn and restore it after, because those turns run through the full
tool loop and *could* call `finish` and clobber the result.

The built self-check is **stronger by construction** instead: it is a single
bare `complete()` call appended directly to `ctx.messages`, never a re-entered
tool loop turn. There is no tool schema offered, so the model **structurally
cannot call `finish`** during the self-check — there is nothing to save and
restore because there is no path back into the terminal-summary machinery at
all. This is a deliberate, stronger invariant than the save/restore pattern,
not merely a smaller implementation of it.

## `SubResult.parent` lineage (t14 + t16)

Every subagent spawn path (`run_subagent`, `make_batch_spawn`) accepts an
optional `parent_task_id`, recorded on the returned `SubResult.parent`
(`None` by default, omitted from serialization). A grandchild's lineage
points at its **immediate** parent (the child that spawned it), not the
top-level root — each nested spawn/batch-spawn callback is rebuilt with
`parent_task_id=child_task.id` before being handed to the next level down —
so a subagent tree is walkable **one hop at a time** from artifacts alone,
without a separate lineage index.

### Workforce structural criteria (`colleague/plan/workforce.py`, t16)

`build_workforce_items` carries each `PlanItem`'s acceptance criteria
**structurally** — a `"acceptance"` key (`list(item.acceptance)`) and a
`"goal"` key (`item.summary`) on the batch-spawn item dict — rather than
flattening them into the instruction prose:

```python
entry = {
    "instruction": item.summary,
    "engine": engine,
    "model": model,
    "goal": item.summary,
    "acceptance": list(item.acceptance),
}
```

`_run_one` (inside `subagents.py`'s `_spawn_children`) reads these keys when
building each child's `Task(goal=..., acceptance=...)`, so the existing t15
loop machinery (the goal/acceptance prompt block + the advisory self-check)
fires for workforce children **automatically** — no new machinery needed for
the workforce path specifically. **Tool schemas are deliberately NOT
extended**: `goal`/`acceptance` are programmatic-only keys used by
non-model callers (the plan workforce today); the `subagents` tool's own
`_parse_batch_items` still strips model-supplied batch items down to their
existing keys, so a model cannot itself set a child's goal/acceptance through
the tool call surface.

**Note on parent lineage at the plan-verb entry point:** `colleague plan run`
itself is not a `Task`/work item — it drives the model through
`Engine.make_complete` outside `execute_work` (see
`docs/features/plan-mode.md`), so there is no natural top-level `task_id` to
pass as `parent_task_id` at that call site
(`colleague/cli/_commands/plan.py`'s `make_batch_spawn(..., counter=...)` call
passes none). Workforce children spawned directly from `colleague plan run`
therefore have `SubResult.parent = None` — correctly, since they have no
parent *task*. The "walkable from artifacts alone" guarantee applies to any
subtree **within** an ordinary work item's own subagent delegation (a child
that itself spawns grandchildren), which is exactly what `SubResult.parent`
was built to make possible.

## `plan continue`

Cross-invocation plan resume (`colleague plan continue`, t17) is a sibling
piece of this same R6 requirement (tasks carry their goal so an interrupted
run can pick back up); it is documented in full in
[`docs/features/plan-mode.md`](plan-mode.md#cross-invocation-resume-plan-continue)
rather than duplicated here.

## Honest limits

- **Self-assessment is advisory ROI evidence, not a gate.** A `met=False`
  outcome never flips `TaskResult.status`, never blocks the handoff, and is
  never treated as authoritative — the operator (or a downstream
  `ask-colleague feedback` grade) remains the authority, matching the
  `devague`-tool convention that the backend cannot self-confirm.
- **Incomplete runs never self-grade.** The self-check only fires on a clean
  `_EXIT_FINISHED`; a run that stopped, was aborted, or ran out of budget
  never spends a turn grading itself.
- **Criterion text is trusted from the Task, evidence is trusted from the
  model.** The self-check can misjudge whether a criterion was actually met
  (it is one bounded completion, not a verification harness) — it is a
  cheap signal, not a test suite.
- **`goal`/`acceptance` are omitted from every model-callable tool schema** —
  they can only be set programmatically (by a CLI caller, the session, or the
  plan workforce), never by the model itself mid-run.

## Spec + plan

- Spec: [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
- Plan: [`docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
  (tasks t14-t17)

## See also

- [`docs/features/plan-mode.md`](plan-mode.md) — `plan continue` +
  the workforce stage that structurally carries acceptance criteria
- [`docs/features/destination.md`](destination.md) — the post-hoc
  announcement this feature's pre-execution goal complements
- [`docs/features/stats-and-feedback.md`](stats-and-feedback.md) — where
  `acceptance_outcomes` feeds the ROI loop
- [`docs/features/tier-visibility.md`](tier-visibility.md) — the session
  cockpit's goal line (`_with_goal`)

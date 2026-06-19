Fan out a converged devague plan's dependency waves to parallel agents in isolated git worktrees, one agent per task per wave, with TDD-gated merges by the main agent. Human gates: the exported spec, the implementation split plan (task map + per-task agent/model proposal + go/no-go), and the final PR. The devague CLI stays deterministic and non-orchestrating (#20) — it only *describes* the graph via `devague plan waves`; the operator (main agent) performs the fan-out. Use when the user says "assign to workforce", "fan out the plan", "parallel subagents", or after the `spec-to-plan` skill exports a plan. Authored and maintained in agentculture/devague (origin = devague); steward pulls this skill from here and broadcasts it to the AgentCulture mesh — it is NOT vendored from steward like the other skills here.

<!-- learned-from: claude; source: .colleague/skills/assign-to-workforce.md; adapt: claude->colleague -->

# assign-to-workforce

# assign-to-workforce — fan out a converged plan's waves to parallel agents

The skill is named **`assign-to-workforce`**; the product/CLI it reads is the
**`devague plan waves`** command. (The prior leg — turning a spec into a plan —
is the sibling **`spec-to-plan`** skill.)

`assign-to-workforce` takes a **converged devague plan** and fans out its
dependency waves to parallel agents (subagents, teammate agents, or generalist
agents) — one agent per task per wave — each working in an **isolated git
worktree**. The main agent merges each completed worktree gated by TDD. The
human owns exactly three gates: the exported spec, the implementation split
plan, and the final PR.

The devague CLI is **never orchestrated by devague itself** — `devague plan
waves` describes the dependency graph (#20); it does not spawn agents, manage
worktrees, mark tasks done, or pick a backend. The fan-out is the *operator's*
job — this skill and the main agent perform it.

## How to run

There is no shell script entry point. Instead, use colleague's native tools:

- **`devague` tool** — call `devague plan waves` (via the `devague` CLI tool) to
  inspect the dependency graph and list wave batches.
- **`subagents` tool** — fan out same-wave tasks in parallel, each as an
  isolated subagent with its own git worktree.
- **`run_command`** — create worktrees, run tests, merge branches, and clean up.

### Usage

| Action | How |
|--------|-----|
| Inspect waves | `devague plan waves` (via the `devague` tool) |
| Render split plan | Read `devague plan waves --json` output and format the task map with per-task agent + model proposal for human go/no-go review. |
| Fan out a wave | Use `subagents` to dispatch same-wave tasks in parallel, each subagent working in its own worktree. |
| TDD-gated merge | Run tests on main, merge the worktree branch, re-run tests, then remove the worktree. |

## The full flow

The flow has three human gates and one automated TDD merge loop.

### Human gate 1 — the exported spec

The plan is seeded from a converged frame (`devague plan new --frame <slug>`).
The human reviewed and approved the spec when it was exported by the `think`
skill. No re-approval needed here — the spec gate is already closed.

### Human gate 2 — the implementation split plan

Before any task is assigned, the main agent presents the **implementation split
plan** for human go/no-go. This is the only gate the human owns at the
implementation stage (per task, the TDD gate is the main agent's).

The split plan contains:

1. **Task map** — every task id, its one-line summary, acceptance criteria, and
   the wave it belongs to (from `devague plan waves`).
2. **Per-task agent + model proposal** — for each task: the proposed agent type
   (subagent / teammate / generalist), the proposed model (e.g. a cheaper/faster
   model for a well-scoped task), and the scope justification (why this task is
   safe to delegate).
3. **Go/no-go question** — explicit human decision: "Approve this split and
   assign the plan to the workforce, or edit it first?"

The human may edit any row (agent type, model, scope) before approving. The
plan is model-agnostic — devague does not pick a backend (#20).

Use the `devague` tool to fetch wave data, then present the split plan to the
human. Do not proceed to fan-out until the human approves the split plan.

### Fan-out — one agent per task per wave in isolated worktrees

Once the human approves, the main agent fans out each wave in order:

1. **Create an isolated git worktree** for each task in the current wave:

   ```bash
   git worktree add ../worktrees/agent-<task-id> -b agent/<task-id>
   ```

2. **Spawn a task agent** inside that worktree (using the approved model from
   the split plan), with:
   - The task id, summary, and acceptance criteria as its brief.
   - Instruction to work **test-first** (TDD): write the failing test(s) that
     match the acceptance criteria before implementing.
   - Instruction to commit its work to the worktree branch.

   Use the **`subagents`** tool to dispatch same-wave tasks in parallel. Each
   subagent receives its own instruction containing the worktree path, task
   brief, and model/engine selection.

3. **Same-wave tasks run in parallel** (within-wave tasks have no
   inter-task dependency; the dependency graph guarantees this). Same-file
   overlap surfaces as a merge conflict at reconcile time, not a live race —
   isolated worktrees prevent clobbering.

4. **Wait for all tasks in the wave to complete** before starting the next wave.

### TDD-gated merge — main agent, no human per task

For each completed task worktree, the main agent:

1. **Runs the task's tests before merge** (on the main branch): baseline must
   pass (or the relevant tests must be absent — the task adds them).
2. **Merges the worktree branch** into the main branch:

   ```bash
   git merge --no-ff agent/<task-id>
   ```

3. **Runs the task's tests after merge**: they must pass. If they do not, the
   merge is reverted and the task agent is given the failure output to fix.
4. **Removes the worktree** once the merge is accepted:

   ```bash
   git worktree remove ../worktrees/agent-<task-id>
   ```

The human does **not** review individual task merges. Per-task acceptance is
the main agent's responsibility — the TDD gate (tests pass before AND after
merge) plus the task's acceptance criteria. This mirrors the non-authoritative
working state pattern of the Human Review Loop (#17): per-task merge records
are uncommitted working state; the authoritative human gate is the final PR.

Advance to the next wave only after all tasks in the current wave are merged
and their tests pass.

### Human gate 3 — the final PR

Once all waves are merged and the full test suite passes, the main agent opens
a PR via the `cicd` skill. The human reviews and merges. This is the last and
only remaining human gate.

## Hard rules (do not violate)

These protect the human-gate contract and the TDD guarantee.

- **Present the split plan before any fan-out.** Never spawn a task agent
  without prior human approval of the implementation split plan (gate 2). The
  split plan is the human's only implementation-stage decision.
- **One worktree per task.** Never run two tasks in the same worktree — file
  contention is managed by isolation, not by trust in the dependency graph.
  The dependency graph guarantees *logical* independence within a wave, not
  *file* disjointness. Conflicts surface at merge time.
- **Tests before AND after merge — no exceptions.** The TDD gate must pass on
  both sides. A merge that makes tests pass only after (not before) means the
  baseline was already broken — fix the baseline first.
- **Human does not gate per-task merges.** The TDD contract replaces the
  human here. Do not pause for human approval between wave tasks.
- **devague CLI is not orchestrated.** `devague plan waves` is read-only
  scheduling metadata (#20). Never run `devague plan` commands inside a task
  worktree to "mark a task done" or modify plan state from a subagent.
- **Three gates only.** The human's gates are: (1) the exported spec, (2) the
  implementation split plan, (3) the final PR. No silent fourth gate.
- **No LLM calls in the devague CLI.** The CLI is deterministic. This skill
  adds orchestration convention, not CLI behavior.

## Output contract

The split plan is rendered to **stdout** (as formatted text or structured data)
and presented for human review. On error (no plan, cyclic graph) the `devague`
tool exits non-zero with a diagnostic on stderr.

## Worked example

Picking up after the `spec-to-plan` skill exported a plan for the frame `my-feature`:

```bash
# 1. Inspect the waves (via the devague tool)
devague plan waves

# 2. Present the implementation split plan for human review
#    (format the devague output into a task map with agent/model proposals)

# --- HUMAN: review the table, edit agent/model assignments if needed,
#     then say "approved" to proceed ---

# 3. Fan out wave 1 (t1, t2, t3 are independent — run in parallel)
#    Use the `subagents` tool to dispatch three parallel subagents,
#    each working in its own worktree.

# 4. TDD-gated merge for each wave-1 task (no human per task)
git merge --no-ff agent/t1   # tests pass before + after
git worktree remove ../worktrees/agent-t1
git merge --no-ff agent/t2
git worktree remove ../worktrees/agent-t2
git merge --no-ff agent/t3
git worktree remove ../worktrees/agent-t3

# 5. Advance to wave 2 (t4 depends on t1–t3 being merged)
git worktree add ../worktrees/agent-t4 -b agent/t4
# ... spawn subagent, await, merge with TDD gate, remove worktree ...

# 6. Open the final PR (human gate 3)
#    Use the `cicd` skill to open the PR
```

The exported plan-md from `devague plan export` is the standing brief for
each task agent — its task id, summary, acceptance criteria, and the targets
it covers are already in that file.

## Provenance

This is a **first-party** skill — its origin is `agentculture/devague`, where
the devague agent maintains it alongside the tools it operates (dogfooding),
next to its siblings `think` and `spec-to-plan`. It is the *third* skill in
that outbound family, covering the implementation leg after a plan converges.
The flow runs the *opposite* direction of the vendored steward skills: steward
pulls this **from** devague and broadcasts it to the rest of the AgentCulture
mesh. The `cite, don't import` policy still holds: downstream repos copy it,
they don't symlink or depend on it. See `docs/skill-sources.md`.

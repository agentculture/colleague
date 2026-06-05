# Operator-driven audit fan-out

> Split a full-repo doc review into small scoped work items, run them in parallel or
> sequence, and synthesize the per-surface reports into one ranked report —
> reliability, not speed.

A full-repo doc-review cannot finish in one work item on a small-context local model:
the single work item accumulates all doc content into one growing context, each model
turn gets slower, and a turn eventually exceeds the per-request timeout. A
bounded-scope audit (one surface) completes.

This recipe uses the **assign-to-workforce** pattern: the operator splits the
surfaces, runs a scoped work item per surface, and synthesizes the results.

## Recipe

1. **Split the doc surfaces into small groups** — e.g. README, each
   `docs/features/*.md`, `CLAUDE.md`, the explain catalog.
2. **For each surface, run a scoped work item:**

   ```bash
   colleague work --command doc-review "<surface>" --repo . --engine <backend> --no-pr
   ```

   Each runs in its own git worktree so they don't collide; run them in parallel
   or in sequence.
3. **Collect each scoped work item's report.**
4. **Synthesize the per-surface reports into ONE ranked report.**

## Why: reliability, not speed

On a vLLM that serializes requests there is **no wall-clock speedup** from
running work items in parallel — but each child work item's context stays small, so no
single request hits the timeout that kills the full-repo work item. The win is
reliability.

## Boundaries

- **`subagents` fan-out is bounded:** `MAX_SUBAGENT_FANOUT=4`, i.e. at most 3
  children + 1 merge child, **one level only** (a batch child cannot spawn another
  batch — nested batches are forbidden in v0).
- **The in-work merge child does a git-branch merge**, which fits file-changing
  work but does **not** fit a read-only text audit (an audit yields findings text,
  not commits). So use **operator-driven fan-out with text synthesis** for audits,
  **not** the in-work `subagents` tool.

## Coverage accounting

When there are more surfaces than you actually run, the synthesized report **must**
name exactly which surfaces were **not** covered. Never silently truncate.

## See also

- [subagents.md](subagents.md) — the in-work child-work-item tool (not suitable for audits).
- [parallel-subagents.md](parallel-subagents.md) — parallel child work items (file-changing work).
- [ask-colleague.md](ask-colleague.md) — the first-party skill that delegates a task to a different mind.

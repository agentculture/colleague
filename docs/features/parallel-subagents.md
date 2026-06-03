# Parallel subagents — run a batch of child drives concurrently

> A backend fans out a batch of scoped child instructions that run concurrently,
> each isolated in its own throwaway git worktree/branch, and a sequential
> merge-subagent integrates them afterward. Opt-in via an operator-controlled
> concurrency width (default 1 = sequential, byte-identical to before).

Subagents now support **parallel children** — instead of one instruction at a
time, a backend can ship a batch of independent tasks that run at the same time.
Each child is **completely isolated** in its own git worktree, so file writes
don't interfere; a **sequential merge-subagent** brings changes back to the main
branch and resolves conflicts via the engine's judgment.

## When to use it

Parallel subagents are useful when:

- An engine identifies a batch of independent sub-tasks that can run in parallel
  (e.g., auditing multiple modules, running multiple small refactors, testing
  variants of an approach).
- The served model supports concurrent requests (so thread-per-child actually
  yields wall-clock speedup instead of just I/O-wait overlap).
- The tasks are narrow enough that conflicts are unlikely or easily resolved.

## How it works

### The `subagents` tool

An engine calls the new `subagents` (plural) loop tool with an array of
instructions:

```python
tool_call(
  name="subagents",
  arguments={
    "instructions": [
      {"task": "audit module_a.py for security issues"},
      {"task": "audit module_b.py for security issues"},
      {"task": "audit module_c.py for security issues"}
    ]
  }
)
```

Each instruction can optionally specify a different `engine` or `model` — the
engine resolves it via the existing config precedence.

### Concurrent isolation

Colleague creates a **separate git worktree** for each child, checked out on its
own branch (`sub/<child-id>`). The child drives entirely within that worktree —
writes, reads, commits — never touching the main working tree. This means:

- Two children writing the same file don't corrupt each other; they commit to
  separate branches.
- A child error doesn't trash the main tree.
- Cleanup is simple: remove the worktree and branch when the child is done.

### The merge phase

After all children finish (successfully or with errors), a **dedicated sequential
merge-subagent** runs:

1. **Git-merges** each child branch (`sub/<child-id>`) into the main branch.
2. **Resolves conflicts** using the engine's judgment (via a `merge` tool call).
3. **Surfaces unresolvable conflicts** in the result — never force-merges or
   silently overwrites a child's work.

The merge phase is **sequential**, so it never races with child writes or other
merges. A clean merge lands; a conflict is surfaced for the caller to see and
handle.

### The single-child `subagent` tool

The existing `subagent` tool (singular) is unchanged — it still takes a single
`instruction` and runs it in-process without isolation. Use it when you don't
need parallelism or per-child worktrees.

## Configuration

### Opt-in via `COLLEAGUE_SUBAGENT_CONCURRENCY`

Parallelism is **opt-in**. Set the environment variable or pass it via
`EngineConfig`:

```bash
COLLEAGUE_SUBAGENT_CONCURRENCY=3 colleague drive "<task>" --repo . --engine vllm-openai
```

**Default:** 1 (sequential, byte-identical to the old behavior — no threads are
ever spawned).

**Effective worker count:** `min(requested, MAX_SUBAGENT_FANOUT - 1)`. With
`MAX_SUBAGENT_FANOUT=4`, a batch is capped at **3 parallel workers** (the 4th
slot is reserved for the merge child).

### Why the operator controls this

The engine **cannot force** parallelism; the operator has sole control. This
means:

- A model can **propose** a batch, but the operator decides if it runs in
  parallel or sequentially.
- On a serializing model-server (one that doesn't truly handle concurrent
  requests), the operator can leave the width at 1 to avoid thread overhead.
- On a capable server, the operator opts in for real wall-clock speedup.

## Bounds

| Parameter | Value | Note |
|-----------|-------|------|
| `MAX_SUBAGENT_DEPTH` | 2 | Recursion cap (unchanged). A subagent cannot spawn its own subagents beyond depth 2. |
| `MAX_SUBAGENT_FANOUT` | 4 | Fan-out cap (unchanged). A batch + merge = at most 4 children per parent. |
| Parallel workers | ≤ 3 | Reserved slot for the merge child (4 - 1). |
| Concurrency width | opt-in, default 1 | `COLLEAGUE_SUBAGENT_CONCURRENCY`. |

## Honest limits

- **Speedup requires a concurrent-serving model.** Real wall-clock reduction
  depends on the served model handling concurrent requests in parallel. If the
  model-server serializes requests under the hood, threads will overlap only
  **I/O wait**, not model compute — so the win is bounded by I/O overlap, not
  speedup. With width=1 (the default), this limitation doesn't apply.

- **Conflicts need conflict resolution.** If two children write the same
  file/section, `git merge` may produce conflicts. The merge-subagent resolves
  them via the engine, but unresolvable conflicts surface in the result and must
  be handled manually (the engine doesn't silently drop or overwrite a child's
  work).

- **Per-subagent git handoff is not supported.** Only the top-level drive hands
  off to a branch/PR. Child drives run in worktrees and merge back; they don't
  open their own PRs.

## Boundary

- **Zero new runtime dependencies.** `concurrent.futures` is part of the Python
  standard library; no third-party packages are added.
- **Threads are confined to `colleague/subagents.py`.** No other colleague
  module imports threading or `concurrent.futures` — enforced by boundary tests.
- **Worktree operations live in `colleague/worktrees.py`.** Git worktree/branch
  lifecycle (subprocess calls) is isolated in a single dedicated module.
- **No asyncio, daemon, or event-loop rewrite.** The parallel phase still uses
  blocking urllib calls per thread; it does not reshape colleague's architecture
  into an async system.

## See also

- **Specification & plan:** [`docs/specs/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md`](../specs/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md) and [`docs/plans/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md`](../plans/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md)
- **Issue #86** — model-gear gains concurrent-request support; subagents
  reclaim that capacity when the operator opts in.
- **The `subagent` tool (singular)** — use it for single children or when
  worktree isolation isn't needed.
- **Outsource skill** — [`docs/features/outsource.md`](outsource.md) — a
  first-party skill that delegates a task to colleague; parallel subagents are
  an internal tool that colleague uses, not what the outsource skill exposes
  directly.

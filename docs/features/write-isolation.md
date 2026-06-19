# write-isolation — a work item never touches your working tree

> `colleague work` / `drive` (and therefore `ask-colleague write --apply`) run
> the bounded tool loop inside a **throwaway git worktree** created at the
> operator's `HEAD` on the `colleague/<id>` branch. Your working tree and
> checked-out branch are never touched; a model self-commit during the loop
> lands on `colleague/<id>`, not on your branch.

Write isolation (#196/#201) is the promise that **delegating to colleague never
silently betrays the caller** — a delegated run can edit, commit, and hand off
without ever sweeping your uncommitted work or mutating the branch you are on.

## How it works (`colleague/worktrees.py` + `colleague/cli/_commands/work.py`)

- `execute_work` (via the `isolate` flag) calls
  `isolation_worktree_add(repo_path, task_id, branch)` to create a worktree at
  `.colleague/worktrees/iso-<id>/`, checked out on a fresh `colleague/<id>`
  branch pointed at the operator's `HEAD`.
- The loop runs **inside that worktree**. A model `run_command` self-commit
  during the loop lands on `colleague/<id>` — `handoff.py` (`head_sha` /
  `base_sha` + `_finish_self_committed`) treats a clean-but-advanced `HEAD` as
  committed work, not "no changes".
- On finish, `isolation_worktree_remove` removes the worktree (the
  `colleague/<id>` branch is kept — it carries the work).
- Two concurrent runs get **distinct** `iso-<id>` worktrees, so they can never
  cross-pollute.

## Degradation

When there is no `HEAD` to isolate from, or the worktree cannot be created
(`head_sha` is `None`), the run **degrades to in-place** — a work item that ran
before always still runs. `session` keeps its in-place interactive path (it
calls `execute_work` without `isolate`).

## Relationship to the dirty-tree guard

The `--allow-dirty` guard (#149) is **kept** as the acknowledgement gate. Because
the isolated run works at `HEAD`, an operator's uncommitted (tracked) edits are
**excluded** from the run — this is clean-`HEAD` isolation. To include
uncommitted work, commit it first.

## Honest limits

- This is isolation, **not a sandbox**: `run_command` still runs arbitrary shell
  (trusted-operator model D2). The [approval gate](approval-gate.md) is the
  policy layer over what executes.
- A run interrupted by `SIGKILL`/OOM/power-loss can leave an orphaned `iso-*`
  worktree — recovered by [`colleague clean`](cleanup-reap.md).

## Key files

- `colleague/worktrees.py` — `isolation_worktree_add` / `isolation_worktree_remove`.
- `colleague/cli/_commands/work.py` — `execute_work` (`isolate` flag, teardown).
- `colleague/handoff.py` — `head_sha` / `base_sha` / `_finish_self_committed`.

## Spec + plan

- [`docs/specs/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md`](../specs/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md)
- [`docs/plans/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md`](../plans/2026-06-16-when-you-delegate-to-colleague-it-never-silently-b.md)

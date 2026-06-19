# An interrupted colleague work item never strands your work: a SIGTERM (a caller's timeout), Ctrl-C, or a cooperative stop commits the model's WIP to the colleague/<id> branch before exiting, and colleague clean reaps the orphaned iso-* worktree a hard kill leaves behind — recovery is one command, never a manual worktree-remove dance.

> An interrupted colleague work item never strands your work: a SIGTERM (a caller's timeout), Ctrl-C, or a cooperative stop commits the model's WIP to the colleague/<id> branch before exiting, and colleague clean reaps the orphaned iso-* worktree a hard kill leaves behind — recovery is one command, never a manual worktree-remove dance.

## Audience

- An agent or human delegating field-work to colleague via ask-colleague write --apply or colleague work (often a fan-out workforce wrapping each run in a caller-side timeout), plus anyone recovering a repo after a run was interrupted.

## Before → After

- Before: A SIGTERM mid-loop bypasses the Python finally teardown in execute_work, so the .colleague/worktrees/iso-<id> worktree, the colleague/<id> branch (at base commit), and the model's uncommitted files are all orphaned. clean does not reap iso-* worktrees, and the branch is checked out in the orphan worktree so git branch -D fails until git worktree remove --force runs first. A near-complete interrupted run loses everything that was not committed.
- After: On SIGTERM/SIGINT and the cooperative stop path, colleague commits whatever is in the iso worktree to colleague/<id> before exiting, so a 90%-done run is inspectable and mergeable. colleague clean reaps orphaned iso-* worktrees (the thing that blocks git branch -D), so a hard-killed leftover is recovered by a single clean.

## Why it matters

- Delegation must never silently betray the caller (the #196/#201 promise) — and the interruption path was the gap: a hard timeout, the natural way a workforce bounds a run, was the exact wrong tool because it stranded complete work as uncommitted files in an orphan worktree.

## Requirements

- On the isolated work path, execute_work installs a SIGTERM+SIGINT handler that commits the iso worktree to colleague/<id> (reusing the worktrees commit primitive) before re-raising/exiting; runtime-owned in the shared work path so every backend inherits it (all-engines rule), restored on exit, never armed on the in-place session path.
  - honesty: The SIGTERM/SIGINT handler is installed only for the isolated work path and removed (restored to the prior disposition) on every exit; the commit is best-effort and idempotent (an empty diff is a no-op, never an error), and a failure to commit never masks the interruption — it still exits.
- The cooperative stop path (flight stop) commits the iso worktree's WIP to colleague/<id> the same way before the work item finishes, so a piloted stop is non-destructive — hooking the existing stop exit, not adding a new control surface.
  - honesty: The cooperative stop already exists (flight stop sets a stop flag the loop reads at a turn boundary); the WIP commit hooks that existing stop exit, so no new daemon/socket/flag is added and the in-place session path is unaffected.
- colleague clean reaps orphaned .colleague/worktrees/iso-* worktrees (git worktree remove --force + prune via worktrees.py) BEFORE the colleague/* branch reap, so a branch checked out in an orphan worktree becomes deletable; scoped strictly to iso-* under .colleague/worktrees, never an unrelated worktree, with --dry-run honored.
  - honesty: The iso-* worktree reap is scoped strictly to .colleague/worktrees/iso-* paths git reports under this repo (never a sub/* child or an unrelated worktree), reuses the worktrees.py subprocess boundary (no new subprocess consumer), and --dry-run reports without changing anything — matching clean's existing contract.

## Honesty conditions

- The announcement is the literal verifiable outcome: an interrupted run's work lands on colleague/<id> and clean reaps the orphan worktree — both checkable via the success_signal.
- The audience is real: #222 was filed by a fan-out-workforce caller (ec2bedrock-cli) that wrapped each write --apply in a caller-side timeout.
- The before_state is reproducible: a timeout (SIGTERM) on colleague work leaves .colleague/worktrees/iso-<id> + a colleague/<id> branch at base + untracked files, because execute_work's finally-based teardown does not run on SIGTERM.
- The after_state is checkable by the success_signal: a committed branch and no orphan worktree after an interrupt, and a single clean after a hard kill.
- The gap is specifically the interruption path; #196/#201 isolation already protects the operator's working tree on the success path.
- The boundary is honest: a SIGKILL inside the commit stays uncatchable (the same residual #162 documents), and no new runtime dep/daemon/thread is added — signals are stdlib, git stays in the worktrees.py subprocess boundary.
- The success_signal is observable with git worktree list + git log colleague/<id> after a wrapped 'timeout' run and after 'colleague clean'.

## Success signals

- A wrapped 'timeout 5 colleague work <task>' leaves a committed colleague/<id> branch whose diff carries the partial work (inspectable, mergeable) and NO orphan worktree; a SIGKILLed run's leftover .colleague/worktrees/iso-* worktree plus its branch are reaped by a single 'colleague clean', with git worktree list clean afterward.

## Scope / boundaries

- Not a sandbox and not a durability guarantee: a SIGKILL/OOM/power-loss inside the commit itself is uncatchable (git/filesystem durability, matching #162's honest limit) — that residual wedge is exactly what clean now recovers by also reaping iso-* worktrees. No daemon, no heartbeat thread, no new runtime dep; signal handling is stdlib, the git commit stays inside the worktrees.py subprocess boundary.

## Decisions

- In scope from the secondary-friction note: a docs fix stating a hard external timeout is the wrong tool to bound a run (it strands WIP) and that --watch + cooperative stop is the documented graceful path; the heartbeat/--deadline surface is parked as a follow-up.

## Open / follow-up

- A heartbeat/elapsed progress signal and a soft --deadline flag (graceful commit at the deadline instead of a hard external SIGTERM) — a larger surface that would let callers budget time; deferred so this spec stays the two interruption-safety asks.

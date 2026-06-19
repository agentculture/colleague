# Build Plan — An interrupted colleague work item never strands your work: a SIGTERM (a caller's timeout), Ctrl-C, or a cooperative stop commits the model's WIP to the colleague/<id> branch before exiting, and colleague clean reaps the orphaned iso-* worktree a hard kill leaves behind — recovery is one command, never a manual worktree-remove dance.

slug: `an-interrupted-colleague-work-item-never-strands-y` · status: `exported` · from frame: `an-interrupted-colleague-work-item-never-strands-y`

> An interrupted colleague work item never strands your work: a SIGTERM (a caller's timeout), Ctrl-C, or a cooperative stop commits the model's WIP to the colleague/<id> branch before exiting, and colleague clean reaps the orphaned iso-* worktree a hard kill leaves behind — recovery is one command, never a manual worktree-remove dance.

## Tasks

### t1 — Add worktrees.py primitives: commit_iso_worktree_wip (stage+commit an iso worktree's WIP to its colleague/<id> branch, empty diff is a no-op) and reap_orphaned_iso_worktrees/list (enumerate+remove .colleague/worktrees/iso-* via git worktree remove --force + prune)

- covers: h1, h3, h9
- acceptance:
  - commit_iso_worktree_wip stages and commits all changes in an iso worktree to its colleague/<id> branch; a clean worktree (empty diff) returns without creating a commit and never raises (idempotent, best-effort)
  - reap_orphaned_iso_worktrees enumerates only .colleague/worktrees/iso-* worktrees git reports under the repo and removes each via git worktree remove --force + prune; a sub/* child or unrelated worktree is never selected; a list/dry-run mode returns paths without removing
  - tests/test_boundary.py still passes: the new git calls live in worktrees.py (the sanctioned subprocess boundary), no new subprocess consumer is introduced

### t2 — execute_work installs SIGTERM+SIGINT handlers on the ISOLATED work path that commit the iso worktree to colleague/<id> via the worktrees primitive before re-raising/exiting (restored on every exit, never armed on the in-place session path); and the cooperative flight-stop exit commits the iso worktree WIP the same way

- depends on: t1
- covers: c1, c3, c4, c5, c6, c8, c9, h1, h2, h6, h7, h8
- acceptance:
  - On the isolated work path, execute_work installs SIGTERM and SIGINT handlers that commit the iso worktree to colleague/<id> via the worktrees primitive before re-raising/exiting; handlers are restored to their prior disposition on every exit path (success, error, interrupt)
  - Handlers are NOT installed on the in-place session path (execute_work called without isolate); a session run's signal disposition is byte-identical to before
  - A simulated SIGTERM/SIGINT mid-loop leaves the partial work committed on colleague/<id> (git log shows the WIP commit) instead of orphaned uncommitted files; a commit failure does not mask the interrupt (the process still exits)
  - The cooperative flight-stop exit commits the iso worktree WIP to colleague/<id> the same way before the work item finishes; no new control surface/flag/daemon is added
  - Runtime-owned/all-engines: behaviour fires identically for mock and vllm-openai; tests/test_e2e_mock.py TaskResult shape is unchanged

### t3 — colleague clean reaps orphaned .colleague/worktrees/iso-* worktrees (via the worktrees reap helper) BEFORE the colleague/* branch reap, so a branch checked out in an orphan iso worktree becomes deletable; scoped strictly, --dry-run honored

- depends on: t1
- covers: c1, c4, c7, c10, h3, h4, h10
- acceptance:
  - clean reaps orphaned iso-* worktrees BEFORE the colleague/* branch reap, so a branch checked out in an orphan iso worktree is deletable in the same clean run; git worktree list is clean afterward
  - clean --dry-run reports the iso-* worktrees it would remove without removing them or deleting any branch (matches clean's existing contract)
  - The reap is scoped strictly to .colleague/worktrees/iso-* under the repo; a decoy unrelated/sub worktree survives a clean (test asserts it)
  - clean.py imports the worktrees reap helper and never touches subprocess itself (boundary test holds)

### t4 — Docs fix (the in-scope decision): state that a hard external timeout (SIGTERM) is the wrong tool to bound a run because it strands WIP, and that colleague work --watch + a cooperative flight stop is the documented graceful way to bound a run; note the heartbeat/--deadline surface as a parked follow-up

- covers: c2, c5, c6, h5
- acceptance:
  - A docs section (write-isolation / ask-colleague feature doc) states a hard external timeout (SIGTERM) is the wrong tool to bound a run (it strands WIP) and that --watch + cooperative flight stop is the graceful path; the parked heartbeat/--deadline follow-up is noted as not-yet-built
  - markdownlint-cli2 passes on the changed docs file; no false claim of a non-existent flag (no --deadline, no --no-hooks)

### t5 — Post-implementation validation (wave 2): after t2/t3 land, verify the success_signal end-to-end and confirm the t4 docs accurately describe the shipped behaviour (no drift, no claim of a non-existent flag)

- depends on: t2, t3, t4
- covers: c1, c7, h4, h10
- acceptance:
  - End-to-end: a wrapped 'timeout 5 colleague work <task>' leaves a committed colleague/<id> branch carrying the partial work and NO orphan worktree; a SIGKILLed run's leftover iso-* worktree + branch are reaped by a single 'colleague clean', git worktree list clean afterward
  - The t4 docs are verified against the shipped behaviour: every described command/flag exists (no --deadline / --no-hooks claimed as built) and the graceful-stop path (--watch + flight stop) works as documented
  - Full suite green (uv run pytest -n auto), boundary + zero-deps + e2e-mock-shape tests all pass after the feature lands

## Risks

- [follow_up] Heartbeat/elapsed progress signal + a soft --deadline flag (graceful commit at the deadline instead of a hard external SIGTERM) — a larger time-budgeting surface deferred so this plan stays the two interruption-safety asks plus the clean reap

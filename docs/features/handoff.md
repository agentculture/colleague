# Git/PR handoff

> After a drive edits the tree, capture the change as a branch + commit, and —
> when allowed — push and open a pull request.

The handoff (`colleague/handoff.py`) is the last leg of a drive: it turns the
working-tree changes a backend made into a reviewable artifact. The sequence is
**branch → commit → push → `gh pr create`**, but every step past the commit is
gated so offline and CI runs never reach the network.

## What it does

1. Runs `git status --porcelain`. If the tree is clean, there is nothing to hand
   off — it returns early with `branch=None` and the note `no changes to hand
   off`. This is the authority on whether work happened, so edits made via
   `run_command` (which the loop's own change-tracking can't see) are still
   captured.
2. Creates/resets a branch named `colleague/<task-id>`, stages everything
   (`git add -A`), and commits with the message `colleague: <instruction>`.
3. If — and only if — PR creation is allowed (see gating), pushes the branch and
   runs `gh pr create --fill --base <base> --title <message>`.

The branch name and `pr_url` land on the `TaskResult`; `pr_url` is `None`
whenever the run stays local.

## Gating

The core predicate is `should_open_pr = open_pr AND has_remote AND gh_available`:

- `--no-pr` sets `open_pr=False` → local commit only.
- No git remote configured → local commit only.
- `gh` CLI not on `PATH` → local commit only.

In every local-only case the handoff commits and returns `pr_url=None` without
ever pushing — so offline and CI drives never touch the network.

## Failure degrades, never raises

A push or PR-creation failure degrades to the same local-commit outcome rather
than aborting the drive. The result note stays honest about what actually
happened — it distinguishes a push that already landed (`pushed branch; PR
creation failed: …`) from one that never left (`local commit only (push failed:
…)`), so the note never contradicts `result.pushed`.

## Usage

Handoff is driven by `colleague drive` / `colleague session`; there is no
standalone handoff verb.

```bash
colleague drive "..." --repo . --engine vllm-openai            # branch + PR (if gated on)
colleague drive "..." --repo . --engine mock --no-pr           # local commit only
colleague drive "..." --repo . --engine mock --base develop    # PR against develop
```

## Key files

- `colleague/handoff.py` — `handoff()`, `should_open_pr()`, `HandoffResult`.

## See also

- [drive-and-loop.md](drive-and-loop.md) — `branch` / `pr_url` on `TaskResult`.
- [doctor.md](doctor.md) — the environment check-group verifies `git` (error)
  and `gh` (warning) are on `PATH`, the handoff prerequisites.

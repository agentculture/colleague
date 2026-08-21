# cleanup-reap — `colleague clean` self-heals a repo a crashed run left wedged

> `colleague clean` reaps the residue a crashed or interrupted `work` run can
> leave behind: dangling `colleague/<id>` branches (including a corrupt tip that
> breaks `git fetch`), 0-byte `.colleague/` artifacts, and a dangling `last_work`
> pointer. Scoped strictly to `colleague/*` refs + `.colleague/` artifacts —
> never an unrelated branch.

The cleanup/reap verb (#162) is the recovery path for the residual wedge that
[write isolation](write-isolation.md) and [handoff](handoff.md) cannot prevent: a
`SIGKILL`/OOM/power-loss inside a commit is uncatchable, and the leftover can
break ordinary git operations.

## What it reaps

- **Branches** — `list_colleague_branches` classifies each `colleague/*` tip as
  corrupt / merged / old / live (via `for-each-ref` + `cat-file -t`);
  `reap_colleague_branches` deletes via `git update-ref -d` (which works even on a
  corrupt tip). **Corrupt is always reaped**; `--merged` / `--older-than DAYS` are
  opt-in.
- **Artifacts** — `reap_artifacts` removes 0-byte `.colleague/` artifacts + a
  dangling `last_work`, **never** a non-empty (gradable) one.
- **Finished-task ledgers** (#411 t19) — an agents-mode run writes its task
  ledger at the **operator** repo (`.colleague/ledger/<id>.jsonl`, rooted at
  `task.flight_repo_path`, the flight-plane precedent), never inside the
  throwaway `work`/`drive` worktree — so the file outlives the worktree and
  `git status` stays clean (the repo's own `/.colleague/*` ignore rule).
  `reap_finished_ledgers` removes a ledger **only** when its task is provably
  over: the artifact `<id>.*.json` parses with a terminal status (`ok` /
  `incomplete` / `error`), or the task is orphaned (its iso liveness marker
  names a dead pid, or this same `clean` just reaped its iso worktree). A
  **live** task — a recent flight id or an alive liveness marker — is never
  touched, and a ledger with no artifact and no liveness opinion is kept (an
  in-place run stamps no marker; absence of evidence is not death). Honest
  consequence: a `work --continue` of a cut run whose ledger `clean` already
  reaped seeds from the artifact's prose recap instead (the documented
  no-ledger degrade).
- **Loose objects** — `empty_loose_objects` *reports* 0-byte `.git/objects` files
  and suggests `git prune`; it **never deletes** them (conservative by design).

## Where the git-touching code lives

The reap helpers live in `colleague/handoff.py` (the sanctioned subprocess
consumer), so `clean.py` and the `doctor` stale-ref check import them and never
touch `subprocess` themselves.

## Surfaces

- `colleague clean` (`--dry-run` reports without changing anything).
- The `ask-colleague clean` skill verb.
- An **advisory** `doctor` stale-ref check
  (`colleague/oilcheck/stale_refs.py`, `warning` severity — flags a wedged repo,
  never flips report health).

## Honest limits

- Scoped strictly to `colleague/*` refs and `.colleague/` artifacts (incl.
  `.colleague/ledger/*.jsonl`, never a nested or non-`.jsonl` file).
- Conservative with `.git/objects` — reports, never deletes.

## Key files

- `colleague/cli/_commands/clean.py` — the verb.
- `colleague/handoff.py` — `list_colleague_branches` / `reap_colleague_branches` /
  `empty_loose_objects` / `reap_finished_ledgers`.
- `colleague/artifact.py` — `reap_artifacts`.
- `colleague/oilcheck/stale_refs.py` — the advisory doctor check.

## Spec + plan

- [`docs/specs/2026-06-06-a-crashed-colleague-work-no-longer-wedges-your-rep.md`](../specs/2026-06-06-a-crashed-colleague-work-no-longer-wedges-your-rep.md)
- [`docs/plans/2026-06-06-a-crashed-colleague-work-no-longer-wedges-your-rep.md`](../plans/2026-06-06-a-crashed-colleague-work-no-longer-wedges-your-rep.md)

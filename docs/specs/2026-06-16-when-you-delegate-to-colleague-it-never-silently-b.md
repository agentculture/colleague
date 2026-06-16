# When you delegate to colleague, it never silently betrays you: write --apply lands its own changes on an isolated colleague/<id> branch (never your branch, never cross-polluted), and review/explore always hand back the verdict they found (never an empty or budget-starved no-op)

> When you delegate to colleague, it never silently betrays you: write --apply lands its own changes on an isolated colleague/<id> branch (never your branch, never cross-polluted), and review/explore always hand back the verdict they found (never an empty or budget-starved no-op)

## Audience

- operators and agents who delegate scoped work to colleague via 'ask-colleague write --apply'/'review'/'explore' or 'colleague work' — especially parallel fan-out, where a different mind works the repo and the caller reviews+merges the colleague/<id> branch

## Before → After

- Before: write --apply runs IN-PLACE in the caller's repo: a model self-commit (git add/commit during the run) lands on the operator's checked-out branch with NO drive branch (#196), concurrent runs sweep each other's tracked edits onto the wrong branch (#201), and an incomplete run leaves loose half-applied files with no branch; meanwhile review can finish with empty args (status ok, no review text — #202) or spend its whole step budget reading a large diff and return incomplete with no verdict (#197)
- After: write --apply ALWAYS runs worktree-isolated and lands ONLY its own task's changes on a fresh colleague/<id> branch, never advancing the operator's checked-out branch or HEAD even when the model self-commits, and never cross-polluting a concurrent run; review/explore ALWAYS return a non-empty verdict or fail loudly — an empty/whitespace finish is never a silent success, and a big-diff review reserves enough budget to synthesize a verdict

## Why it matters

- the colleague/<id>-branch-then-merge contract IS colleague's isolation+review gate and its whole value as a delegated 'second mind'; a silent betrayal — a commit on the wrong branch, a review that delivers nothing, lost findings (one #202 case lost a real off-by-one bug) — destroys trust in delegation, the exact reflex CLAUDE.md tells callers to reach for

## Requirements

- write --apply runs in an isolated git worktree at the operator's HEAD (the SAME machinery review/explore already use), so the model works a private tree; the operator's working tree and checked-out branch are structurally untouchable, and the colleague/<id> branch stays visible+mergeable from the main repo via the shared .git
  - honesty: the operator's tree+branch are provably unmodifiable by the run (every model write/commit happens in the worktree), and the colleague/<id> branch is still listed by 'git branch' and mergeable from the main repo after the run
- a model self-commit during write --apply is reaped onto the colleague/<id> branch, never left on the operator's branch: the handoff detects 'the agent already committed' (a clean tree is no longer read as 'no changes to hand off') and still produces a recoverable branch (#196)
  - honesty: a write --apply whose model itself runs 'git commit' still produces a colleague/<id> branch containing that commit, with the operator's branch HEAD unchanged (#196 repro passes)
- an empty/whitespace finish on review/explore is never a silent success: the runtime folds the gathered findings (last-substantive/scratchpad) into the summary or fails loudly — extending the #191 forced-synthesis safety net to the explicit-finish (_EXIT_FINISHED) path for read-only verbs (#202)
  - honesty: a review whose model calls finish with empty/whitespace args returns either a non-empty verdict folded from what it read OR a non-zero error — never 'status ok' with an empty summary (#202 repro passes)
- a read-heavy review/explore reliably yields a verdict on a large diff instead of spending its whole budget reading — review reserves synthesis capacity so a 100+-file review returns findings or a loud, actionable partial naming a concrete larger budget (#197)
  - honesty: a review of a large (100+-file) diff returns a non-empty verdict within budget, or a loud partial that names a concrete larger --max-steps — never a silent 'incomplete, no findings' (#197 repro passes)

## Honesty conditions

- every documented silent-betrayal mode has a regression test that FAILS on today's main and PASSES after — #196 (self-commit→operator branch), #201 (concurrent cross-pollute + incomplete strand), #202 (empty finish), #197 (verdict-less big-diff review) — 'never betrays' is verified, not asserted
- the same isolation guarantee serves both callers with no divergence: the interactive ask-colleague.sh write --apply path and the direct 'colleague work --apply' path land identical worktree-isolated branches
- each before_state failure is first reproduced by a test on current main: a self-committing write --apply advances the operator branch; two concurrent runs cross-pollute; an empty finish returns status ok; a big-diff review returns incomplete with no verdict
- after a write --apply run (with OR without a model self-commit) 'git rev-parse HEAD' and the current branch name are byte-identical to pre-run, and the colleague/<id> branch's diff contains exactly the run's own changed files
- the success summary can never claim a committed change without pointing at a recoverable colleague/<id> branch — the #196 'reported success, no branch' contradiction is structurally impossible after the fix
- the disjoint-parallel-branches test and the non-empty-verdict review test both run in CI and fire identically for mock and vllm-openai (e2e shape test / all-engines rule holds)
- no new pyproject runtime dependency (zero-deps guard holds), no socket/daemon opened, and a write --apply with no self-commit / a review with no stall is byte-identical (strict no-op) to before

## Success signals

- a parallel two-task 'write --apply' fan-out in one repo yields two colleague/<id> branches whose diffs are DISJOINT (neither contains the other's files) and leaves the operator's branch+HEAD byte-identical; a review of a 100+-file diff (or a model that calls finish with empty args) always returns a non-empty verdict or a loud non-zero error, never 'status ok' with no text

## Scope / boundaries

- NOT an execution sandbox, NOT a multi-backend router, NOT a daemon/socket; does not change the default write PREVIEW (read-only) behavior; adds NO runtime dependency (reuses worktrees.py + handoff.py, stays zero-deps/all-engines); chunked-per-file diff aggregation is one OPTION for #197, not a required mechanism

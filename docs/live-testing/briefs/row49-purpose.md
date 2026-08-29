# Row 49 brief — decomposable survey, purpose-tool delegation observed (n=3)

Pre-registered for `docs/live-testing.md` row 49 (plan t12, spec
`docs/specs/2026-08-28-purpose-tools-associate-seat.md`, covers c11/h11).
The brief is the row-48 brief verbatim (the same task text pasted into
`colleague work`); only the arm and the pass bar change — the branch arm
offers the purpose tools (`code_survey` among them) instead of raw
`subagent`/`subagents`, and the main baseline is RE-RUN on `e589451`
(v1.65.1), never reused from row 48's `4e814c8` numbers.
Run this verbatim n=3 times on the branch arm, and the same brief n=3 times
on the main baseline (main @ `e589451` RE-RUN) for the ratio.

## Pass bar (committed BEFORE the run)

- purpose calls ≥ 1 on ≥ 2 of 3 runs (a purpose-tool step — `code_survey`
  among them — in the artifact; delegation is observed, never forced)
- turns ≤ 1.0× and wall ≤ 1.2× vs the same brief on main @ `e589451`
  RE-RUN n=3 (computed by `scripts/compare_arms.py --bar-wall 1.2
  --bar-turns 1.0` from artifact stats, never from prose; the
  `delegations` column = purpose-tool calls)
- a miss is written as a miss

## The brief (paste into `colleague work`)

```text
Survey three modules, then change one.

1. Survey the three modules `alpha`, `beta` and `gamma` in this repo —
   their public interfaces, how they call each other, and where the
   duplication lives. If the survey is large, hand one or more of the
   read-only surveys to scout children (subagent / subagents) and review
   their digests before acting — or do it yourself; the choice is yours.

2. Then change exactly one of the three modules to remove the duplication
   you found, keeping its public interface stable. Make the smallest edit
   that does it and say which module you changed and why.
```

## After the run — record (never fill before)

per-run purpose-call count, scout served model, turns and wall-clock; the
delegation-rate column from `scripts/compare_arms.py` output; the memory
distill counters (attempts/validated/detached) and the distill child's
served model from the artifact.

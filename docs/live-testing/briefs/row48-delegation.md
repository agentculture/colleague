# Row 48 brief — decomposable survey, delegation observed (n=3)

Pre-registered for `docs/live-testing.md` row 48 (plan t7, spec
`docs/specs/2026-08-28-web-scout-associate.md`, covers c14/h11/c32/h21).
Run this verbatim n=3 times on the branch arm, and the same brief n=3 times
on the main baseline (main @ `4e814c8`) for the ratio.

## Pass bar (committed BEFORE the run)

- delegation ≥ 1 on ≥ 2 of 3 runs (a `subagent`/`subagents` step in the
  artifact; delegation is observed, never forced)
- turns ≤ 1.0× and wall ≤ 1.2× vs the same brief on main @ `4e814c8`
  (computed by `scripts/compare_arms.py` from artifact stats, never from
  prose; the `delegations` column is the tracked delegation rate)
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

per-run delegation count, scout served model, turns and wall-clock; the
delegation-rate column from `scripts/compare_arms.py` output.

# Build Plan — colleague fans a large read-only audit out across scoped subagents and aggregates their findings into one ranked report — past the single-drive context wall

slug: `colleague-fans-a-large-read-only-audit-out-across` · status: `exported` · from frame: `colleague-fans-a-large-read-only-audit-out-across`

> colleague fans a large read-only audit out across scoped subagents and aggregates their findings into one ranked report — past the single-drive context wall

## Tasks

### t1 — Make the doc-review command reliably scopeable to a single surface so a fanned-out per-surface drive completes

- covers: c4, c8, h5, h6, h10
- acceptance:
  - running 'colleague drive --command doc-review <surface> --engine mock --no-pr' audits only the named surface and the drive calls finish with a report
  - on budget/timeout exhaustion the scoped drive finishes with an INCOMPLETE report naming covered vs remaining surfaces, never a silent no-finish
  - a surface that previously contributed to a timed-out full-repo drive completes when run as its own scoped drive (empirical proof recorded)

### t2 — Document the operator-driven audit fan-out recipe (assign-to-workforce) with honest coverage accounting and the bounded-fan-out boundaries

- depends on: t1
- covers: c1, c2, c3, c5, c6, c7, c10, h2, h3, h4, h7, h8, h9
- acceptance:
  - docs/features/audit-fanout.md describes the recipe end to end: split surfaces -> run N scoped doc-review drives in parallel worktrees -> synthesize one ranked report
  - the doc states the reliability-not-speed rationale (zero wall-clock gain on a serializing server) and the boundaries: in-drive fan-out is one-level / <=3 children + 1 merge, nested batches forbidden, git-merge does not fit a read-only text audit
  - the coverage-accounting section requires the synthesized report to name exactly which surfaces were NOT covered when the surface set exceeds what was run (no silent truncation)
  - linked from the README feature table and docs/features/README.md index

## Risks

- [unknown_nonblocking] the exact surface-splitting heuristic (per-file vs per-doc-group, sizing to stay under the per-request timeout) is left to operator judgment in v0; a built-in splitter is a follow-up

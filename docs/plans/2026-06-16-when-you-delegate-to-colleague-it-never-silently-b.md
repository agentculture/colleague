# Build Plan — When you delegate to colleague, it never silently betrays you: write --apply lands its own changes on an isolated colleague/<id> branch (never your branch, never cross-polluted), and review/explore always hand back the verdict they found (never an empty or budget-starved no-op)

slug: `when-you-delegate-to-colleague-it-never-silently-b` · status: `exported` · from frame: `when-you-delegate-to-colleague-it-never-silently-b`

> When you delegate to colleague, it never silently betrays you: write --apply lands its own changes on an isolated colleague/<id> branch (never your branch, never cross-polluted), and review/explore always hand back the verdict they found (never an empty or budget-starved no-op)

## Tasks

### t1 — Worktree-isolate write --apply and reap model self-commits onto colleague/<id> (runtime: colleague/handoff.py + colleague/worktrees.py)

- covers: c8, h8, c9, h9, c4, h4, c5, h5
- acceptance:
  - write --apply runs the bounded loop inside an isolated git worktree created at the operator's HEAD (reusing colleague/worktrees.py); after the run 'git rev-parse HEAD', the current branch name, and the operator working-tree status are byte-identical to before
  - a write --apply whose model itself runs git add/commit still yields a colleague/<id> branch containing that commit and the operator's branch HEAD is unchanged (#196 repro: red on main, green after)
  - the colleague/<id> branch diff contains exactly the run's own changed files, and the success summary can never report a committed change without a recoverable branch (the #196 'success, no branch' state is unreachable)

### t2 — Regression tests: #196/#201 repros (self-commit, concurrent cross-pollute, incomplete strand) red-on-main/green-after; prove disjoint branches + clean operator tree (tests/test_write_apply_isolation.py)

- depends on: t1
- covers: c3, h3
- acceptance:
  - a test reproduces each #196/#201 betrayal on current main (self-commit advances the operator branch; two concurrent in-place runs cross-pollute; an incomplete run strands loose files) — red before t1, green after
  - two concurrent write --apply runs in one repo produce colleague/<id> branches whose diffs are DISJOINT (neither contains the other's files)
  - an incomplete write --apply run (hits --max-steps before finish) leaves the operator working tree clean — a clearly-marked partial branch or nothing, never loose half-applied files in --repo

### t3 — Guard an empty/whitespace finish on read-only verbs (review/explore) so it is never a silent ok (colleague/loop.py: extend the synthesis net to _EXIT_FINISHED)

- covers: c10, h10
- acceptance:
  - a review/explore run whose model calls finish with empty/whitespace args returns a non-empty verdict folded from gathered findings (last-substantive/scratchpad) OR a non-zero error — never status ok with an empty summary (#202 repro: red on main, green after)
  - the guard fires on the explicit _EXIT_FINISHED path for read-only verbs, extending the #191 forced-synthesis net; a finish carrying a real summary stays byte-identical to before

### t4 — Reserve synthesis budget so a read-heavy review yields a verdict on a large diff instead of dying mid-read (colleague/loop.py)

- depends on: t3
- covers: c11, h11
- acceptance:
  - a review of a large (100+-file) diff that would spend its whole budget reading returns a non-empty verdict within budget OR a loud partial naming a concrete larger --max-steps — never a silent 'incomplete, no findings' (#197 repro)
  - review reserves synthesis capacity so the verdict-producing turn is not starved by context-reading; the mechanism is documented and a no-stall review is byte-identical to before

### t5 — Wire both callers to the runtime isolation + scale review steps + retire --allow-dirty for --apply (.claude/skills/ask-colleague/scripts/ask-colleague.sh)

- depends on: t1, t4
- covers: c2, h2
- acceptance:
  - the interactive ask-colleague write --apply path and direct 'colleague work --apply' land identical worktree-isolated colleague/<id> branches — isolation lives in the runtime, the shell adds no divergent path (h2)
  - --allow-dirty is retired/no-op for --apply (clean-HEAD isolation only) with a clear message telling the caller to commit WIP first (q1)
  - review's --max-steps scales with diff size (or documents the reserved-synthesis default) so the headline review reflex converges on a big diff

### t6 — Cross-cutting verification: all-engines shape (mock+vllm), zero-deps guard, strict no-op, and the four-betrayal integration assertion (tests)

- depends on: t1, t3, t4
- covers: c6, h6, c7, h7, c1, h1
- acceptance:
  - the parallel-disjoint-branches test and the non-empty-verdict review test run in CI and pass identically for engine mock and vllm-openai (e2e shape test / all-engines rule)
  - the zero-deps guard still passes (no new pyproject runtime dependency) and no socket/daemon is opened (c7/h7)
  - a write --apply with no self-commit and a review with no stall are byte-identical (strict no-op) to before; all four betrayal repros are green (c1/h1)

### t7 — Docs + CHANGELOG + version bump (minor): CLAUDE.md, docs/features/ask-colleague.md, CHANGELOG.md, pyproject.toml, colleague/__init__.py

- depends on: t2, t5, t6
- acceptance:
  - CLAUDE.md (handoff/write-apply + review-delivery bullets) and docs/features/ask-colleague.md accurately describe worktree-isolation + empty-finish guard + review synthesis budget + --allow-dirty retirement (doc-test alignment)
  - CHANGELOG.md has a Keep-a-Changelog entry and pyproject.toml + colleague/__init__.py are version-bumped (minor) so the version-check CI job passes

## Risks

- [unknown_nonblocking] self-commit isolation mechanism (t1): run on a detached HEAD in the worktree, pre-create+checkout the colleague/<id> branch, or cherry-pick+reset after — pick during build (task t1)
- [unknown_nonblocking] incomplete write --apply handling (t1): land a clearly-marked partial colleague/<id> branch vs leave nothing — operator tree must stay clean either way (task t1)
- [unknown_nonblocking] big-diff review verdict mechanism (t4): auto-scale --max-steps by diff size, hold a fixed synthesis reserve, or chunk-and-aggregate — multiple viable, choose during build (task t4)
- [follow_up] --allow-dirty retirement for --apply (t5) is a user-facing behavior change; needs a clear deprecation message + CHANGELOG note (task t5)

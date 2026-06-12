# Build Plan — ask-colleague.sh is correct at its origin: when colleague is not on PATH it resolves the local-dev CLI against the --repo target (not just $PWD), it propagates colleague's documented tri-state exit code (0/1/2) end-to-end through a drive, and it never prints an artifact path that points into a soon-deleted worktree — so the downstreams that vendor it verbatim (steward, agentirc, culture) can re-vendor instead of carrying divergences.

slug: `ask-colleague-sh-is-correct-at-its-origin-when-col` · status: `exported` · from frame: `ask-colleague-sh-is-correct-at-its-origin-when-col`

> ask-colleague.sh is correct at its origin: when colleague is not on PATH it resolves the local-dev CLI against the --repo target (not just $PWD), it propagates colleague's documented tri-state exit code (0/1/2) end-to-end through a drive, and it never prints an artifact path that points into a soon-deleted worktree — so the downstreams that vendor it verbatim (steward, agentirc, culture) can re-vendor instead of carrying divergences.

## Tasks

### t1 — #181: resolve_colleague() honors --repo for the uv local-dev fallback

- covers: c3, h2
- acceptance:
  - With 'colleague' absent from PATH, --repo pointing at a colleague checkout, and uv present, the wrapper resolves and runs (e.g. 'clean --dry-run') instead of exiting 2
  - Resolution factors a '_colleague_via_uv <dir>' helper tried against $PWD then the resolved $REPO, invoking 'uv run --project <dir> colleague' so cwd need not be inside the checkout
  - When 'colleague' is on PATH the uv helper is never reached and COLLEAGUE=(colleague) is byte-identical to today

### t2 — #180 finding-1: propagate colleague's tri-state drive exit code (0/1/2) end-to-end

- depends on: t1
- covers: c4, c12, h3, h5
- acceptance:
  - A drive env/setup failure (colleague exits 2 emitting a partial TaskResult JSON on stdout, --json mode) propagates as exit 2 through the wrapper; a user-input failure as 1; success as 0
  - Parse-level failures in print_result (empty stdout / unparseable JSON) still exit 2
  - The real drive rc is captured at each call site WITHOUT the 'local out; out=$(...)' rc-masking gotcha (declaration split from assignment, guarded by set +e/set -e) and threaded into print_result via ASK_COLLEAGUE_DRIVE_RC
  - print_result exit precedence is: 0 on status==ok; else 2 on its own parse failure; else the threaded rc when 1 or 2; else 1 — and the digest-on-failure still prints to stderr

### t3 — #180 finding-2: never print an 'artifact:' line into a soon-deleted worktree

- depends on: t2
- covers: c5, h4
- acceptance:
  - A 'write --apply' run still prints its real 'artifact:' path (drive ran in $REPO)
  - A preview run, and a read-only run whose _preserve_artifact did not land, print NO 'artifact:' line
  - The print is gated on the existing ASK_COLLEAGUE_GRADABLE=='1' flag (unified with the grade: hint) — no new survives-signal is introduced

### t4 — Black-box regression tests for all three fixes in tests/test_ask_colleague_skill.py

- depends on: t3
- covers: c1, c9, h1, h10
- acceptance:
  - New cases install a fake 'colleague' stub on PATH (as the existing worktree/feedback/preserve cases do) and need no live model
  - Cases assert: (a) colleague-hidden-from-PATH + --repo-at-checkout resolves via uv and runs; (b) a stub env failure (exit 2 + partial JSON) yields wrapper exit 2 and a stub user-input failure yields exit 1; (c) a preview / non-preserved run prints no 'artifact:' line
  - The existing happy-path stdout assertions still pass (wrapper-only: a successful drive's stdout is byte-identical)

### t5 — Version bump + CHANGELOG + cross-reference the three downstream issues

- depends on: t3
- covers: c2, c6, c7, c8, h6, h7, h8, h9
- acceptance:
  - pyproject.toml + CHANGELOG.md bumped (patch) so the version-check CI gate passes
  - The CHANGELOG entry states the change is wrapper-only, names #180 + #181 and the three downstreams (steward/agentirc/culture), and notes #179 is re-vendored via the operator's ../rollout-cli (no repo change)
  - The final diff is confined to ask-colleague.sh + tests/test_ask_colleague_skill.py + CHANGELOG.md/pyproject.toml — colleague's Python CLI, prompts/*.md, SKILL.md, and .markdownlint-cli2.yaml are untouched

## Risks

- [unknown_nonblocking] The regression tests assert tri-state exit propagation against a FAKE colleague stub; the real CLI's 'exit 2 + partial TaskResult JSON on stdout' path is verified by code-reading (_errors.py:34-37, work.py:314) but not exercised live in CI. (task t4)

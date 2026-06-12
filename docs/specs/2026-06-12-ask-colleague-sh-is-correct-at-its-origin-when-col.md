# ask-colleague.sh is correct at its origin: when colleague is not on PATH it resolves the local-dev CLI against the --repo target (not just $PWD), it propagates colleague's documented tri-state exit code (0/1/2) end-to-end through a drive, and it never prints an artifact path that points into a soon-deleted worktree — so the downstreams that vendor it verbatim (steward, agentirc, culture) can re-vendor instead of carrying divergences.

> ask-colleague.sh is correct at its origin: when colleague is not on PATH it resolves the local-dev CLI against the --repo target (not just $PWD), it propagates colleague's documented tri-state exit code (0/1/2) end-to-end through a drive, and it never prints an artifact path that points into a soon-deleted worktree — so the downstreams that vendor it verbatim (steward, agentirc, culture) can re-vendor instead of carrying divergences.

## Audience

- The three downstream repos that vendor ask-colleague verbatim (steward, agentirc, culture), the agents/automation that call the wrapper and branch on its exit code, and colleague maintainers.

## Before → After

- Before: Today the uv fallback walks only $PWD (a --repo checkout is missed -> 'error: colleague CLI not found', exit 2); every drive call discards rc with '|| true' and print_result collapses every non-ok status to 1; a preview prints an 'artifact:' path into the throwaway worktree that is deleted on exit.
- After: With colleague off PATH and --repo pointing at a colleague checkout, the wrapper resolves via 'uv run --project <checkout> colleague' and runs; the normal colleague-on-PATH path stays byte-identical.
- After: A drive environment/setup failure exits 2 through the wrapper, a user-input failure exits 1, success exits 0; parse-level failures (no stdout / unparseable JSON) stay 2; the failure digest is still printed.
- After: A preview run, and a read-only run whose artifact was not preserved, print no 'artifact:' line into a deleted worktree; the line appears only when the artifact survives.

## Why it matters

- colleague is the ORIGIN of this first-party skill; defects must be fixed at the source so downstreams re-vendor verbatim rather than fork — culture already carries a marked '# culture-divergence:' for #181, and the documented #161 tri-state must actually hold or caller automation breaks.

## Requirements

- #180 finding-1 fix: capture the real drive rc (replace '|| true' with a set +e / set -e capture at each drive call site) and thread it into print_result via ASK_COLLEAGUE_DRIVE_RC; print_result exits 0 on ok, its own 2 on parse-level failure (no stdout / unparseable), else the threaded rc when it is 1 or 2, else 1. The digest-on-failure behavior is preserved.
  - honesty: print_result exit precedence becomes: 0 when status==ok; else 2 when its own parse checks fail (empty or unparseable stdin); else the threaded ASK_COLLEAGUE_DRIVE_RC when it is 1 or 2; else 1. The drive-failure digest still prints (to stderr), so digest-on-failure is preserved.

## Honesty conditions

- All three fixes are wrapper-only (.claude/skills/ask-colleague/scripts/ask-colleague.sh): no change to colleague's Python CLI, the prompt templates, or SKILL.md; the normal colleague-on-PATH resolution and a successful drive's stdout stay byte-identical.
- The three downstreams are real and currently vendor this skill verbatim: steward (PR #76 / issue #179), agentirc (PR #39 / issue #180), culture (PR #447 / issue #181); each filed its defect upstream rather than forking. Callers that branch on exit code are the documented #161 tri-state consumers.
- 'uv run --project <dir> colleague' runs the colleague console-script from <dir>'s project environment regardless of $PWD, and when colleague is on PATH the uv helper is never reached (installed path unchanged).
- Verified against colleague: 'colleague drive --json' on an engine/env failure WITH a partial result surfaces the partial TaskResult JSON to stdout AND exits 2 (emit_error result-to-stdout path, _errors.py:34-37) — the wrapper today parses it and exits 1. A no-partial env failure has empty stdout and already exits 2 via print_result's parse-level branch; a normal status=error drive (rc 1) stays 1.
- ASK_COLLEAGUE_GRADABLE=='1' is true exactly when the artifact survives in the real repo (read-only run whose _preserve_artifact landed, or write --apply whose drive ran in $REPO); gating the 'artifact:' print on it suppresses the line for a preview / failed-preservation run and keeps it for write --apply (whose path is already real).
- Each defect is present in current main's .claude/skills/ask-colleague/scripts/ask-colleague.sh: resolve_colleague walks only $PWD (lines 51-62); the four drive call sites use '|| true' (425/449/502/504); print_result exits '0 if ok else 1' (line 306) and prints 'artifact:' whenever ap is set (lines 294-299).
- colleague is the declared origin of this first-party skill (docs/skill-sources.md + SKILL.md 'first-party'); culture is carrying a marked '# culture-divergence:' for #181 that it drops only on re-vendor, which can happen only once the fix lands upstream here.
- The out-of-scope items are genuinely untouched: colleague/cli/_errors.py's tri-state is unchanged (the wrapper only reads rc); prompts/*.md and SKILL.md stay byte-identical; .markdownlint-cli2.yaml already ignores '.claude/skills/**' so no lint change is needed; no sync/notification code is added.
- The new cases are black-box and need no live model — they install a fake 'colleague' stub on PATH exactly as test_ask_colleague_skill.py already does for the worktree/feedback/preserve cases — and assert the wrapper's resolution choice, propagated exit code, and the absence of a dead 'artifact:' line.

## Success signals

- tests/test_ask_colleague_skill.py gains cases that pass: (1) colleague hidden from PATH + --repo at a checkout resolves via uv and runs; (2) a drive env/setup failure exits 2 and a user-input failure exits 1 through the wrapper; (3) a preview / non-preserved run prints no 'artifact:' line at a dead path. Black-box, no live model. Downstreams can drop their divergence on re-vendor.

## Scope / boundaries

- Out of scope: changing colleague's CLI exit-code contract (the wrapper only faithfully propagates it); editing prompt templates or SKILL.md semantics; any markdownlint config change (colleague already ignores .claude/skills/** so the #179 prompts-gotcha does not apply here); building any downstream auto-sync or notification mechanism.

## Decisions

- #181 fix: factor the upward pyproject walk into a '_colleague_via_uv <dir>' helper, try it against $PWD then the resolved $REPO, and run 'uv run --project <dir> colleague' so cwd need not be inside the checkout (culture's offered-back patch, verbatim).
- #180 finding-2 fix: gate the 'artifact:' print on the existing ASK_COLLEAGUE_GRADABLE=='1' flag (which already means 'the artifact survives in the real repo'), unifying artifact: with the grade: hint — write --apply keeps printing its real path, preview/non-preserved suppress it — rather than introducing a new survives signal.
- #179 (downstream tracking) requires no change in this repo: after these wrapper fixes land, the operator re-vendors/redeploys the corrected ask-colleague back to the downstreams (steward, agentirc, culture) via the ../rollout-cli agent. No docs/skill-sources.md ledger edit is part of this spec.

## Hard questions

- risk: Bash gotcha: under 'set -euo pipefail', 'local out; out=$(cmd)' on ONE line masks the command's rc (local's own rc wins, always 0). To capture the real drive rc the declaration must be split from the assignment (declare 'local out rc'; then 'out=$(cmd); rc=$?' wrapped in set +e / set -e), or the tri-state is silently lost again.

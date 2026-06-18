# Build Plan — ask-colleague is now a trustworthy standing pre-PR reflex: review front-loads a filtered diff and fans out parallel reviewers so it finishes fast on a real diff and always returns findings; monitor truly streams a running flight's live feed; write --apply no longer trips on a read-only probe's own .colleague/ artifacts; and the SKILL.md provenance reads honestly in any consumer regardless of how it vendors its other skills.

slug: `ask-colleague-is-now-a-trustworthy-standing-pre-pr` · status: `exported` · from frame: `ask-colleague-is-now-a-trustworthy-standing-pre-pr`

> ask-colleague is now a trustworthy standing pre-PR reflex: review front-loads a filtered diff and fans out parallel reviewers so it finishes fast on a real diff and always returns findings; monitor truly streams a running flight's live feed; write --apply no longer trips on a read-only probe's own .colleague/ artifacts; and the SKILL.md provenance reads honestly in any consumer regardless of how it vendors its other skills.

## Tasks

### t1 — SKILL.md docs: soften the provenance paragraph (#218) and make the monitor docs describe a truthful live/streaming feed (#219 docs side)

- covers: c9, h9, c10
- acceptance:
  - provenance paragraph states only first-party-from-colleague + cite-don't-import, has NO 'vendored from guildmaster' claim about sibling skills, and references docs/skill-sources.md as the per-repo ledger (grep test: removed phrase gone, first-party phrasing present)
  - monitor lines describe a streaming/live feed matching the new --follow behavior with no one-shot contradiction; a doc test asserts the SKILL.md monitor description and the wrapper help agree

### t2 — colleague flight status --follow: stdlib poll loop over the .colleague/flight/<id> feed (#219 runtime)

- covers: c10, h10
- acceptance:
  - flight status --follow polls the feed and prints each newly-appended record in order as it arrives (test simulates appends and asserts streamed order)
  - follow mode exits cleanly on flight-finish (terminal record), EOF, and KeyboardInterrupt; --json emits one JSON object per record (JSONL)
  - one-shot 'flight status' (no --follow) output is byte-identical to before (regression test pins it); stdlib only — no new runtime dep/daemon/socket (zero-deps + boundary guards still pass)

### t3 — Advisory early review fan-out: when the front-loaded diffstat spans many folders, recommend per-folder read-only reviewer subagents reusing #188 + reviewer role + batch_spawn (#220b)

- covers: c12, h12
- acceptance:
  - when a review's diffstat spans more than the fan-out threshold of folders, the loop injects exactly ONE advisory recommendation pointing at the subagents tool with a per-folder partition and the read-only reviewer role (unit test on the recommendation builder)
  - advisory/backend-judged + byte-identical when not triggered/below-threshold/off and on mock (TaskResult unchanged); reviewer children are read-only and cannot mutate the tree; NO new worktree/merge code (reuses make_batch_spawn/batch_spawn)

### t4 — ask-colleague.sh wrapper: narrow the write --apply dirty guard to tracked files (#217), wire monitor to flight status --follow (#219), and front-load a filtered/capped diff into the review instruction (#220a)

- depends on: t2
- covers: c8, h8, c11, h11, c10
- acceptance:
  - #217: dirty guard uses 'git status --porcelain --untracked-files=no'; after explore/review writes untracked .colleague/ artifacts, write --apply on a clean tracked tree runs WITHOUT --allow-dirty; a tracked uncommitted edit STILL refuses without --allow-dirty
  - #220a: review path computes 'git diff --stat <base>...HEAD' (always) + the diff body with lockfile/vendored noise (uv.lock, package-lock.json, *.min.js) excluded, capped to COLLEAGUE_MAX_OUTPUT_CHARS, inlined into the review instruction; when capped the diffstat is retained and truncation is explicit (test asserts diffstat present, uv.lock excluded, truncation note over cap)
  - #219-wire: ask-colleague monitor <id> invokes 'colleague flight status <id> --follow' and the monitor help describes a streaming feed (grep test)

### t5 — Feature doc + CHANGELOG + version bump + conventions-guard extensions tying the four fixes together honestly

- depends on: t1, t2, t3, t4
- covers: c1, c2, c3, c4, c5, c6, c7, h1, h2, h3, h4, h5, h6, h7, h13
- acceptance:
  - docs/features/ask-colleague-trustworthy-reflex.md documents all four issues, the wrapper-first front-load decision, the advisory early fan-out, and the honest #220b limit (h13: ~no wall-clock speedup on a serializing GPU; front-load is the win that holds); CHANGELOG entry added; version bumped in pyproject.toml + colleague/__init__.py (version-check CI passes)
  - zero-deps (test_zero_deps.py) + boundary (test_boundary.py) guards still pass — no new runtime dep/daemon/socket/subprocess consumer (h1); changed paths are verifiable on the mock backend without a live GPU (h7)
  - deferred items (--deadline flag, contention detection) recorded as parked follow-ups and forced-synthesis (#191/#197) unchanged (h6); the four after-states map to filed acceptance criteria #220/#219/#217/#218 (h3) and before-states to filed evidence (h4)

## Risks

- [unknown_nonblocking] Exact filtered-diff byte cap + the lockfile/vendored-noise exclusion globs (uv.lock, package-lock.json, *.min.js, …) need a live-diff calibration pass (task t4)
- [unknown_nonblocking] Follow-mode poll interval default (proposed ~2s) and --json streaming shape (proposed JSONL) to confirm during build (task t2)
- [unknown_nonblocking] Whether front-load should also seed full touched-file contents beyond the diff body (budget risk; default is diff-only, model reads further on demand) (task t4)
- [follow_up] Build is via Claude this round, not colleague-as-planner/workforce — that path is walled on the served 27B (#215); the plan is workforce-fan-out-ready but built serially now

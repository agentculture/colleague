# Build Plan — Colleague finishes what it starts: a run that stalls mid-task is nudged to continue instead of ending on a half-done file, and at the finish boundary it auto-compacts its history — freeing context so it keeps working and leaving a clean model-authored summary instead of trailing prose.

slug: `colleague-finishes-what-it-starts-a-run-that-stall` · status: `exported` · from frame: `colleague-finishes-what-it-starts-a-run-that-stall`

> Colleague finishes what it starts: a run that stalls mid-task is nudged to continue instead of ending on a half-done file, and at the finish boundary it auto-compacts its history — freeing context so it keeps working and leaving a clean model-authored summary instead of trailing prose.

## Tasks

### t1 — config knob: COLLEAGUE_MAX_CONTINUE_NUDGES (lift the hardcoded _MAX_FINISH_NUDGES=1)

- covers: h1, c7
- acceptance:
  - EngineConfig.resolve reads COLLEAGUE_MAX_CONTINUE_NUDGES then CONVERTIBLE_ fallback, precedence flag>env>file>default, default >1; to_dict includes max_continue_nudges; a test pins precedence + default
  - config.py + tests/test_config.py only (file-disjoint from loop.py)

### t2 — continue-working: configurable nudge cap; resume a stalled run instead of stopping after one nudge

- depends on: t1
- covers: c8, c3, c4, h1
- acceptance:
  - _handle_no_tool_turn uses the resolved cap threaded via ContextControls + both backends (mock + vllm), not the hardcoded _MAX_FINISH_NUDGES; a scripted mock that stalls then resumes continues past the first stall and only reaches _EXIT_STOPPED after the cap is spent
  - an explicit finish still ends immediately with no nudge; nudge turns count against the existing step/token budget so termination stays bounded (test asserts the cap is honored)

### t3 — auto-compact-on-finish: compacted summary at the stop/give-up boundary + free context on nudge-resume

- depends on: t2
- covers: c9, h2, h3, c3
- acceptance:
  - at the STOP/budget give-up boundary (where the summary would otherwise be trailing prose like 'Let me check:') the summary is produced via the existing compaction helper (build_compaction_request/apply_compaction), NOT raw prose; an explicit clean finish keeps the model's own finish summary (unchanged)
  - on the nudge-resume path context is compacted via the same helper when it exceeds budget so a continued run does not overflow; NO new summarizer; falls back to the documented windowing/forced-synthesis floor (#191) when compaction cannot run; strict no-op (byte-identical TaskResult) when there is no stop/give-up boundary with content

### t4 — prove the contract on mock: scripted stall->resume completes, stop yields compacted summary, strict no-op, mock==vllm shape

- depends on: t2, t3
- covers: c6, h5, h7, h10, h11
- acceptance:
  - test_e2e_mock proves WITHOUT a live model: a scripted stall-then-resume run completes more work than a single-nudge run; a stop-without-finish run carries a compacted (non-prose) summary; a clean-finish (no-trigger) run's TaskResult is byte-identical to pre-change
  - mock and vllm result shapes stay identical (all-engines e2e), and the zero-deps + boundary guards still pass

### t5 — document the feature + bump version

- depends on: t4
- covers: c1, c2, c5, c7, h6, h8, h9
- acceptance:
  - CLAUDE.md gains an architecture bullet for continue-working + auto-compact-on-finish with honest limits (cap-bounded termination, zero new deps, all-engines, strict no-op, NO new caller flag), citing the t5 evidence + salvage cost and naming the COLLEAGUE_MAX_CONTINUE_NUDGES knob
  - CHANGELOG.md + pyproject.toml bumped one minor; spec + plan cross-referenced

## Risks

- [unknown_nonblocking] Exact COLLEAGUE_MAX_CONTINUE_NUDGES default value (2 vs 3) — tune at build against the t5-class stall (task t1)
- [follow_up] Reconcile the auto-compact stop-summary with the t3 forced-synthesis floor (#191) so a run gets ONE end summary, not two — define ordering (task t3)
- [unknown_nonblocking] Bound repeated compaction across multiple nudge-resume cycles (the #156 fill-line is once-per-item) to avoid compaction thrash (task t3)
- [follow_up] Build depends on PR #195 (forced-synthesis #191 + fanout) landing on main; tasks are authored against the post-#195 tree — build after #195 merges or stack this branch on it

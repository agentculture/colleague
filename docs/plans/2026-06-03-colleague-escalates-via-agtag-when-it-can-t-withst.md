# Build Plan — colleague escalates via agtag when it can't withstand a request — opening one tracked continuation issue with what it finished, what's needed, and a suggested split

slug: `colleague-escalates-via-agtag-when-it-can-t-withst` · status: `exported` · from frame: `colleague-escalates-via-agtag-when-it-can-t-withst`

> colleague escalates via agtag when it can't withstand a request — opening one tracked continuation issue with what it finished, what's needed, and a suggested split

## Tasks

### t1 — Add a continuation-record builder (colleague/escalation.py) that renders the 5-section body from a partial TaskResult + DriveStats

- covers: c4, c11, h5, h8
- acceptance:
  - build_continuation(result, stats) returns a body with all five labelled sections: continuation/state, remaining, what's-needed, suggested split, why
  - the body reflects real drive state (step/turn counts, elapsed, artifact id) drawn from DriveStats, not boilerplate
  - pure function: no network/subprocess/filesystem I/O; unit-tested in tests/test_escalation.py

### t2 — Add escalation gating + idempotency in colleague/escalation.py (opt-in, offline/CI-safe, approval-gated, one issue per task)

- depends on: t1
- covers: c6, c9, c10, h3, h4, h10, h11
- acceptance:
  - should_escalate() returns False by default; True only when the opt-in env flag is set AND not offline/CI (reusing handoff's guard) AND not in a throwaway worktree/test
  - an agtag invocation not permitted by the approval gate (colleague/policy.py) is denied
  - idempotency keyed on task_id: a second escalation for the same task_id is skipped — a test running the same failing task twice asserts exactly one issue

### t5 — Add an explicit not-finished flag to TaskResult, set in loop.py finalize when the drive exhausts the step budget without calling finish

- acceptance:
  - TaskResult carries an explicit boolean (e.g. not_finished) that is True iff the drive ran out the step budget without calling finish and without raising DriveAborted; False on a clean finish or a no-tool-call answer
  - the flag is set in loop.py finalize and does NOT rely on stats.step_count (which counts tool calls, not the max_steps turn budget); all-engines (mock and vllm), zero new deps
  - the #109 TaskResult-field-set guard (tests/test_result_fidelity.py) and the e2e shape test are updated for the new field; mock and vllm produce the identical shape

### t3 — Wire the finalize-time escalation seam into colleague/loop.py on the DriveAborted and not-finished branches, posting via the culture/agtag path

- depends on: t1, t2, t5
- covers: c1, c3, c7, c8, h1, h2, h7
- acceptance:
  - with escalation enabled, a deliberately-capped drive (tiny step budget / forced timeout) files exactly ONE agtag issue carrying the preserved partial result
  - with escalation disabled the run is byte-identical to today (no post); the seam fires on BOTH the DriveAborted and not-finished branches
  - fires identically for mock and vllm-openai (all-engines rule); guarded by the e2e shape test and a zero-deps check (no new runtime dep/socket/daemon)

### t4 — Document the escalation feature (docs/features/escalation.md): what the filed issue looks like, the opt-in/gating model, and the runtime-auto-over-model-judged rationale

- depends on: t3
- covers: c2, c5, h6, h9
- acceptance:
  - docs/features/escalation.md explains who the continuation issue serves, the opt-in default-off gating, and why runtime-auto was chosen over model-judged escalation
  - the doc frames the output as an actionable, continuable artifact (not a failure notification) and is linked from the README feature table + docs/features/README.md

## Risks

- [follow_up] build is gated on colleague#109 (result fidelity): until a drive reliably surfaces its partial state at the wall, the continuation body has nothing to carry — implement #109 first, then this plan

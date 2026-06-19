# Build Plan — Colleague plan mode gets the served 27B further and fails honestly when it can't converge

slug: `colleague-plan-mode-gets-the-served-27b-further-an` · status: `exported` · from frame: `colleague-plan-mode-gets-the-served-27b-further-an`

> Colleague plan mode gets the served 27B further and fails honestly when it can't converge

## Tasks

### t1 — Honesty-call robustness: split the combined claims+honesty call so the spec stage gathers honesty conditions reliably on a weak model

- covers: c8, h8, c3, h3
- acceptance:
  - make_propose_claims issues a DEDICATED honesty-only call (single {honesty:[...]}) after gathering claims, and a BOUNDED per-claim fallback fills any spec-affecting claim still missing honesty
  - the honesty path routes through robust_simple_complete; an empty/unparseable honesty response is tolerated (no crash) and honesty conditions land state=proposed
  - a unit test with a scripted mock SimpleComplete proves: a combined call yielding no honesty + a dedicated honesty call yielding honesty => claims end with confirmed-eligible honesty conditions

### t2 — Plan-only mode: colleague plan run --no-workforce stops after gating plan items, skipping the workforce fan-out

- covers: c9, h9
- acceptance:
  - run_plan_mode(workforce=False) returns after plan items are proposed and gated, with empty waves and sub_results, and never calls run_wave / batch_spawn (no subagent worktree created)
  - colleague plan run --no-workforce sets workforce=False; omitting it is byte-identical to today (workforce runs); OrchestratorResult shape unchanged
  - a unit test proves workforce=False yields empty waves/sub_results and the injected batch_spawn is never invoked

### t3 — Honest reporting: surface claims_missing_honesty on both the human and --json plan surfaces

- depends on: t2
- covers: c10, c5, h5
- acceptance:
  - _render_run: when missing_kinds is empty but claims_missing_honesty is non-empty, render 'claims missing a confirmed honesty condition: <ids>' (never 'missing: (none)')
  - _run_payload adds a 'claims_missing_honesty' key alongside missing_kinds

### t4 — Drift test: a non-converged plan result always names a non-empty failure reason on every surface

- depends on: t3
- covers: h10, c7, h7
- acceptance:
  - a test asserts that for a non-converged result whose SOLE gap is claims_missing_honesty, _render_run output is not 'missing: (none)' and names the honesty ids
  - the same test asserts _run_payload does not report all failure lists empty when converged is False

### t5 — Skill flags: ask-colleague plan exposes --no-workforce/--quick and forwards --timeout, with an honest remediation hint

- covers: c11, h11, c2, h2
- acceptance:
  - ask-colleague plan forwards --no-workforce and --quick to 'colleague plan run', and --timeout N sets COLLEAGUE_TIMEOUT=N for that run only
  - an unusable-proposal or timeout failure prints a clear remediation hint naming --no-workforce/--quick/--timeout; no silent semantic auto-degrade; the --json contract is unchanged

### t6 — Live validation + docs: confirm --no-workforce returns spec+plan on the 27B and document the honesty-call split

- depends on: t1, t2, t3, t5
- covers: c1, h1, c4, h4, c6, h6
- acceptance:
  - an opt-in live check (or honestly-recorded result) confirms 'plan run --no-workforce' on the served 27B returns spec+plan at exit 0, or records the actual outcome
  - docs/features/plan-mode.md + the CLAUDE.md plan-mode bullet note the dedicated honesty call, the per-claim fallback, --no-workforce, and the all-engines (mock==vllm shape) invariant
  - no code path adds a router, weakens the convergence rule, or changes the work-mode timeout default

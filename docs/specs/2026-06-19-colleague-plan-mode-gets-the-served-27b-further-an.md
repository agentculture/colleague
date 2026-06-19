# Colleague plan mode gets the served 27B further and fails honestly when it can't converge

> Colleague plan mode gets the served 27B further and fails honestly when it can't converge

## Audience

- An agent (Claude or another) delegating a planning task to colleague via 'colleague plan' / 'ask-colleague plan' against the served reference 27B backend

## Before → After

- Before: On the served 27B plan mode walls: the combined requirements+honesty call returns no honesty conditions so the spec never converges, the gate reports 'missing: (none)', and the only path past spec (--quick) times out in the workforce at 120s
- After: On the served 27B the spec stage reliably gathers honesty conditions and the convergence gate names the exact gap; a caller can obtain a spec+plan without triggering the side-effecting workforce fan-out

## Why it matters

- plan mode is the advertised 'colleague is the planning mind' surface; a caller leaning on it today gets an error, not a plan, and cannot even tell why it failed

## Requirements

- The spec stage proposes honesty conditions in a dedicated focused call (single {honesty:[...]} array), with a bounded per-claim fallback for any spec-affecting claim still missing one, all routed through robust_simple_complete
  - honesty: The dedicated honesty call and per-claim fallback are BOUNDED (capped call count) and route through robust_simple_complete; a partial/empty honesty response is tolerated (never a crash); honesty conditions still land proposed (operator/gate confirms)
- colleague plan run gains a --no-workforce (plan-only) mode that stops after proposing and gating plan items, skipping the workforce waves entirely
  - honesty: --no-workforce stops after gating plan items and creates no subagent worktree; the default (workforce on) stays byte-identical; OrchestratorResult shape is unchanged when workforce is skipped (empty waves/sub_results)
- The convergence gate surfaces claims_missing_honesty on both the human (_render_run) and --json (_run_payload) surfaces; a drift test asserts a non-converged result always names at least one non-empty failure list
  - honesty: The claims_missing_honesty surface is additive (empty/omitted when converged); a drift test pins: non-converged result => at least one non-empty failure list on each surface
- The ask-colleague plan skill verb exposes --no-workforce and --quick and forwards a --timeout (COLLEAGUE_TIMEOUT), with a clear remediation hint on an unusable-proposal or timeout failure (no silent auto-degrade)
  - honesty: The skill changes are flag pass-throughs only (no new colleague runtime behavior), the --json contract is unchanged, and there is no silent semantic auto-degrade

## Honesty conditions

- On the served 27B an end-to-end 'plan run --no-workforce' actually returns a spec+plan at exit 0 in a live test, not just on mock
- The audience is the delegating agent — verified by 'ask-colleague plan' being the documented entry the division-of-labor docs point callers to
- Honesty conditions are gathered by a dedicated call whose effect is observable (claims gain honesty in the frame/checkpoint), and --no-workforce returns before any subagent worktree is created
- The before_state reproduces on the served 27B today (documented in #215/#224): the combined requirements+honesty call yields zero honesty conditions
- The current failure is unactionable to a caller — verified by #224's 'missing: (none)' reproduction
- No code path adds a multi-model router, weakens the convergence rule, or changes EngineConfig's work-mode timeout default; the all-engines rule holds (mock and vllm-openai identical TaskResult/Orchestrator shape)
- A test asserts a non-converged ConvergenceResult always renders AND serializes a non-empty failure reason; the --no-workforce exit-0 path is live-validated on the 27B

## Success signals

- On the served 27B, 'colleague plan run --no-workforce' returns a spec+plan at exit 0; and every non-converged run names a non-empty failure reason on BOTH the human and --json surfaces

## Scope / boundaries

- NOT a guarantee a weak model converges, NOT a multi-model router, NOT a change to the convergence rule (honesty conditions stay mandatory), NOT a change to work-mode's default timeout

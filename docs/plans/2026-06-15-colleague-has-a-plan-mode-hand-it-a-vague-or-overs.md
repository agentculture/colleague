# Build Plan — Colleague has a plan mode: hand it a vague or oversized assignment and it works backwards into a reviewed spec, turns that spec into a split plan, then runs the small items as a workforce of subagent colleagues — staged in small steps, not one big leap

slug: `colleague-has-a-plan-mode-hand-it-a-vague-or-overs` · status: `exported` · from frame: `colleague-has-a-plan-mode-hand-it-a-vague-or-overs`

> Colleague has a plan mode: hand it a vague or oversized assignment and it works backwards into a reviewed spec, turns that spec into a split plan, then runs the small items as a workforce of subagent colleagues — staged in small steps, not one big leap

## Tasks

### t1 — Native plan-mode frame data model (colleague/plan/frame.py): claims + honesty conditions + steps, each step carrying a mandatory/optional attribute; pure stdlib, no devague import

- covers: c24, c11
- acceptance:
  - A PlanFrame round-trips JSON identically (save->load->equal)
  - Claims carry kind + state (proposed/confirmed/rejected); steps carry a mandatory/optional flag
  - Module imports no third-party package (stdlib only)

### t2 — Native convergence / required-kinds rule (colleague/plan/convergence.py): enforce the mandatory kinds (announcement, audience, after_state, before_state-or-why, boundary, success_signal, honesty-on-spec-affecting); record skipped optional steps

- depends on: t1
- covers: c24, h10
- acceptance:
  - converge() returns not-passed listing each missing mandatory kind, and passes only when all mandatory kinds are confirmed AND every spec-affecting claim has a confirmed honesty condition
  - Proceeding past an unresolved mandatory step is blocked; skipping an optional step is permitted and recorded in the artifact

### t3 — File-based gate/checkpoint + resume (colleague/plan/checkpoint.py): durable state under .colleague/plan/<id>.*, surfaces the proposed item + recommended move, resumes from the last resolved gate; no daemon, no socket

- depends on: t1
- covers: c17, h4
- acceptance:
  - Killing the process between gates and re-loading resumes from the last resolved gate (state entirely on disk)
  - No thread/socket/daemon is opened; a gate persists the proposed item plus the recommended operator move

### t4 — Same-model critic reviewer (colleague/plan/reviewer.py): a second completion against config.model with a distinct critic system prompt; advisory critique, never confirms; disable flag -> byte-identical flow

- depends on: t1
- covers: c22, h8
- acceptance:
  - The reviewer issues one completion against config.model with a critic system prompt and returns a non-authoritative critique (no confirm path)
  - With the reviewer disabled the propose->operator-gate flow is byte-identical; mock and vllm produce the same result shape (all-engines)

### t5 — Spec stage (colleague/plan/spec_stage.py): per-claim capture->interrogate->review micro-cycle, one proposed item per gate, blocking on confirm/reject before the next; runs the critic on consequential steps

- depends on: t2, t3, t4
- covers: c11, h2
- acceptance:
  - A transcript shows exactly one proposed item surfaced per gate, each blocking on confirm/reject before the next is proposed (not a single bulk capture)
  - The spec stage reaches convergence only after all mandatory items are confirmed

### t6 — Plan stage (colleague/plan/plan_stage.py): emit items each sized for one bounded child work item, each with acceptance criteria and an explicit acyclic dependency order (deterministic waves)

- depends on: t2, t3
- covers: c16, h3
- acceptance:
  - Each emitted plan item carries >=1 acceptance criterion and a step/token budget fitting one child
  - Dependency order is explicit and acyclic; waves are emitted deterministically (refuses a cyclic/dangling graph)

### t7 — Workforce stage (colleague/plan/workforce.py): map plan waves onto the existing subagents fan-out, reusing make_batch_spawn/batch_spawn unchanged (FANOUT=4/DEPTH=2), isolated worktrees + sequential merge child

- depends on: t6
- covers: c18, h5
- acceptance:
  - The fan-out calls colleague/subagents.py make_batch_spawn/batch_spawn unchanged (no new worktree/merge code added) and honours FANOUT=4/DEPTH=2
  - An unresolvable merge conflict is surfaced to the operator, not force-merged

### t8 — Auto-trigger detection (colleague/plan/trigger.py + one loop hook): during a normal work item detect a no-clean-path/hard feature and inject ONE advisory recommendation to enter plan mode (auto-split/capacity precedent); backend-judged, never forced

- depends on: t1
- covers: c36, h22
- acceptance:
  - On a no-clean-path task exactly ONE advisory plan-mode recommendation is injected; the model decides whether to act (not a forced gate)
  - On a clear scoped task the loop is a byte-identical no-op (strict no-op)

### t9 — Pushback on too-small tasks (colleague/plan/pushback.py, invoked from the verb): decline the full spec->plan->workforce pipeline for a clearly small task and recommend a direct 'colleague work'

- depends on: t1
- covers: c37, h23
- acceptance:
  - Invoking plan mode on a trivially small task yields a pushback message recommending a plain 'colleague work', not a full pipeline run

### t10 — Orchestrator (colleague/plan/orchestrator.py): drive spec->plan->split->workforce through gated checkpoints, applying mandatory/optional + reviewer; runtime-owned, all-engines, never self-confirms

- depends on: t5, t6, t7, t8
- covers: c1, h9, c34, h20, c33, h19
- acceptance:
  - The orchestrator runs spec->plan->workforce gated at every step, has no self-confirm path, and drives identically for mock and vllm
  - Both entry paths reach the SAME staged arc; resuming via checkpoint continues from the last gate; planning happens before any implementation

### t11 — colleague plan CLI verb (colleague/cli/_commands/plan.py + wire in cli/__init__.py): 'plan' / 'plan status' / 'plan continue', --json, CliError, explain entry, overview

- depends on: t10, t9
- covers: c4, h14
- acceptance:
  - 'colleague plan <task>' enters the staged flow; 'plan status' reports the gate; 'plan continue' resumes; results to stdout, diagnostics to stderr; --json supported; 'colleague explain plan' exists
  - An absence->presence test confirms there was no native 'plan' verb before this change (covers h14)

### t12 — ask-colleague 'plan' verb (.claude/skills/ask-colleague/ + docs/features/ask-colleague.md): a delegating agent hands the WHOLE planning arc to colleague (colleague plans), mirroring how /think keeps Claude as planner

- depends on: t11
- covers: c33, h19, c32, h18
- acceptance:
  - 'ask-colleague plan "<task>"' invokes 'colleague plan' with colleague as the planning mind, documented as the inverse of /think
  - Safety/preview semantics are consistent with the other ask-colleague verbs (worktree isolation where read-only)

### t13 — Conventions guard (tests/test_plan_boundary.py, test_plan_zero_deps.py, test_plan_e2e.py): prove no socket/daemon, subprocess/threading only via sanctioned modules, zero-deps (no third-party incl. devague), and identical mock/vllm shape with a strict no-op when not engaged

- depends on: t7, t10, t11
- covers: c26, h17, c35, h21
- acceptance:
  - Boundary test: colleague/plan/* opens no socket/daemon and imports subprocess/threading only via the sanctioned modules; zero-deps guard imports colleague.plan and asserts no third-party leak (devague used via subprocess only)
  - e2e: plan-mode result shape is identical for mock and vllm, byte-identical no-op when plan mode is not engaged; a sample complex task produces spec+plan+workforce end-to-end

## Risks

- [unknown_nonblocking] Exact native-vs-devague boundary: how much of devague's convergence / spec-to-plan / waves engine colleague reimplements natively vs shells out to devague if reimplementation proves too costly. Native-first; decide during the build (task t1)
- [follow_up] Sub-step gate ergonomics: one 'colleague plan continue' per gate could be tedious across dozens of sub-steps; may need a batched-review confirm or a session-embedded interactive mode (task t11)
- [unknown_nonblocking] loop.py (t8 auto-trigger hook) and cli/__init__.py (t11 verb wiring) are shared hot files; the wave schedule already separates them, but builders must not collapse t8/t11 into a same-wave fan-out (task t8)

# Colleague has a plan mode: hand it a vague or oversized assignment and it works backwards into a reviewed spec, turns that spec into a split plan, then runs the small items as a workforce of subagent colleagues — staged in small steps, not one big leap

> Colleague has a plan mode: hand it a vague or oversized assignment and it works backwards into a reviewed spec, turns that spec into a split plan, then runs the small items as a workforce of subagent colleagues — staged in small steps, not one big leap

## Audience

- Operators — and delegating agents via ask-colleague — who need colleague to handle genuinely COMPLEX implementations using the devague paradigm (spec -> plan -> workforce), not just single scoped work items

## Before → After

- Before: Today colleague meets a too-big/too-vague task with a one-shot auto-split or graceful degradation; the staged spec->plan->workforce pipeline only exists as external Claude Code skills (think / spec-to-plan / assign-to-workforce) the operator drives by hand — colleague can't run it itself
- After: Plan mode has two entry paths: (1) explicit — invoked with 'colleague plan' / 'ask-colleague plan'; (2) automatic — during a normal work item colleague detects a feature that needs investigation (no clean implementation path) and triggers/suggests the spec-based devague-paradigm flow. Either path stages the assignment idea -> reviewed spec -> plan -> small items -> subagent-colleague workforce, each step a gated checkpoint

## Why it matters

- Two reasons: colleague can carry genuinely complex tasks instead of degrading on them; and a DIFFERENT mind does the planning (the diversity is the value) — converging on evidence, not vibes

## Requirements

- The spec stage handles each spec item separately — a per-claim capture -> interrogate -> review micro-cycle — rather than capturing the whole spec in one turn
  - honesty: The spec stage surfaces one proposed item at a time and blocks on the operator's confirm/reject before proposing the next — demonstrable in a transcript of per-item gates, not a single bulk capture
- The plan stage produces items each sized for one bounded child work item — granular in the plan stage as well as the spec stage — each carrying acceptance criteria and an honest dependency order
  - honesty: Each plan item carries acceptance criteria and is small enough that one child work item completes it within the step/token budget; the dependency order is explicit (waves), not implied
- Each gate is a durable file-based checkpoint (precedent: the flight control plane plus devague's own .devague state): 'colleague plan' stops with the proposed item + the recommended operator move surfaced, and 'colleague plan continue' resumes after the operator resolves it. No daemon, no socket
  - honesty: Killing colleague between stages or sub-steps and re-running 'colleague plan continue' resumes from the last resolved gate (state is entirely on disk); no daemon/socket/background process is required
- The workforce stage fans the plan's dependency waves out to parallel subagent colleagues in isolated worktrees with a sequential merge child, reusing make_batch_spawn / batch_spawn unchanged (caps unchanged: FANOUT=4, DEPTH=2) — TDD-gated merges, surfacing not force-merging conflicts
  - honesty: The fan-out calls colleague/subagents.py make_batch_spawn/batch_spawn unchanged (no new worktree/merge code), honours FANOUT=4/DEPTH=2, and surfaces unresolvable merge conflicts rather than force-merging
- Selected steps get an agent-reviewer critique pass BEFORE the operator gate: colleague runs the SAME backend model with a critic system prompt (an adversarial persona) over the proposed item and surfaces weaknesses, risks, and missing honesty conditions as advisory input. The reviewer never confirms — confirmation stays user-only. This intra-model critique (persona swap) is deliberately distinct from the different-backend diversity of ask-colleague / subagents
  - honesty: The reviewer is a second completion against config.model with a critic system prompt (no second model required); its critique is surfaced at the gate as non-authoritative input; with the reviewer disabled the propose->operator-gate flow is byte-identical, and it fires identically for mock and vllm-openai (all-engines)
- Mandatory steps cannot be skipped and must be resolved at their gate: announcement, audience, after_state, before_state-or-why_it_matters, boundary, success_signal, and a confirmed honesty condition on every spec-affecting claim. Every other step (extra risks, extra assumptions, nice-to-have claims) is optional; the operator may skip it and the skip is recorded
  - honesty: Proceeding past a mandatory step without resolving it is blocked by plan mode's own native convergence check (the same required-kinds rule); skipping an optional step is permitted and recorded in the artifact
- Auto-trigger: beyond the explicit verb, during a normal work item colleague detects when a feature needs investigation (no clean implementation path / genuinely hard) and injects ONE advisory recommendation to enter the spec-based plan flow — precedent: the auto-split and capacity-warning recommendations; backend-judged, never a forced gate, strict no-op on a clear task
  - honesty: On a no-clean-path task colleague injects exactly ONE advisory plan-mode recommendation (like the auto-split recommendation); the model decides whether to act; on a clear scoped task it is a byte-identical no-op
- Pushback: colleague declines to spin up the full spec -> plan -> workforce pipeline for a clearly small/scoped task — it pushes back and recommends a direct 'colleague work' instead, rather than over-engineering a trivial task
  - honesty: Invoking 'colleague plan' on a trivially small task yields a pushback recommending a plain 'colleague work', not a full pipeline run

## Honesty conditions

- 'colleague plan "<vague task>"' runs the staged arc to a reviewed spec, then a plan, then a workforce fan-out, pausing at every operator gate, with NOTHING extra installed (native-first, zero deps); any devague fallback degrades gracefully when devague is absent, never crashing or silently skipping
- Today colleague has no native staged planner — verifiable by the absence of a 'plan' verb in the CLI; the staged arc exists only as the Claude Code skills
- Plan mode opens no socket and forks no daemon, never auto-confirms its own spec, and reuses colleague/subagents.py for the fan-out — verifiable by the boundary tests and the absence of a self-confirm path in colleague's own gate
- The zero-deps guard still passes: plan mode imports no third-party package; any devague use is via subprocess only, never an import
- There is a real class of complex implementations colleague today cannot do well in one bounded work item; plan mode lets colleague carry them via the devague paradigm — verifiable on a sample complex task
- Both entry paths reach the SAME staged gated arc: 'colleague plan <task>' enters it explicitly, and a normal work item on a no-clean-path feature surfaces an advisory trigger into it
- The planning mind is colleague (a different backend than the requesting agent) and the staged arc converges on confirmed evidence before any implementation
- On a complex task colleague produces spec+plan+workforce implementation; on a trivially small task 'colleague plan' pushes back to a plain work item; on a hard normal task colleague suggests plan mode — all three observable, identical in shape for mock and vllm-openai, zero new deps

## Success signals

- Colleague can spec, plan, and implement a complex task end-to-end via the subagent-colleague workforce; AND it exercises judgment about WHEN to plan — pushing back when a task is too small for the pipeline, suggesting the spec-based flow when a task is hard. Fires identically for mock and vllm-openai; zero new runtime deps; strict no-op when not engaged

## Scope / boundaries

- Not a daemon/server, not a multi-backend router, not autonomous (every stage AND every sub-step is an operator gate; colleague never self-confirms), not a reimplementation of subagents (the workforce reuses the existing fan-out/merge machinery). It DOES reimplement devague's planning methodology natively (native-first) rather than hard-depending on the devague CLI

## Assumptions

- Plan mode keeps 'dependencies = []': the native arc imports no third-party package and shells out to nothing by default. Any future devague fallback is a subprocess CLI (never a Python import), so the zero-deps guard passes either way

## Decisions

- Surface: a new agent-first verb 'colleague plan' with staged sub-states (plan status / plan continue), not a session toggle or a single loop tool
- The agent-reviewer is same-model / different-system-prompt by default, on for consequential steps (the spec as a whole, each parked risk, the plan, the workforce go/no-go) and configurable/disableable; the critic prompt is a built-in plan-mode default, overridable via the existing layered AGENTS/skills config
- Engine: plan mode drives the staged arc NATIVELY — a colleague-owned plan artifact plus its own staged capture/interrogate/converge/waves logic mirroring devague's methodology — so the verb carries NO hard dependency and 'dependencies = []' holds; it runs with nothing extra installed. devague is added as an optional subprocess fallback ONLY IF reimplementing its convergence/spec-to-plan/waves engine proves too costly. Native-first, devague-only-if-we-have-to
- Overlap resolved: SAME arc, DIFFERENT planner. 'colleague plan' / 'ask-colleague plan' = COLLEAGUE is the planning mind; the 'think' skill = Claude is the planning mind. Parallel-by-design (the diversity is the point), not duplication
- 'ask-colleague' gains a 'plan' verb so a delegating agent (e.g. Claude) can hand the WHOLE planning arc to colleague — colleague does the planning — the inverse-skill surface mirroring how 'think' keeps Claude as planner
- Deliberate re-spec expanding colleague's v1 scope with a new orchestration verb, holding the conventions: zero Python runtime deps (native-first; devague only as an optional subprocess fallback), no socket, no daemon (gates are file-based + resume), all-engines (orchestration/checkpoints/critique/fan-out are runtime-owned; only proposal quality varies by backend)
- Gate model: every stage AND every sub-step is an operator gate (the announcement, each captured claim, each risk, each plan item, the workforce go/no-go). Colleague proposes via its native staged capture/interrogate; the operator confirms or rejects each one. Nothing past a gate runs autonomously — a guided, heavily-checkpointed flow, not fire-and-forget

## Open / follow-up

- Ergonomics of many sub-step gates: one 'colleague plan continue' per gate could be tedious; may need a batched-review confirm (devague confirm --from-review) or a session-embedded interactive mode
- Exact boundary of native vs devague-fallback: how much of devague's convergence / spec-to-plan / waves engine colleague reimplements natively vs shells out to devague if reimplementation proves too costly. Decide during the build (native-first)

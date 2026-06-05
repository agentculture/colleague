# Colleague auto-splits a too-large assignment into up to ~4 hand-over child assignments before it degrades lossily or fails — reaching ~1M-token effective capacity by reusing the subagent fan-out machinery, advisory and backend-judged, never a forced gate.

> Colleague auto-splits a too-large assignment into up to ~4 hand-over child assignments before it degrades lossily or fails — reaching ~1M-token effective capacity by reusing the subagent fan-out machinery, advisory and backend-judged, never a forced gate.

## Audience

- Colleague operators who hand it assignments larger than one context window, and the working backend/model that must carry them out — plus callers that delegate big tasks via 'colleague work' or the ask-colleague skill.

## Before → After

- Before: Today a job bigger than one window either (a) silently loses context to lossy windowing (graceful degradation drops oldest history with a placeholder), or (b) hits a limit and escalates AFTER the fact via an agtag continuation issue. No path splits the WORK before degrading or failing — escalation's '## Suggested Split' is advisory prose filed post-failure, not an actual hand-over.
- After: When colleague detects an assignment is too large for one context window, it recommends splitting it into up to ~4 coherent child assignments (hand-over assignments) that each fit one window, handed over through the existing subagent fan-out + merge machinery — so effective capacity reaches ~1M tokens (≈4×250k) without lossy windowing.

## Why it matters

- Splitting the work BEFORE degrading turns a hard ceiling (one window, lossy) into ~4× effective capacity with no context loss; escalation becomes the final fallback only when even a split can't fit, instead of the first response to overflow.

## Requirements

- The reactive split trigger is evaluated at the degradation-exhaustion point (when _MAX_OVERFLOW_RETRIES is reached in the loop) and is sequenced BEFORE the escalation seam, so a split recommendation is offered before any continuation issue is filed.
  - honesty: A test proves that, when degradation's overflow retries are exhausted, the split recommendation is offered STRICTLY BEFORE _escalation.escalate() runs on the aborted/not-finished path — escalation only fires if the split is declined or still can't fit.
- On trigger, the runtime injects exactly one structured recommendation message into the loop history that states the per-child token budget and the max child count (≤ MAX_SUBAGENT_FANOUT-1, reserving the merge slot), and points the model at the existing 'subagents' tool. The model is then given bounded additional turns to act.
  - honesty: The injected recommendation message names a concrete per-child token budget and a child cap ≤ MAX_SUBAGENT_FANOUT-1, and the model is granted ≥1 bounded additional turn to call 'subagents'; verifiable by inspecting the injected message text + turn accounting in a test.
- The actual fan-out + integration reuses colleague.subagents.make_batch_spawn / batch_spawn unchanged (isolated per-child worktrees on sub/<id> branches + the sequential merge child surfacing conflicts). No new worktree, merge, or concurrency code is added.
  - honesty: No new function is added to subagents.py or worktrees.py; the feature calls existing make_batch_spawn/batch_spawn, and tests/test_boundary.py still passes (threads/subprocess stay confined to the two sanctioned modules).
- Capacity is governed by a tunable EngineConfig knob (with a COLLEAGUE_* env, resolved via EngineConfig.resolve precedence and a CONVERTIBLE_* fallback) defaulting to ~4 children × the per-child context budget ≈ 1M tokens, structurally clamped so children never exceed MAX_SUBAGENT_FANOUT-1.
  - honesty: The knob resolves through EngineConfig.resolve with COLLEAGUE_* preferred over CONVERTIBLE_*; a configured value implying more than MAX_SUBAGENT_FANOUT-1 children is clamped down, proven by a config unit test.
- The feature is runtime-owned (lives in colleague/loop.py, all-engines rule): it fires identically for mock and vllm-openai, and when no trigger fires it is a strict no-op with TaskResult shape unchanged (guarded by tests/test_e2e_mock.py and the zero-deps guard).
  - honesty: With no trigger fired, the loop makes ZERO extra model turns and TaskResult is byte-identical to today; tests/test_e2e_mock.py and tests/test_zero_deps.py both pass, and the identical code path serves mock and vllm-openai.

## Honesty conditions

- A triggered oversize assignment demonstrably yields a split recommendation and, when the model acts, ≤ MAX_SUBAGENT_FANOUT child hand-over assignments end-to-end in a test.
- The feature is reachable via the documented entry points ('colleague work' / ask-colleague) with NO new operator flag required to arm it — detection is automatic and the response is advisory.
- An assignment exceeding the per-child budget triggers the recommendation; when the model acts, up to ~4 children each fit one window and are merged via the existing merge child — measured against the configured target.
- The contrast is real and toggleable: with the trigger disabled, the same oversize assignment degrades lossily or escalates with NO split offered — provable by toggling detection off in a test.
- Effective capacity on a successful split is ~children × per-child budget, strictly greater than one window, and no oldest history is dropped within a child solely because the PARENT assignment was oversize.
- No runtime dependency is added (dependencies=[] holds), no socket/daemon opens, and MAX_SUBAGENT_FANOUT/DEPTH are unchanged — guarded by tests/test_zero_deps.py and tests/test_boundary.py.
- A runtime-owned test exercises trigger→recommendation→subagents→merge and asserts it is offered identically for mock and vllm-openai (all-engines rule).
- With no trigger, an e2e mock run yields a byte-identical TaskResult shape and zero extra model turns (tests/test_e2e_mock.py).
- window_messages provably never drops messages[0]/messages[1] (head = messages[:2]); a test confirms the original assignment instruction survives the most aggressive windowing, so the split-authoring turn always sees it.

## Success signals

- An assignment that previously degraded lossily or hit a limit + escalated now instead surfaces a structured split recommendation that the model acts on via the 'subagents' tool, producing up to ~4 child hand-over assignments that are fanned out + merged — verified by a runtime-owned test that fires identically on mock and vllm-openai (all-engines rule).
- When neither the reactive trigger nor the up-front hint fires, behavior is byte-identical to today (a strict no-op): no extra model turn, no recommendation injected, TaskResult shape unchanged — guarded by the e2e shape test.

## Scope / boundaries

- This is a split/hand-over POLICY over the existing subagent runtime — NOT a multi-backend router/routing policy, NOT an execution sandbox, NOT a daemon, and it adds no runtime dependency, socket, or live MCP client. It does not raise MAX_SUBAGENT_FANOUT (4) or MAX_SUBAGENT_DEPTH (2); it does not replace graceful degradation or escalation, it sequences in front of them.

## Non-goals

- Not a forced auto-split gate: the runtime never splits the work itself against the model's judgment; it only detects + recommends.
- Not a separate planner subsystem: no new split-planner model turn, no heuristic file/token chop, no new merge/worktree code — the existing subagents machinery is reused verbatim.
- Not removing graceful degradation or escalation: degradation still windows within a child; escalation still fires when a split cannot be produced or still can't fit.

## Assumptions

- The reactive split is coherent because window_messages always preserves messages[:2] (system prompt + the original assignment text); so even on a degraded/windowed turn the model authoring the child briefs still sees the FULL original assignment, only intermediate working history was elided.

## Decisions

- Trigger mode is ADVISORY/backend-judged: the runtime detects 'too much' and injects a strong, structured split recommendation into the model's context; the model decides whether and how to split. Never a forced runtime gate (consistent with subagent delegation being optional).
- Detection is REACTIVE-primary: the trigger fires when graceful degradation's bounded overflow retries (_MAX_OVERFLOW_RETRIES) are exhausted — the well-defined point that today re-raises into escalation. A COARSE up-front token estimate of the task instruction acts as an early advisory hint only.
- The coherent split is authored by the MODEL using the EXISTING 'subagents' (plural) tool (which already takes a list of child instructions); the runtime does not run a separate split-planner turn and does not heuristically chop. Coherence stays where the intelligence is.
- Capacity is encoded as a TUNABLE target — children × per-child budget (default ~4 × 250k ≈ 1M tokens), structurally clamped by MAX_SUBAGENT_FANOUT=4 / MAX_SUBAGENT_DEPTH=2. The '1M target' is operator-adjustable but cannot exceed the existing caps.

## Hard questions

- risk: Real wall-clock speedup needs concurrent-request support on the served model (same caveat as parallel-subagents); on a serializing server the gain is bigger effective context + overlapped I/O, not compute parallelism.
- risk: Advisory means the model MAY ignore the recommendation and keep drowning; the runtime cannot guarantee a split happens, only that one is recommended. Mitigation/measurement is an open question.

## Open / follow-up

- How to MEASURE/ensure the model reliably acts on the advisory recommendation (vs ignoring it and continuing to drown) — a follow-up on recommendation efficacy + possible escalation-after-decline.

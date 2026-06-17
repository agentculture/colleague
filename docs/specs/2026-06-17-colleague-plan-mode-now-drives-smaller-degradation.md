# colleague plan mode now drives smaller, degradation-aware plan jumps — it stays robust on a smaller or reasoning served model where a monolithic one-shot proposal used to fail empty-handed, and it offers a spec-less quick-plan middle path for medium tasks

> colleague plan mode now drives smaller, degradation-aware plan jumps — it stays robust on a smaller or reasoning served model where a monolithic one-shot proposal used to fail empty-handed, and it offers a spec-less quick-plan middle path for medium tasks

## Audience

- An operator or Claude dogfooding colleague-as-planner (the diverse-second-mind) against a smaller or reasoning served backend such as the reference Qwen3.6-27B

## Before → After

- Before: The proposal seams (propose_claims/propose_plan_items in cli_driver.py) make two monolithic one-shot completions via to_simple_complete, which reads resp.content only and bypasses the loop's forced-synthesis (#191) and degradation (#154/#156) machinery; on the 27B the JSON lands in resp.reasoning with empty content so parse_claims raises ValueError
- After: colleague plan run completes the claims-proposal and plan-items-proposal stages on a reasoning model that emits its answer in the reasoning channel with empty content, instead of dying with 'no JSON object found in model output'

## Why it matters

- colleague-as-planner is the whole point of dogfooding plan mode with a diverse second mind; if it cannot run on the served reasoning model it is non-functional exactly where its value lies (filed live as #210)

## Requirements

- Plan proposals route through a robust JSON-completion helper that: (1) on empty content fires ONE forced no-thinking follow-up turn ('emit ONLY the JSON now, do not think step by step'), reusing the loop's _maybe_force_synthesis pattern; (2) if still empty, recovers the first balanced JSON object from resp.reasoning before failing; (3) classifies timeout/overflow via classify_degradable and shrink-retries bounded, like _complete_with_degradation
  - honesty: Unit tests simulate the three failure shapes — empty content, JSON-only-in-reasoning, and a classify_degradable timeout — and assert the helper recovers/retries rather than raising; a live 27B claims-proposal that previously raised 'no JSON object found' now parses
- to_simple_complete (or its robust successor) surfaces resp.reasoning to the recovery path instead of discarding it; the public CompleteFn/ModelResponse contract is unchanged
  - honesty: A unit test feeds a ModelResponse with content='' and reasoning carrying the JSON object and asserts the helper returns the parsed object; the CompleteFn/ModelResponse public contract is unchanged (no field added/removed)
- The robust proposal path fires identically for mock and vllm-openai (all-engines) and is a strict no-op for a run that already succeeds (non-empty content): TaskResult/plan-result shape byte-identical, e2e shape test green
  - honesty: The e2e mock shape test (tests/test_e2e_mock.py) passes unchanged, and a content-non-empty proposal path yields byte-identical Claim/PlanItem objects to the pre-change code (a regression test pins this)

## Honesty conditions

- Shipped behavior matches the announcement: a 27B plan run that used to fail empty-handed now completes both proposal stages
- The audience is real — this is the exact #210 dogfood path that failed live on Qwen3.6-27B
- The after_state is observable: the previously-raising run now returns parsed claims and plan items
- The before_state is accurate — to_simple_complete reads resp.content only (cli_driver.py:167) and parse_claims raises 'no JSON object found' on empty content
- The value holds — colleague-as-planner runs on the served reasoning model, not only on a hosted frontier model
- No new runtime dep, no socket/daemon, no router: the zero-deps guard and boundary tests stay green
- The success signal is checkable: an end-to-end plan run on the 27B and the mock e2e shape test both pass
- quick-plan still requires operator confirmation of the task split + waves at the plan level; it skips only the per-claim spec micro-cycle, never the plan-level gate

## Success signals

- A plan run on the reference 27B produces a parseable claims proposal and plan-items proposal end-to-end without raising; the mock backend stays byte-identical and the e2e shape test passes

## Scope / boundaries

- Not a multi-backend router, not a change to gate semantics (operator still gates every step, LLM proposals stay proposed), not an MCP/daemon/socket, no new runtime deps, runtime-owned and all-engines (fires for mock and vllm-openai)

## Decisions

- Chunk the proposal jumps smaller: propose the mandatory claim kinds first, then requirements + honesty conditions in a follow-up call; propose plan items in bounded batches conditioned on the prior set rather than one monolithic JSON
- Add a spec-less quick-plan path (colleague plan run --quick / --no-spec, #199) that skips the per-claim spec micro-cycle and goes straight to the plan stage from the request, still operator-gated at the plan level
- Close #204 with no new code — Engine.make_complete already landed (engine.py:82, vllm_openai.py:269, consumed at plan.py:153); the spec records it as done and the work is verify-and-close

## Hard questions

- risk: Chunking into more model calls raises latency/cost on a serializing server; bound the number of follow-up calls and keep each within the timeout so the cure is not slower than the monolith it replaces

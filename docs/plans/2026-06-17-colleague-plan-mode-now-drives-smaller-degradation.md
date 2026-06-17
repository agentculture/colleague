# Build Plan — colleague plan mode now drives smaller, degradation-aware plan jumps — it stays robust on a smaller or reasoning served model where a monolithic one-shot proposal used to fail empty-handed, and it offers a spec-less quick-plan middle path for medium tasks

slug: `colleague-plan-mode-now-drives-smaller-degradation` · status: `exported` · from frame: `colleague-plan-mode-now-drives-smaller-degradation`

> colleague plan mode now drives smaller, degradation-aware plan jumps — it stays robust on a smaller or reasoning served model where a monolithic one-shot proposal used to fail empty-handed, and it offers a spec-less quick-plan middle path for medium tasks

## Tasks

### t1 — Robust plan-proposal completion helper in cli_driver.py: empty-content forced follow-up + reasoning-channel JSON recovery + classify_degradable shrink-retry

- covers: c8, c9, c3, c4, c5, h1, h2, h7, h8, h9
- acceptance:
  - A robust completion wrapper detects empty/whitespace resp.content and issues ONE follow-up turn appending a 'respond with ONLY the JSON object now, do not think step by step' directive, then uses that content (the _maybe_force_synthesis pattern)
  - When content is still empty, the helper recovers the first balanced JSON object from resp.reasoning via _extract_json_object before raising ValueError
  - A timeout/overflow error classified by colleague.context.classify_degradable triggers a bounded shrink-retry (cap mirrors loop _MAX_TIMEOUT_RETRIES/_MAX_OVERFLOW_RETRIES), not a hard fail
  - Unit tests cover all three shapes (empty-content->follow-up recovers; content empty + JSON in reasoning -> recovered; classify_degradable timeout -> retried) AND a non-empty-content path returns byte-identical Claim/HonestyCondition objects to the current code
  - The public CompleteFn/ModelResponse contract is unchanged (no field added or removed); fires identically for mock and vllm-openai

### t2 — Chunk the proposal jumps smaller in cli_driver.py: mandatory claim kinds first then requirements+honesty in a second call; plan items in bounded batches

- depends on: t1
- acceptance:
  - propose_claims proposes the mandatory kinds first (announcement/audience/after_state/boundary/success_signal + before_state|why_it_matters), then requirements + honesty conditions in a SECOND bounded call conditioned on the first set
  - propose_plan_items proposes items in bounded batches (<=N per call) conditioned on the prior set rather than one monolithic JSON
  - Each chunk routes through the t1 robust helper; the follow-up call count is bounded so total latency stays within budget (the q1 latency risk)
  - A test asserts a multi-chunk proposal accumulates all items and that a single empty chunk does not abort the whole stage

### t3 — Spec-less --quick / --no-spec path for colleague plan run (#199): skip the per-claim spec micro-cycle, go straight to the plan stage, still operator-gated at plan level

- acceptance:
  - colleague plan run --quick (alias --no-spec) skips the spec-convergence micro-cycle and proposes plan items directly from the request
  - The quick path still gates at the plan level (operator confirms task split + waves; --yes auto-confirms); LLM proposals stay proposed
  - An e2e test on the mock backend asserts --quick reaches plan-items proposal WITHOUT running the spec stage, and the default (non-quick) path is byte-identical to before

### t4 — Verify-and-close #204: pin Engine.make_complete as a public seam (no production code change)

- acceptance:
  - A test asserts Engine.make_complete exists on the Engine base, mock inherits the default (NotImplementedError), and vllm-openai returns a working CompleteFn
  - #204 recorded as done in the changelog/PR; confirmed no production code change is needed

### t5 — All-engines strict-no-op regression + integration verification: e2e mock unchanged, byte-identical success path, zero-deps/boundary green

- depends on: t1, t2, t3
- covers: c12, c7, c1, c2, c6, h3, h5, h6, h10, h11
- acceptance:
  - tests/test_e2e_mock.py passes unchanged (robust path is a strict no-op for mock's non-empty content); TaskResult/plan-result shape byte-identical
  - A regression test pins that a content-non-empty proposal yields byte-identical Claim/PlanItem objects pre/post change
  - The zero-deps guard (tests/test_zero_deps.py) and boundary tests (tests/test_boundary.py) stay green — no new runtime dep, no new subprocess/thread consumer outside sanctioned modules
  - Every claim-kind and honesty-condition target traces to at least one assertion; the live 27B end-to-end plan run (manual, post-merge by the integrator) is noted as the c14/v1 live validation

### t6 — Docs + version bump: feature doc, CLAUDE.md plan-mode bullet, CHANGELOG, minor version bump

- depends on: t1, t2, t3, t4, t5
- acceptance:
  - A feature doc (docs/features/) documents the robust proposal path, chunking, --quick, and honest limits (the c14 live-27B bet and the q1 latency tradeoff)
  - CLAUDE.md plan-mode bullet updated; CHANGELOG entry added; version bumped (minor) via the version-bump skill

## Risks

- [unknown_nonblocking] Chunking adds model calls; on a serializing server total latency could exceed the monolith. Mitigate by bounding follow-up calls and keeping each within COLLEAGUE_TIMEOUT (task t2)
- [unknown_nonblocking] The c14 bet (27B emits content under the no-thinking follow-up) is verified only by a live plan run; the reasoning-recovery fallback is the insurance (task t1)

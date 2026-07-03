# Build Plan — Colleague drives with a cortex and senses: it resolves its minds by role from lobes — cortex (Qwen 3.6 27B @128K) the authoritative tool-calling mind working behind the scenes, senses (Gemma 4 12B @32K) the multimodal front door the operator talks to and hears back from — with the raw request preserved verbatim across the boundary, a senses layer that structurally cannot act, and the split architecture measurable against cortex-only.

slug: `colleague-drives-with-a-cortex-and-senses-it-resol` · status: `exported` · from frame: `colleague-drives-with-a-cortex-and-senses-it-resol`

> Colleague drives with a cortex and senses: it resolves its minds by role from lobes — cortex (Qwen 3.6 27B @128K) the authoritative tool-calling mind working behind the scenes, senses (Gemma 4 12B @32K) the multimodal front door the operator talks to and hears back from — with the raw request preserved verbatim across the boundary, a senses layer that structurally cannot act, and the split architecture measurable against cortex-only.

## Tasks

### t1 — t1 lobes contract client: new colleague/lobes.py resolving roles from the gateway (urllib GET /capabilities), parsing {role: {endpoint, model, context, ready, responsibilities}}, degrade-to-None on any error — pure stdlib, no subprocess, no new dep. Plan decision: HTTP transport (not CLI shell-out), re-resolved per run, no disk cache in v1.

- covers: c6, h1
- acceptance:
  - resolve_roles(url) returns cortex+senses metadata from a stub gateway fixture matching the lobes-cli#81 shape, with zero model ids originating in colleague
  - unreachable gateway / malformed JSON / missing role each return None (or partial with absent roles) without raising; no subprocess import (boundary test untouched)

### t2 — t2 contract additions: ContextPacket dataclass {original, interpretation, confidence, task_type, omissions} + optional Task.context_packet + omit-when-None TaskResult.senses block {mode, packet, records:[{point, latency, tokens, degraded}]} — the artifact shape for the whole arc.

- covers: c9, h4
- acceptance:
  - a Task/TaskResult round-trip with no senses involvement serializes byte-identical to today (no new keys)
  - a populated senses block round-trips through the artifact JSON with the packet's original text preserved verbatim

### t3 — t3 SensesConfig in colleague/config.py: mirror of DeepthinkConfig (model, base_url, api_key, context_budget default 24000 for the 32K window, multimodal declaration) resolved from COLLEAGUE_SENSES_* env > config.json senses section > absent; presence keyed solely on a resolved model. No lobes rung yet (t4).

- covers: c7, h2
- acceptance:
  - absent senses config resolves to None and EngineConfig serialization is byte-identical to today
  - env > config.json precedence pinned by test; deepthink section resolution untouched (existing tests pass unmodified)

### t4 — t4 lobes discovery rung in config resolution: when armed (COLLEAGUE_LOBES_URL env or config.json lobes section), EngineConfig.resolve + SensesConfig resolution consume t1's resolved roles as a defaults source — precedence explicit flag > env > config.json > lobes discovery > builtin; unreachable lobes degrades to the next rung with ONE stderr notice, never a hard-fail.

- depends on: t1, t3
- covers: c6, h1, c3, h10
- acceptance:
  - a config with zero model ids + a stub lobes gateway resolves cortex as main model and senses as SensesConfig; the precedence order including the lobes rung is pinned by test
  - lobes armed but unreachable: run proceeds on the next precedence rung with a stderr notice; lobes absent entirely: resolution byte-identical to today

### t5 — t5 colleague/senses.py invocation layer: run_senses_intake(text, config) -> ContextPacket|None and run_senses_speakback(summary, config) -> str|None — ONE bounded tools-off completion each via Engine.make_complete(config, tools=[]), windowed to the senses model's OWN budget via make_count_tokens (the deepthink.py pattern), degrade-never-raise, each invocation returning a {point, latency, tokens, degraded} record. A failed/lossy intake returns None so callers pass raw text through untouched.

- depends on: t2, t3
- covers: c8, h3, c11, h6
- acceptance:
  - no senses request ever carries a tool schema on the wire (asserted on the captured request payload)
  - an unreachable senses endpoint yields None + a degraded record; the caller's raw text is what proceeds (intake can never lose the request)
  - runtime records carry latency/tokens/degraded per point; no field asserts answer quality

### t6 — t6 loop + media-bridge integration (the hot-file task, solo wave): a Task carrying context_packet injects the ORIGINAL text verbatim as the user message with the packet as ONE advisory companion message; senses records fold onto TaskResult.senses; the c24 media bridge prefers a declared senses config (point recorded under senses) and falls back byte-identically to deepthink.multimodal when only deepthink is declared. All-engines: both backends inherit via ContextControls/make-bindings.

- depends on: t2, t5
- covers: c9, h4, c7, h2, c11, h6
- acceptance:
  - test asserts cortex's prompt contains the operator's original text verbatim whenever a packet is present, and the packet never replaces it
  - deepthink-only config: media bridge behavior + TaskResult.deepthink byte-identical to v1.34.0 (existing media tests pass unmodified)
  - senses-declared config: bridge point recorded under TaskResult.senses; mock engine records a degraded no-op identically (all-engines)

### t7 — t7 structural cannot-act proof (tests-only): senses invocations offer no tool surface and cannot mutate — even when the senses model emits tool-call-shaped output (literal markup or OpenAI tool_calls), nothing routes to ToolExecutor writes, run_command, or handoff; the packet path is data-only. Mirrors lobes forbidden_responsibilities = [final_decision, repo_action, security_decision].

- depends on: t5, t6
- covers: c8, h3
- acceptance:
  - a senses stub returning tool-call markup / tool_calls JSON produces a plain advisory packet or degraded record — repo tree provably untouched, zero ToolExecutor invocations
  - grep-level pin: colleague/senses.py imports neither tools.ToolExecutor nor subprocess (boundary-test style assertion)

### t8 — t8 session split-mode wiring: with senses resolved, session free-text runs senses intake (synchronous, v1 plan decision) -> ContextPacket -> execute_work with the packet on the Task; the final summary gets senses speak-back shaping for DISPLAY, with the raw cortex summary always retained in the artifact (plan decision: shaping is display-layer only). Per-run bypass --cortex-only flag on work/session; --debug-senses prints the packet to stderr; intake/speak-back timings recorded. cortex-only default: senses unresolved = byte-identical session.

- depends on: t4, t6
- covers: c10, h5, c2, h9
- acceptance:
  - with senses resolved, a session free-text line produces an artifact carrying mode=split + the packet + intake/speak-back timings; the displayed summary is shaped, the artifact summary is the raw cortex one
  - --cortex-only forces the unshaped path for one run and the artifact records mode=cortex-only; no senses config = byte-identical session (existing session tests pass)
  - --debug-senses surfaces the packet on stderr; intake degradation falls through to raw text with a visible notice, the run never fails

### t9 — t9 mesh-resident split-mode wiring: the [resident] appserver harness runs inbound mesh messages through senses intake (packet onto the work item) and shapes the reply via speak-back, under the c19 trust model unchanged (non-operator = read-only explorer or refused); base install stays byte-identical (no agent-lifecycle import at base; zero-deps + boundary pins untouched).

- depends on: t8
- covers: c2, h9, c10, h5
- acceptance:
  - a resident-mode inbound message with senses resolved produces a work item whose artifact carries the packet + mode, and the mesh reply is the shaped speak-back
  - senses unresolved: resident behavior byte-identical to v1.34.0; test_zero_deps + test_boundary pass unmodified

### t10 — t10 lobes introspection verb: a read-only 'colleague lobes' noun (rendered tool: show/overview + --json) displaying the armed state, resolved roles with their metadata, and the degradation rung actually in effect — plus explain/learn catalog entries and cross-surface parity.

- depends on: t1
- covers: c6, h1
- acceptance:
  - 'colleague lobes show' against a stub gateway renders all resolved roles + ready state; unarmed prints a clean 'not configured' (exit 0), unreachable shows the degradation honestly
  - explain entry + cross-surface parity test (registry == MCP catalog == learn) pass

### t11 — t11 byte-identical + all-engines proofs (tests-only): the arc-wide no-op guarantee — absent lobes/senses config leaves the e2e mock artifact shape, session behavior, and config serialization byte-identical to v1.34.0; with senses declared, mock and vllm-openai produce the same TaskResult.senses shape (mock = degraded no-ops); the role generalization added no base dep, no socket, no daemon.

- depends on: t6, t8
- covers: c1, h8, c4, h11, c10, h5
- acceptance:
  - test_e2e_mock passes unmodified with everything unset; a senses-armed mock run pins the full TaskResult.senses shape (all-engines)
  - test_zero_deps + test_boundary pass unmodified (lobes.py is urllib-only, senses.py subprocess-free)

### t12 — t12 docs + boundary line: feature doc docs/features/cortex-senses.md (architecture, config, modes, packet, measurement story, honest limits incl. the 32K intake window); CLAUDE.md architecture part + scope line recording this as the SECOND sanctioned increment at the router-exclusion boundary (senses-direct stays out -> #276, voice/retrieval -> #277); the why-it-matters hardware claims cite the 2026-07 rig probes; a no-'brain' vocabulary grep test; docs/live-testing.md rows added as PENDING.

- depends on: t11
- covers: c5, h12, c12, h7, c3, h10, c7, h2
- acceptance:
  - grep test fails the suite if 'brain' appears as role vocabulary in colleague code or docs (allow-listing historical/changelog text)
  - CLAUDE.md scope line names the boundary increment + the #276/#277 exclusions with rationale; feature doc's hardware claims cite the recorded probes

### t13 — t13 livecheck + measurement comparison: a cortex-senses livecheck scenario running the SAME task cortex-only and split against the live rig (real session/--attach surfaces), grading from artifact evidence (mode, packet, verbatim original, comparable runtime numbers) and honestly SKIPping when the rebalanced stack (cortex@128K + senses@32K) is not serving; docs/live-testing.md rows filled or PENDING.

- depends on: t8, t11
- covers: c17, h13, c4, h11, c11, h6
- acceptance:
  - livecheck emits per-mode wall-clock + senses runtime numbers from the two artifacts side-by-side, asserting only runtime facts (no quality score anywhere)
  - on a rig without the rebalanced stack the scenario reports SKIP with the reason, never a failure or a fabricated pass

## Risks

- [unknown_nonblocking] lobes-cli#81 is spec-only upstream (no plan/impl yet): the /capabilities contract shape could shift before it ships — t1 parses a fixture of the SPEC shape; if the shipped shape drifts, t1's fixture + parser update in one place
- [unknown_nonblocking] The rebalanced rig (cortex@128K + senses@32K co-resident) does not exist yet — lobes must land its REBALANCE requirement first; until then t13 livecheck rows stay PENDING/SKIP and the intake-latency plan decision (synchronous v1) rests on MTP numbers not yet measured
- [unknown_nonblocking] Deepthink/senses coexistence: an operator declaring BOTH gets disjoint surfaces (deepthink keeps judgment points, senses takes perception/presentation); the media bridge prefers senses when both are multimodal-declared — pinned in t6, revisit if a real dual-declaration operator appears

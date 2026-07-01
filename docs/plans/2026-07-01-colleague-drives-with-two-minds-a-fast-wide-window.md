# Build Plan — colleague drives with two minds: a fast wide-window main model does the driving, and a deepthink model is called in for the hard reasoning - dual-model on one rig, or single-model exactly as before

slug: `colleague-drives-with-two-minds-a-fast-wide-window` · status: `exported` · from frame: `colleague-drives-with-two-minds-a-fast-wide-window`

> colleague drives with two minds: a fast wide-window main model does the driving, and a deepthink model is called in for the hard reasoning - dual-model on one rig, or single-model exactly as before

## Tasks

### t1 — t1 Resolve dual-model deepthink config (colleague/config.py): a DeepthinkConfig carried on EngineConfig, precedence COLLEAGUE_DEEPTHINK_* env > .colleague/config.json deepthink section > absent = None

- covers: c8, h1, c2, h11
- acceptance:
  - resolve() yields deepthink=None with no env var and no config section, and the resolved EngineConfig is field-for-field identical to today (no-deepthink resolution test)
  - COLLEAGUE_DEEPTHINK_MODEL/_BASE_URL/_API_KEY/_CONTEXT_BUDGET env vars override the config-file deepthink section which overrides absent; base_url/api_key default to the main endpoint values; to_dict() redacts the deepthink api_key
  - nothing in code names lobes, gemma, or qwen: any pair of OpenAI-compatible endpoints resolves (test uses two arbitrary endpoints)

### t2 — t2 New colleague/deepthink.py: the one-shot completion seam - windowing to the deepthink budget, tools-off invariant, degradation, call records

- depends on: t1
- covers: c9, h2, c12, h4, c13, h5
- acceptance:
  - run_deepthink() issues exactly ONE tools-off completion via the public Engine.make_complete seam against the deepthink config and returns a call record {point, tokens, duration, degraded}; a test asserts NO tool schema is offered (the acceptance-self-check invariant class)
  - the prompt is windowed to the deepthink model's OWN context_budget BEFORE the request (per-endpoint /tokenize with char-heuristic fallback); an over-budget prompt never reaches the wire un-windowed
  - a dead port, request error, or overflow from the deepthink endpoint returns a degraded record naming the fallback and never raises out of the seam (dead-port test)

### t3 — t3 TaskResult.deepthink block (colleague/contract.py): optional per-run list of deepthink call records, omit-when-None

- covers: c14, h6
- acceptance:
  - TaskResult carries an optional deepthink field (list of {point, tokens, duration, degraded}) serialized omit-when-None: a result with zero calls serializes byte-identical to today (shape test on to_dict/from_dict round-trip)

### t4 — t4 The deepthink loop tool (colleague/tools.py + roles curation): backend-judged escalation the main model MAY call with a question plus self-composed digest

- depends on: t2
- covers: c10, c5, h14
- acceptance:
  - the deepthink tool schema is offered ONLY when dual config is present; a single-model run offers exactly today's tool list (schema-equality test)
  - the tool description instructs the main model to escalate JUDGMENT (verdicts, plans, tricky decisions), not mechanics, and to compose a digest that fits the deepthink budget; the executor dispatches to the deepthink seam
  - role curation is pinned by test: the tool is pure computation (no writes, no shell) and is available to read-only roles so a reviewer can escalate a verdict

### t5 — t5 Loop wiring + all-engines forwarding (colleague/loop.py + both engines): offer the tool, escalate the acceptance self-check, record calls, keep synthesis/compaction main-model-only

- depends on: t2, t3, t4
- covers: c10, c14, h6
- acceptance:
  - when dual config is present the acceptance self-check runs via the deepthink seam and degrades to the main model on failure; when absent the path is byte-identical (existing e2e mock shape test unchanged)
  - every deepthink call fired in a run lands on TaskResult.deepthink with its point label; both backends forward the deepthink config through ContextControls identically (all-engines test)
  - forced synthesis (#191) and fill-line compaction (#156) never touch the deepthink seam - a test asserts those paths complete against the main model even with dual config present

### t6 — t6 Plan-mode proposals drive the deepthink model (colleague/plan/cli_driver.py)

- depends on: t2
- covers: c10
- acceptance:
  - with dual config, plan-mode proposal completions route to the deepthink model via make_complete; without it, today's path is byte-identical (test injects a recording complete-fn and asserts the target model per config)

### t7 — t7 Test-integrity reviewer defaults to the deepthink model (colleague/config.py resolution)

- depends on: t1
- covers: c10
- acceptance:
  - with dual config and no explicit COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL, the reviewer model resolves to the deepthink model; an explicit value still wins; with no dual config the resolution is unchanged (precedence test)

### t8 — t8 Boundary test: the enumerated escalation surface is the complete reachable surface

- depends on: t5, t6, t7
- covers: c7, h15, h3
- acceptance:
  - a boundary test enumerates the modules allowed to invoke the deepthink seam (tools executor, acceptance self-check, plan proposals, reviewer default) and fails if any other colleague module imports or calls it
  - the feature doc's escalation list and out-of-scope wording (no automatic routing policy, no N-model generalization) are drift-tested against the enumerated surface

### t9 — t9 Byte-identical + zero-dep guards (tests only)

- depends on: t5
- covers: c1, h10, h1, c15, h7, c13
- acceptance:
  - test_e2e_mock passes unchanged: a single-model run's TaskResult JSON has NO deepthink key; a dual-config run on mock records deepthink as a degraded no-op instead of failing (lint fix-turn precedent)
  - tests/test_zero_deps.py passes with no new allow-list entry and the subprocess/threads boundary stays pinned to worktrees.py/subagents.py

### t10 — t10 Env-gated live dual-model proof + benchmark procedure

- depends on: t5
- covers: c16, h8, c3, h12
- acceptance:
  - a COLLEAGUE_DUAL_E2E=1-gated test drives a real work item on the rig where the main model calls the deepthink tool at least once and the artifact records the call (skipped cleanly when un-gated)
  - the wall-clock + quality benchmark (dual vs single, graded via the existing feedback loop) is scripted and documented; until it runs on the rig, docs/live-testing.md records the proof as PENDING - never declared validated

### t11 — t11 Docs: feature doc + CLAUDE.md bullet + the honest lines

- depends on: t5
- covers: c4, h13
- acceptance:
  - docs/features/deepthink.md and a CLAUDE.md architecture bullet describe the config shape, the enumerated escalation points, the degradation ladder, and the synthesis/compaction-stays-main decision with the window-size reason
  - the out-of-scope section still names automatic routing policy and N-model generalization as excluded; the before-state narrative matches shipped code (one model drives every turn today); multimodal input and mode-level model preference are recorded as parked follow-ups

## Risks

- [unknown_nonblocking] the served Gemma 4 tool-call parser on lobes is unproven (rig evidence #66: no tool-calling backend today) - blocks the LIVE proof and benchmark, not the build; mock pins the contract
- [unknown_nonblocking] deepthink digest composition (how much context the main model hands over, in what form) needs live tuning on the rig
- [unknown_nonblocking] per-model overlay semantics in a dual run (.colleague/<model>/ hooks, skills, profiles): working decision is overlays-follow-the-model-being-called; verify against layers.py exact-path isolation during t5 (task t5)
- [unknown_nonblocking] a single-GPU rig may serialize the two models under load, so deepthink calls add latency exactly when the rig is saturated - the benchmark must measure under realistic load

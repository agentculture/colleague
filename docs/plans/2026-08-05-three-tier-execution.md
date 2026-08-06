# Build Plan — three-tier execution

slug: `three-tier-execution` · status: `exported` · from frame: `three-tier-execution`

> Colleague gains an opt-in three-tier execution mode: senses relays the worker's answer faithfully, the worker drives the bounded tool loop, and cortex configures what the other seats run under — resolved by role name from the lobes gateway, byte-identical when unconfigured (#364, design brief #363)

## Tasks

### t1 — Propagate `finish_reason` end-to-end (unconditional observability)

- instruction: loop.py:370 ModelResponse gains `finish_reason` (default empty); `vllm_openai.py` already reads `finish_reason` near line 363 for stream termination — carry the value out of the accumulator. New artifact fields are additive, no renames (c12). mock sets deliberate finishes so `test_e2e_mock` shape stays green.
- covers: c4, h4
- acceptance:
  - ModelResponse carries `finish_reason`; the vLLM SSE accumulator's value reaches it instead of being dropped at stream termination
  - truncated / stopped / timeout / empty / deliberate are distinguishable states with tests; `__COLLEAGUE_NO_RESULT_PRODUCED__` never counts as a completed answer
  - the artifact records per-seat finish state + truncation on EVERY run, unconfigured included (decision c30); mock emits the same fields (all-engines rule)

### t2 — Structural senses relay fidelity in the existing lane

- instruction: senses.py + `senses_loop.py`/`senses_moves.py` only. Compose the grounding clause ('you can see only the status block you are given') and the fidelity clause (answer the current message from the current result first; background knowledge never replaces it) into every prompt-bearing senses surface; knowledge entries labeled optional background, placed before current content.
- covers: c5, h5
- acceptance:
  - with a worker answer present the displayed response contains it verbatim — structural containment test, not prompt hope
  - fidelity failure triggers raw-answer fallback and records a degradation; counters land: verbatim-presence, unrelated-knowledge repetition, fallback, truncation
  - the embodiment 6/6 domain-mismatch failure shape is a committed regression test; ContextPacket.original and tools=\[\] pins untouched

### t3 — Worker role resolution, loud refusal, same-origin key hygiene

- instruction: Add worker to lobes.py's optional roles (existing RoleInfo parse). config.py grows the explicit three-tier mode block — role NAMES only, never model-name parsing. Reuse `_same_origin` for the key rule. The refusal fires at resolution time, before any episode starts.
- covers: c3, h3, c25, h21
- acceptance:
  - lobes.py resolves worker as an OPTIONAL role; absence never errors a legacy run
  - explicit three-tier config with worker missing or undialable exits with a loud refusal naming the gap — no silent cortex-as-actor, tested on both fronts
  - a cross-origin worker dial never receives the main Bearer token (withheld default + notice); same-origin inherits — mirroring the deepthink/senses hygiene tests

### t4 — Typed change lattice + authority ceiling (refuse-whole)

- instruction: New module colleague/lattice.py: pure data + validation, no I/O, no subprocess. The catalog input is the resolved tool allow-list the loop already computes through roles.py + engine schema curation. worker may write only senses.knowledge (origin-stamped).
- covers: c6, h6, c13, h13
- acceptance:
  - a typed change unit exists with exactly the targets worker.tools / worker.prompt.strategist / worker.knowledge / senses.prompt.strategist / senses.knowledge and origins host/cortex/worker; every knowledge entry names its origin
  - the capability catalog derives ONLY from the task's resolved effective authority (no constructor mints from the executor); a change selecting an id outside the ceiling refuses the WHOLE unit with a recorded refusal
  - unknown/extra/forbidden keys refuse whole, never strip-and-retain; no operator-owned surface (approvals, hooks, command approvals, task roles, mode gates, handoff) is a valid target — tested

### t5 — Bounded task-local strategist prompt section via layers

- instruction: Compose through layers.py's existing path (`system_prompt_for` / `compose_role_prompt`) — injected once on Engine.`system_prompt`(), exact-path isolation preserved. The section is named, bounded, and absent renders nothing.
- depends on: t4
- covers: c7, h7
- acceptance:
  - baseline vs cortex-configured composed prompt differs in exactly ONE named task-local strategist section; base prompt, AGENTS layers, role prompts, skills, and operator text pinned unchanged by test

### t6 — Episode-boundary config lifecycle (synchronous review window)

- instruction: chain.py's between-episode window (plus before episode 1) is the ONLY application point; review runs synchronously on the calling thread. Default for children: subagents spawned inside an episode inherit the episode's resolved immutable config (risk r2). The loop seam edits live here — t8 must not touch loop.py.
- depends on: t4, t1
- covers: c8, h8, c26, h22
- acceptance:
  - the effective-config digest is constant across every model turn within an episode; a mid-episode proposal applies only at the next between-episode window; config discarded at top-level task end
  - a no-tool episode end increments the boundary counter — the T1 regression, tested
  - the diff adds no threading/concurrent.futures import anywhere; tests/`test_boundary.py` unmodified and green; proposal latency bounded + recorded

### t7 — Append-only config event stream on the artifact

- instruction: contract.py + artifact.py own this; additive fields only, no second durable store. Digest = deterministic hash over the replayed event sequence.
- depends on: t4, t1
- covers: c9, h9
- acceptance:
  - TaskResult carries the config event stream (proposed/refused/verified/applied/reverted) + effective-config digest; replaying events ALONE reproduces the digest — the baseline is itself an event (the T8 trap)
  - liveness counters advance in a live run; no surface reports tier health from armed alone

### t8 — Opt-in worker-as-actor resolution (strategist absent, deepthink absent)

- instruction: Delivery step 4: ship worker-as-actor BEFORE any configurator exists. config.py resolution + engines wiring only — the loop seam belongs to t6; do not touch loop.py here.
- depends on: t3
- covers: c12, h12
- acceptance:
  - with three-tier config the worker drives the tool loop and cortex does not act; a muse advert present alongside three-tier config constructs no DeepthinkConfig — tested
  - every legacy deepthink test stays untouched and green; no flag, artifact field, or public contract renamed

### t9 — Seat-aware attribution: no cortex label on the worker's work

- instruction: attribution.py's `CORTEX_STATUS_LABEL` becomes seat-aware; livecheck.py:544 narration follows; sweep cockpit/TAUI/presence for actor-naming strings. Legacy path renders the exact current strings.
- depends on: t8
- covers: c24, h20
- acceptance:
  - a three-tier run renders worker-attributed status lines — zero cortex-working lines while the worker acts
  - a legacy run's lines are byte-identical to today's — pinned by test

### t10 — Doctor three-tier readiness group

- instruction: Extend the doctor rubric; the network checks ride --probe like `provider_reachable`. This kills the #363 section-7 deafness class (healthy-looking mesh agents on a stale model id).
- depends on: t3
- covers: c27, h23
- acceptance:
  - doctor reports worker advertised + dialable + tool-calling probe + served-model-id-matches-advert; a mismatched id FAILs naming the exact id and exits 1 while role discovery alone still passes — committed test

### t11 — Opt-in cortex configurator through the lattice

- instruction: Delivery step 7, LAST of the build tasks by design. Cortex consumes episode summaries/snapshots, emits lattice units; nothing cortex-authored reaches the worker's message history.
- depends on: t5, t6, t7, t8
- covers: c19, h16
- acceptance:
  - cortex proposes typed change units only; the worker's conversation contains zero cortex-authored advisory prose and its completion seam is never wrapped by a strategist model — pinned by test
  - proposals verify then apply only at sanctioned windows; refusals recorded on the event stream; the configurator is opt-in and off by default

### t12 — Re-pin the structural gates: byte-identical, loud refusal, finish-state CI

- instruction: Tests + CI wiring only — no production code. This is the audience pin (c17/h14): legacy operators, agent callers, --json/piped fronts, resident all observe zero change.
- depends on: t1, t3, t8
- covers: c11, h11, c17, h14, c21, h18
- acceptance:
  - the byte-identical suite (mock + vllm-openai) asserts no-config behavior + existing-field identity AND presence of the new finish fields — scoped per decision c30
  - the three-tier-without-worker refusal test runs on both fronts; finish-state, refusal, and byte-identical tests all run in the default CI pytest job

### t13 — Experiment A: senses fidelity gate (pre-registered, committed)

- instruction: Matched domain-mismatch design from #364: seed senses knowledge with repeated domain-A facts, ask domain-B questions, provide a good worker answer; measure whether the current question is addressed and the worker answer stays visible.
- depends on: t1, t2
- covers: c22, h19, c10
- acceptance:
  - runs through the experiment noun with the embodiment failure shape as fixture; result committed; measures verbatim-visibility 6/6, unrelated-knowledge replacement 0/6, attribution 6/6, plus fallbacks, latency, truncation

### t14 — Experiment B: worker promotion, live performs-better (c23 gate)

- instruction: The probes retired protocol risk (c28 native `tool_calls`; c29 window 262144). Tune `max_tokens` from measured truncation (risk r1) before the scored runs. Real tasks: multi-step read/edit/test/finish with gates and handoff.
- depends on: t12, t8
- covers: c10
- acceptance:
  - pre-registered live comparison worker vs acting cortex on colleague's real surface: completion rate, tool-protocol failures, truncation/empty rate, latency, tokens, operator-graded quality; result committed
  - per operator decision c23 the live performs-better verdict lands BEFORE the delivery summary and the cicd PR leg

### t15 — Experiment C: strategist value + off-by-default pin

- instruction: This is the experiment that does not exist yet in either repo (#363 section 5's caveat): give the strategist something real to fix. A negative verdict ships the arc anyway — worker + senses tiers stand alone.
- depends on: t11
- covers: c10, h10
- acceptance:
  - pre-registered misconfigured-actor experiment (repo-A conventions, repo-B task, correctly configured control) through the experiment noun; result committed; counts detection, proposed/verified/applied changes, later outcome, false interventions, latency, tokens
  - a test holds the strategist opt-in and OFF until a supporting verdict is committed — the three standing negatives keep it off otherwise

### t16 — Docs: eighth increment record + legacy/three-tier distinction

- instruction: Also record the non-goals honestly: nothing imported from embodiment (#358 separate), no multi-gateway merging, no durable cross-task promotion, retrieval lane still parked.
- depends on: t8, t11
- covers: c2, h2, c18, h15
- acceptance:
  - CLAUDE.md's v1 scope line gains increment (8) with FIXED-surface wording; docs/features/three-tier.md lands; cortex-senses/deepthink/senses feature docs gain the legacy vs three-tier distinction (cortex-only keeps its legacy meaning); the c30 convention change is recorded the way #313 and WorkStats were
  - before-state citations name the real records: embodiment 0.14.0 live-test-results + colleague code facts (loop.py:370, lobes.py)

### t17 — Live three-seat proof + arc wrap

- instruction: The wrap order per c23: this live proof + experiment B's performs-better verdict land, THEN /summarize-delivery, THEN the cicd PR.
- depends on: t9, t10, t13, t14, t15, t16
- covers: c1, h1, c20, h17
- acceptance:
  - one recorded live session on the rig demonstrates: worker acted, senses preserved the answer verbatim (or a recorded fallback fired), a cortex change applied between episodes, counters advanced, per-seat finish states recorded — in docs/live-testing.md
  - the same commands without three-tier config behave byte-identically (t12 suite re-run at wrap); rig facts re-probed before the proof

## Risks

- [unknown_nonblocking] the worker's `max_tokens` truncation budget is untuned (window measured 262144, but the embodiment session truncated 5/6 turns at 16000) — tune from t1's `finish_reason` data before experiment B's scored runs (task t14)
- [unknown_nonblocking] subagent children spawned inside a worker-driven episode: default is inherit the episode's resolved immutable config (frame park v2) — revisit only if the T1/T8 tests surface a conflict (task t6)
- [unknown_nonblocking] experiment A may return a negative fidelity verdict on gemma-4-12B (the embodiment session precedent) — the raw-answer fallback is the shipped floor; a negative verdict blocks only free-form senses rewriting, not the arc (task t13)
- [unknown_nonblocking] experiment C may repeat the three standing strategist negatives — the strategist then stays off and the arc ships worker + senses tiers alone; this outcome is acceptable and pre-declared (task t15)
- [unknown_nonblocking] same-wave file-overlap hazard: t6 owns the loop.py seam and t8 owns config.py/engines wiring — both instructions scope ownership explicitly; the workforce merge gate re-runs tests per merge to catch any crossing

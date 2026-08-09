# Build Plan — post-387 program: evaluator rename + self-learn specificity + headless SSE

slug: `post-387-program-evaluator-rename-self-learn-speci` · status: `exported` · from frame: `post-387-program-evaluator-rename-self-learn-speci`

> colleague lands the post-#387 program: headless work streams SSE so turn generation time decouples from the socket timeout (#393); self-learning lessons become answer-shaped — pattern + constant + reason — with retrieval-precision instrumentation and store hygiene (#396 step 3); and the three-tier roles sharpen, renaming the strategist seat to evaluator in line with #397's thought→action→coherence authority split.

## Tasks

### t1 — Arm headless SSE streaming default-ON with env opt-out (#393)

- instruction: Decouple 'stream' from the delta sink in colleague/engines/`vllm_openai.py`:`_build_chat_payload` (line ~810): streaming arms when `on_delta` is set OR headless streaming is enabled (default true, env `COLLEAGUE_STREAM`=0 disables). Use a no-op delta sink or a payload-level flag — do NOT touch the `on_delta` seam semantics used by session/cockpit (work.py:594-632). `_stream_or_blocking` stays the transport.
- covers: c2, h2, c3, h3
- acceptance:
  - with no delta sink and opt-out unset, the vllm-openai chat payload carries stream:true + `stream_options` (`include_usage`) on headless work
  - `COLLEAGUE_STREAM`=0 restores the blocking request path byte-identically (payload has neither SSE key)
  - the existing mid-stream→blocking same-turn fallback and keepalive tolerance tests stay green unchanged
  - tests/`test_e2e_mock.py` passes unchanged — mock and vllm-openai result shapes identical on all three paths (streaming, blocking, opt-out)
  - streaming stalls still classify as request timeouts for #268 survival (test), and the backpressure-under-streaming decision (#255 thresholds kept or re-keyed) is recorded in the feature doc
  - streaming arms engine-uniform: every vllm-openai completion (acting, deepthink, senses, evaluator seats) carries the same SSE payload rule

### t2 — Live-validate headless streaming on the reference rig

- instruction: Run the same task class that produced the #387 finish-turn timeout kill (see docs/experiments/2026-08-08-prove-self-learning-387-arms/) against the 35B worker rig with streaming default-on; record the row verbatim. Operator-gated: needs the live rig.
- depends on: t1
- covers: c30, h23
- acceptance:
  - a docs/live-testing.md row records a headless run with at least one turn >300s completing with 0 socket-timeout kills, per-turn ceiling no longer tracks `COLLEAGUE_TIMEOUT`

### t3 — Replace the lesson schema: pattern + constant + reason (#396)

- instruction: Replace `_REQUIRED_KEYS` and the field vocabulary in colleague/lessons.py; keep `MAX_FIELD_LENGTH`-style bounds and the refuse-whole stance verbatim. 'constant' means the specific repo anchor (an identifier, value, path, or invariant) the lesson pins — validation should reject a lesson whose constant field is generic prose. Update tests/`test_lessons`\*.py.
- covers: c8, h7, c39
- acceptance:
  - colleague/lessons.py validates exactly the new answer-shaped keys refuse-whole (missing/extra/empty/over-length keys refuse the WHOLE lesson, no partial repair)
  - a g3-latch-style lesson (concrete pattern + constant + reason) validates; a process-narrative lesson without a constant is refused whole with the honest no-lesson-extracted marker
  - no dual-schema validator exists; already-stored 3-key lessons recall as legacy free text without error
  - component target, artifact ids, evidence source, and provenance live in record METADATA or a versioned schema envelope — never ad hoc keys in the validated payload; payload keys stay exactly the versioned schema's

### t4 — Move distill + code-lesson authors onto the new schema

- instruction: Touch colleague/distill.py (the detached child's prompt + lessons.py validation call) and colleague/correction.py (`build_code_lesson` field mapping). Author precedence (deepthink/muse > armed-lobes main > rung-1 floor) stays byte-identical.
- depends on: t3
- covers: c8, h7, c38, h30
- acceptance:
  - distill.py's author prompt requests and validates the new pattern/constant/reason shape; the distill.json outcome and alive-counters surface unchanged
  - correction.py `build_code_lesson` emits the same answer-shaped fields from a correction-diff hunk; honest no-diff behavior unchanged
  - distillation author resolution refuses the evaluator seat in the armed mode unless a distinct distiller authority is declared (test pins the split even on a shared checkpoint)

### t5 — Retrieval-precision instrumentation on TaskResult.memory

- instruction: Extend the memory exchange record built in colleague/loop.py's recall-before path and documented at contract.py:1567-1574. The scoring rule must be deterministic (e.g. lesson id/slug match against the task's failure class), never LLM judgment at record time. This is what makes the #394 rerun's learning CURVE measurable at N≥16.
- covers: c9, h8, c31, h24
- acceptance:
  - TaskResult.memory gains per-task precision fields (e.g. `relevant_recalled`/`top_k` outcome) computed from artifact-recorded recall results by a pre-declared deterministic rule, omit-when-None serialization preserved
  - a memory-less run serializes byte-identically (no new key)
  - the rule for 'class-relevant' is documented in the feature doc and testable without post-hoc judgment

### t6 — Recall thresholding + supersedes hygiene, colleague-side

- instruction: Filter in colleague/memory.py's recall()/`build_recall_block`() over the score/signal fields the eidetic CLI already returns — no new eidetic verbs (that follow-up is parked cross-repo). Keep `RECALL_BLOCK_CAP` as the final bound.
- depends on: t5
- covers: c10, h9
- acceptance:
  - a below-threshold record (by eidetic's returned score/signal fields) is excluded from the injected recall block AND the exclusion is recorded on TaskResult.memory — traceable, never silent
  - superseded records (supersedes metadata present on a sibling hit) are dropped in favor of the superseding record
  - with thresholding env-disabled, recall behavior is byte-identical to today

### t7 — Rename strategist → evaluator across the living surface (#397)

- instruction: Mechanical sweep: lattice.py Target values (worker.prompt.evaluator / senses.prompt.evaluator) + `_STRATEGIST_TARGETS`, layers.py compose section + seat constants, contract.py `_STRATEGIST_TARGET_VALUE` + `strategist_sections` record keys, configlifecycle.py snapshot, configurator.py prompt vocabulary, engine.py seam, subagents.py, work.py, the 13 test files (incl. renaming `test_layers_strategist.py` / `test_engine_strategist_seam.py`), docs/features/three-tier.md + the CLAUDE.md bullet. ConfigEvent.target parses free-form (configevents.py:147) so persisted artifacts need no migration — prove it with the compat test.
- covers: c4, h4, c5, h5, c6, h6
- acceptance:
  - grep -ri strategist over colleague/ and tests/ returns zero hits after the rename
  - git diff touches nothing under docs/specs/, docs/plans/, docs/deliveries/, docs/experiments/, or .devague/
  - a pre-rename artifact carrying worker.prompt.strategist `config_events` loads and --continue s without error on the renamed code (compat test committed)
  - the full existing three-tier suite passes with only vocabulary-level diffs

### t8 — Thought contract: typed, versioned, raw-input-preserving

- instruction: New module (e.g. colleague/thought.py), pure stdlib, refuse-whole validation mirroring lattice.py's unknown-key stance. Reuse ContextPacket.original for immutable raw-input preservation — do not copy text into the thought as the only record.
- covers: c21, h14, c36
- acceptance:
  - a Thought dataclass carries `thought_id`/supersedes/`observation_refs`/intent/why/constraints/`success_conditions`/uncertainties with strict validation
  - a thought embedding an executable tool call is refused at validation
  - the raw operator input reads back byte-identical from the artifact alongside the thought (ContextPacket.original seam)
  - the Thought contract distinguishes presence-mode output from committed thoughts: presence prose carries no action-authorizing fields, and only a committed Thought grants action-planning authority

### t9 — ActionProposal contract bound to its thought

- instruction: Same module family as the thought contract (e.g. colleague/actionproposal.py or shared thought.py) — keep file-disjoint from loop.py; wiring happens in t13. The worker's consequential field is evidence; host classification is authority (t13).
- depends on: t8
- covers: c22, h15
- acceptance:
  - every consequential ActionProposal names exactly one `thought_id` with `expected_effect` + `evidence_refs`; a proposal without a live `thought_id` is refused
  - an action referencing a superseded `thought_id` is refused with a legible reason (routes back through evaluation, never silently retargeted)

### t10 — Evaluation contract: closed verdicts, tools-off envelope

- instruction: New module (e.g. colleague/evaluation.py): the envelope builder + verdict parser over a tools-off completion (`senses_moves.py`'s prompted-JSON pattern is the precedent — nothing tool-shaped on the wire). Alignment-is-not-permission is the load-bearing invariant: encode it as a test, not a comment.
- depends on: t8
- covers: c23, h16
- acceptance:
  - the evaluation result validates only the closed vocabulary (verdict + route ∈ {execute, rethink, replan, block}); an unknown verdict/route string refuses whole
  - a 'block' route can never reach execution; an 'aligned' verdict still passes approvals/hooks/policy before execution (test proves alignment cannot execute a gated command)
  - the evaluator input is a bounded thought/action/evidence envelope — a test proves worker conversation history is not in it

### t11 — Evaluation ledger: one traceable chain on the artifact

- instruction: New record types in contract.py (dep on t5 is file-serialization: both touch contract.py). Append-only with a digest, following configevents.py's `to_dict`/`from_dict` + digest conventions — but a separate surface: configuration and intention answer different questions.
- depends on: t9, t10, t5
- covers: c24, h17
- acceptance:
  - thought, action, evaluation, reroute, execution, and outcome append to one ledger surface on TaskResult (omit-when-None), DISTINCT from `config_events`/EpisodeConfigLifecycle
  - given the ledger alone, a test reconstructs which thought produced which action, verdict, route, and outcome for a full episode
  - each entry carries actual contributing seat/model attribution mirroring the config-events conventions

### t12 — Mode arming: independent opt-in, roles by name, byte-identical unarmed

- instruction: Mirror three-tier's arming shape in colleague/config.py + lobes.py role resolution. Pinning tests in the style of the three-tier byte-identity suite (see docs/features/three-tier.md § Honest limits for the existing pinning-test inventory).
- depends on: t8
- covers: c26, h19, c17, h10
- acceptance:
  - a distinct config.json key / env var arms the mode (not `three_tier`); unarmed = byte-identity pinning tests over the landed three-tier suites pass with zero diffs
  - seats resolve BY ROLE NAME from the lobes /capabilities contract; a rig missing a required role refuses to arm with a legible reason — never model-name parsing, never silent fallback
  - deepthink stays absent in this mode (as in three-tier)

### t13 — Control-loop wiring: front commits, worker acts, evaluator routes

- instruction: The boundary list is an enumerated constant. The host owns consequential-action classification (worker's consequential field is evidence only). Dep on t7 so the rename lands before this wiring builds on the evaluator vocabulary.
- depends on: t11, t12, t7
- covers: c25, h18, c29, h22, c33, h26, h28
- acceptance:
  - the front loop (`senses_loop.py`/`presence_engine.py` reuse) commits typed Thoughts; the front seat has no repo tools offered
  - the evaluator is invoked ONLY at the enumerated deterministic boundaries (initial plan commit, host-classified consequential actions, declared infeasibility/ambiguity, drift threshold, episode completion) — a test proves ordinary tool calls do not invoke it
  - rethink routes to the front, replan to the worker under the unchanged thought; host policy/approvals remain the execution gate on every route
  - loop.py's diff is wiring, not rewrite; chain.`CONTINUABLE_REASONS` pin test untouched
  - with the mode armed, flight/senses-direct guidance routes to the FRONT as observations; a mid-run objective change produces a new/superseded thought and the worker's next consequential action names the new `thought_id` (test)
  - mid-action supersession is complete-then-re-evaluate; evaluator seat loss is bounded-retry-then-block with a legible reason (both per the c35 decision)
  - a presence-mode utterance implying an objective produces NO ActionProposal — action planning requires a committed `thought_id` (test); the front's two cadences (presence: thinking off / commitment: bounded thinking) are wired per c36

### t14 — Experiments A–C: pre-registered bars, honest tabulation

- instruction: Follow the #387 ledger discipline (docs/experiments/2026-08-08-prove-self-learning-387-arms/ is the template). Dep on t1: run the arms with streaming landed so the timeout confound is gone. Adversarial cases in A where conversational context conflicts with the latest explicit request. Execution is operator-gated (live rig).
- depends on: t13, t1
- covers: c27, h20, c32, h25, c25
- acceptance:
  - protocol docs for A (thought preservation), B (thought-to-action evaluation), C (end-to-end value vs landed three-tier and worker-only) are committed with pre-registered bars in a PR that PRECEDES any results commit (provable from git history)
  - experiment B's five mismatch classes + expected verdicts are pre-registered verbatim from issue #397; the bar: ≥4/5 mismatch classes detected, 0 false blocks on aligned pairs
  - results tabulate verbatim, falsifying wording never softened; no default flip from structural tests alone
  - evaluator invocations per episode stay within the enumerated boundary count (measured in C)
  - experiments report false approvals AND false rejections; the front model is promoted to decision authority only on experiment A evidence (intent-quality gain without becoming the bottleneck) — Gemma stays a candidate, not a requirement

### t15 — Docs: feature docs, CLAUDE.md tenth increment, evidence-cited framing

- instruction: Follow the repo's feature-doc pattern (a few lines in CLAUDE.md + the deep detail in docs/features/ linking spec/plan). The default-posture table (streaming default-on, schema mandatory, mode opt-in) covers h12.
- depends on: t13
- covers: c18, h11, c19, h12, c20, h13, c28, h21
- acceptance:
  - a docs/features/ page for the thought→action→evaluation mode documents the authority contract, closed vocabulary, invocation boundaries, seat-loss/supersession decisions, and honest limits; three-tier.md updated for the evaluator vocabulary
  - the CLAUDE.md v1-scope section gains the tenth sanctioned increment with the NEVER-a-routing-policy language and enumerates every newly consumed role surface
  - before/after/why claims in the docs cite their evidence (#387 run docs, three-tier.md) and the cognition-placement claim stays framed as a hypothesis experiment C measures — never asserted as proven

### t16 — Delivery: three separately mergeable lane PRs, versioned

- instruction: Sequencing honors c12: the SSE PR merges first, then self-learn, then the mode arc. Use the version-bump + cicd skills per PR. This task is the wrap/accountability leg — /summarize-delivery closes it.
- depends on: t2, t6, t14, t15
- covers: c1, h1
- acceptance:
  - the three lanes land as separately mergeable PRs (SSE; self-learn; evaluator/mode) each with its own version bump + CHANGELOG entry; no lane's failure blocks another's merge
  - each PR passes the full CI gate (black/isort/flake8/bandit/pytest/teken/version-check)

### t17 — Component-attributed, role-scoped lessons + evidence linkage

- instruction: Builds on t3's metadata envelope and t11's ledger ids. Role-scoping rides recall metadata filters in memory.py (colleague-side, per the c16 decision); component attribution is deterministic where possible (which seat's artifact the evidence cites). The existing flywheel guard (self-learning arc) is the precedent to extend, not replace.
- depends on: t3, t11
- covers: c37, h29, c39, h31, c36
- acceptance:
  - every distilled lesson's metadata attributes the failed component (front/worker/evaluator/system) and links thought, action, evaluation, outcome, and qualifying external evidence ids
  - a lesson whose only evidence is an evaluator verdict is refused at distillation (the flywheel guard extended)
  - recall-before injects only lessons scoped to the recalling role, or explicitly cross-role-marked ones; the task-local trace is discardable after distillation

## Risks

- [unknown_nonblocking] thought lifecycle across --until-done chaining + fill-line compaction — the active thought must survive episode boundaries and validated compaction (parked frame v5); pin during t13's wiring (task t13)
- [unknown_nonblocking] subagent consequential actions under the armed mode — v1 stance (attribute to parent thought vs out-of-scope) must be decided and documented during t13 (task t13)
- [unknown_nonblocking] front (12B) context exhaustion under continuous conversation + growing thought ledger — watch during experiment C (frame v6) (task t14)
- [unknown_nonblocking] out-of-repo artifact consumers may read `strategist_sections` keys — mesh-side sweep before the rename PR merges (frame v4) (task t7)
- [unknown_nonblocking] experiments and live validation are operator-gated on the reference rig's availability (t2, t14) (task t14)

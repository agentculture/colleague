# post-387 program: evaluator rename + self-learn specificity + headless SSE

> colleague lands the post-#387 program: headless work streams SSE so turn generation time decouples from the socket timeout (#393); self-learning lessons become answer-shaped — pattern + constant + reason — with retrieval-precision instrumentation and store hygiene (#396 step 3); and the three-tier roles sharpen, renaming the strategist seat to evaluator in line with #397's thought→action→coherence authority split.

## Audience

- colleague operators running lobes-armed multi-model rigs (reference rig: Gemma 12B front / Qwen 35B acting / Qwen 27B evaluator — seats resolved BY ROLE, never by parsing model names) plus the self-learning lane's experimenters

## Before → After

- Before: headless turns block on full completion so the request timeout is a per-turn generation ceiling (#387: 300-430s turns vs the 600s ceiling, one task killed on its finish turn); process-shaped lessons produce identical traces (exp-1) while answer-shaped ones transform behavior (5x); and in the landed three-tier mode cognition sits with the worker — the front only relays, cortex only configures between episodes
- After: headless runs stream so only a genuine stall times out; rung-2 distills and code-lessons carry pattern + constant + reason; recall is precision-instrumented and thresholded; and an opt-in thought→action→evaluation mode has the front committing typed Thoughts, the worker realizing them, and a tools-off evaluator returning closed fidelity verdicts — with the strategist vocabulary gone from the living surface

## Why it matters

- \#387's falsifying evidence identified lesson SPECIFICITY as the variable and the timeout confound as rerun-corrupting; and the current authority split may place cognition in the wrong seat — the operator converses with the front continuously, so intent should be committed where it is perceived

## Requirements

- headless SSE (#393): `vllm_openai`.`_build_chat_payload` arms streaming solely off config.`on_delta` (line 810) and headless work passes None (cli/`_commands`/work.py:630) — arm streaming for headless work (no-op delta sink or an engine stream knob) while keeping `_stream_or_blocking`'s mid-stream→blocking same-turn fallback and keepalive tolerance unchanged
  - honesty: with streaming armed headless, a turn generating longer than the socket timeout completes; a genuine stall (no chunks for the timeout window) still fails fast
- evaluator rename (#397): rename the strategist vocabulary to evaluator across the LIVE three-tier surface — lattice.py Target.`WORKER_PROMPT_STRATEGIST`/`SENSES_PROMPT_STRATEGIST` + `_STRATEGIST_TARGETS`, layers.py `compose_strategist_section` + seat constants (~45 refs), contract.py `_STRATEGIST_TARGET_VALUE` + `strategist_sections` record keys, configlifecycle.py snapshot, configurator.py prompt text (the target-name vocabulary the cortex model must emit), engine.py prompt seam, subagents.py snapshot, work.py, 13 test files (220 refs), docs/features/three-tier.md
  - honesty: after the rename, grep for 'strategist' over colleague/ and tests/ returns zero hits; dated docs (specs/plans/deliveries/experiments) still contain it
- lesson specificity (#396 step 3): rung-2 distills and code-lessons carry answer-shaped substance — pattern + constant + reason — not process narrative; touches lessons.py (the strict refuse-whole 3-key cause/lesson/`next_delta` schema, `MAX_FIELD_LENGTH` 1000), distill.py (the detached child's author prompt + validation), and correction.py `build_code_lesson` (area/pattern fields, low-confidence default)
  - honesty: the g3-latch class of lesson (pattern + constant + reason) validates under the new schema and a process-narrative lesson without a constant is refused whole
- retrieval-precision instrumentation (#396): TaskResult.memory already records {query, recalled, `injected_chars`, `lesson_recorded`} (contract.py:1567) — extend to score per task whether the class-relevant lesson surfaced in top-k when one existed (the #394 addendum shows injections near-saturating `RECALL_BLOCK_CAP` by g7: selection, not store size, becomes binding)
  - honesty: given a store holding a class-relevant lesson, the artifact records whether it surfaced in top-k — measured on a real run, not synthetic recall output
- store hygiene (#396): the recall-before path (memory.py recall, `top_k`=5, `RECALL_BLOCK_CAP`=4000, `build_recall_block`) gains relevance thresholding and consolidation/supersedes handling — a mechanism for the operator's decline-risk (too much context, wrong lesson surfaced), not hope; eidetic already returns per-record score/signal fields to threshold on
  - honesty: with thresholding on, a below-threshold record is excluded from the injected block AND the exclusion is visible in TaskResult.memory (traceable, never silent)
- thought contract (#397): the front produces a typed, versioned Thought (intent, why, constraints, `success_conditions`, uncertainties, supersedes, `observation_refs`) while the raw operator input is preserved separately and immutably (ContextPacket.original is the existing seam) — a thought never encodes executable tool calls and never becomes a lossy replacement for the input
  - instruction: verify: a Thought dataclass with version/supersession; a test proving the raw operator text survives verbatim alongside the thought; front seat has no repo tools offered
  - honesty: a thought that attempts to embed a tool call is refused at validation; the raw operator input is byte-identical when read back from the artifact
- action contract (#397): every consequential worker action names exactly one active `thought_id` with `expected_effect` and `evidence_refs`; the worker may report a thought infeasible/underspecified but cannot silently substitute a different objective
  - instruction: verify: ActionProposal typed with `thought_id` required; a test that an action without a live `thought_id` is refused
  - honesty: an action referencing a superseded `thought_id` is refused with a legible reason routing back through the evaluator, not silently retargeted
- evaluation contract (#397): the evaluator is tools-off and answers ONE question — does this action faithfully realize this thought under the available evidence — returning only the closed vocabulary verdict + route (execute | rethink | replan | block); rethink returns to the front, replan to the worker under the unchanged thought; alignment is never permission (host policy/approvals stay the hard authority)
  - instruction: verify: closed-vocab enum; a test that an unknown verdict/route string refuses whole (lattice unknown-key stance); a test that block never executes; evaluator receives a bounded thought/action/evidence envelope, not worker conversation history
  - honesty: an 'aligned' verdict still passes through approvals/hooks/policy before execution — a test proves evaluator alignment cannot execute a gated command by itself
- evaluation ledger (#397): thought, action, evaluation, rerouting, execution, and outcome are recorded in one traceable chain on the artifact, DISTINCT from EpisodeConfigLifecycle (configuration and intention answer different questions) — append-only, with actual contributing seat/model attribution
  - instruction: verify: a new ledger surface on TaskResult (omit-when-None), not folded into `config_events`; digest/attribution mirrors the config-events conventions
  - honesty: given the ledger alone (no worker history), a reviewer can reconstruct which thought produced which action, verdict, route, and outcome for a full episode
- invocation policy (#397): the evaluator sits at deterministic boundaries only — initial plan commit, host-classified consequential actions, declared infeasibility/ambiguity, drift threshold, episode completion — NEVER on every tool call; the host owns consequential-action classification (the worker's consequential field is evidence, not authority)
  - instruction: verify: the boundary list is an enumerated constant; a test that ordinary tool calls do not invoke the evaluator
  - honesty: in experiment C, evaluator invocations per episode stay bounded by the enumerated boundary count — the 27B seat is never observed on ordinary tool calls
- mode arming (#397): the thought→action→evaluation mode is an INDEPENDENT opt-in (config.json key or env var, distinct from `three_tier`) resolved BY ROLE NAME from lobes; absent = byte-identical including the landed three-tier mode's behavior; deepthink stays absent in this mode as in three-tier
  - instruction: verify: unarmed byte-identity pinning tests in the style of three-tier's; existing three-tier suites stay green untouched
  - honesty: with the mode unarmed, a byte-identity pinning test over the landed three-tier suites passes with zero diffs
- experiments (#397): experiments A (thought preservation), B (thought-to-action evaluation on pre-registered verdict/routing expectations), and C (end-to-end value vs landed three-tier and worker-only) are committed under docs/experiments/ with pre-committed bars and falsifying results preserved verbatim (#387 ledger discipline); no default flip follows from structural tests alone
  - instruction: verify: experiment docs exist with pre-registered bars BEFORE the runs; results tabulated verbatim
  - honesty: each experiment doc's bar section is committed in a PR that precedes the results commit (pre-registration provable from git history)
- structural reuse (#397): the front loop builds on `senses_loop.py`/`presence_engine.py`, the acting loop is loop.py unchanged where possible, and chain.`CONTINUABLE_REASONS` stays pinned unchanged — the mode is new wiring over proven parts, not a parallel runtime
  - instruction: verify: no fork of loop.py; `senses_loop` reuse visible in the diff; `CONTINUABLE_REASONS` pin test untouched
  - honesty: the acting-loop diff in the mode PR is reviewably small (wiring, not rewrite); the `CONTINUABLE_REASONS` pin test is untouched

## Honesty conditions

- all three lanes land as separately mergeable PRs; no lane's failure silently drops another (the announcement stays honest per-lane)
- tests/`test_e2e_mock.py` passes unchanged after the streaming default flips — result shape identical between blocking, streaming, and opt-out paths
- a pre-rename artifact with worker.prompt.strategist `config_events` loads and continues (--continue) without error on the renamed code
- git diff of the rename PR touches nothing under docs/specs/, docs/plans/, docs/deliveries/, docs/experiments/, or .devague/
- every seat in the new mode resolves from the lobes /capabilities contract by role name; a rig missing a role degrades honestly (mode refuses to arm with a legible reason), never falls back to parsing model names
- each before-state fact cites its evidence: #387 run docs for the timeout and lesson-trace claims, three-tier.md for the authority placement
- the after-state holds with every lane's default posture stated: streaming default-on, new lesson schema mandatory, thought→action→evaluation opt-in
- the cognition-placement claim stays framed as hypothesis to MEASURE (experiment C), never asserted as proven in docs
- the CLAUDE.md v1-scope section gains the tenth increment with the same NEVER-a-routing-policy language, and the spec enumerates every new consumed role surface
- measured on the reference rig with the same task class that produced the #387 timeout kill
- the top-k precision score is computed from artifact-recorded recall results, and 'class-relevant' is determined by a pre-declared rule, not post-hoc judgment
- experiment B's five mismatch classes and expected verdicts are pre-registered verbatim from issue #397's list before any evaluator run

## Success signals

- streaming: a headless run on the reference rig sustains turns >300s with 0 socket-timeout kills on finish turns (vs 1 in the #387 arms), and the per-turn ceiling no longer tracks `COLLEAGUE_TIMEOUT`; unarmed/opt-out runs stay byte-identical (existing suites green)
- self-learn: every distilled lesson validates against the answer-shaped schema (pattern + constant + reason, refuse-whole) and TaskResult.memory scores class-relevant-lesson-in-top-k per task, so the #394 rerun can measure a learning CURVE at N≥16 instead of totals
- thought→action→evaluation: experiments A-C committed with pre-registered bars; experiment B detects ≥4 of the 5 seeded mismatch classes with 0 false blocks on the aligned pairs; unarmed byte-identity pinned by test

## Scope / boundaries

- headless SSE keeps the all-engines rule: TaskResult shape stays byte-identical (only wire behavior changes); mock's `_emit_synthetic_deltas` path and tests/`test_e2e_mock.py` guard mock/vllm-openai parity — neither diverges
- the rename never invalidates persisted state: ConfigEvent.`from_dict` parses target as a free-form string (configevents.py:147), `config_digest` is recomputed from the events themselves, and no code path round-trips persisted target strings through the Target enum outside lattice.py's live-proposal parse — old artifacts stay readable unchanged
- historical dated records keep the word strategist: docs/specs/, docs/plans/, docs/deliveries/, docs/experiments/ (e.g. 2026-08-06-experiment-c-strategist-value.md) and .devague/ frames are provenance, never rewritten by a rename
- v1 scope line: this arc is the TENTH sanctioned increment — an authority split with a FIXED closed vocabulary, seats resolved BY ROLE NAME from lobes, re-spec'd via this frame — NEVER a routing policy (no automatic task→model decisions); host policy, approvals, hooks, and role tool curation remain the hard authority ceiling; no chain-of-thought exposure, no training/merging, cortex never becomes a second actor, the front never calls repo tools

## Assumptions

- sequencing per #396: #393 lands first (removes the timeout-pressure confound and would have absorbed most of the run's 32 chain legs), then the specificity redesign; the #397 role sharpening is independent of that ordering

## Scope exploration

- `s1` — `colleague/engines/vllm_openai.py (_build_chat_payload:810, _make_complete, _stream_or_blocking)`: streaming is armed exclusively by config.`on_delta` is not None; the streaming machinery (incremental ModelResponse assembly, keepalive tolerance, mid-stream fallback to one blocking request) already exists from the feels-alive arc — #393 is a re-arming decision, not new transport code
  - seeds: `c2`
- `s2` — `colleague/cli/_commands/work.py:594-632 (delta seam)`: headless work sets config.`on_delta` = None on every non-cockpit path, so every headless turn takes the blocking urlopen whose read returns only at full completion — the request timeout becomes a per-turn generation ceiling (observed live: #387 arms, 300-430s turns vs 600s ceiling)
  - seeds: `c2`
- `s3` — `colleague/engines/mock.py (_emit_synthetic_deltas)`: mock already reconstructs content exactly through ordered synthetic deltas when `on_delta` is armed — a headless-streaming knob must keep mock and vllm-openai result shapes identical (tests/`test_e2e_mock.py` is the guard)
  - seeds: `c3`
- `s4` — `colleague/lattice.py:40-125 (Target enum)`: strategist is the lattice's content-bearing target vocabulary — Target.`WORKER_PROMPT_STRATEGIST` = 'worker.prompt.strategist' / `SENSES_PROMPT_STRATEGIST`, the only targets whose changes carry content; renaming changes the wire string the configurator model must emit
  - seeds: `c4`
- `s5` — `colleague/layers.py:518-760 (compose_strategist_section + prompt composition)`: 45 strategist references — the seat constants (`STRATEGIST_SEAT_WORKER`), the size-capped section composer, and the `strategist_section`/`strategist_seat` parameters threaded through both system-prompt composers
  - seeds: `c4`
- `s6` — `colleague/contract.py:2058-2183 + colleague/configlifecycle.py (snapshot)`: `_STRATEGIST_TARGET_VALUE` and `strategist_sections` appear in serialized record/snapshot keys ('content only on applied strategist records', snapshot `to_dict`) — the rename touches artifact-facing key names, not just identifiers
  - seeds: `c4`
- `s7` — `colleague/configevents.py:98-165 (ConfigEvent)`: target/origin are free-form strings not tied to the lattice enum; `from_dict` str()s whatever is persisted, and `config_digest` recomputes from the events — old artifacts carrying worker.prompt.strategist parse fine after a rename
  - seeds: `c5`
- `s8` — `docs/ tree (specs, plans, deliveries, experiments) + .devague/ frames`: strategist appears in dated records including docs/experiments/2026-08-06-experiment-c-strategist-value.md and the three-tier spec/plan/delivery — these are provenance records a rename must not rewrite; only the living surface (code, tests, docs/features/three-tier.md, CLAUDE.md bullet) renames
  - seeds: `c6`
- `s9` — `tests/ (13 files, 220 strategist refs)`: `test_layers_strategist.py` and `test_engine_strategist_seam.py` are named after the vocabulary; the rename footprint includes renaming test modules and their fixtures, guarded by the existing three-tier suites
  - seeds: `c4`
- `s10` — `colleague/lessons.py (schema + validator)`: the distillation lesson is a strict refuse-whole 3-key JSON schema (cause/lesson/`next_delta`, each ≤1000 chars); invalid input records the honest no-lesson-extracted marker — the specificity redesign changes this schema, so back-compat with already-stored 3-key lessons is a real question
  - seeds: `c8`
- `s11` — `colleague/distill.py (detached rung-2 child)`: the distillation author resolves by role (deepthink/muse > armed-lobes main > rung-1 floor), runs as a detached one-shot child re-reading the persisted artifact, and validates via lessons.py — the author prompt and validation both move with the schema
  - seeds: `c8`
- `s12` — `colleague/correction.py (build_code_lesson)`: code-lessons build from correction-diff hunks with file/area/pattern fields and a low confidence default — the same answer-shaped bar (pattern + constant + reason) applies here; #387 evidence: the g3 latch code-lesson's class never recurred, process-shaped lessons produced identical traces
  - seeds: `c8`
- `s13` — `colleague/contract.py:1567-1574 (TaskResult.memory)`: the memory exchange record already captures query/recalled/`injected_chars`/`lesson_recorded` with omit-when-None serialization — the natural hook for per-task retrieval-precision scoring without a new artifact surface
  - seeds: `c9`
- `s14` — `colleague/memory.py (recall via eidetic CLI)`: recall shells out to the operator-installed eidetic CLI (allow-listed verbs, `top_k`=5, scope colleague, visibility public) and returns parsed JSON records; `RECALL_BLOCK_CAP`=4000 bounds injection — thresholding/consolidation must either filter colleague-side over returned score/signal fields or need new eidetic-cli verbs (sibling-repo scope)
  - seeds: `c10`

## Decisions

- the FULL #397 thought→action→evaluation redesign lands in this arc as a separate opt-in experimental mode (front commits typed Thoughts, worker proposes/executes Actions, evaluator returns closed verdicts), alongside the strategist→evaluator rename on the landed three-tier surface
- headless work streams by default (#393): a no-op delta sink arms SSE on every headless turn, the mid-stream→blocking fallback stays, and an env opt-out (`COLLEAGUE_STREAM`=0-style) restores the old wire behavior
- the lesson schema is REPLACED outright: answer-shaped pattern + constant + reason supersedes cause/lesson/`next_delta`; no dual-schema validator; already-stored 3-key lessons recall as legacy free text
- store hygiene lands colleague-side only: relevance thresholding + supersedes handling in memory.py's recall-before path over eidetic's returned score/signal fields; new eidetic-cli verbs are a parked cross-repo follow-up

## Open parks

- [unknown_nonblocking] the exact drift-threshold metric that triggers a mid-episode evaluator invocation — define during planning, must be deterministic
- [unknown_nonblocking] whether the 12B front becomes the quality bottleneck — experiment C measures it; no default flip either way from structural tests alone
- [follow_up] eidetic-cli consolidation/supersedes verbs (cross-repo) — hygiene beyond colleague-side thresholding

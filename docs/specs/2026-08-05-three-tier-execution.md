# three-tier execution

> Colleague gains an opt-in three-tier execution mode: senses relays the worker's answer faithfully, the worker drives the bounded tool loop, and cortex configures what the other seats run under — resolved by role name from the lobes gateway, byte-identical when unconfigured (#364, design brief #363)
> instruction: verify against the recorded live three-seat session in docs/live-testing.md plus the byte-identical no-config suite; the seven design decisions of #364 are the implementation contract

## Audience

- the colleague operator running work/drive/session against a lobes rig advertising all three seats (today: thor serves cortex unsloth/Qwen3.6-27B-NVFP4 + worker unsloth/Qwen3.6-35B-A3B-NVFP4, orin serves senses unsloth/gemma-4-12B-it-qat-w4a16, all ready:true); the unchanged secondary audience is every consumer WITHOUT three-tier configuration — legacy operators, agent callers, --json/piped fronts, the resident — who must observe zero change
  - instruction: check the spec names the lobes-armed opt-in operator as the only three-tier audience and pins every unconfigured surface byte-identical

## Before → After

- Before: today cortex both acts and is the only mind (worker unknown to lobes.py); senses relays but the matched embodiment live session showed relay fidelity FAIL 6/6 (knowledge recited over the current answer) while attribution held 6/6; truncation is invisible (ModelResponse has no `finish_reason` — 5/6 actor turns silently truncated at 16000); a strategist measured negative 3x with nothing to fix
  - instruction: cite docs/live-test-results in embodiment 0.14.0 + colleague loop.py:370 as the pre-change record
- After: an operator with three-tier configuration runs the same work/drive/session verbs: the worker drives the bounded tool loop, senses relays with the worker's answer present verbatim (raw-answer fallback on fidelity failure), cortex may only propose task-local configuration applied between episodes under the resolved authority ceiling; the artifact records the config event stream, per-seat finish state, and advancing liveness counters; without the configuration nothing anywhere changes
  - instruction: run one live three-seat session on the rig and check each guarantee against the recorded artifact

## Why it matters

- it is an authority split, not three sizes of the same job: the actor never learns a strategist exists (configuration changes, not advisory prose it may ignore), the voice structurally cannot claim work it did not do or suppress the worker's answer, and every promotion is gated on pre-registered committed evidence — unawareness replaces persuasion, counters replace 'armed==true'
  - instruction: verify the worker's conversation contains zero cortex-authored advisory prose (pinned by test) and the spec's promotion gates reference committed experiment records

## Requirements

- three-tier is the EIGHTH sanctioned router-exclusion increment: a FIXED enumerated surface (three seats resolved by role name — worker/cortex/senses — never model-name parsing, never an automatic task->model routing policy), opt-in behind an explicit mode/config block, entering CLAUDE.md's v1 scope line via this re-spec
  - instruction: check CLAUDE.md's v1 scope list gains entry (8) with FIXED-surface wording; grep the whole diff for any task->model routing decision
  - honesty: CLAUDE.md's v1 scope line gains increment (8) with the FIXED-surface wording (three roles by name, opt-in, no automatic task->model routing decision anywhere in the diff) — the router stays excluded and the spec records the distinction honestly
- lobes.py gains optional 'worker' role resolution alongside cortex/senses/stt/tts/embedder/muse — the live gateway already advertises worker (unsloth/Qwen3.6-35B-A3B-NVFP4, ready:true); explicit three-tier mode must refuse loudly, never silently substitute cortex-as-actor, when worker is missing or undialable
  - instruction: verify lobes.py optional-role parsing gains worker and the loud-refusal path (three-tier + no worker) has a test asserting no cortex fallback
  - honesty: lobes.py resolves worker as an OPTIONAL role (absence is never an error for legacy runs); explicit three-tier mode with worker missing or undialable exits with a loud, tested refusal — no code path substitutes cortex as actor silently
- `finish_reason` propagates through ModelResponse (loop.py:370 has no such field today; `vllm_openai.py`:363 consumes `finish_reason` for SSE stream termination only and drops it) — truncated / stopped / timeout / empty / deliberate completion become distinguishable states, recorded per seat; delivery step 1 before any experiment is trusted
  - instruction: verify ModelResponse.`finish_reason` exists, `vllm_openai.py` propagates it from the SSE accumulator, and the five completion states have tests
  - honesty: `finish_reason` rides ModelResponse end-to-end from the vLLM SSE accumulator; truncated / stopped / timeout / empty / deliberate are distinguishable states with tests; the artifact records truncation per seat; `__COLLEAGUE_NO_RESULT_PRODUCED__` is never counted as a completed answer
- senses relay fidelity becomes structural IN the existing lane (senses.py): a worker answer, when present, stays visible verbatim in the displayed response; knowledge-block entries are labeled optional background answered AFTER the current result; fidelity failure triggers raw-answer fallback + a recorded degradation — new health counters beyond transport (verbatim-presence, unrelated-knowledge repetition, fallback, truncation)
  - instruction: verify the displayed-response path asserts verbatim worker-answer containment and the domain-mismatch regression (embodiment 6/6 shape) is in the suite
  - honesty: with a worker answer present the displayed response contains it verbatim (structural test, not prompt hope); fidelity failure triggers raw-answer fallback plus a recorded degradation; the embodiment 6/6 failure shape is a committed regression test; ContextPacket.original and tools=\[\] pins remain untouched
- the authority ceiling: cortex's capability catalog derives from the task's already-resolved effective authority (mode + role + schema curation + operator policy); cortex may narrow the worker's tool set, never add beyond the resolved allow-list; worker cannot alter its own tools/prompt/knowledge/authority — owners are roles.py, engine schema curation, and the tool executor in loop.py/tools.py
  - instruction: verify the catalog builder's only input is the resolved allow-list and refuse-whole tests cover add-beyond-ceiling, unknown target, forbidden key
  - honesty: the capability catalog is derived ONLY from the task's resolved effective authority (no from-executor constructor, no minting); a cortex change selecting an id outside the ceiling refuses the WHOLE unit with a recorded refusal, tested; the worker's schema exposes no self-modification surface
- cortex-authored prompt changes touch ONLY a bounded, named, task-local strategist section composed through layers.py's existing system-prompt path (`system_prompt_for`/`compose_role_prompt`); base prompt, AGENTS layers, role prompts, skills, and operator text stay immutable; the change lattice refuses the WHOLE unit on unknown/extra/forbidden keys, never strips-and-retains
  - instruction: diff composed prompts baseline vs configured: exactly one named strategist section differs; check the immutability pin tests
  - honesty: diffing the composed system prompt between a baseline and a cortex-configured run touches exactly ONE named task-local strategist section; base prompt, AGENTS layers, role prompts, skills, and operator text are pinned unchanged by test; unknown/extra/forbidden keys refuse the whole unit, never strip-and-retain
- the episode boundary is the configuration boundary: resolved configuration is immutable for a whole episode (system prompt / knowledge / tool surface never rewritten between model turns); with --until-done chaining armed (chain.py), changes apply only between episodes; a no-tool episode end still counts as a boundary (embodiment T1 regression: a tool-step boundary rule leaves the tier dead with armed:true); configuration is discarded at top-level task end
  - instruction: verify config digest constant within an episode, the T1 no-tool-end regression, and chain.py between-episode application tests
  - honesty: the effective-config digest is constant across every model turn within an episode (tested); a mid-episode proposal applies only in the next between-episode window; a no-tool episode end still increments the boundary counter (the T1 regression, tested); config is discarded at top-level task end
- the task artifact carries an append-only configuration event stream + derived effective-config digest on TaskResult (artifact.py/contract.py are the owners) — proposed/refused/verified/applied/reverted all recorded; liveness is an advancing counter, never 'armed==true'
  - instruction: verify the TaskResult event stream is append-only, the digest derives from events alone, and liveness reads counters never armed
  - honesty: TaskResult carries an append-only config event stream whose replay reproduces the effective-config digest; proposed/refused/verified/applied/reverted are all recorded; a tier is reported alive only when a progress counter advanced — armed alone never reports health
- three pre-registered promotion gates run through the existing experiment noun (colleague/experiment.py, landed in #291): A senses-fidelity (domain-mismatch regression from the failed 6/6 live session), B worker-vs-acting-cortex on colleague's real surface, C strategist value on a misconfigured-actor script; the strategist stays opt-in and OFF until C returns a supporting verdict (three independent negatives stand today); no default flip before all three verdicts are committed
  - instruction: verify A/B/C are pre-registered under the experiment noun with committed results and a test holds the strategist off by default
  - honesty: experiments A (senses fidelity), B (worker vs acting cortex), C (strategist value on a misconfigured actor) exist as pre-registered runs through the experiment noun with committed results; a test holds the strategist opt-in and OFF until C's supporting verdict is committed; no default flips before all three verdicts land
- with no three-tier configuration, behavior and serialized artifacts stay byte-identical — the same gate every prior increment shipped under (cortex-only byte-identical, no-muse byte-identical)
  - instruction: run the byte-identical suite on both backends: no-config runs produce identical behavior and serialized artifacts
  - honesty: the no-config path is proven byte-identical by test on BOTH backends (mock + vllm-openai, the all-engines rule): same behavior, same serialized artifacts — the identical gate cortex-only and no-muse shipped under

## Honesty conditions

- a live three-seat session on the rig (cortex+worker+senses all ready) records the worker acting, senses relaying with the worker's answer verbatim-present, and cortex proposing at least one verified config change applied between episodes — recorded in docs/live-testing.md; the same commands with no three-tier config behave byte-identically, proven by test
- a muse advert present alongside three-tier configuration arms NOTHING (tested — no DeepthinkConfig constructed in three-tier mode); every legacy deepthink test stays untouched and green; no flag, artifact field, or public contract is renamed
- the change-lattice target enum contains no operator-owned surface (approvals, hooks, command approvals, task roles, mode gates, handoff policy); a unit naming one refuses WHOLE with a recorded refusal, tested; policy.py is unreachable from cortex
- every consumer without three-tier configuration observes ZERO change — proven byte-identical by test, the same gate the presence and cortex-senses arcs used; the three-seat rig facts are recorded as of 2026-08-05 and re-probed before the live proof
- each pre-change gap cites a real record: embodiment 0.14.0 docs/live-test-results (relay fidelity 0/6, attribution 6/6, 5/6 truncations, strategist negatives x3) and colleague code as explored (loop.py:370 no `finish_reason`, lobes.py no worker role)
- the worker's conversation contains zero cortex-authored advisory prose and its completion seam is never wrapped by a strategist model — both pinned by test; senses attribution is measured, not assumed, in experiment A
- one recorded live session demonstrates every after-state guarantee against its artifact: worker acted, senses preserved the answer verbatim (or a recorded fallback fired), cortex changes applied only between episodes, counters advanced, per-seat finish states recorded
- the byte-identical suite, the loud-refusal test, and the `finish_reason` state tests all run in CI and gate the PR — 0 diff, 100% refusal, 100% distinguishable are test assertions, not prose claims
- experiment A runs pre-registered through the experiment noun with the embodiment failure shape as fixture and its result committed; the strategist-off default is held by a test until experiment C commits a supporting verdict

## Success signals

- structural gate: with no three-tier config the suite proves 0 behavioral or artifact diff; explicit three-tier mode with worker missing/undialable refuses loudly in 100% of cases (never silent cortex-as-actor); truncated vs deliberate completion is distinguishable in 100% of vLLM turns via `finish_reason`
  - instruction: point CI at the byte-identical suite + the refusal test + the `finish_reason` state tests
- fidelity gate: in the committed domain-mismatch regression (the embodiment 6/6 failure shape) the worker's answer is visible in 6/6 turns (raw-answer fallback counts, and each fallback records a degradation), unrelated knowledge replaces the current answer in 0/6, and attribution holds in 6/6; the strategist stays off until experiment C commits a supporting verdict (>= 1 verified beneficial intervention on the misconfigured-actor script, 0 on the control)
  - instruction: run experiment A as a pre-registered run through the experiment noun and commit the result before any default discussion

## Scope / boundaries

- deepthink/muse is ABSENT from three-tier mode (offering it makes the design four-tier and restores an advisory-prose path into the worker); legacy mode keeps the muse->deepthink discovery rung unchanged (config.py `_muse_deepthink_fallback`); no global renames of existing flags, artifact fields, or public contracts during the experiment
  - instruction: test that three-tier config with a muse advert present constructs no DeepthinkConfig; confirm legacy deepthink tests untouched
- operator-owned controls are immutable to cortex: policy.py approvals (checksum/token gate), hooks.json, command approvals, task roles, mode gates, and handoff policy; there is NO generic strategist-writable 'permissions' target in v1 — colleague's permission-like surfaces keep their distinct owners
  - instruction: verify the change-lattice target enum excludes every operator-owned surface and an attempted policy target refuses whole with a recorded refusal

## Non-goals

- nothing is imported from embodiment: #358 (import the extracted loop) stays a separate open issue blocked on the C1b dependency decision; this arc CITES the design (cite-don't-import); agentfront remains the only sanctioned base dep (`test_zero_deps.py` allow-lists exactly it)
- multi-gateway advert merging is OUT — seat resolution keeps the current single discovery gateway with per-role endpoints (the live rig proxies every role through :8001, so cross-machine seats already resolve today); durable cross-task configuration promotion is OUT for v1 (task-local only, discarded at task end)

## Assumptions

- ground truth for the three seats is the actually-served models, not the current stale /capabilities adverts: thor serves cortex unsloth/Qwen3.6-27B-NVFP4 + worker unsloth/Qwen3.6-35B-A3B-NVFP4 (both live in /v1/models); orin serves senses unsloth gemma4 12b via the mesh; muse is absent — the operator is updating the lobes CLI/gateway adverts to match

## Scope exploration

- `s1` — `issues #364 + #363 (embodiment 0.14.0 design brief)`: \#364 is the colleague-native translation (design decisions 1-8, three promotion gates, 10-step delivery order, acceptance criteria); #363 carries the evidence — worker protocol proven hermetically (36/36), strategist measured negative 3x independently, senses attribution held 6/6 but relay fidelity FAILED 6/6, plus the eight seam traps (T1 no-tool boundary, T2 cadence memory) — the increment claim and every design boundary trace here
  - seeds: `c2`, `c10`
- `s2` — `CLAUDE.md v1 scope line (seven sanctioned increments)`: worker-as-actor + cortex-as-configurator is not covered by any of the seven landed increments — it is an eighth FIXED enumerated surface requiring exactly this re-spec; the excluded multi-model router stays excluded (role-by-name resolution, no task->model routing decision)
  - seeds: `c2`
- `s3` — `colleague/lobes.py (role resolution client)`: resolves cortex+senses mandatory, stt/tts/embedder/muse optional via `_parse_role`; 'worker' is unknown today; RoleInfo already parses model/endpoint/ready per role, so worker lands as one more optional role; ready is CONFIG-PROXY for non-stt/tts roles (lobes-cli#89 semantics)
  - seeds: `c3`
- `s4` — `live gateway /capabilities (localhost:8001, probed 2026-08-05)`: worker advertised ready:true (unsloth/Qwen3.6-35B-A3B-NVFP4); senses ready:FALSE with model id coolthor/gemma-4-12B-it-NVFP4A16 contradicting the operator's stated unsloth gemma4 12b on orin; muse STILL advertised ready:false despite removal; all roles proxy through the one :8001 origin
  - seeds: `c3`, `c15`
- `s5` — `colleague/loop.py:370 ModelResponse + engines/vllm_openai.py SSE accumulator`: ModelResponse carries content/`tool_calls`/token counts but NO `finish_reason`; the vLLM adapter reads `finish_reason` (line 363) solely to terminate the SSE stream and drops it — truncation is invisible to the loop, the artifact, and every experiment counter
  - seeds: `c4`
- `s6` — `colleague/senses.py + senses_loop.py/senses_moves.py (the existing senses lane)`: the structural pins #364 §5 requires already exist and must be preserved: ContextPacket.original is never truncated (senses.py:91), every senses completion is tools=\[\] (lines 515/590/653), the coordination loop is prompted-JSON with nothing tool-shaped on the wire — relay-fidelity work EXTENDS this lane (grounding + fidelity clauses, verbatim worker-answer guarantee, fidelity counters), never builds a second one
  - seeds: `c5`
- `s7` — `colleague/config.py _muse_deepthink_fallback (lines 733-766) + deepthink.py`: muse discovery returns None only when the role is absent or its model blank — it does NOT consult ready, so the stale ready:false muse advert still arms deepthink in legacy runs (degrades visibly at the c13 escalation ladder, but per-run); three-tier mode must not offer deepthink at all; legacy paths stay untouched
  - seeds: `c12`
- `s8` — `colleague/roles.py + tools.py schema curation + the loop's tool executor`: the subagent-role machinery already proves the enforcement shape #364 needs: a Role's `tool_allowlist` filters SCHEMAS so a read-only role provably cannot mutate — the worker's authority ceiling and cortex's narrow-only catalog reuse this ownership, not a new subsystem
  - seeds: `c6`
- `s9` — `colleague/layers.py (system_prompt_for / compose_role_prompt)`: prompt composition is injected once on Engine.`system_prompt`() with exact-path per-model isolation — the bounded task-local strategist section composes here; everything else in the stack (base prompt, AGENTS, skills, operator text) stays immutable to cortex
  - seeds: `c7`
- `s10` — `colleague/policy.py (approval gate)`: the approval gate is checksum/token-based operator policy, explicitly a policy gate not a sandbox — it is operator-owned and must be unreachable from the cortex change lattice; no strategist-writable permissions target exists or gets invented
  - seeds: `c13`
- `s11` — `colleague/chain.py (episode chaining, --until-done)`: the chain driver already treats the episode as the unit (`CONTINUABLE_REASONS` allow-list, between-episode window for pilot stops) — the configuration boundary maps onto this existing seam: immutable within an episode, applied in the between-episode window, discarded at task end; the no-tool episode end (T1) must be a tested boundary here
  - seeds: `c8`
- `s12` — `colleague/artifact.py + contract.py (TaskResult / the JSON artifact)`: the artifact is the single durable record (WorkStats always-on, tokens exact from usage) — the config event stream + effective-config digest land as new TaskResult surface written through artifact.write; no second durable repo-configuration store
  - seeds: `c9`
- `s13` — `colleague/experiment.py (the experiment noun, #291)`: a first-class experiment surface already landed with the integration front — the three promotion gates (senses fidelity / worker promotion / strategist value) should run as pre-registered experiments through it rather than ad-hoc scripts, with results committed before any default flip
  - seeds: `c10`
- `s14` — `issue #358 (import embodiment's extracted loop)`: open and explicitly separate — blocked on the C1b dependency decision which is the operator's; #363 is a design brief, not a dependency ask, and everything here is adoptable by citing; the base-dependency line (agentfront only, `test_zero_deps.py`) is untouched
  - seeds: `c14`
- `s15` — `docs/features/cortex-senses.md + deepthink.md + senses-live-presence.md + talking-to-one*.md`: four feature docs pin today's two-role semantics (cortex acts, senses perceives; cortex-only byte-identical; muse discovery no-muse=byte-identical) — three-tier mode re-frames 'cortex' from actor to configurator ONLY inside the new mode, so these docs need a legacy/three-tier distinction, not a rewrite; 'cortex-only' keeps its current meaning in legacy mode
  - seeds: `c11`, `c12`
- `s16` — `gateway /v1/models (localhost:8001, probed 2026-08-05)`: actually-served set is cortex Qwen3.6-27B + worker Qwen3.6-35B-A3B + embedders/reranker — NO gemma and NO muse Gemma-31B served through the gateway, corroborating that the muse and senses /capabilities adverts are both stale; senses (orin unsloth gemma4 12b) reaches the mesh outside this list until the operator's CLI/gateway update lands
  - seeds: `c16`

## Decisions

- operator decision (2026-08-05): the arc's LAST step before the delivery summary and the cicd PR leg is a LIVE test on the rig proving colleague PERFORMS BETTER — the worker-promotion comparison (experiment B: three-tier worker-as-actor vs the current acting cortex on colleague's real surface) must return a supporting verdict, live, before anything is summarized or a PR opened
  - instruction: run experiment B pre-registered on the live rig (worker Qwen3.6-35B-A3B vs cortex Qwen3.6-27B baseline) and commit the result; summary + cicd only after the verdict supports promotion

## Open parks

- [unknown_nonblocking] worker's usable context window and `max_tokens` budget on the new Qwen3.6-35B-A3B MoE are unmeasured (the embodiment live session truncated 5/6 actor turns at 16000, and proxied roles have historically advertised the local window, not the serving box's) — `finish_reason` propagation (delivery step 1) makes this measurable before experiment B

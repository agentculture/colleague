# Live-testing ledger

The unit suite (1700+ test functions) proves the **contract** against the `mock`
backend and fixtures. It does **not** prove the runtime works end-to-end against a
real served model. Two layers stay invisible to unit tests:

1. **Tools the model must *choose* to invoke** — `subagent`/`subagents`,
   `culture`, `devague`. A drive only exercises them if the live model decides to
   call them. Across every real drive trace captured so far, the live model has
   invoked **only the base five** (`read_file`, `write_file`, `list_dir`,
   `run_command`, `finish`). The newer `edit_file` (partial-edit, #174) has not
   yet appeared in a captured live trace — see its own matrix row below.
2. **Config surfaces that must be *present* to fire** — `approvals.json`,
   `hooks.json`, `neighbours.json`, per-model AGENTS/skills layers, the `[otel]`
   extra. None are present in this repo, so none have ever fired in a live drive.

This ledger tracks that second layer: **live validation against the reference
rig**, with a commit+date stamp per feature so staleness is detectable.

## Reference rig

| Field | Value |
|-------|-------|
| Provider `base_url` | `http://localhost:8001/v1` |
| Model | `unsloth/Qwen3.8-27B-NVFP4` |
| Readiness check | `colleague doctor --probe` (must report `provider_reachable` + `provider_model_available` → passed) |

A served model that exposes tool calling is required: the vLLM rig must run with
`--enable-auto-tool-choice` plus a model-appropriate `--tool-call-parser`
(e.g. `hermes` or `qwen3_coder`).

## How to use this ledger

Each feature has a row in the [matrix](#validation-matrix) and a procedure below.
A row records **Last validated** as `<commit> · <date>` — the commit the code was
at when the procedure was last run and passed.

**Staleness check.** A row is stale when its source files have commits newer than
the recorded SHA. To check one feature:

```bash
# compare the feature's source files against the row's "Last validated" SHA
git log -1 --format='%h %cs' -- colleague/subagents.py colleague/worktrees.py
```

If that SHA differs from the ledger's recorded SHA for the row, the live
validation is stale: re-run the procedure and update the row (commit, date,
status, evidence). A row whose code moved but whose stamp did not is **lying** —
treat ❌-by-staleness the same as never-validated.

**Status legend:** ✅ validated live · ⚠️ partial / flaky · ❌ not yet validated live

## Validation matrix

| # | Feature | Source | Status | Last validated | Issue |
|---|---------|--------|--------|----------------|-------|
| — | Base loop (5 tools), drive | `colleague/loop.py`, `colleague/tools.py` | ✅ | `83fe6aa` · 2026-06-04 (17 live drives) | — |
| — | `outsource explore` | `.claude/skills/outsource/` | ✅ | `83fe6aa` · 2026-06-04 (drive `d2dc294f3c41`, `f9f17b0d924f`) | — |
| — | `outsource review` | `.claude/skills/outsource/` | ✅ | `83fe6aa` · 2026-06-04 (drive `782a90785b30`, rated 4) | — |
| — | `feedback` record/show | `colleague/feedback.py` | ✅ | `83fe6aa` · 2026-06-04 (graded drives present) | — |
| — | `doctor` / `doctor --probe` | `colleague/cli/_commands/doctor.py` | ✅ | `83fe6aa` · 2026-06-04 | — |
| — | Command templates | `colleague/commands.py` | ✅ | `83fe6aa` · 2026-06-04 (`doc-review`) | — |
| — | Drive stats | `colleague/loop.py`, `colleague/contract.py` | ✅ | `d1b4d54` · 2026-06-05 (drive `a6c5f0c1fd13`, `bytes_written` exact); see §0 result | — |
| — | Step-budget termination | `colleague/loop.py` | ✅ | `83fe6aa` · 2026-06-04 (drive `99d1a4ee9572`, `901e9d61bf31`) | — |
| 1 | `outsource write` reliability | `.claude/skills/outsource/`, `colleague/handoff.py` | ✅ | `6eb843d` · 2026-06-04 (apply `b885fbb`,`5bc48e7`,`f51427e` + PR `221b4ce`/#130); see §1 caveats | [#121](https://github.com/agentculture/colleague/issues/121) |
| 2 | Subagents (`subagent`/`subagents`) | `colleague/subagents.py`, `colleague/worktrees.py` | ✅ | `61d15cc` · 2026-06-04 (drive `6c27147eb917`); see §2 caveat | [#122](https://github.com/agentculture/colleague/issues/122) |
| 3 | Gated configs (approvals / hooks / per-model layers) | `colleague/policy.py`, `colleague/hooks.py`, `colleague/layers.py` | ✅ | `304002a` · 2026-06-04 (3a/3c/3d live, 3b/3e deterministic); see §3 result | [#123](https://github.com/agentculture/colleague/issues/123) |
| 4 | Loop tools: `culture` + `devague` | `colleague/culture.py`, `colleague/devague.py` | ✅ | `7a12d1e` · 2026-06-05 (4a `2395f7d5d9b9`, 4b `80cb15c5f9cd`); see §4 result | [#124](https://github.com/agentculture/colleague/issues/124) |
| 5 | Neighbours read-only clones | `colleague/neighbours.py` | ✅ | `64361da` · 2026-06-05 (drive `711505cb4c3f`); see §5 result | [#125](https://github.com/agentculture/colleague/issues/125) |
| 6 | Telemetry end-to-end | `colleague/telemetry/` | ✅ | `d5c9312` · 2026-06-05 (e2e in CI + live drive `eff14af763d4`); see §6 result | [#126](https://github.com/agentculture/colleague/issues/126) |
| 7 | Context-overflow graceful degradation | `colleague/context.py`, `colleague/loop.py` | ✅ | `fcbf4ec` · 2026-06-05 (proactive `36b022abc7f0`, reactive `0323db53b1dd`); see §7 result | [#127](https://github.com/agentculture/colleague/issues/127) |
| 8 | Partial-edit tool (`edit_file`) | `colleague/tools.py` | ✅ | `bf6cf2d` · 2026-07-02 (work items `ede0f61fb28b` ×7, `5ccdf8573cad` ×2, `6422d3224e32` ×11 — real TDD builds on this repo) | [#174](https://github.com/agentculture/colleague/issues/174) |
| 9 | Memory: recall-before / remember-after | `colleague/memory.py`, `colleague/loop.py` | ✅ | `bf6cf2d` · 2026-07-02 (smoke `e082b37e602e` lesson persisted to the durable store; warm-vs-cold `503b0a36c33a` vs `c5774404bc3d` — 10→2 steps, 23.4k→4.3k tokens; see `docs/features/memory.md`) | — |
| 10 | Finish recovery (thin/meta/literal-markup) | `colleague/loop.py` | ⚠️ | `bf6cf2d` · 2026-07-02 (deterministic regression suite on the #248/#231 evidence shapes; a live re-occurrence not yet observed post-fix — the fix removes the trigger) | [#248](https://github.com/agentculture/colleague/issues/248) [#231](https://github.com/agentculture/colleague/issues/231) |
| 11 | Background one-shot (`work --background`) | `colleague/background.py` | ⚠️ | `bf6cf2d` · 2026-07-02 (mock-engine e2e through `main()` incl. kill-reap; a live-model background run not yet exercised) | — |
| 12 | Resident appserver (agent-lifecycle embed) | `colleague/resident/appserver.py` | ⚠️ | `bf6cf2d` · 2026-07-02 (real `agent_lifecycle` 0.9.0 + reference transport e2e; REAL mesh transport PENDING upstream — h15, never claimed) | — |
| 13 | Spontaneous `subagents` delegation | `colleague/subagents.py` | ✅ | `bf6cf2d` · 2026-07-02 (work items `5ccdf8573cad` ×1, `6422d3224e32` ×2 with 7 folded sub_results — UNPROMPTED, superseding §2's "needs an explicit invite" caveat) | — |
| 14 | Substantial decomposed write (h9) | `colleague/loop.py`, `colleague/tools.py`, `colleague/subagents.py` | ⚠️ | `22adbb3` · 2026-07-02 (pre-fix `4c6a96107269` CRASHED on a malformed tool call; post-fix `55859cb1d605` survived to an honest `incomplete` — harness proven, the served 27B couldn't land the full decomposition; see the substantial-write section below) | — |
| 15 | Media image live proof (`media_image`) | `colleague/livecheck.py` | ⚠️ | `ec500c0` · 2026-07-02 (classification logic unit-proven, `tests/test_livecheck_media.py`; live rig run PENDING — see the media-proofs section below) | — |
| 16 | Media audio honest-skip (`media_audio`) | `colleague/livecheck.py` | ⚠️ | `ec500c0` · 2026-07-02 (SKIP-on-drop classification unit-proven; a live run today is EXPECTED to SKIP, never pass — see the media-proofs section below) | — |
| 17 | Cortex-only vs split comparison | `colleague/livecheck.py`, `colleague/senses.py`, `colleague/loop.py` | ✅ | 2026-07-03 (LIVE: `run_cortex_senses_check` against the served Qwen 27B + Gemma senses — cortex-only wall-clock **34.56s** vs split **32.49s**; senses runtime intake **2.52s** + speak-back **1.22s**; **verbatim original preserved** across the boundary; status=passed, runtime facts only, no quality score) | — |
| 18 | Lobes role discovery (live gateway) | `colleague/lobes.py`, `colleague/config.py`, `colleague/cli/_commands/lobes.py` | ✅ | 2026-07-03 (LIVE: `colleague lobes show` + `config show --json` against the real gateway `:8001` resolved both roles `ready` with zero model ids in colleague — cortex→main `base_url=:8001/v1`, senses→SensesConfig; `probe_lobes_stack` serving=True; the informational per-role `endpoint` `:8000` correctly bypassed for the reachable gateway origin) | — |
| 19 | Flywheel: export → refine → validate (real graded work) | `colleague/feedback.py`, data-refinery `refine`, sloth `validate` | ✅ | `e7f9314` · 2026-07-06 (LIVE: `feedback export --min-rating 4` on the coherence-cli store → 2 REAL graded work items (incl. colleague's own 5/5 t15 run) → `data-refinery refine dataset` kept 2/2 with per-example provenance → real `sloth validate`: `{valid: true, schema: chat, line_count: 2}`) | — |
| 20 | Experiment: detached QLoRA via `colleague experiment` | `colleague/experiment.py`, sloth train/registry | ✅ | `e7f9314` · 2026-07-06 (LIVE on the busy rig, 24GB free: `experiment start` validated then detached pid 3188660; NGC container QLoRA on Qwen3-1.7B over the flywheel dataset; 5 steps, train_loss 3.237; registry row `status: ok`; `experiment status/list` tracked it mid-run) | — |
| 21 | Experiment memory: `summarize --remember` → eidetic | `colleague/experiment.py`, `colleague/memory.py` | ✅ | `e7f9314` · 2026-07-06 (LIVE: summarize read metadata+trainer_state (final_step 5, final_loss 3.4953, checkpoint-5), `remembered: true`; `eidetic recall "experiment 850be4db qlora"` round-trips the record — scope colleague/public per the S9 contract) | — |
| 22 | Adapter export → lobes serve | sloth `export`, lobes fleet | ⚠️ | `e7f9314` · 2026-07-06 (export LIVE: 7-file PEFT/safetensors layout at a lobes-consumable path; SERVING honestly deferred — mounting the adapter needs an operator fleet restart, not a colleague verb) | — |
| 23 | Coherence gate (live scorer, frame provenance) | `colleague/coherence.py`, `colleague/loop.py` | ✅ | `e7f9314` · 2026-07-06 (LIVE: real `coherence meaning score` through the lobes-gateway embedder `:8001/v1` scored the gate's own feature doc 0.492 with `missing_owner`/`missing_next_action` hints; frame provenance recorded; offline exit-2 shape pinned by fixture) | — |
| 24 | Middle-manager beats (talking-to-one, t9) | `colleague/livecheck.py`, `colleague/cli/_commands/session.py`, `colleague/senses.py` | ✅ | 2026-07-06 (LIVE: `test_vllm_live_talking_to_one.py` drove the REAL session path — Gemma senses acked **in its own words** before Qwen cortex's first step, 1/1 proactive update rendered grounded mid-run, conversational speak-back answer; 3 `senses:` transcript lines, chat folded, whole exchange machine-checked from artifact + transcript by `classify_middle_manager_check`; full run 15.69s) | — |
| 25 | Front latency measured (talking-to-one, h7) | `colleague/livecheck.py` | ✅ | 2026-07-06 (LIVE: median senses turn **0.83s** over 3 turns, max 3.52s — target median<3s; wall-clock from `SensesRecord.latency`, never estimated) | — |
| 26 | Lobes advertised role `endpoint` regression | `colleague/lobes.py` (rig-side gap) | ⚠️ | 2026-07-06 (the gateway advertises `endpoint: :8000` + `ready: true` for every role, but `:8000` 404s — only the gateway origin `:8001/v1` serves; the t19 per-role dialing trusted the advertisement, so lobes-discovered senses degraded instantly at ~0.002s/call. Worked around via explicit `COLLEAGUE_SENSES_BASE_URL=:8001/v1` (operator rung outranks discovery); rig/lobes-cli fix pending — the lobes-cli#87 shape, regressed. **2026-07-09 re-probe: FIXED rig-side** — `/capabilities` now advertises the reachable `:8001` for every role, stt/tts included) | — |
| 27 | Global arming shadow proof (at-home arc, t11a) | `colleague/config.py`, `colleague/configdir.py`, `colleague/cli/_commands/lobes.py` | ✅ | 2026-07-10 (LIVE: env dark, repo `.colleague/config.json` carrying only `model` — the pre-arc whole-file-shadow case — plus a user-level `~/.colleague/config.json` `{"lobes": :8001}`: `config show` AND `lobes show --repo` both report armed at the same gateway; graded `passed` by `classify_at_home_check("global-arming", …)`) | — |
| 28 | Mid-run typing survives updates (at-home arc, t11b) | `colleague/cli/_commands/_input_line.py`, `session.py` | ✅ | 2026-07-10 (LIVE over a real PTY on the rig: typed `status please` per-keystroke while Qwen cortex drove a 2-section README edit; capture shows the patch_stdout dance — `colleague ❯ status p` … erase … `[list_dir] .` printed ABOVE … `colleague ❯ status please` repainted and surviving; graded `passed` by `classify_at_home_check("input-line", …)`; line delivery to the talk lane is unit-pinned in `tests/test_input_line.py` + `tests/test_session_input_line.py`) | — |
| 29 | Self-knowledge on BOTH minds (at-home arc, t11c / #306) | `colleague/selfknowledge.py`, `colleague/loop.py`, `colleague/frontdoor.py` | ✅ | 2026-07-10 (LIVE: senses front door answered "what model are you?" naming BOTH exact resolved ids (Gemma senses + Qwen cortex) with no work item — the pre-arc "I don't know which model" deferral is gone; cortex `--mode explore` answered the same plus a correct affected-tests-gate explanation read from the live guide (`read_file` ×1, 2 steps, status ok); both graded `passed` by `classify_at_home_check("self-knowledge", …)` on exact-match ids — the c18 measurable) | — |
| 30 | 35B plan-mode claim parse (#376, t15) | `colleague/plan/cli_driver.py` | ✅ | 2026-08-07 (LIVE: the t14-failing invocation `plan run --model unsloth/Qwen3.6-35B-A3B-NVFP4 --no-workforce --review --yes` reran to a PARSED, CONVERGED frame — 5 plan items, exit 0; the muse lingering-advert fired first (unreachable Gemma-31B) and the fallback-to-main degrade carried; the t6 raw-capture seam stands as the net for future mismatches) | — |
| 31 | Rung-2 distillation, full pipeline (self-learning t17) | `colleague/distill.py`, `colleague/lessons.py`, `colleague/oilcheck/distillation.py` | ✅ | 2026-08-07 (LIVE, a four-round probe series on a throwaway repo with real eidetic + the 27B: round 1 caught the child argv naming a CLI verb that never existed (dead silently — fixed to `-m colleague.distill`); round 2 caught the child racing the artifact write (fixed with the c31 bounded 60s wait); round 3 landed an HONEST `dead: HTTP 404` marker (the muse lingering-advert author — recorded, not silent); round 4 with the served author pinned: completion → schema validate → `status: done` + the lesson upserted into the store (`Lesson (origin=model)` on the same work-lesson id) — and the lesson correctly diagnosed the #346 zero-step collapse. Doctor's alive-counter told the true story throughout, finishing `4 attempt(s), 1 validated`; the marker-less-dead-child hole was closed (artifact-side counting, h23) after round 1 showed `[ok] no distillation activity` over a dead child) | anti-fabrication held all four rounds: no invalid lesson ever landed |
| 32 | #378 correction-diff ablation | `colleague/correction.py`, `colleague/feedback.py` | ✅ | 2026-08-08 (LIVE, EXECUTED IN FULL — **outcome: FALSIFYING per the pre-committed c20 bar, recorded as such**): both arms ran the full 8-task Transformer benchmark (byte-identical briefs, 35B worker verbatim on 32/32 artifacts, separate repos/stores with EIDETIC_DATA_DIR isolation, ON first per c32, real PR + squash + immediate grade per task, every capture sidecar fired). Primary metric verbatim from sidecars/diffs: ON **57** correction lines (0,0,10,17,1,2,27,0) vs OFF **38** (0,2,0,11,9,12,0,4) — ON equal-or-worse = falsified; mean grade identical 3.75; steps 661 vs 601, turns 503 vs 493 (near-parity; duration reported never load-bearing). OFF purity: memory:null 16/16 artifacts; ON recall fired 15/16 (g1 cold-store 0 honest). Recorded texture (never softening the verdict): ON's class-level transfer was REAL (the g3/g4 input-correction classes never recurred; g5 x→KeyX + g6 e→KeyE applied both stored patterns unprompted), while the OFF arm compensated via code-as-memory (self-built latch at 4-leg/195-step cost in g3; reused its own g5 dedup in g7 for 0 lines vs ON's 27) — an un-removable control-arm channel. The run's own capture path caught TWO dead-lane instrument bugs fixed test-first as separately-recorded commits: #391 (distill sidecar shadowed slugged artifacts — capture dead on armed runs since v1.56.0) and #392 (code-lessons missing the eidetic-required text key — zero lessons ever stored in production before this run). Memory-default decision recorded: KEEP conditioned on the lesson-specificity re-design (row 34's same next-delta). Full evidence: docs/experiments/2026-08-08-prove-self-learning-387-arms/ (final-comparison.md + per-task cycle records + metrics tabulation); game shipped winnable in BOTH arms (35.9s / 55.8s timed playthroughs). #394 tracks the post-streaming rerun removing the timeout-pressure confound | anti-fabrication held: the falsifying outcome stands unspun; no gate skipped, no vacuous comparison |
| 33 | #377 NEBULA strive ablation (recall ON vs OFF) | `colleague/strive.py` | ⏳ | RECIPE RECORDED (same goal/measure/seeds/attempt-cap, only recall differing; attempts_ON < attempts_OFF supported, equal-or-worse FALSIFYING); needs the nebula-run benchmark + rig hours — pending a future session; strive's mechanics are CI-proven end-to-end (`tests/test_e2e_selflearning.py`, real episode worktree + measure cwd) | — |
| 34 | #387 exp-1: SELF-taught warm-vs-cold (the pipeline's own lesson) | `colleague/memory.py`, `colleague/distill.py`, `colleague/loop.py` | ✅ | 2026-08-07 (LIVE, 35B worker, `pipeline-sim` fixture at base `8c3fdf7`, cap 4 turns, identical task/runtime both legs — **outcome: FALSIFYING per the confirmed c20 bar, recorded as such**. COLD `bf3c9b411a91`: budget-exhausted incompletion, 5 turns / 13.4s / 0 deliverable, honest-cold (recalled=2, both records verified generic — the h3/h14 footnote); its OWN pipeline distilled a validated `origin=model` process lesson ("all steps went to tracing; transition to execution early"). WARM `f19a83e1f7bb`: the lesson VERIFIABLY in context (recalled=3, injected 2071 vs 1180 chars — the +891 delta IS the lesson) yet the step trace was IDENTICAL (same 5 reads, same cut): 5 turns / 15.6s / 0 deliverable / 149 answer chars (names `adaptive.py` without reaching it, vs 0 cold). A self-taught PROCESS-level lesson did not change step-capped behavior; contrast the hand-seeded ANSWER-level lesson (memory.md h3/h14: 5× fewer steps) — **lesson specificity is the operative variable**, the arc's next-delta. Four discarded attempts retained as evidence (#1 `c8d6a6f88577` too easy at cap 10; #2 `41a658e6b757` incomplete-but-correct, its store record deleted on an integrator misread BEFORE inspection — error recorded; #3 `6469dfdcda19` invalidated: child-race store contamination + turn-batching beat cap 6; warm-1 `18ef817069be` vacuous: recalled=0 under the stale installed CLI). The session also caught + fixed the eidetic-0.13 recall envelope bug (#389, commit `163574d` — every armed run silently recalled 0 before it) and filed the ellipsis-lesson validator hole (#388, the dots lesson `41a658e6b757` vs the genuinely diagnostic `6469dfdcda19`/`bf3c9b411a91` side by side) | anti-fabrication held: no gate was skipped, no vacuous comparison was reported, the falsifying outcome stands unspun |
| 35 | Qwen3.8 rollover: new default + 131072 budget, live (#404) | `colleague/config.py`, `colleague/distill.py`, `colleague/oilcheck/*` | ✅ | 2026-08-20 (LIVE, three proofs on the rolled rig — cortex `unsloth/Qwen3.8-27B-NVFP4` @ 1,048,576-token YaRN: **(1) before-state** reproduced twice — the resolution-time refresh warning on the stale `CONVERTIBLE_MODEL` pin (t1, lobes-armed) AND a hard 404 from the installed 1.59.0 CLI's old builtin default (route a, caught via the stale-PATH gotcha); **(2) bare smoke** — no pins, lobes+three-tier disarmed: the NEW builtin default dialed directly, `status: ok`, exit 0, 27s, deliverable verified on the work branch; **(3) long-context proof at the 131072 default** — a 3-file WebGPU game brief (Nebula Drift): completed `status: ok`, streaming end-to-end, ZERO overflow churn, 9 model turns / 7 steps / 37,419 bytes written / 686,893 reasoning chars, 3h07m wall — the latency strain was real and MANAGED live: backpressure escalated (#255), the request timeout self-raised 300→600s bounded (#268), and ONE flight guidance (#309) broke a single-turn mega-composition into per-file writes; `node --check` PASS on the delivered module. Distill/probe caps were sized from live measurement the same day (t3: worst realistic rung-2 payload 1449/1600 tokens; the 35B worker seat misreports tool-calling at 128 → both raised). Reasoning-heavy creative briefs remain slow at temperature 0 — pair `COLLEAGUE_TIMEOUT` guidance (c11) with decomposed briefs | — |
| 36 | Game-benchmark two-arm + WebGPU postmortem (v1.60.0 tree) | `~/.colleague/commands/game-benchmark.md`, `colleague/loop.py`, lobes worker proxy | ⚠ | 2026-08-20 (LIVE, three findings on this exact tree): **(a) WebGPU postmortem** — browser-executing row 35's game revealed its runtime was broken by 6 WebGPU/WGSL bug classes across 17 sites (malformed `var<uniform>` bindings, `@builtin(index)`, JS-vs-WGSL uniform packing, missing COPY_DST everywhere, strip-quads as triangle-list, indexFormat on non-strip) — `node --check` green throughout, WebGPU errors async+non-throwing so logic "ran" with zero draws; fixed operator-side and verified rendering. Second occurrence of the NEBULA DOA signature: **a browser-execute gate is the missing verification rung** (#407/#408 filed). **(b) Benchmark arm A (solo cortex, task `47e232d3bca6`): PASS grade 5** — self-playable terminal game, 12/12 tests + skill gradient (greedy 1532 > random 118 > passive 76) verified by independent rerun byte-for-byte; it CAUGHT its own gradient failure and fixed the game design (2x center-lane spawn), not the test; zero guidance, 1h20m, 16 turns. **(c) Arm B (three-tier, remote-proxied 35B worker): 2 attempts, 0 completions** — both wedged in the SEAMS, never the minds: a proxied streaming read starved 46 min past the timeout ladder (#409) and SIGTERM salvage committed WIP but wrote no artifact, blocking `--continue` (#410). Operator verdict recorded: complex topology is the problem; solo is default until the seams harden | #407 #408 #409 #410 |
| 37 | #411 model-bound agents — live armed runs (agents mode, worker dormant → recorded cortex fallback) | `colleague/agents/*`, `colleague/loop.py` seams, `colleague/tools.py` | ✅ | 2026-08-21 (LIVE, Spark rig, cortex `unsloth/Qwen3.8-27B-NVFP4` @ 1,048,576, `agents: true`, throwaway repo): **run 1** `216d1110b1bc` — `status: ok`, 10 turns / 11 steps / 830 s, 58,949 tokens exact; **10/10 invocations attributed** (`thinker_coder` → role `cortex`, `/tokenize`-sourced estimates, max `token_estimate` 3,520 → manifest ratio **0.0034** of the advert), ledger `.colleague/ledger/<id>.jsonl` at the operator repo with `operator_request` + 10 `invocation` + 3 `changed_path`, subagent spawned and its tests passed — but the child carried NO identity: the model-facing `subagent` tool had no `profile`/`context_mode` params (gap found by this run; fixed in `2f8b167`). **run 2** `0ff226c60ebe` (after the fix) — `status: ok`, 12 turns / 16 steps / 374 s, 76,907 tokens; 12/12 attributed (max estimate 5,648, ratio 0.0054); the child bound via `profile: associate`, `context_mode: clear` → `SubResult.agent_id=agent-382c2a866009`, `resolved_model` cortex, **`fallback_from_role: associate`** (the recorded fallback, no `associate` role served), `delegate` + `return` events bracketing the spawn on the ledger, clear-mind handover; 0 refusals. Both runs: worker/associate absent, no refusal, unarmed repos untouched | #411 |
| 38 | #411 matched experiment: solo cortex (A) vs agents mode (B) on the game-benchmark brief | `colleague/agents/*` | ⏳ | PRE-REGISTERED 2026-08-21 — bars committed in `docs/deliveries/2026-08-21-model-bound-agents-411.md` BEFORE the arms run (completion, grade, latency ≤1.5×, tokens ≤1.25×, invalid tool calls, corrections, 100 % attribution, manifest ratio <0.5); agents mode stays OPT-IN until this row carries both arms' numbers | #411 |
| 39 | #416 per-seat thinking effort — live proof (t11): seat payloads + reasoning_tokens, child fan-out by role | `colleague/effort.py`, `colleague/engines/vllm_openai.py` (`chat_template_kwargs`), seat builders, `colleague/subagents.py` | ✅ | 2026-08-22 (LIVE, Spark rig via the lobes gateway, cortex `unsloth/Qwen3.8-27B-NVFP4`): **(a)** `tests/test_vllm_live_thinking_effort.py` 3 passed — the senses seat sent `{"enable_thinking": false}` and `usage.completion_tokens_details.reasoning_tokens == 0`; the deepthink seat sent `{"reasoning_effort": "xhigh"}` and reasoned (> 0); the acting seat at `medium` formed a `read_file` tool call. **(b)** child fan-out on a throwaway repo (`colleague work` → ONE `subagents` call, roles explorer/reviewer/validator/planner): status ok, 3m53s, all four children returned with correct answers (explorer listed files + defs; reviewer 3-line review; validator ran pytest → "All tests passed"; planner 3-step plan) — 18 requests on the wire: 6 at `enable_thinking:false` (senses acks + the explorer child), 6 at `low` (reviewer + validator children), 6 at `medium` (acting seat + planner child); no file edits; merge child ok. **(c)** dispatch-lane evidence from the workforce itself (ledger in `docs/experiments/2026-08-22-per-seat-thinking-effort-416-workforce-ledger.md`): colleague's own runs switched from the rig's `xhigh` default to `medium` the moment t1–t3 merged (t8b: 14 acting requests at medium + 5 senses at off). Honest limits: n=1 per cell; `low`/`off` children on shallow read-only tasks only; the `low` acting-seat arm (t7b) did NOT bound the long silent turns on an existing-module edit brief — see the ledger. **(d)** final end-to-end run on the merged branch (`7968b1281593`, throwaway repo, "add mul + test"): status ok in 2m09s, 6 steps, real edits + `2 passed`; 7 requests = 5 acting at `medium` + 2 senses at `enable_thinking:false`. | #416 |
| 40 | qwen-direct single-model default (spec 2026-08-22): bare session dials only cortex; senses/muse discovery opt-in; `/model` + `/effort` listings; not-consumed lines | `colleague/config.py`, `colleague/cli/_commands/_listing.py`, `_session_actions.py` | ✅ | 2026-08-22 — `docs/evidence/2026-08-22-qwen-direct-no-gemma-results.md`: default arm 2 requests both Qwen3.8 (wall 12.45 s, correct self-knowledge answer) vs senses-opted-in 1 gemma request (6.81 s) → h17 1.83× ≤ 2×; suite 9160/0; #422 trio green on a lobes-armed checkout; config/lobes show + bare `--model`/`--effort` print the not-consumed lines and tables | — |
| 41 | adopt-from-qwen-code (spec 2026-08-27): pre-registration — three model arms + a temperature arm on the game-benchmark brief | `scripts/compare_arms.py`, `docs/specs/2026-08-27-adopt-from-qwen-code.md` | ⏳ | PRE-REGISTERED 2026-08-27, BEFORE any arm runs — brief: the game-benchmark command template (`~/.colleague/commands/game-benchmark.md`) plus one small repo task, n>=3 runs per brief per arm; arms: `main` / branch `associate-unarmed` / branch `associate-armed` / a temperature arm (T=0.0 vs the served model's default, decision c51); rig: `localhost:8001` `unsloth/Qwen3.8-27B-NVFP4`; effort table: the v3 defaults (`docs/features/thinking-effort.md`); bar (decision c22/c28): wall-clock ratio <= 0.7x, model-turns ratio <= 0.8x, success rate >= main's — computed by `scripts/compare_arms.py` from artifact `stats.duration_seconds`/`stats.model_turns`, never from prose | — |
| 42 | adopt-from-qwen-code: main before-state (no `max_tokens` clamp) | `colleague/engines/vllm_openai.py` | ✅ | main @ `ff7331e` (worktree `baseline-main`, GPU otherwise idle, `COLLEAGUE_TIMEOUT=300`); `COLLEAGUE_DUMP_REQUEST=1` shows no `max_tokens`; game-benchmark n=3: `15bda418a881` ok 817 s / 15 turns, `602a40e5a2ee` ok 581 s / 13 turns, `184e9f98957e` STALLED at step 5 (silent turn, flight heartbeat stale 17 min, GPU 7 %, vLLM `num_requests_running` 0 while the client waited; gateway `BrokenPipe`/`JSONDecodeError` tracebacks — SIGTERM'd, scored as failure); repo task n=3: `ed07bc33333f` 33 s / 3 turns, `621d22eb6469` 26 s / 3 turns, `c8b1de2bf765` 32 s / 4 turns, all ok. Artifacts + gateway log under the session scratchpad `baseline/` (2026-08-27) | game-3 stall = the #415 shape the branch's stream-idle guard (t7) cuts at 240 s |
| 43 | adopt-from-qwen-code arm 2: branch, all mechanics, adopted prompt, associate unarmed | `colleague/turnbudget.py` + the ported modules | ✅ | game n=3 all ok: `e8a556390cd8` 1589 s/18, `a998d62c96ed` 1612 s/22, `822b346e40ef` ~1610 s/18 → mean 1604 s / 19.3 turns = **2.30× / 1.38× vs main (MISS)**; repo n=3 ok: `32e62af65c95` `e7d6dd7208c6` `021dbfa8d48b` → 52 s / 5.3 turns = 1.70× / 1.60× (MISS). Reasoning 99–101k chars/run vs 24–37k on main; extra grep_search/glob verification turns on the repo brief (2026-08-27 20:00–21:15, spec tip `b90aff9`) | the adopted prompt text is the cost — see row 44 |
| 44 | adopt-from-qwen-code attribution arm: branch + `COLLEAGUE_PROMPT_VARIANT=v1` | `colleague/prompttext.py` | ✅ | game n=3: `18dbc304b4e9` 1041 s/15 ok, `91f300b0a858` 498 s/15 ok, game-2 INCOMPLETE — gateway hang cut by the **stream-lifetime guard at exactly 900 s** (`warnings[0].guard = stream-lifetime`, 8 steps preserved) → mean 769 s / 15 turns = **1.10× / 1.07× (near parity, still MISS)**; repo n=3 ok: `dfe950269a32` `68f6da73e023` `7becea3fad09` → 36 s / 3.7 = 1.18× / 1.10× (21:19–22:08) | prompt wording accounts for most of row 43's miss → `v1` becomes the default (h21 revert-or-flag) |
| 45 | adopt-from-qwen-code arm 3: branch + `COLLEAGUE_ASSOCIATE_MODEL=lobes` | `colleague/associate*.py` | ✅ | game n=3 ok: `e6a35cbbdd57` 1156 s/26, `69d02da0ba77`, `c6c498415c94` → mean 1367 s / 26 turns = 1.96× / 1.86× (MISS); repo n=3 ok: `2fb906f2593e` `f19dfcc7e8a4` `d96143bc4752` → 38 s / 4.0 = 1.25× / 1.20×. **Zero associate calls**: no scout spawned (#435) and the throwaway repo has no eidetic store so the distill seat never fired — the arm measures 'arming is inert here' (22:08–23:19) | associate's evidence is the direct seat experiments (17 s survey / 9 s digest off; 25 s / 61 s low) — #439 |
| 46 | adopt-from-qwen-code temperature arm: branch + `COLLEAGUE_TEMPERATURE=0.6` | `colleague/config.py` | ⚠️ | game: game-1 STALLED 1413 s at step 2 (GPU 3 %, vLLM idle; lifetime guard did NOT fire — blocking-fallback path, #438) SIGTERM'd; game-2 hang cut by the lifetime guard at 900 s in its first turn; game-3 `bea01103c7e4` ok 1029 s/12 turns (n=1: 1.47× / 0.86×); repo n=3 ok: `a7540e7ebc7d` `1d48f469431b` `69728386c198` → 38 s / 3.7 = 1.26× / 1.10× (23:19–00:21) | underpowered by the gateway flake (lobes-cli#220); rerun after #438 |
| 47 | web-scout-associate (spec 2026-08-28): pre-registration — web-scout brief in a repo WITH an eidetic store | `colleague/web.py`, `colleague/associate_seats.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-28, BEFORE any run — brief (verbatim in `docs/live-testing/briefs/row47-web-scout.md`): 'survey these three upstream docs, then change one module' (three upstream references read via the `web` tool, then the smallest edit to one module matching the docs' auth error shape); repo: a throwaway repo WITH an eidetic store (`.eidetic/` present) so the distill seat can fire, associate armed (`COLLEAGUE_ASSOCIATE_MODEL=lobes`), `webglass` on PATH; pass bar: the scout child's served model = the associate's (recorded on the child artifact), the scout's digest cites WebGlass evidence ids (`operation_id`/`evidence_refs` verbatim), cortex's final answer cites them, and `associate_calls` > 0 — delegation observed, never forced; main baseline: `4e814c8` (artifact ids recorded after the run); result: pending → RUN 1 2026-08-28 13:10 `c6c53ac2c214` (v1.65.0 pre-t14): ok, 5 turns, 8 web calls — but 7 were CLI usage errors (wrong argv: page verbs need `--url`, search needs options before `--`; rendered header-less, `web_failed` 1) → **bug d14**, fixed in t14 (colleague `0a2542790cfe`, merged 098e46d). RUN 2 14:01 `a5fe419b2a36` (post-t14): 6 web calls, every step with `operation_id`/`lifecycle_state`; both `search` calls **succeeded with real Brave results inside the UNTRUSTED delimiter**; the 3 `page read` + 1 `page open` failed `navigation_failed` (the pre-registered `docs.example.com` never resolves — RFC 6761 — and browser DNS is dead from this host anyway), counted `web_failed` 4; **0 delegations, associate_calls 0** — cortex fetched itself, then drifted into host network reconnaissance (`/etc/hosts`, `ss -ltnp`, `~/.cloudflared`) and was stopped by pilot at step 22 / 10 turns / 612 s (d15). **MISS** on the bar (no scout on the associate, no evidence ids cited in an answer); the tool itself is proven end-to-end. Evidence → #443 | #435 #436 |
| 48 | web-scout-associate (spec 2026-08-28): pre-registration — decomposable brief, delegation observed, n=3 | `colleague/subagents.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-28, BEFORE any run — brief (verbatim in `docs/live-testing/briefs/row48-delegation.md`): 'survey three modules, then change one' (survey modules `alpha`/`beta`/`gamma` — interfaces, call graph, duplication — optionally via scout children, then the smallest edit to one module removing the duplication, interface stable); n=3 runs on the branch arm and the same brief n=3 on the main baseline; pass bar: delegation ≥ 1 on ≥ 2 of 3 runs (a `subagent`/`subagents` step in the artifact), turns ≤ 1.0× / wall ≤ 1.2× vs main @ `4e814c8` — computed by `scripts/compare_arms.py` from artifact stats (the new `delegations`/`associate_calls`/`web_calls` columns), never from prose; main baseline: `4e814c8` (artifact ids recorded after the run); result: pending → RUN 2026-08-28 13:12–13:31 (`scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0`): main @ 4e814c8 n=3 `df6a2ffd0437` `b6eb2ac23576` `d9590dbc7f09` → 89 s / 5.67 turns; branch (v1.65.0 tip, associate armed, web offered) n=3 `038619813cc8` `83a953c5c584` `84414109dddd` → 295 s / 8.0 turns = **3.31× / 1.41× — MISS**; delegations **0/3 on both arms**, associate_calls 0, web_calls 0 (the brief needs no web); all six runs `ok`, each changed one module (branch: gamma ×3; main: gamma, beta, beta); branch runs are deterministic replicas (identical 15-step trajectories, 19k reasoning chars vs 9.6k on main, +2 grep_search verification turns + a second edit_file) — the #437 pattern: a larger offered surface buys deliberation, not delegation | #435 #436 |
| 49 | purpose-tools-associate-seat (spec 2026-08-28): pre-registration — decomposable brief, purpose-tool delegation observed, n=3 | `colleague/purpose_schemas.py`, `colleague/subagents.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-28, BEFORE any run — brief (verbatim in `docs/live-testing/briefs/row49-purpose.md`, the row-48 brief verbatim): 'survey three modules, then change one' (survey modules `alpha`/`beta`/`gamma` — interfaces, call graph, duplication — optionally via scout children, then the smallest edit to one module removing the duplication, interface stable); repo: a throwaway repo WITH an .eidetic store, eidetic CLI 0.13.0 (so the distill seat can fire); n=3 runs on the branch arm (purpose tools offered, associate armed) and the same brief n=3 on the main baseline; pass bar: purpose calls ≥ 1 on ≥ 2 of 3 runs (a purpose-tool step in the artifact), turns ≤ 1.0× / wall ≤ 1.2× vs main @ `e589451` RE-RUN n=3 — computed by `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` from artifact stats (the `delegations` column = purpose-tool calls), never from prose; record the memory distill counters (attempts/validated/detached) and the distill child's served model; result: pending → RUN 2026-08-28 19:54–20:29 (`scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0`): main @ `e589451` RE-RUN n=3 `70eb4ddcb69c` `1abb0335ad27` `df76184e7eca` → 327 s / 5.67 turns (232/628/119 s — the runs went through the lobes gateway with cortex served on two machines, so wall spread across hosts: a confound on the wall column); branch @ `80b4138` (purpose tools offered, associate armed) n=3 `78b0f0f90855` `480b6d6ea857` `59fb72435645` → 88.6 s / 6.67 turns = **0.27× wall / 1.18× turns — MISS on turns**; **purpose calls 0/3, sub_results 0 — MISS** on the delegation clause; all six runs `ok`, each changed one module (branch: beta, beta+gamma, beta; main: gamma, gamma, beta); reasoning 2.8–3.6k chars on the branch. A writer-role smoke on `95520cb` (`6ce1ed9bd8fe`, not pre-registered) also made 0 purpose calls at 777 s / 6 turns / 154k reasoning chars. Reading: on a three-small-file brief cortex reads the files itself; the purpose form does not lower the ask enough to be chosen (#435 stands). Memory: distill counters not exercised (no lesson written — the runs were `ok` with no failure substance). | #435 #443 |
| 50 | purpose-tools-associate-seat (spec 2026-08-28): pre-registration — web-survey purpose tool, scout on the associate seat | `colleague/purpose_schemas.py`, `colleague/associate_seats.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-28, BEFORE any run — brief (verbatim in `docs/live-testing/briefs/row50-web-purpose.md`, the row-47 web brief adapted to the purpose-tool arm): 'survey these three upstream docs, then change one module' (three upstream references read via the `web_survey` tool — cortex holds `web_survey` and NO raw `web` — then the smallest edit to one module matching the docs' auth error shape); repo: a throwaway repo WITH an .eidetic store, eidetic CLI 0.13.0 (so the distill seat can fire), associate armed (`COLLEAGUE_ASSOCIATE_MODEL=lobes`), `webglass` on PATH; pass bar: the scout child's served model = the associate's (recorded on the child artifact), the scout's digest cites WebGlass evidence ids (`operation_id`/`evidence_refs` verbatim) and cortex's final answer cites them, and zero `run_command` steps outside the repo (the d15 host-recon drift cannot recur — the seat holding web has no `run_command`); delegation observed, never forced; record the memory distill counters (attempts/validated/detached) and the distill child's served model; result: pending → RUN 2026-08-28 20:29–20:54 `0780c75e2519` (tip `80b4138`, webglass-cli 0.8.3, eidetic 0.13.0): **delegation observed** — cortex fired `web_survey` ×3 in its FIRST turn (one per URL) and never touched `run_command` (0 steps outside the repo: the d15 host-recon path is closed — PASS); all three scout children ran on the associate seat (`served_model` recorded as the wire alias `associate` on the parent's steps/`sub_results`; the served Nemotron id is NOT on the parent artifact because in-process purpose children persist no artifact of their own — PARTIAL on the served-model clause, follow-up); child outcomes ok/incomplete/incomplete — the ONE work-item web budget (`COLLEAGUE_WEB_MAX_CALLS`=20) was consumed across the three children (`web_calls` 20, `web_failed` 3: the pre-registered `docs.example.com` URLs never resolve, so the scouts searched around them — Speakeasy/Zendesk/API7 guides — read-only drift inside the scout, not the host); each digest cites WebGlass `operation-…` ids; then cortex step-stalled at step 7 (stream-lifetime 900 s, #438) with NO final answer → the 'evidence ids cited in cortex's final answer' clause is a **MISS**; no module changed. Webglass sessions 17 before and after (no leak growth on 0.8.3). Overall: **MISS on the bar, mechanism proven** (purpose-form delegation happens exactly where the raw tool is absent). | #435 #443 #438 |
| 51 | purpose-tools-get-chosen (spec 2026-08-29, plan t13): row-49 VALIDITY re-run — is the 0/3 real or dropped markup? | `colleague/toolmarkup.py`, `colleague/runcounts.py`, `docs/live-testing/briefs/row49-purpose.md` | ✅ | RUN 2026-08-30 on the wave-2/3 tip (`95c921b`). Purpose: row 49 recorded **0/3 purpose calls**, and #360's failure mode (cortex emits tool-call markup as plain text, silently dropped) makes 'never tried' indistinguishable from 'tried and dropped' — so the arc's own motivating evidence was unverified until the t6 markup counter existed. Method: the row-49 brief text re-run **verbatim** (`docs/live-testing/briefs/row49-purpose.md`, confound and all — an exact replay, not the re-authored neutral brief), n=3, on a rebuilt `alpha`/`beta`/`gamma` fixture (duplicated normalisation across alpha/beta; call graph gamma→beta→alpha). Row 49's SURFACE was replicated on the current tip via the t8 drop knob `COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents` (t11 has since restored the raw pair to the default allow-list) plus `COLLEAGUE_ASSOCIATE_MODEL=lobes`. Result: `d03f17450031` 10 steps, `cff5a0e0ca96` 9 steps, `35dd40cbdfb7` 9 steps — **delegation 0/3, markup 0/3**, all three `ok`, each changed exactly `beta.py` and correctly identified `beta.canonicalise_payload` as the line-for-line copy of `alpha.normalise_record`. **Verdict: the clause that decided it is the markup clause — markup was 0 on every run, so row 49's 0/3 is REAL BEHAVIOUR, not an instrumentation artifact; the arc's framing needs no correction.** Counter validity is not assumed: `tests/test_toolmarkup_count.py` (13 nodes, incl. the end-to-end AC1 landing a nonzero count on a real artifact) passes on this tip, so the zero is a measured zero. **Unplanned finding:** every run recorded `batches_run: 2`, `calls_parallelised: 7` — cortex used the parallel read-only tool batch (convention change (6)) instead of delegating. It is not refusing concurrency; it already holds a cheaper form of it, which is a stronger explanation of the 0/3 than 'the purpose form does not lower the ask enough'. Honest limits: row 49's original fixture was not recorded in reproducible detail, so this used an equivalent rebuilt fixture, not a byte-identical one; and the brief is three small files cortex can rationally read itself (c46), so this row validates the INSTRUMENT, and does not establish that delegation would be declined on a brief that genuinely needs it. `scripts/compare_arms.py` unmodified (`git diff` empty). | #360 #443 |
| 52 | purpose-tools-get-chosen (spec 2026-08-29, plan t14): **arm A0 — decomposable BASELINE**, the reference every decomposable ratio is computed against | `docs/live-testing/briefs/arm-decomposable-neutral.md`, `colleague/actingsurface.py`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any arm run — **result: RECORDED 2026-08-30 — the six cells and the verdict are at the END of this row.** Arc: `purpose-tools-get-chosen` (spec `docs/specs/2026-08-29-purpose-tools-get-chosen.md`, plan t14). **Tip pin (deviation d1).** Every run of this arm executes on the POST-t9 tip — `95c921b` (*fix(t9): the default prompt names the six purpose tools, not subagent/subagents*) or later on `spec/purpose-tools-get-chosen-w2`; d1 (`devague deviate --list`) records the operator ruling that t9 regenerated `tests/snapshots/prompttext_v1.txt`, so any run from before `95c921b` is NOT comparable and is voided rather than averaged in. The exact tip SHA of each run is recorded beside its id. **Pass bar (committed before the run).** Delegation: ≥ 1 delegation call on ≥ 2 of 3 runs, read off the artifact steps, never from prose. Ratios: `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` — the two flags are written out because the script's DEFAULTS are 0.7/0.8 and this arc deliberately overrides them; the numbers come from `stats.duration_seconds` / `stats.model_turns` on the artifacts, never from prose. n=3 per arm. `scripts/compare_arms.py` is NOT modified by this arc (its `git diff` must stay empty; a modified comparator voids the whole matrix). **Cells to fill after the run (six, in this order, never before):** (1) delegation rate n/3 and which tool was called; (2) markup count per run (`stats.counts.markup_tool_calls`, the #360 counter added by t6 — a zero-delegation run with markup > 0 is INCONCLUSIVE, not a refusal to delegate); (3) task success (status, whether exactly one module changed, whether its public interface stayed stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`). Recorded beside them: `stats.counts` in full (notably `batches_run` / `calls_parallelised` — row 51's unplanned finding — and `stream_guard_trips`), stalls-cut / stalls-escaped per run (q4: a `step-stall` run is RE-RUN, never averaged in), the child's served model where a child ran, and the memory distill counters (attempts/validated/detached). **Arm identity is the digest, not the operator's belief.** Each run's arm is established by `TaskResult.prompt_digest` read off its artifact (t7, `colleague/contract.py` `prompt_digest_for`, sha256 of the composed system prompt) — never by the overlay file the operator believes was staged. All three runs of an arm must carry ONE digest, and that digest must be the one this row pre-registers; a mismatch VOIDS that run. **P0 is the CONTROL, not the baseline.** t12 established that an operator overlay REPLACES the built-in writer `prompt_fragment` (`colleague/roles.py` `_resolve_role_prompt` — the file prompt wins), so a prose arm's prompt is NOT 'the default prompt plus prose'. A1/A2/A3 all lose the built-in fragment identically — a constant ACROSS the three prose arms, never a between-arm confound — but it means **the prose lever is measured A2-vs-A1 and A3-vs-A1, never A2-vs-A0**. A0 is the true default and is the reference only for the surface lever (A4) and for absolute task success. **Task success sits BESIDE the delegation rate (c46).** The only outcome evidence so far says the DELEGATING run failed (row 50: budget consumed, step-stall, no module changed) and the NON-delegating ones succeeded (rows 49 and 51: 3/3 `ok`, correct module, correct duplicate identified), and row 51 found cortex already holds a cheaper form of concurrency — the parallel read-only tool batch (`batches_run` 2, `calls_parallelised` 7 on every run). So **"cortex was right not to delegate" is an admissible verdict of this row** and is written as a finding, not as a failure of the arc. **Verdict discipline.** The verdict line written after the run MUST name which clause decided it — the digest clause (arm identity), the markup clause (#360 dropped calls), the delegation clause (≥1 on ≥2 of 3), the task-success clause (c46), or the ratio clause (`--bar-wall 1.2` / `--bar-turns 1.0`) — never a bare PASS/MISS, and a miss is written as a miss. **Containment (s26).** The arm runs in a throwaway repo with an `.eidetic` store (so the distill seat can fire); nothing in a run's output announces an active role overlay, so `<repo>/.colleague/agents/writer.md` is staged for the arm and deleted after it. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Lever: NONE — this is the reference arm** (exactly one lever per row; A0's is the empty one, and it is named explicitly so no later reader treats it as a condition). **Instrument cited:** (a) the drop-knob VALUE `COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents` (t8, `colleague/actingsurface.py` `ACTING_DROP_ENV`), recorded verbatim from the run's environment — the raw delegation pair is OFF the acting seat here, so A0 is the purpose-tools-only surface; and (b) the `prompt_digest` read off each artifact, which for A0 is the NO-overlay composed prompt (the run also asserts that `<repo>/.colleague/agents/writer.md` does not exist before it starts, per the c31 instruction — but the digest on the artifact, not that assertion, is what identifies the arm). A0 carries the built-in writer `prompt_fragment`; it is the only decomposable arm that does. **A0 is the reference for the SURFACE lever (A4) and for absolute task success — it is NOT the reference for the prose lever** (see the P0 paragraph above). Its own verdict clause is the digest clause plus the markup clause: A0 is usable as a reference only if all three runs share one no-overlay digest and their markup counts are recorded. Brief: `docs/live-testing/briefs/arm-decomposable-neutral.md`, pasted verbatim (tool-free by design — the same brief runs across arms whose surfaces differ, so no tool name may steer it). Fixture: the rebuilt `alpha`/`beta`/`gamma` repo of row 51 (duplicated normalisation across alpha/beta; call graph gamma→beta→alpha), identical on every decomposable arm. **RESULT (2026-08-30, n=3).** Matrix tip `3b59d24` — the t14 pre-registration commit itself, i.e. later than `95c921b`, so deviation d1's post-t9 requirement is satisfied and no run is voided on the tip pin. Ordering is clean: the rows were committed 01:31:56 and the matrix started 01:33:36, so every cell below was pre-committed before its run. `scripts/compare_arms.py` was NOT modified by this arc — its `git diff` is empty, so the matrix is not voided on the comparator clause. Across all 21 runs of the matrix every run's `prompt_digest` matched the arm this row pre-registers for it: **zero voided runs**, and `stats.counts.markup_tool_calls` = 0 on all 21, so no run is INCONCLUSIVE under the markup clause. Artifacts `6f65eab59370`, `66d5b4225a6c`, `a8b8803ffcab`. **Digest clause:** all three runs carry the pre-registered NO-overlay digest `b7491476a61238a4` — one digest across the arm, none voided. **(1) Delegation:** 0/3 runs, calls per run `[0,0,0]` — no purpose tool and no raw `subagent`/`subagents` step on any run. **(2) Markup:** `markup_tool_calls` = 0 on all three runs, so the zero is a real refusal to delegate and not a dropped call (row 51's finding, re-confirmed on the default surface). **(3) Task success:** 3/3 `ok`, each run changing exactly one module. **(4)/(5) Ratios: none** — A0 is the baseline the whole decomposable family is computed against, so it has no ratio of its own. **(6) Reasoning chars:** mean 7574; mean turns 7.67; mean wall 258.26 s. `stats.counts`: `batches_run` `[2,2,2]`, `calls_parallelised` `[7,7,7]` — cortex ran the parallel read-only tool batch on EVERY run while delegating nothing. Recorded as a GAP rather than estimated: `stream_guard_trips`, stalls-cut / stalls-escaped per run, and the memory distill counters (attempts/validated/detached) are not present in the t16 results extract, so they are reported as not captured, never inferred. **VERDICT: PASS as a reference arm — decided by the digest clause plus the markup clause** (the two this row pre-committed as its own): one shared no-overlay digest across three runs, markup counts recorded and zero, so A0 is usable as the reference for A4 and for absolute task success. **Finding recorded per c46:** the NON-delegating baseline succeeded 3/3, so 'cortex was right not to delegate' is the supported reading of this arm, written as a finding and not as a failure of the arc. | #443 #360 |
| 53 | purpose-tools-get-chosen (spec 2026-08-29, plan t14): **arm A1 — prose CONTROL (P0 overlay)**, the reference every prose ratio is computed against | `docs/live-testing/overlays/P0/writer.md`, `colleague/roles.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-30, BEFORE any arm run — **result: RECORDED 2026-08-30 — the six cells and the verdict are at the END of this row.** Arc: `purpose-tools-get-chosen` (spec `docs/specs/2026-08-29-purpose-tools-get-chosen.md`, plan t14). **Tip pin (deviation d1).** Every run of this arm executes on the POST-t9 tip — `95c921b` (*fix(t9): the default prompt names the six purpose tools, not subagent/subagents*) or later on `spec/purpose-tools-get-chosen-w2`; d1 (`devague deviate --list`) records the operator ruling that t9 regenerated `tests/snapshots/prompttext_v1.txt`, so any run from before `95c921b` is NOT comparable and is voided rather than averaged in. The exact tip SHA of each run is recorded beside its id. **Pass bar (committed before the run).** Delegation: ≥ 1 delegation call on ≥ 2 of 3 runs, read off the artifact steps, never from prose. Ratios: `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` — the two flags are written out because the script's DEFAULTS are 0.7/0.8 and this arc deliberately overrides them; the numbers come from `stats.duration_seconds` / `stats.model_turns` on the artifacts, never from prose. n=3 per arm. `scripts/compare_arms.py` is NOT modified by this arc (its `git diff` must stay empty; a modified comparator voids the whole matrix). **Cells to fill after the run (six, in this order, never before):** (1) delegation rate n/3 and which tool was called; (2) markup count per run (`stats.counts.markup_tool_calls`, the #360 counter added by t6 — a zero-delegation run with markup > 0 is INCONCLUSIVE, not a refusal to delegate); (3) task success (status, whether exactly one module changed, whether its public interface stayed stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`). Recorded beside them: `stats.counts` in full (notably `batches_run` / `calls_parallelised` — row 51's unplanned finding — and `stream_guard_trips`), stalls-cut / stalls-escaped per run (q4: a `step-stall` run is RE-RUN, never averaged in), the child's served model where a child ran, and the memory distill counters (attempts/validated/detached). **Arm identity is the digest, not the operator's belief.** Each run's arm is established by `TaskResult.prompt_digest` read off its artifact (t7, `colleague/contract.py` `prompt_digest_for`, sha256 of the composed system prompt) — never by the overlay file the operator believes was staged. All three runs of an arm must carry ONE digest, and that digest must be the one this row pre-registers; a mismatch VOIDS that run. **P0 is the CONTROL, not the baseline.** t12 established that an operator overlay REPLACES the built-in writer `prompt_fragment` (`colleague/roles.py` `_resolve_role_prompt` — the file prompt wins), so a prose arm's prompt is NOT 'the default prompt plus prose'. A1/A2/A3 all lose the built-in fragment identically — a constant ACROSS the three prose arms, never a between-arm confound — but it means **the prose lever is measured A2-vs-A1 and A3-vs-A1, never A2-vs-A0**. A0 is the true default and is the reference only for the surface lever (A4) and for absolute task success. **Task success sits BESIDE the delegation rate (c46).** The only outcome evidence so far says the DELEGATING run failed (row 50: budget consumed, step-stall, no module changed) and the NON-delegating ones succeeded (rows 49 and 51: 3/3 `ok`, correct module, correct duplicate identified), and row 51 found cortex already holds a cheaper form of concurrency — the parallel read-only tool batch (`batches_run` 2, `calls_parallelised` 7 on every run). So **"cortex was right not to delegate" is an admissible verdict of this row** and is written as a finding, not as a failure of the arc. **Verdict discipline.** The verdict line written after the run MUST name which clause decided it — the digest clause (arm identity), the markup clause (#360 dropped calls), the delegation clause (≥1 on ≥2 of 3), the task-success clause (c46), or the ratio clause (`--bar-wall 1.2` / `--bar-turns 1.0`) — never a bare PASS/MISS, and a miss is written as a miss. **Containment (s26).** The arm runs in a throwaway repo with an `.eidetic` store (so the distill seat can fire); nothing in a run's output announces an active role overlay, so `<repo>/.colleague/agents/writer.md` is staged for the arm and deleted after it. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Lever: PROSE — the P0 overlay**, staged to `<repo>/.colleague/agents/writer.md` from `docs/live-testing/overlays/P0/writer.md` (t12): `effort: medium` frontmatter (consumed and validated by `colleague/roles.py` `_split_effort_frontmatter`, so the #417/#421 effort confound is pinned identical across A1/A2/A3) followed by the built-in writer sentence's content and nothing more. **Instrument cited: the overlay DIGEST** — `TaskResult.prompt_digest` read off each artifact must equal the P0 digest pre-recorded for this arm; the overlay file's own sha256 is recorded beside it as provenance only, never as the arm's evidence. The surface is held constant with A0: the same drop-knob value `COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents`. **This arm exists BECAUSE P0 is the control and not the baseline** — A1's prompt has already lost the built-in `prompt_fragment` that A0 keeps, so A1 is the only valid reference for A2 and A3. Reporting a prose effect as A2-vs-A0 or A3-vs-A0 would attribute the fragment REPLACEMENT to the added paragraph, and any row that does so is wrong. A1-vs-A0 is reported too, and is labelled for what it is: the cost of the replacement itself, not a prose effect. Brief: `docs/live-testing/briefs/arm-decomposable-neutral.md`, pasted verbatim (tool-free by design — the same brief runs across arms whose surfaces differ, so no tool name may steer it). Fixture: the rebuilt `alpha`/`beta`/`gamma` repo of row 51 (duplicated normalisation across alpha/beta; call graph gamma→beta→alpha), identical on every decomposable arm. **RESULT (2026-08-30, n=3).** Matrix tip `3b59d24` — the t14 pre-registration commit itself, i.e. later than `95c921b`, so deviation d1's post-t9 requirement is satisfied and no run is voided on the tip pin. Ordering is clean: the rows were committed 01:31:56 and the matrix started 01:33:36, so every cell below was pre-committed before its run. `scripts/compare_arms.py` was NOT modified by this arc — its `git diff` is empty, so the matrix is not voided on the comparator clause. Across all 21 runs of the matrix every run's `prompt_digest` matched the arm this row pre-registers for it: **zero voided runs**, and `stats.counts.markup_tool_calls` = 0 on all 21, so no run is INCONCLUSIVE under the markup clause. Artifacts `e24f59c3ea93`, `665637d35b14`, `3bf144d47184`. **Digest clause:** all three runs carry the pre-registered P0 digest `7ad1f9fe8e898cf4`, distinct from A0's `b7491476a61238a4` — one digest across the arm, none voided. **(1) Delegation:** 0/3 runs, calls per run `[0,0,0]`. **(2) Markup:** 0 on all three runs. **(3) Task success:** 3/3 `ok`, exactly one module changed per run. **(4) Turns ratio 0.826** and **(5) wall ratio 0.560** against the A0 family baseline (`scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0`, verdict `pass`); mean turns 6.33, mean wall 144.70 s. **(6) Reasoning chars:** mean 3539. `stats.counts`: `batches_run` `[2,2,2]`, `calls_parallelised` `[7,5,7]`. Recorded as a GAP rather than estimated: `stream_guard_trips`, stalls-cut / stalls-escaped per run, and the memory distill counters (attempts/validated/detached) are not present in the t16 results extract, so they are reported as not captured, never inferred. **VERDICT: MISS — decided by the delegation clause** (≥ 1 delegation call on ≥ 2 of 3 runs; observed 0/3). The ratio clause PASSES (0.560 wall / 0.826 turns, both inside the pre-committed bars) but cannot rescue the row: this arc's bar is delegation first, and the row pre-committed that a miss is written as a miss. **A1-vs-A0 is labelled for what it is** — the cost of the built-in writer fragment being REPLACED by an overlay, not a prose effect: the replacement made the run cheaper (wall 0.560×, turns 0.826×, mean reasoning chars 3539 against A0's 7574) and left delegation exactly where A0 had it, at zero. A1 is therefore a valid control for A2 and A3, and the small brief is confirmed to sit at the delegation FLOOR on the default and control prompts alike. | #443 #360 |
| 54 | purpose-tools-get-chosen (spec 2026-08-29, plan t14): **arm A2 — prose LEVER (P1 overlay)**, imperative delegate-the-survey paragraph, measured A2-vs-A1 | `docs/live-testing/overlays/P1/writer.md`, `colleague/roles.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-30, BEFORE any arm run — **result: RECORDED 2026-08-30 — the six cells and the verdict are at the END of this row.** Arc: `purpose-tools-get-chosen` (spec `docs/specs/2026-08-29-purpose-tools-get-chosen.md`, plan t14). **Tip pin (deviation d1).** Every run of this arm executes on the POST-t9 tip — `95c921b` (*fix(t9): the default prompt names the six purpose tools, not subagent/subagents*) or later on `spec/purpose-tools-get-chosen-w2`; d1 (`devague deviate --list`) records the operator ruling that t9 regenerated `tests/snapshots/prompttext_v1.txt`, so any run from before `95c921b` is NOT comparable and is voided rather than averaged in. The exact tip SHA of each run is recorded beside its id. **Pass bar (committed before the run).** Delegation: ≥ 1 delegation call on ≥ 2 of 3 runs, read off the artifact steps, never from prose. Ratios: `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` — the two flags are written out because the script's DEFAULTS are 0.7/0.8 and this arc deliberately overrides them; the numbers come from `stats.duration_seconds` / `stats.model_turns` on the artifacts, never from prose. n=3 per arm. `scripts/compare_arms.py` is NOT modified by this arc (its `git diff` must stay empty; a modified comparator voids the whole matrix). **Cells to fill after the run (six, in this order, never before):** (1) delegation rate n/3 and which tool was called; (2) markup count per run (`stats.counts.markup_tool_calls`, the #360 counter added by t6 — a zero-delegation run with markup > 0 is INCONCLUSIVE, not a refusal to delegate); (3) task success (status, whether exactly one module changed, whether its public interface stayed stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`). Recorded beside them: `stats.counts` in full (notably `batches_run` / `calls_parallelised` — row 51's unplanned finding — and `stream_guard_trips`), stalls-cut / stalls-escaped per run (q4: a `step-stall` run is RE-RUN, never averaged in), the child's served model where a child ran, and the memory distill counters (attempts/validated/detached). **Arm identity is the digest, not the operator's belief.** Each run's arm is established by `TaskResult.prompt_digest` read off its artifact (t7, `colleague/contract.py` `prompt_digest_for`, sha256 of the composed system prompt) — never by the overlay file the operator believes was staged. All three runs of an arm must carry ONE digest, and that digest must be the one this row pre-registers; a mismatch VOIDS that run. **P0 is the CONTROL, not the baseline.** t12 established that an operator overlay REPLACES the built-in writer `prompt_fragment` (`colleague/roles.py` `_resolve_role_prompt` — the file prompt wins), so a prose arm's prompt is NOT 'the default prompt plus prose'. A1/A2/A3 all lose the built-in fragment identically — a constant ACROSS the three prose arms, never a between-arm confound — but it means **the prose lever is measured A2-vs-A1 and A3-vs-A1, never A2-vs-A0**. A0 is the true default and is the reference only for the surface lever (A4) and for absolute task success. **Task success sits BESIDE the delegation rate (c46).** The only outcome evidence so far says the DELEGATING run failed (row 50: budget consumed, step-stall, no module changed) and the NON-delegating ones succeeded (rows 49 and 51: 3/3 `ok`, correct module, correct duplicate identified), and row 51 found cortex already holds a cheaper form of concurrency — the parallel read-only tool batch (`batches_run` 2, `calls_parallelised` 7 on every run). So **"cortex was right not to delegate" is an admissible verdict of this row** and is written as a finding, not as a failure of the arc. **Verdict discipline.** The verdict line written after the run MUST name which clause decided it — the digest clause (arm identity), the markup clause (#360 dropped calls), the delegation clause (≥1 on ≥2 of 3), the task-success clause (c46), or the ratio clause (`--bar-wall 1.2` / `--bar-turns 1.0`) — never a bare PASS/MISS, and a miss is written as a miss. **Containment (s26).** The arm runs in a throwaway repo with an `.eidetic` store (so the distill seat can fire); nothing in a run's output announces an active role overlay, so `<repo>/.colleague/agents/writer.md` is staged for the arm and deleted after it. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Lever: PROSE — the P1 overlay** (`docs/live-testing/overlays/P1/writer.md`, staged to `<repo>/.colleague/agents/writer.md`): the P0 body PLUS one imperative paragraph naming surveying and searching as work to hand to a scout child, one child per independent question, digests judged in seat, deciding and writing kept in seat. Same `effort: medium` rung as P0/P2. This is ENCOURAGE, not FORCE (c-frame line 106): the model may ignore it, and the runtime still chooses nothing. **Instrument cited: the overlay DIGEST** — the artifact `prompt_digest` for all three runs must equal this arm's pre-recorded P1 digest and must DIFFER from A1's; a run carrying A1's digest is voided, not relabelled. Surface held constant with A0/A1 (`COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents`). **Measured A2-vs-A1, never A2-vs-A0** (P0 is the control, not the baseline — see above). **Promotion rule, pre-committed here per q3:** the prose promotes to default-on (into `BUILTIN_ROLES['writer'].prompt_fragment`, NOT into the v1 global literal, and the v1 snapshot is not regenerated) only if, against A1, the delegation rate is UP **and** turns and reasoning chars are NOT up (#437 guidance 2). Delegation up bought with more turns or more reasoning is a MISS on the ratio clause and does not promote. Brief: `docs/live-testing/briefs/arm-decomposable-neutral.md`, pasted verbatim (tool-free by design — the same brief runs across arms whose surfaces differ, so no tool name may steer it). Fixture: the rebuilt `alpha`/`beta`/`gamma` repo of row 51 (duplicated normalisation across alpha/beta; call graph gamma→beta→alpha), identical on every decomposable arm. **RESULT (2026-08-30, n=3).** Matrix tip `3b59d24` — the t14 pre-registration commit itself, i.e. later than `95c921b`, so deviation d1's post-t9 requirement is satisfied and no run is voided on the tip pin. Ordering is clean: the rows were committed 01:31:56 and the matrix started 01:33:36, so every cell below was pre-committed before its run. `scripts/compare_arms.py` was NOT modified by this arc — its `git diff` is empty, so the matrix is not voided on the comparator clause. Across all 21 runs of the matrix every run's `prompt_digest` matched the arm this row pre-registers for it: **zero voided runs**, and `stats.counts.markup_tool_calls` = 0 on all 21, so no run is INCONCLUSIVE under the markup clause. Artifacts `bc9a37cf3e8a`, `5488c17654a9`, `d21b354c2e04`. **Digest clause:** all three runs carry the pre-registered P1 digest `ff96762a9b1f931e`, distinct from A1's `7ad1f9fe8e898cf4` — one digest across the arm, none voided. **(1) Delegation:** 0/3 runs, calls per run `[0,0,0]`. **(2) Markup:** 0 on all three runs. **(3) Task success:** 3/3 `ok`, exactly one module changed per run. **(4) Turns ratio 0.913** and **(5) wall ratio 0.908** — note these are computed against the A0 family baseline, which is how the comparator was run (verdict `pass`); the prose contrast this row owns, A2-vs-A1, has no comparator ratio in the results extract and is reported in raw means instead, never as a figure derived here: mean turns 7.00 against A1's 6.33, mean wall 234.56 s against 144.70 s. **(6) Reasoning chars:** mean 6019, against A1's 3539. `stats.counts`: `batches_run` `[1,2,1]`, `calls_parallelised` `[3,7,3]`. Recorded as a GAP rather than estimated: `stream_guard_trips`, stalls-cut / stalls-escaped per run, and the memory distill counters (attempts/validated/detached) are not present in the t16 results extract, so they are reported as not captured, never inferred. **VERDICT: MISS — decided by the delegation clause** (≥ 1 call on ≥ 2 of 3 runs; observed 0/3). The ratio clause passes against A0, and does not change the verdict. **q3 promotion rule, applied as pre-committed:** against A1 the delegation rate is NOT up (0/3 vs 0/3) while turns and reasoning chars ARE up, so the P1 paragraph does NOT promote into `BUILTIN_ROLES['writer'].prompt_fragment`. **The honest reading is a FLOOR EFFECT, not a null result:** every small-brief arm in this matrix — A0, A1, A2, A3 and A4 alike — sat at exactly zero delegating runs, so the decomposable brief has no room below it to detect a prose effect at all. This row records that the P1 prose lever was NOT DETECTABLE on this brief; it must not be read, cited or summarised as 'the prose does not work'. A brief that is not already at the floor would be required to measure it. | #443 #360 |
| 55 | purpose-tools-get-chosen (spec 2026-08-29, plan t14): **arm A3 — prose LEVER (P2 overlay)**, peer-seat re-description plus the imperative paragraph, measured A3-vs-A1 | `docs/live-testing/overlays/P2/writer.md`, `colleague/roles.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-30, BEFORE any arm run — **result: RECORDED 2026-08-30 — the six cells and the verdict are at the END of this row.** Arc: `purpose-tools-get-chosen` (spec `docs/specs/2026-08-29-purpose-tools-get-chosen.md`, plan t14). **Tip pin (deviation d1).** Every run of this arm executes on the POST-t9 tip — `95c921b` (*fix(t9): the default prompt names the six purpose tools, not subagent/subagents*) or later on `spec/purpose-tools-get-chosen-w2`; d1 (`devague deviate --list`) records the operator ruling that t9 regenerated `tests/snapshots/prompttext_v1.txt`, so any run from before `95c921b` is NOT comparable and is voided rather than averaged in. The exact tip SHA of each run is recorded beside its id. **Pass bar (committed before the run).** Delegation: ≥ 1 delegation call on ≥ 2 of 3 runs, read off the artifact steps, never from prose. Ratios: `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` — the two flags are written out because the script's DEFAULTS are 0.7/0.8 and this arc deliberately overrides them; the numbers come from `stats.duration_seconds` / `stats.model_turns` on the artifacts, never from prose. n=3 per arm. `scripts/compare_arms.py` is NOT modified by this arc (its `git diff` must stay empty; a modified comparator voids the whole matrix). **Cells to fill after the run (six, in this order, never before):** (1) delegation rate n/3 and which tool was called; (2) markup count per run (`stats.counts.markup_tool_calls`, the #360 counter added by t6 — a zero-delegation run with markup > 0 is INCONCLUSIVE, not a refusal to delegate); (3) task success (status, whether exactly one module changed, whether its public interface stayed stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`). Recorded beside them: `stats.counts` in full (notably `batches_run` / `calls_parallelised` — row 51's unplanned finding — and `stream_guard_trips`), stalls-cut / stalls-escaped per run (q4: a `step-stall` run is RE-RUN, never averaged in), the child's served model where a child ran, and the memory distill counters (attempts/validated/detached). **Arm identity is the digest, not the operator's belief.** Each run's arm is established by `TaskResult.prompt_digest` read off its artifact (t7, `colleague/contract.py` `prompt_digest_for`, sha256 of the composed system prompt) — never by the overlay file the operator believes was staged. All three runs of an arm must carry ONE digest, and that digest must be the one this row pre-registers; a mismatch VOIDS that run. **P0 is the CONTROL, not the baseline.** t12 established that an operator overlay REPLACES the built-in writer `prompt_fragment` (`colleague/roles.py` `_resolve_role_prompt` — the file prompt wins), so a prose arm's prompt is NOT 'the default prompt plus prose'. A1/A2/A3 all lose the built-in fragment identically — a constant ACROSS the three prose arms, never a between-arm confound — but it means **the prose lever is measured A2-vs-A1 and A3-vs-A1, never A2-vs-A0**. A0 is the true default and is the reference only for the surface lever (A4) and for absolute task success. **Task success sits BESIDE the delegation rate (c46).** The only outcome evidence so far says the DELEGATING run failed (row 50: budget consumed, step-stall, no module changed) and the NON-delegating ones succeeded (rows 49 and 51: 3/3 `ok`, correct module, correct duplicate identified), and row 51 found cortex already holds a cheaper form of concurrency — the parallel read-only tool batch (`batches_run` 2, `calls_parallelised` 7 on every run). So **"cortex was right not to delegate" is an admissible verdict of this row** and is written as a finding, not as a failure of the arc. **Verdict discipline.** The verdict line written after the run MUST name which clause decided it — the digest clause (arm identity), the markup clause (#360 dropped calls), the delegation clause (≥1 on ≥2 of 3), the task-success clause (c46), or the ratio clause (`--bar-wall 1.2` / `--bar-turns 1.0`) — never a bare PASS/MISS, and a miss is written as a miss. **Containment (s26).** The arm runs in a throwaway repo with an `.eidetic` store (so the distill seat can fire); nothing in a run's output announces an active role overlay, so `<repo>/.colleague/agents/writer.md` is staged for the arm and deleted after it. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Lever: PROSE — the P2 overlay** (`docs/live-testing/overlays/P2/writer.md`, staged to `<repo>/.colleague/agents/writer.md`): P1's imperative paragraph plus a re-described child seat — a PEER from the same model family, read-only by design, forming its own independent view — instead of P0/P1's quicker-seat-with-reasoning-off description. This is the counter-evidence claim c52/s32 made testable: the SHIPPED armed-facts sentence accurately describes a weaker helper, which gives a careful model a reason NOT to delegate, so P2 tests whether the description (not the instruction) is what suppresses delegation. Same `effort: medium` rung. **Instrument cited: the overlay DIGEST** — all three runs' artifact `prompt_digest` must equal this arm's pre-recorded P2 digest and differ from both A1's and A2's. Surface held constant (`COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents`). **Measured A3-vs-A1, never A3-vs-A0.** A3-vs-A2 is reported as a secondary contrast (description vs instruction) and is labelled as such. The same q3 promotion rule applies verbatim: delegation rate UP against A1 **and** turns and reasoning chars NOT up. **Honesty on P2's wording:** if P2 beats P0/P1 while describing the child seat as a same-family peer, the row must check that description against what the arm actually ran — a prose rung that wins by overstating the child's seat is recorded as such and does not promote. Brief: `docs/live-testing/briefs/arm-decomposable-neutral.md`, pasted verbatim (tool-free by design — the same brief runs across arms whose surfaces differ, so no tool name may steer it). Fixture: the rebuilt `alpha`/`beta`/`gamma` repo of row 51 (duplicated normalisation across alpha/beta; call graph gamma→beta→alpha), identical on every decomposable arm. **RESULT (2026-08-30, n=3).** Matrix tip `3b59d24` — the t14 pre-registration commit itself, i.e. later than `95c921b`, so deviation d1's post-t9 requirement is satisfied and no run is voided on the tip pin. Ordering is clean: the rows were committed 01:31:56 and the matrix started 01:33:36, so every cell below was pre-committed before its run. `scripts/compare_arms.py` was NOT modified by this arc — its `git diff` is empty, so the matrix is not voided on the comparator clause. Across all 21 runs of the matrix every run's `prompt_digest` matched the arm this row pre-registers for it: **zero voided runs**, and `stats.counts.markup_tool_calls` = 0 on all 21, so no run is INCONCLUSIVE under the markup clause. Artifacts `eaf7a755a051`, `2ff4e9fa7640`, `7827604b2762`. **Digest clause:** all three runs carry the pre-registered P2 digest `3477dbc29322321b`, distinct from both A1's `7ad1f9fe8e898cf4` and A2's `ff96762a9b1f931e` — one digest across the arm, none voided. **(1) Delegation:** 0/3 runs, calls per run `[0,0,0]`. **(2) Markup:** 0 on all three runs. **(3) Task success:** 3/3 `ok`, exactly one module changed per run. **(4) Turns ratio 0.783** and **(5) wall ratio 0.866** against the A0 family baseline the comparator was run with (verdict `pass`); the A3-vs-A1 prose contrast this row owns has no comparator ratio in the extract and is reported in raw means: mean turns 6.00 against A1's 6.33, mean wall 223.59 s against 144.70 s. **(6) Reasoning chars:** mean 4611, against A1's 3539. `stats.counts`: `batches_run` `[2,2,2]`, `calls_parallelised` `[7,7,7]`. **Secondary contrast A3-vs-A2 (description vs instruction), labelled as secondary:** delegation 0/3 against 0/3, mean turns 6.00 against 7.00, mean reasoning chars 4611 against 6019 — the peer-seat re-description is cheaper than the bare imperative paragraph but moves delegation not at all. Recorded as a GAP rather than estimated: `stream_guard_trips`, stalls-cut / stalls-escaped per run, and the memory distill counters (attempts/validated/detached) are not present in the t16 results extract, so they are reported as not captured, never inferred. **VERDICT: MISS — decided by the delegation clause** (≥ 1 call on ≥ 2 of 3 runs; observed 0/3). **q3 promotion rule, applied as pre-committed:** against A1 the delegation rate is NOT up (0/3 vs 0/3), so P2 does not promote into `BUILTIN_ROLES['writer'].prompt_fragment`. **The P2-wording honesty check does not arise here:** P2 did not beat P0 or P1 on delegation, so there is no win to audit against what the arm actually ran. **A3-vs-A1 is the clean prose comparison in this matrix** — both arms are overlays, both lose the built-in writer fragment identically — and it reads 0/3 against 0/3. That result is a FLOOR, not a null: with all five small-brief arms at exactly zero delegating runs, this brief cannot detect a prose effect of any size. The isolated prose effect is therefore recorded as NOT DETECTABLE on the decomposable brief, and must not be restated as 'prose does not work'. | #443 #360 |
| 56 | purpose-tools-get-chosen (spec 2026-08-29, plan t14): **arm A4 — SURFACE lever**, the raw subagent/subagents pair restored to the acting seat, measured A4-vs-A0 | `colleague/roles.py`, `colleague/actingsurface.py`, `scripts/compare_arms.py` | ❌ | PRE-REGISTERED 2026-08-30, BEFORE any arm run — **result: RECORDED 2026-08-30 — the six cells and the verdict are at the END of this row.** Arc: `purpose-tools-get-chosen` (spec `docs/specs/2026-08-29-purpose-tools-get-chosen.md`, plan t14). **Tip pin (deviation d1).** Every run of this arm executes on the POST-t9 tip — `95c921b` (*fix(t9): the default prompt names the six purpose tools, not subagent/subagents*) or later on `spec/purpose-tools-get-chosen-w2`; d1 (`devague deviate --list`) records the operator ruling that t9 regenerated `tests/snapshots/prompttext_v1.txt`, so any run from before `95c921b` is NOT comparable and is voided rather than averaged in. The exact tip SHA of each run is recorded beside its id. **Pass bar (committed before the run).** Delegation: ≥ 1 delegation call on ≥ 2 of 3 runs, read off the artifact steps, never from prose. Ratios: `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` — the two flags are written out because the script's DEFAULTS are 0.7/0.8 and this arc deliberately overrides them; the numbers come from `stats.duration_seconds` / `stats.model_turns` on the artifacts, never from prose. n=3 per arm. `scripts/compare_arms.py` is NOT modified by this arc (its `git diff` must stay empty; a modified comparator voids the whole matrix). **Cells to fill after the run (six, in this order, never before):** (1) delegation rate n/3 and which tool was called; (2) markup count per run (`stats.counts.markup_tool_calls`, the #360 counter added by t6 — a zero-delegation run with markup > 0 is INCONCLUSIVE, not a refusal to delegate); (3) task success (status, whether exactly one module changed, whether its public interface stayed stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`). Recorded beside them: `stats.counts` in full (notably `batches_run` / `calls_parallelised` — row 51's unplanned finding — and `stream_guard_trips`), stalls-cut / stalls-escaped per run (q4: a `step-stall` run is RE-RUN, never averaged in), the child's served model where a child ran, and the memory distill counters (attempts/validated/detached). **Arm identity is the digest, not the operator's belief.** Each run's arm is established by `TaskResult.prompt_digest` read off its artifact (t7, `colleague/contract.py` `prompt_digest_for`, sha256 of the composed system prompt) — never by the overlay file the operator believes was staged. All three runs of an arm must carry ONE digest, and that digest must be the one this row pre-registers; a mismatch VOIDS that run. **P0 is the CONTROL, not the baseline.** t12 established that an operator overlay REPLACES the built-in writer `prompt_fragment` (`colleague/roles.py` `_resolve_role_prompt` — the file prompt wins), so a prose arm's prompt is NOT 'the default prompt plus prose'. A1/A2/A3 all lose the built-in fragment identically — a constant ACROSS the three prose arms, never a between-arm confound — but it means **the prose lever is measured A2-vs-A1 and A3-vs-A1, never A2-vs-A0**. A0 is the true default and is the reference only for the surface lever (A4) and for absolute task success. **Task success sits BESIDE the delegation rate (c46).** The only outcome evidence so far says the DELEGATING run failed (row 50: budget consumed, step-stall, no module changed) and the NON-delegating ones succeeded (rows 49 and 51: 3/3 `ok`, correct module, correct duplicate identified), and row 51 found cortex already holds a cheaper form of concurrency — the parallel read-only tool batch (`batches_run` 2, `calls_parallelised` 7 on every run). So **"cortex was right not to delegate" is an admissible verdict of this row** and is written as a finding, not as a failure of the arc. **Verdict discipline.** The verdict line written after the run MUST name which clause decided it — the digest clause (arm identity), the markup clause (#360 dropped calls), the delegation clause (≥1 on ≥2 of 3), the task-success clause (c46), or the ratio clause (`--bar-wall 1.2` / `--bar-turns 1.0`) — never a bare PASS/MISS, and a miss is written as a miss. **Containment (s26).** The arm runs in a throwaway repo with an `.eidetic` store (so the distill seat can fire); nothing in a run's output announces an active role overlay, so `<repo>/.colleague/agents/writer.md` is staged for the arm and deleted after it. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Lever: SURFACE — the acting-seat tool allow-list** (t11, `ab76f74`): the raw `subagent`/`subagents` pair is on the acting seat, with the prompt left untouched (post-t9 the default section already names the six purpose tools, so this arm asks whether the RAW pair is reached for when the prose does not mention it). No overlay is staged — `<repo>/.colleague/agents/writer.md` must not exist, and A4's artifact `prompt_digest` must therefore EQUAL A0's; a digest that differs from A0's means an overlay leaked in and voids the run. **Instrument cited: the ALLOW-LIST DIFF plus the drop-knob value.** The drop knob is UNSET (`COLLEAGUE_ACTING_DROP_TOOLS` absent from the environment — recorded as absent, not as empty), and the row pastes the rendered offered-tool list from `loop.curated_schemas` for BOTH arms at depth 0 and at depth 1: A4 minus A0 at depth 0 must be exactly `{subagent, subagents}`, and the two lists at depth ≥ 1 must be IDENTICAL — t11 restored the pair to the acting seat and never to children (the c42/s22 hazard), and a run where a child also holds the pair is void. **Measured A4-vs-A0** — A0 is the correct reference for the surface lever precisely because both arms carry the same, unmodified, built-in writer prompt. A delegation call here is a `subagent`/`subagents` step; `compare_arms.py` counts both those and the six purpose tools in one `delegations` column, so the row records WHICH tool each call named, not just the count. Brief: `docs/live-testing/briefs/arm-decomposable-neutral.md`, pasted verbatim (tool-free by design — the same brief runs across arms whose surfaces differ, so no tool name may steer it). Fixture: the rebuilt `alpha`/`beta`/`gamma` repo of row 51 (duplicated normalisation across alpha/beta; call graph gamma→beta→alpha), identical on every decomposable arm. **RESULT (2026-08-30, n=3).** Matrix tip `3b59d24` — the t14 pre-registration commit itself, i.e. later than `95c921b`, so deviation d1's post-t9 requirement is satisfied and no run is voided on the tip pin. Ordering is clean: the rows were committed 01:31:56 and the matrix started 01:33:36, so every cell below was pre-committed before its run. `scripts/compare_arms.py` was NOT modified by this arc — its `git diff` is empty, so the matrix is not voided on the comparator clause. Across all 21 runs of the matrix every run's `prompt_digest` matched the arm this row pre-registers for it: **zero voided runs**, and `stats.counts.markup_tool_calls` = 0 on all 21, so no run is INCONCLUSIVE under the markup clause. Artifacts `0407235d01d0`, `036a60f7cca9`, `0edde984af3d`. **Digest clause:** all three runs carry digest `b7491476a61238a4`, EQUAL to A0's as this row required — no overlay leaked in, none voided. Drop knob recorded ABSENT (`COLLEAGUE_ACTING_DROP_TOOLS` unset), so the raw `subagent`/`subagents` pair was ON the acting seat for this arm. **(1) Delegation:** 0/3 runs, calls per run `[0,0,0]` — and the tool-name cell this row demanded has nothing to name: there is no call to name. **(2) Markup:** 0 on all three runs, so this zero is not dropped markup. **(3) Task success:** 3/3 `ok`, exactly one module changed per run. **(4) Turns ratio 0.783** and **(5) wall ratio 0.522** against A0 (verdict `pass`); mean turns 6.00, mean wall 134.88 s. **(6) Reasoning chars:** mean 2736. `stats.counts`: `batches_run` `[2,2,2]`, `calls_parallelised` `[7,7,7]`. **The decisive finding of the whole matrix, stated plainly: the SURFACE lever did nothing.** Restoring the raw `subagent`/`subagents` pair to the acting seat produced 0/3 delegating runs, exactly as A0 did without it — and **no `subagent` or `subagents` call occurred ANYWHERE in the entire 21-run matrix, including this arm, the one arm where both tools were on the seat.** So #443's removal of the raw pair was NOT what suppressed delegation; the suppression predates the removal and survives its reversal. **VERDICT: MISS — decided by the delegation clause** (≥ 1 call on ≥ 2 of 3 runs; observed 0/3). The ratio clause passes (0.522 wall / 0.783 turns) and does not change the verdict. **Recorded as a GAP:** the rendered `loop.curated_schemas` offered-tool lists at depth 0 and depth 1 that this row asked to be pasted for both arms are not present in the t16 results extract; what the extract does establish is the drop knob's absence for this arm and the equality of A4's digest with A0's. Recorded as a GAP rather than estimated: `stream_guard_trips`, stalls-cut / stalls-escaped per run, and the memory distill counters (attempts/validated/detached) are not present in the t16 results extract, so they are reported as not captured, never inferred. **ADDENDUM (2026-08-30, no figure above changed): the default has since REVERTED.** On this row's own evidence — A4 0/3 delegation with the raw pair on the seat, and zero `subagent`/`subagents` calls across all 21 runs — Qodo comment `3888125915` was accepted and `roles._writer_allowlist` drops `web`/`subagent`/`subagents` again (`docs/features/purpose-tools.md` § *Arm 4*). This row records what RAN: arm A4 genuinely executed against the restored surface. The child-confinement strip (`actingsurface.CHILD_FORBIDDEN_TOOLS`) was kept. | #443 #360 |
| 57 | purpose-tools-get-chosen (spec 2026-08-29, plan t14): **arm A5 — large-surface BASELINE**, the reference every large-surface ratio is computed against | `docs/live-testing/briefs/arm-large-surface.md`, `scripts/make_large_surface_fixture.py`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any arm run — **result: RECORDED 2026-08-30 — the six cells and the verdict are at the END of this row.** Arc: `purpose-tools-get-chosen` (spec `docs/specs/2026-08-29-purpose-tools-get-chosen.md`, plan t14). **Tip pin (deviation d1).** Every run of this arm executes on the POST-t9 tip — `95c921b` (*fix(t9): the default prompt names the six purpose tools, not subagent/subagents*) or later on `spec/purpose-tools-get-chosen-w2`; d1 (`devague deviate --list`) records the operator ruling that t9 regenerated `tests/snapshots/prompttext_v1.txt`, so any run from before `95c921b` is NOT comparable and is voided rather than averaged in. The exact tip SHA of each run is recorded beside its id. **Pass bar (committed before the run).** Delegation: ≥ 1 delegation call on ≥ 2 of 3 runs, read off the artifact steps, never from prose. Ratios: `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` — the two flags are written out because the script's DEFAULTS are 0.7/0.8 and this arc deliberately overrides them; the numbers come from `stats.duration_seconds` / `stats.model_turns` on the artifacts, never from prose. n=3 per arm. `scripts/compare_arms.py` is NOT modified by this arc (its `git diff` must stay empty; a modified comparator voids the whole matrix). **Cells to fill after the run (six, in this order, never before):** (1) delegation rate n/3 and which tool was called; (2) markup count per run (`stats.counts.markup_tool_calls`, the #360 counter added by t6 — a zero-delegation run with markup > 0 is INCONCLUSIVE, not a refusal to delegate); (3) task success (status, whether exactly one module changed, whether its public interface stayed stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`). Recorded beside them: `stats.counts` in full (notably `batches_run` / `calls_parallelised` — row 51's unplanned finding — and `stream_guard_trips`), stalls-cut / stalls-escaped per run (q4: a `step-stall` run is RE-RUN, never averaged in), the child's served model where a child ran, and the memory distill counters (attempts/validated/detached). **Arm identity is the digest, not the operator's belief.** Each run's arm is established by `TaskResult.prompt_digest` read off its artifact (t7, `colleague/contract.py` `prompt_digest_for`, sha256 of the composed system prompt) — never by the overlay file the operator believes was staged. All three runs of an arm must carry ONE digest, and that digest must be the one this row pre-registers; a mismatch VOIDS that run. **P0 is the CONTROL, not the baseline.** t12 established that an operator overlay REPLACES the built-in writer `prompt_fragment` (`colleague/roles.py` `_resolve_role_prompt` — the file prompt wins), so a prose arm's prompt is NOT 'the default prompt plus prose'. A1/A2/A3 all lose the built-in fragment identically — a constant ACROSS the three prose arms, never a between-arm confound — but it means **the prose lever is measured A2-vs-A1 and A3-vs-A1, never A2-vs-A0**. A0 is the true default and is the reference only for the surface lever (A4) and for absolute task success. **Task success sits BESIDE the delegation rate (c46).** The only outcome evidence so far says the DELEGATING run failed (row 50: budget consumed, step-stall, no module changed) and the NON-delegating ones succeeded (rows 49 and 51: 3/3 `ok`, correct module, correct duplicate identified), and row 51 found cortex already holds a cheaper form of concurrency — the parallel read-only tool batch (`batches_run` 2, `calls_parallelised` 7 on every run). So **"cortex was right not to delegate" is an admissible verdict of this row** and is written as a finding, not as a failure of the arc. **Verdict discipline.** The verdict line written after the run MUST name which clause decided it — the digest clause (arm identity), the markup clause (#360 dropped calls), the delegation clause (≥1 on ≥2 of 3), the task-success clause (c46), or the ratio clause (`--bar-wall 1.2` / `--bar-turns 1.0`) — never a bare PASS/MISS, and a miss is written as a miss. **Containment (s26).** The arm runs in a throwaway repo with an `.eidetic` store (so the distill seat can fire); nothing in a run's output announces an active role overlay, so `<repo>/.colleague/agents/writer.md` is staged for the arm and deleted after it. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Lever: NONE — this is the large-surface reference arm.** **Instrument cited:** the drop-knob VALUE `COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents` (purpose-tools-only surface, identical to A0's) plus the `prompt_digest` read off each artifact, which must be the NO-overlay digest — the same digest A0's runs carry, since A0 and A5 differ only in the brief. A5 is the reference for A6 and for NOTHING else: a ratio across briefs (A5-vs-A0, A6-vs-A2) is meaningless and is not computed. Beyond the six cells, this arm records which of the three admissible limits the run hit, quoted from the artifact field that showed it — `incompletion.reason == 'budget-exhausted'` with `stats.step_count` at `max_steps`; or `capacity_decision` / `capacity_warning` / `stats.counts.results_blanked` / `stats.counts.outputs_spilled`; or `stats.web_calls` at `COLLEAGUE_WEB_MAX_CALLS` — and 'none of the three' is the EXPECTED outcome here, because the pilot already refuted the cannot-fit premise. A `step-stall` (`stats.counts.stream_guard_trips` > 0) is a rig failure, not a limit: that run is re-run. Brief: `docs/live-testing/briefs/arm-large-surface.md`, pasted verbatim (tool-free, same reason). Fixture: the deterministic 12-module `src/mod_a`…`mod_l` tree from `scripts/make_large_surface_fixture.py` (post-Qodo-fix generator: 18,362 lines / 757,130 chars, 10–11 public functions per module, both call edges present, four behaviourally distinct duplicate pairs); exact per-file line and byte counts recorded with the result. This brief is the arc's LARGER-surface arm, not a cannot-fit arm: its recorded pilot (three attempts on `1d49c54`) REFUTED the cannot-fit premise — the acting seat built a `grep -nE` symbol index in one `run_command` and did ranged `sed -n` reads, so `read_file`'s 25,000-char paging never bound and neither the 40-step nor the 131,072-token budget was approached. Per c55 the operator accepted 'small briefs only' as the reported scope rather than narrowing the seat further. **RESULT (2026-08-30, n=3).** Matrix tip `3b59d24` — the t14 pre-registration commit itself, i.e. later than `95c921b`, so deviation d1's post-t9 requirement is satisfied and no run is voided on the tip pin. Ordering is clean: the rows were committed 01:31:56 and the matrix started 01:33:36, so every cell below was pre-committed before its run. `scripts/compare_arms.py` was NOT modified by this arc — its `git diff` is empty, so the matrix is not voided on the comparator clause. Across all 21 runs of the matrix every run's `prompt_digest` matched the arm this row pre-registers for it: **zero voided runs**, and `stats.counts.markup_tool_calls` = 0 on all 21, so no run is INCONCLUSIVE under the markup clause. Artifacts `0019fd62545a`, `20254137426f`, `a439f039c39f`. **Digest clause:** all three runs carry the NO-overlay digest `b7491476a61238a4` — the same digest A0's runs carry, as this row required (A0 and A5 differ only in the brief); none voided. **(1) Delegation:** 2/3 runs, calls per run `[3,0,3]`, 6 calls in total, and every one of them named `code_survey` — never `subagent`/`subagents`. **(2) Markup:** 0 on all three runs. **(3) Task success:** 3/3 `ok`, exactly one module changed per run. **(4)/(5) Ratios: none** — A5 is the large-surface baseline and is the reference for A6 and for nothing else; no cross-brief ratio was computed. **(6) Reasoning chars:** mean 10661; mean turns 14.00; mean wall 586.49 s. `stats.counts`: `batches_run` `[0,3,2]`, `calls_parallelised` `[0,10,10]`. **Admissible-limits cell:** all three runs finished `ok`, so no run ended `budget-exhausted`; the `capacity_decision` / `capacity_warning` / `results_blanked` / `outputs_spilled` and `web_calls` fields, and `stream_guard_trips`, are not present in the t16 results extract and are recorded as NOT CAPTURED rather than inferred — the pre-registered expectation of 'none of the three' is consistent with 3/3 `ok` but is not fully evidenced here. **VERDICT: PASS — decided by the delegation clause** (≥ 1 call on ≥ 2 of 3 runs; observed 2/3 with 3 calls each on those two runs), with the task-success clause also satisfied 3/3. **Unplanned finding — cortex substitutes the parallel tool batch for delegation, and the two trade off WITHIN this one arm:** run 1 delegated 3 times with `batches_run` 0, while run 2 delegated 0 times with `batches_run` 3 and `calls_parallelised` 10. Cortex is not refusing concurrency; it holds a cheaper form of it and prefers that form until the surface is genuinely too large. This corroborates row 51 and matches A0–A4, every one of which showed `batches_run` 1–2 with `calls_parallelised` 3–7 and zero delegation. | #443 #360 |
| 58 | purpose-tools-get-chosen (spec 2026-08-29, plan t14): **arm A6 — large-surface + PROSE lever (P2 overlay)**, measured A6-vs-A5 | `docs/live-testing/overlays/P2/writer.md`, `docs/live-testing/briefs/arm-large-surface.md`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any arm run — **result: RECORDED 2026-08-30 — the six cells and the verdict are at the END of this row.** Arc: `purpose-tools-get-chosen` (spec `docs/specs/2026-08-29-purpose-tools-get-chosen.md`, plan t14). **Tip pin (deviation d1).** Every run of this arm executes on the POST-t9 tip — `95c921b` (*fix(t9): the default prompt names the six purpose tools, not subagent/subagents*) or later on `spec/purpose-tools-get-chosen-w2`; d1 (`devague deviate --list`) records the operator ruling that t9 regenerated `tests/snapshots/prompttext_v1.txt`, so any run from before `95c921b` is NOT comparable and is voided rather than averaged in. The exact tip SHA of each run is recorded beside its id. **Pass bar (committed before the run).** Delegation: ≥ 1 delegation call on ≥ 2 of 3 runs, read off the artifact steps, never from prose. Ratios: `scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0` — the two flags are written out because the script's DEFAULTS are 0.7/0.8 and this arc deliberately overrides them; the numbers come from `stats.duration_seconds` / `stats.model_turns` on the artifacts, never from prose. n=3 per arm. `scripts/compare_arms.py` is NOT modified by this arc (its `git diff` must stay empty; a modified comparator voids the whole matrix). **Cells to fill after the run (six, in this order, never before):** (1) delegation rate n/3 and which tool was called; (2) markup count per run (`stats.counts.markup_tool_calls`, the #360 counter added by t6 — a zero-delegation run with markup > 0 is INCONCLUSIVE, not a refusal to delegate); (3) task success (status, whether exactly one module changed, whether its public interface stayed stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`). Recorded beside them: `stats.counts` in full (notably `batches_run` / `calls_parallelised` — row 51's unplanned finding — and `stream_guard_trips`), stalls-cut / stalls-escaped per run (q4: a `step-stall` run is RE-RUN, never averaged in), the child's served model where a child ran, and the memory distill counters (attempts/validated/detached). **Arm identity is the digest, not the operator's belief.** Each run's arm is established by `TaskResult.prompt_digest` read off its artifact (t7, `colleague/contract.py` `prompt_digest_for`, sha256 of the composed system prompt) — never by the overlay file the operator believes was staged. All three runs of an arm must carry ONE digest, and that digest must be the one this row pre-registers; a mismatch VOIDS that run. **P0 is the CONTROL, not the baseline.** t12 established that an operator overlay REPLACES the built-in writer `prompt_fragment` (`colleague/roles.py` `_resolve_role_prompt` — the file prompt wins), so a prose arm's prompt is NOT 'the default prompt plus prose'. A1/A2/A3 all lose the built-in fragment identically — a constant ACROSS the three prose arms, never a between-arm confound — but it means **the prose lever is measured A2-vs-A1 and A3-vs-A1, never A2-vs-A0**. A0 is the true default and is the reference only for the surface lever (A4) and for absolute task success. **Task success sits BESIDE the delegation rate (c46).** The only outcome evidence so far says the DELEGATING run failed (row 50: budget consumed, step-stall, no module changed) and the NON-delegating ones succeeded (rows 49 and 51: 3/3 `ok`, correct module, correct duplicate identified), and row 51 found cortex already holds a cheaper form of concurrency — the parallel read-only tool batch (`batches_run` 2, `calls_parallelised` 7 on every run). So **"cortex was right not to delegate" is an admissible verdict of this row** and is written as a finding, not as a failure of the arc. **Verdict discipline.** The verdict line written after the run MUST name which clause decided it — the digest clause (arm identity), the markup clause (#360 dropped calls), the delegation clause (≥1 on ≥2 of 3), the task-success clause (c46), or the ratio clause (`--bar-wall 1.2` / `--bar-turns 1.0`) — never a bare PASS/MISS, and a miss is written as a miss. **Containment (s26).** The arm runs in a throwaway repo with an `.eidetic` store (so the distill seat can fire); nothing in a run's output announces an active role overlay, so `<repo>/.colleague/agents/writer.md` is staged for the arm and deleted after it. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Lever: PROSE — the P2 overlay** (`docs/live-testing/overlays/P2/writer.md` staged to `<repo>/.colleague/agents/writer.md`), carried onto the larger brief to ask whether the strongest prose rung moves delegation where the surface to survey is twelve modules rather than three. Surface held constant with A5 (`COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents`). **Instrument cited: the overlay DIGEST** — all three runs' artifact `prompt_digest` must equal the SAME P2 digest this matrix pre-registers for A3 (the composed prompt does not depend on the brief), and must differ from A5's no-overlay digest; a mismatch voids the run. **Measured A6-vs-A5 only.** **The P0-control caveat is SHARPER here, and the row must say so:** there is no P0 control on the large-surface brief (two conditions, not four), so A6-vs-A5 measures the P2 overlay AS A WHOLE — the imperative paragraph AND the replacement of the built-in writer fragment, confounded — never the added paragraph in isolation. The isolated paragraph effect is available ONLY on the decomposable brief, as A3-vs-A1. Any reading of this row as 'prose moved delegation by X' without that caveat is wrong; the honest statement is 'the P2 overlay, replacement included, moved delegation by X against the default prompt on this brief'. Per c46 the task-success cell carries extra weight here: the large-surface brief's non-delegating baseline was EXPECTED to fail its bar and did not (the pilot finished `ok` in 18 steps), so a no-delegation A6 that also succeeds is a finding about the seat's grep-index strategy, not a failure. Brief: `docs/live-testing/briefs/arm-large-surface.md`, pasted verbatim (tool-free, same reason). Fixture: the deterministic 12-module `src/mod_a`…`mod_l` tree from `scripts/make_large_surface_fixture.py` (post-Qodo-fix generator: 18,362 lines / 757,130 chars, 10–11 public functions per module, both call edges present, four behaviourally distinct duplicate pairs); exact per-file line and byte counts recorded with the result. This brief is the arc's LARGER-surface arm, not a cannot-fit arm: its recorded pilot (three attempts on `1d49c54`) REFUTED the cannot-fit premise — the acting seat built a `grep -nE` symbol index in one `run_command` and did ranged `sed -n` reads, so `read_file`'s 25,000-char paging never bound and neither the 40-step nor the 131,072-token budget was approached. Per c55 the operator accepted 'small briefs only' as the reported scope rather than narrowing the seat further. **RESULT (2026-08-30, n=3).** Matrix tip `3b59d24` — the t14 pre-registration commit itself, i.e. later than `95c921b`, so deviation d1's post-t9 requirement is satisfied and no run is voided on the tip pin. Ordering is clean: the rows were committed 01:31:56 and the matrix started 01:33:36, so every cell below was pre-committed before its run. `scripts/compare_arms.py` was NOT modified by this arc — its `git diff` is empty, so the matrix is not voided on the comparator clause. Across all 21 runs of the matrix every run's `prompt_digest` matched the arm this row pre-registers for it: **zero voided runs**, and `stats.counts.markup_tool_calls` = 0 on all 21, so no run is INCONCLUSIVE under the markup clause. Artifacts `eaf6f7c0947b`, `a866f8fac478`, `0788f4cee2bf`. **Digest clause:** all three runs carry the P2 digest `3477dbc29322321b` — the same digest A3's runs carry, as this row required, and different from A5's no-overlay `b7491476a61238a4`; none voided. **(1) Delegation:** 3/3 runs, calls per run `[4,4,4]`, 12 calls in total, and every one of them named `code_survey`. **(2) Markup:** 0 on all three runs. **(3) Task success:** 3/3 `ok`, exactly one module changed per run — so per c46 the delegating arm succeeded here just as the non-delegating baseline did. **(4) Turns ratio 0.762** and **(5) wall ratio 1.193** against A5 (`--bar-wall 1.2 --bar-turns 1.0`, verdict `pass`). Said plainly: **1.193 is only just under the pre-committed 1.2 wall bar** — the arm clears the bar by a hair, not comfortably, and a fourth run could plausibly have pushed it over. **(6) Reasoning chars:** mean 10852 against A5's 10661; mean turns 10.67 against 14.00; mean wall 699.50 s against 586.49 s. `stats.counts`: `batches_run` `[2,2,3]`, `calls_parallelised` `[11,10,10]` — unlike A5's run 1, this arm ran the tool batch AND delegated on every run. **VERDICT: PASS — decided by the delegation clause** (≥ 1 call on ≥ 2 of 3 runs; observed 3/3) **and by the ratio clause** (0.762 turns and 1.193 wall, both inside the pre-committed bars, the latter narrowly). **q3 promotion rule, applied as pre-committed:** against A5 delegation is UP (2/3 runs and 6 calls become 3/3 runs and 12 calls) while turns are DOWN (0.762×) and reasoning chars are essentially flat (10661 to 10852) — a qualified pass of the rule. **It does NOT trigger promotion, and this row says so explicitly:** the rule passes only on the CONFOUNDED comparison this row already warned about — there is no P0 control on the large-surface brief, so A6-vs-A5 measures the P2 overlay AS A WHOLE, the imperative paragraph AND the replacement of the built-in writer fragment together, and never the added paragraph in isolation. Nothing here may be promoted into `BUILTIN_ROLES['writer'].prompt_fragment`; a clean A3-vs-A1-style comparison run on a brief that is NOT sitting at the delegation floor would be required first. **The cross-matrix finding this row carries: TASK SHAPE is what moved delegation.** Zero delegating runs out of the 15 small-brief runs (A0–A4), and 5 delegating runs out of the 6 large-surface runs (A5–A6). Neither the prose lever nor the surface lever moved delegation anywhere in this matrix; the size of the surface to be surveyed did. Recorded as a GAP rather than estimated: `stream_guard_trips`, stalls-cut / stalls-escaped per run, and the memory distill counters (attempts/validated/detached) are not present in the t16 results extract, so they are reported as not captured, never inferred. | #443 #360 |
| 59 | delegation-follow-ups-a7-p3-hire (spec 2026-08-30, plan t5/t6): **arm A7 — the raw-vs-purpose FAIR FIGHT**: the large-surface brief with BOTH the raw `subagent`/`subagents` pair AND the six purpose tools on the acting seat, measured A7-vs-A5 | `docs/live-testing/briefs/arm-large-surface.md`, `colleague/actingsurface.py` (`COLLEAGUE_ACTING_ADD_TOOLS`, t1), `colleague/contract.py` (`offered_tools`, t2), `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any run. Arc: `delegation-follow-ups-a7-p3-hire` (spec `docs/specs/2026-08-30-delegation-follow-ups-a7-p3-hire.md`, plan t5 pre-registers, t6 runs). **Tip pin.** Every run executes on a tip that carries t1's add knob (merge `e936015`), t2's `offered_tools` (`c74a684`), t3's overlays (merge `83d3a3a`) and t4's knob attestation (`7f17aed`) — i.e. `83d3a3a` or later on `spec/delegation-follow-ups-a7-p3-hire`; the exact SHA of each run is recorded beside its artifact id; a run from an earlier tip is VOIDED, never averaged in. **Fixture:** the deterministic 12-module `src/mod_a`…`mod_l` tree from `scripts/make_large_surface_fixture.py`, rebuilt fresh per arm, with an `.eidetic` store as row 57 did; fixture per-file (lines/bytes): mod_a 1539/63371, mod_b 1535/63346, mod_c 1533/63202, mod_d 1538/63343, mod_e 1518/62656, mod_f 1518/62656, mod_g 1539/63361, mod_h 1518/62656, mod_i 1535/63335, mod_j 1518/62656, mod_k 1533/63232, mod_l 1538/63340 — total 18,362 lines / 757,154 bytes (row 57 quoted 757,130 CHARS; the byte count differs by the multibyte characters, same generator output). **Brief:** `docs/live-testing/briefs/arm-large-surface.md` pasted verbatim. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Rig (recorded at pre-registration, re-read at run time):** lobes armed at `http://localhost:8001`, cortex `unsloth/Qwen3.8-27B-NVFP4`, senses/muse/associate advertised but NOT consumed (a scout child runs on cortex itself), `reasoning_effort` unset (writer rung `medium`, the same rung every overlay's `effort: medium` line names — the overlays are prose-only, spec c36), `COLLEAGUE_TIMEOUT=300`, `max_steps` 40. Runs are sequential (the GPU serializes). A gateway stall / `step-stall` run is a rig failure: VOIDED and re-run (q4 precedent). **Comparator (h3):** `scripts/compare_arms.py` is NOT modified in this matrix — `git diff main -- scripts/compare_arms.py` is recorded EMPTY at every run's SHA; the ratio cells use `--bar-wall 1.2 --bar-turns 1.0` exactly as rows 52-58 did. **Arm identity is read off the artifact, never from the shell (h18):** each artifact carries `prompt_digest` (t7) AND the new `offered_tools` list (t2) — the depth-0 curated tool names in schema order; both are pasted per run. **Cells to fill after the run (in this order, never before):** (1) delegation count PER TOOL NAME per run, a histogram over `Step.tool` (raw `subagent`/`subagents` and each purpose tool separately — the whole point of row 59); (2) markup count per run (`stats.counts.markup_tool_calls`; markup > 0 with zero delegation is INCONCLUSIVE, not a refusal); (3) task success (status, exactly one module changed, public interface stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`); beside them `stats.counts` in full (`batches_run` / `calls_parallelised`), stalls per run, the child's served model where a child ran, the memory distill counters, and the artifact ids with their SHAs. **Every number comes from an artifact; a figure without an artifact id beside it is a defect in the row (h16).** **Before-state this matrix closes (h14, cited on tip `daedbc6`):** row 56 (A4 — the raw pair on the SMALL brief, 0/3, so no arm ever paired the raw pair with a delegating brief); row 58 (A6 — the large brief has no prose control, so A6-vs-A5 is confounded); `colleague/prompttext.py:131-145` (`_PURPOSE_TOOLS` gives permission and a brake but no size trigger, and never names `subagent`/`subagents`); `colleague/purpose_schemas.py` `dispatch` (every delegation is one-shot). **Audience (h12):** the operator reads these rows and takes the one promotion decision; cortex on the acting seat is OFFERED a surface or a sentence and calls or ignores it explicitly — no cell here records the runtime choosing on its behalf. **Instrument (D3, spec c3):** `COLLEAGUE_ACTING_ADD_TOOLS=subagent,subagents`, `COLLEAGUE_ACTING_DROP_TOOLS` UNSET, no overlay. Issue #456's 'leave the drop knob unset' would NOT have produced this surface: since arm 4's revert `roles._writer_allowlist` drops the raw pair unconditionally, so an ADD knob at the same depth-0 seam is the only instrument (spec s1-s3); a spawned child still has the pair stripped (`CHILD_FORBIDDEN_TOOLS`). **Validity clause (h2):** every A7 artifact's `offered_tools` must contain `subagent`, `subagents` AND all six of `web_survey`/`code_survey`/`review`/`validate`/`plan`/`handover_to_colleague` (minus `web_survey` only if webglass is absent on the rig — recorded either way); a run whose offered list lacks either half is VOIDED. **Digest clause:** the composed prompt does NOT change with the add knob, so every A7 artifact's `prompt_digest` must equal the no-overlay digest `b7491476a61238a4a5eba21f43d69484b6faa0e1c6eaf985fe8501e942b51cf6` — the SAME digest A5 carried (row 57) — which is precisely why the digest cannot identify this arm and `offered_tools` is the cell of record. **Known confound, pre-registered (spec c4):** the shipped t9 prompt names the six purpose tools and NOT the raw pair, so under A7 `subagent`/`subagents` are offered-but-undescribed in prose (schema description only); no prose overlay is added to correct this (it would confound the surface arm with the prose arms), and the row's reading is QUALIFIED accordingly (below). **The raw pair re-exposes model-chosen seat arguments (spec c35, h19):** the raw `subagent` schema carries `context_mode`/`effort`/`engine`/`model`/`profile`/`role`; the row records, per raw call, the (role, effort, engine, model) arguments the model chose — a raw call naming an engine or model is a finding in its own right — or the line 'no raw call occurred'. **Baseline:** A5 (row 57): 2/3 delegating (3 `code_survey` calls each on those two runs), mean turns 14.00, mean wall 586.49 s, mean reasoning chars 10661, `batches_run` [0,3,2], `calls_parallelised` [0,10,10]; ratios (4)/(5) are computed against it. **Pass bar (committed before the run):** the delegation clause is A5's — ≥ 1 delegation call (raw OR purpose) on ≥ 2 of 3 runs — and the cell that answers the arm's question is the per-tool split. **Verdict wording, pinned (h20):** with the raw pair undescribed in prose, 0 raw calls + N `code_survey` calls supports 'cortex chose `code_survey` while `subagent` was offered but undescribed' — NEVER a bare 'cortex prefers `code_survey`'; only a matrix where the raw pair is also DESCRIBED could support the bare form. Raw calls > 0 are reported with their argument table and their success. **Non-goal (c6):** whatever this row finds, the default allow-list does not change — the raw pair does not return to the shipped seat (row 56 addendum); a preference finding is recorded and reasoned about in `docs/features/purpose-tools.md`, never auto-promoted. n=3. **Result: RECORDED 2026-08-30 (t6).** Artifacts `e628e78742d7` (tip `9ec6760`, 08:05:56–08:16:57), `781f143cf839` (`9ec6760`, 09:04–09:10:57), `d2dc0f32cef0` (`b188cb8`, 09:25:45–09:31:29) — the tips differ only by docs/plan-state commits (`9ec6760`→`b188cb8`: rows 59-62 + `.devague` state; no code path changed; `scripts/compare_arms.py` sha256 `f7e25fdc…` identical at every tip and equal to `main`'s, `git diff main -- scripts/compare_arms.py` empty). **Validity (h2/h18): 3/3 VALID** — each artifact's `offered_tools` has 22 names including `subagent`, `subagents` AND all six purpose names; `prompt_digest` = `b7491476a61238a4…` on all three (= A5's, as pre-registered). **(1) Delegation per tool name: 0/3 runs delegating — raw `subagent` 0, `subagents` 0, every purpose tool 0, on every run.** Tool histograms: run 1 `run_command` 12 / `edit_file` 2 / `list_dir` 1 / `read_file` 1 / `finish` 1; run 2 `run_command` 8 / `read_file` 2 / `edit_file` 2 / `list_dir` 1 / `finish` 1 (13 turns); run 3 `run_command` 10 / `read_file` 3 / `edit_file` 2 / `list_dir` 1 / `finish` 1 (16 turns). **(1b) Raw-call argument table (h19): no raw call occurred** in any run. **(2) Markup:** `stats.counts` absent on all three (omit-when-empty, `contract.py:319`) = `markup_tool_calls` 0 — and `batches_run` 0: this arm used NEITHER delegation NOR the parallel batch (A5 had `batches_run` [0,3,2]). **(3) Task success: 3/3 `ok`**, exactly one module changed per run (`src/mod_i.py` ×3; numstat +1/−8, +1/−8, +1/−6), zero `def` lines changed (public interface stable); modules named explicitly in the summary 8/12, 8/12, 8/12 (the summaries use range notation for the rest). **(4)/(5) Ratios vs A5 (`compare_arms.py --bar-wall 1.2 --bar-turns 1.0`, A5 = `0019fd62545a`,`20254137426f`,`a439f039c39f` copied beside these artifacts): mean turns 14.33 vs 14.00 → turns_ratio 1.024 (MISS, bar 1.0); mean wall 421.47 s vs 586.49 s → wall_ratio 0.719 (pass).** **(6) Reasoning chars:** 62,491 / 9,765 / 14,970 (mean 29,075). Stalls: none; warnings: none; children: none; memory distill counters: not captured (no child ran, no distill record on the artifact). **GPU tenancy (recorded, not inferred):** an external colleague run from another session shared the GPU during parts of the matrix — one (`notion-agent` plan t4, seen at 08:47) overlapping row 60's run 1, and a `colleague work --continue 5ffc0595d92c` process started 09:33:16 and still running at 10:19, overlapping row 60's run 3, row 61's run 3 and row 62's run 1; wall-clock cells for those runs are contended. **Fixture hygiene note:** the runner's `git add -A` committed `src/__pycache__/*.pyc` into each fixture base commit; every work branch shows them as removed binaries — harmless to every cell, recorded because the numstat shows it. **VERDICT: MISS — decided by the delegation clause (0/3 against ≥ 2 of 3), and the fair-fight question is UNANSWERED:** no run delegated by EITHER form, so the arm cannot say whether cortex prefers `code_survey` over `subagent` when both are offered — it used neither. The qualified reading (h20) is therefore narrower still: with the raw pair offered but undescribed in prose, cortex on this brief chose to survey in-seat (grep index + ranged `run_command` reads, the row-57 mechanism) 3/3, where A5 with the identical prompt digest and a purpose-only surface delegated 2/3. That contrast is NOT attributable to the surface: row 60 (P2-0 overlay, purpose-only) also fell to 1/3 today against A6's 3/3 with the near-identical P2 overlay yesterday, so the day-to-day variance of this brief's delegation rate is at least as large as the A7-vs-A5 gap, and n=3 cannot separate the two. Non-goal (c6) holds: nothing changes on the default seat. | #456 |
| 60 | delegation-follow-ups-a7-p3-hire (spec 2026-08-30, plan t5/t6): **arm P2-0 — the large-surface prose CONTROL**, the reference row 61's prose ratio is computed against | `docs/live-testing/overlays/P2-0/writer.md`, `docs/live-testing/briefs/arm-large-surface.md`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any run. Arc: `delegation-follow-ups-a7-p3-hire` (spec `docs/specs/2026-08-30-delegation-follow-ups-a7-p3-hire.md`, plan t5 pre-registers, t6 runs). **Tip pin.** Every run executes on a tip that carries t1's add knob (merge `e936015`), t2's `offered_tools` (`c74a684`), t3's overlays (merge `83d3a3a`) and t4's knob attestation (`7f17aed`) — i.e. `83d3a3a` or later on `spec/delegation-follow-ups-a7-p3-hire`; the exact SHA of each run is recorded beside its artifact id; a run from an earlier tip is VOIDED, never averaged in. **Fixture:** the deterministic 12-module `src/mod_a`…`mod_l` tree from `scripts/make_large_surface_fixture.py`, rebuilt fresh per arm, with an `.eidetic` store as row 57 did; fixture per-file (lines/bytes): mod_a 1539/63371, mod_b 1535/63346, mod_c 1533/63202, mod_d 1538/63343, mod_e 1518/62656, mod_f 1518/62656, mod_g 1539/63361, mod_h 1518/62656, mod_i 1535/63335, mod_j 1518/62656, mod_k 1533/63232, mod_l 1538/63340 — total 18,362 lines / 757,154 bytes (row 57 quoted 757,130 CHARS; the byte count differs by the multibyte characters, same generator output). **Brief:** `docs/live-testing/briefs/arm-large-surface.md` pasted verbatim. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Rig (recorded at pre-registration, re-read at run time):** lobes armed at `http://localhost:8001`, cortex `unsloth/Qwen3.8-27B-NVFP4`, senses/muse/associate advertised but NOT consumed (a scout child runs on cortex itself), `reasoning_effort` unset (writer rung `medium`, the same rung every overlay's `effort: medium` line names — the overlays are prose-only, spec c36), `COLLEAGUE_TIMEOUT=300`, `max_steps` 40. Runs are sequential (the GPU serializes). A gateway stall / `step-stall` run is a rig failure: VOIDED and re-run (q4 precedent). **Comparator (h3):** `scripts/compare_arms.py` is NOT modified in this matrix — `git diff main -- scripts/compare_arms.py` is recorded EMPTY at every run's SHA; the ratio cells use `--bar-wall 1.2 --bar-turns 1.0` exactly as rows 52-58 did. **Arm identity is read off the artifact, never from the shell (h18):** each artifact carries `prompt_digest` (t7) AND the new `offered_tools` list (t2) — the depth-0 curated tool names in schema order; both are pasted per run. **Cells to fill after the run (in this order, never before):** (1) delegation count PER TOOL NAME per run, a histogram over `Step.tool` (raw `subagent`/`subagents` and each purpose tool separately — the whole point of row 59); (2) markup count per run (`stats.counts.markup_tool_calls`; markup > 0 with zero delegation is INCONCLUSIVE, not a refusal); (3) task success (status, exactly one module changed, public interface stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`); beside them `stats.counts` in full (`batches_run` / `calls_parallelised`), stalls per run, the child's served model where a child ran, the memory distill counters, and the artifact ids with their SHAs. **Every number comes from an artifact; a figure without an artifact id beside it is a defect in the row (h16).** **Before-state this matrix closes (h14, cited on tip `daedbc6`):** row 56 (A4 — the raw pair on the SMALL brief, 0/3, so no arm ever paired the raw pair with a delegating brief); row 58 (A6 — the large brief has no prose control, so A6-vs-A5 is confounded); `colleague/prompttext.py:131-145` (`_PURPOSE_TOOLS` gives permission and a brake but no size trigger, and never names `subagent`/`subagents`); `colleague/purpose_schemas.py` `dispatch` (every delegation is one-shot). **Audience (h12):** the operator reads these rows and takes the one promotion decision; cortex on the acting seat is OFFERED a surface or a sentence and calls or ignores it explicitly — no cell here records the runtime choosing on its behalf. **Why this control and not P0 (D2, spec c8):** A6 (row 58) ran the P2 overlay, and P2's FIRST paragraph ('a peer seat drawn from the same model family') is the TRUE description of a scout child on this rig (associate not consumed → the child runs on cortex itself), whereas P0/P1's 'runs considerably quicker, reasoning switched off' sentence is untrue here. So the control is P2-0 = P2's `effort: medium` line + its first paragraph, byte-for-byte (t3's `tests/test_overlays_p3.py` pins head-equality with P2), staged as `.colleague/agents/writer.md` in the fixture — which REPLACES the built-in writer fragment (row 53's P0 finding), identically for row 61, so the built-in-fragment loss is a constant across the pair and never a between-arm confound. This is the control row 58 said the large brief lacked. **Surface:** no knobs; on this tip the acting seat is purpose-only by default (the raw pair is off the allow-list), so `offered_tools` must contain the six purpose names and NEITHER raw name (h18). **Digest clause:** every P2-0 artifact's `prompt_digest` must equal `2155eb8007b170d4534f66e5ede34d5e1340c8352ce0809a0ba28bb0c8ff668d` (composed on `83d3a3a` with the overlay staged); a mismatch VOIDS the run. **Pass bar:** none of its own beyond validity (digest + offered_tools) and task success; this row is the reference for row 61 and for nothing else (no cross-brief ratio, the row-57 rule). All six cells are recorded. n=3. **Result: RECORDED 2026-08-30 (t6).** Artifacts `8e49d9d936cd` (tip `9ec6760`, 08:16:57–08:59:24), `6d327403fd15` (`9ec6760`, 09:10:57–09:16:47), `0efe5cf792ca` (`b188cb8`, 09:31:29–09:37:19); comparator unchanged at every tip (sha256 `f7e25fdc…`). **Validity: 3/3 VALID** — `prompt_digest` = `2155eb8007b170d4…` on all three (the pre-registered P2-0 digest); `offered_tools` 20 names, all six purpose names, neither raw name. **(1) Delegation: 1/3 runs delegating** — run 1: **4 `code_survey` calls** (parent steps 2, 3, 4, 5, three modules each), four scout children all `ok`, each on `unsloth/Qwen3.8-27B-NVFP4` (cortex — the associate not consumed, as pre-registered), child `usage.total_tokens` 321,253 / 424,800 / 363,091 / 240,505; runs 2 and 3: 0 (grep index + ranged reads). Histograms: run 1 `read_file` 9 / `code_survey` 4 / `run_command` 3 / `edit_file` 2 / `grep_search` 2 / `list_dir` 1 / `check_test_integrity` 1 / `finish` 1; run 2 `run_command` 12 / `edit_file` 3 / `read_file` 2 / `grep_search` 1 / `list_dir` 1 / `finish` 1; run 3 `run_command` ~8 / `read_file` / `edit_file` / `finish` (11 turns). **(2) Markup: 0** on all three (`counts` present only on run 1: `batches_run` 1, `calls_parallelised` 8; absent = zero on runs 2-3). **(3) Task success: 3/3 `ok`**, one module per run (`mod_g`, `mod_g`, `mod_i`; numstat +2/−12, +5/−12, +4/−8), zero `def` lines changed; modules named explicitly 12/12, 8/12, 8/12. **(4)/(5):** no ratio of its own — this row is row 61's reference: mean turns **11.67** (11, 13, 11), mean wall **1071.65 s** (2536.4 contended, 338.9, 339.6). **(6) Reasoning chars:** 11,007 / 10,180 / 8,137 (mean **9,775**). Stalls: none; warnings: none. **Unplanned finding — the purpose child's step cap is NOT applied:** `efforttables.PURPOSE_STEPS['code_survey']` is 12, yet row 60 run 1's four `code_survey` children finished at their own steps 28, 26, 28 and 22 (23–29 steps each, read off the run log's child step stream; the parent artifact carries only `sub_results[].usage`), and each consumed 240k–425k total tokens. `purpose_schemas.dispatch` passes `max_steps=PURPOSE_STEPS[name]` into the spawn, so the override is lost between the spec and the child's `EngineConfig` (candidate: the per-child budget share in `colleague/subagents.py` ~1215-1227 or the mode profile refilling `max_steps`); filed with t7 as a follow-up issue, NOT fixed mid-matrix (the arms ran on this behaviour and say so). **GPU tenancy (recorded, not inferred):** an external colleague run from another session shared the GPU during parts of the matrix — one (`notion-agent` plan t4, seen at 08:47) overlapping row 60's run 1, and a `colleague work --continue 5ffc0595d92c` process started 09:33:16 and still running at 10:19, overlapping row 60's run 3, row 61's run 3 and row 62's run 1; wall-clock cells for those runs are contended. **Fixture hygiene note:** the runner's `git add -A` committed `src/__pycache__/*.pyc` into each fixture base commit; every work branch shows them as removed binaries — harmless to every cell, recorded because the numstat shows it. **Reading:** the control delegated 1/3 where A6 (P2 overlay = this text + the imperative paragraph) delegated 3/3 on 2026-08-30's earlier matrix and A5 (no overlay) 2/3 — today's runs on a free GPU finished the brief in-seat in 5–6 minutes (338 s, 340 s), which is the row-57 mechanism at full speed; the only delegating run was the one under GPU contention. This is the P0-style control the large brief lacked; it supports row 61's comparison and no promotion of its own. | #456 |
| 61 | delegation-follow-ups-a7-p3-hire (spec 2026-08-30, plan t5/t6): **arm P3 — the size-TRIGGER prose lever**, P2-0 plus one trigger sentence, measured P3-vs-P2-0 | `docs/live-testing/overlays/P3/writer.md`, `docs/live-testing/overlays/P2-0/writer.md`, `docs/live-testing/briefs/arm-large-surface.md`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any run. Arc: `delegation-follow-ups-a7-p3-hire` (spec `docs/specs/2026-08-30-delegation-follow-ups-a7-p3-hire.md`, plan t5 pre-registers, t6 runs). **Tip pin.** Every run executes on a tip that carries t1's add knob (merge `e936015`), t2's `offered_tools` (`c74a684`), t3's overlays (merge `83d3a3a`) and t4's knob attestation (`7f17aed`) — i.e. `83d3a3a` or later on `spec/delegation-follow-ups-a7-p3-hire`; the exact SHA of each run is recorded beside its artifact id; a run from an earlier tip is VOIDED, never averaged in. **Fixture:** the deterministic 12-module `src/mod_a`…`mod_l` tree from `scripts/make_large_surface_fixture.py`, rebuilt fresh per arm, with an `.eidetic` store as row 57 did; fixture per-file (lines/bytes): mod_a 1539/63371, mod_b 1535/63346, mod_c 1533/63202, mod_d 1538/63343, mod_e 1518/62656, mod_f 1518/62656, mod_g 1539/63361, mod_h 1518/62656, mod_i 1535/63335, mod_j 1518/62656, mod_k 1533/63232, mod_l 1538/63340 — total 18,362 lines / 757,154 bytes (row 57 quoted 757,130 CHARS; the byte count differs by the multibyte characters, same generator output). **Brief:** `docs/live-testing/briefs/arm-large-surface.md` pasted verbatim. **Scope:** measures small briefs only (large-surface pilot refuted the cannot-fit premise; see `arm-large-surface.md`). **Rig (recorded at pre-registration, re-read at run time):** lobes armed at `http://localhost:8001`, cortex `unsloth/Qwen3.8-27B-NVFP4`, senses/muse/associate advertised but NOT consumed (a scout child runs on cortex itself), `reasoning_effort` unset (writer rung `medium`, the same rung every overlay's `effort: medium` line names — the overlays are prose-only, spec c36), `COLLEAGUE_TIMEOUT=300`, `max_steps` 40. Runs are sequential (the GPU serializes). A gateway stall / `step-stall` run is a rig failure: VOIDED and re-run (q4 precedent). **Comparator (h3):** `scripts/compare_arms.py` is NOT modified in this matrix — `git diff main -- scripts/compare_arms.py` is recorded EMPTY at every run's SHA; the ratio cells use `--bar-wall 1.2 --bar-turns 1.0` exactly as rows 52-58 did. **Arm identity is read off the artifact, never from the shell (h18):** each artifact carries `prompt_digest` (t7) AND the new `offered_tools` list (t2) — the depth-0 curated tool names in schema order; both are pasted per run. **Cells to fill after the run (in this order, never before):** (1) delegation count PER TOOL NAME per run, a histogram over `Step.tool` (raw `subagent`/`subagents` and each purpose tool separately — the whole point of row 59); (2) markup count per run (`stats.counts.markup_tool_calls`; markup > 0 with zero delegation is INCONCLUSIVE, not a refusal); (3) task success (status, exactly one module changed, public interface stable); (4) turns ratio; (5) wall ratio; (6) reasoning chars (`stats.reasoning_chars`); beside them `stats.counts` in full (`batches_run` / `calls_parallelised`), stalls per run, the child's served model where a child ran, the memory distill counters, and the artifact ids with their SHAs. **Every number comes from an artifact; a figure without an artifact id beside it is a defect in the row (h16).** **Before-state this matrix closes (h14, cited on tip `daedbc6`):** row 56 (A4 — the raw pair on the SMALL brief, 0/3, so no arm ever paired the raw pair with a delegating brief); row 58 (A6 — the large brief has no prose control, so A6-vs-A5 is confounded); `colleague/prompttext.py:131-145` (`_PURPOSE_TOOLS` gives permission and a brake but no size trigger, and never names `subagent`/`subagents`); `colleague/purpose_schemas.py` `dispatch` (every delegation is one-shot). **Audience (h12):** the operator reads these rows and takes the one promotion decision; cortex on the acting seat is OFFERED a surface or a sentence and calls or ignores it explicitly — no cell here records the runtime choosing on its behalf. **The single moving contrast (h4):** `diff overlays/P2-0/writer.md overlays/P3/writer.md` is exactly one added line — "When the survey does not fit in one pass, hand parts of it to code_survey and review the digests before you act." (as staged by t3, where `code_survey` is wrapped in backticks in the overlay file — quoted here as the text that ran, backticks elided for the table) — appended after P2-0's paragraph; `tests/test_overlays_p3.py` pins the one-line diff. This is the size trigger issue #456 found missing from the shipped prompt (permission + brake, no trigger). **Surface:** as row 60 (purpose-only, no knobs; `offered_tools` must hold the six purpose names and neither raw name). **Digest clause:** every P3 artifact's `prompt_digest` must equal `d2d0d201f2c9e6dcb5418e325234d772d909ba8ebd6621feecb16b29cce3b835` (composed on `83d3a3a`), and differ from row 60's; a mismatch VOIDS the run. **Promotion rule (q3, committed before the run, h5):** the trigger PROMOTES only if ALL THREE hold against row 60 — delegation rate (delegating runs, then total delegation calls) is UP, mean `stats.model_turns` is NOT above the control's, and mean `stats.reasoning_chars` is NOT above the control's; the ratio cells use `compare_arms.py --bar-wall 1.2 --bar-turns 1.0` with row 60 as the baseline argument. Any clause failing = 'does not promote', written as such; a null is written as a null (c46). **On promotion (D4, conditional):** the sentence lands in `prompttext._PURPOSE_TOOLS` ONLY together with gating that section to the top-level acting seat (it renders for every seat today, children included — the c2/h10 smell), with `tests/snapshots/prompttext_v1.txt` regenerated under a RECORDED deviation; if that gate is not taken, the target is `BUILTIN_ROLES['writer'].prompt_fragment`. **Until promotion nothing ships:** the overlay is a staged instrument (t3 pins that the v1 snapshot and the writer fragment are untouched by this arm). **Honest caveat carried from #456:** the model already delegated on this brief unaided (A5 2/3, A6 3/3) and every run succeeded either way — this arm closes an inference gap, it fixes no defect. n=3. **Result: RECORDED 2026-08-30 (t6).** Artifacts `b96adf8ad74f` (tip `9ec6760`, 08:59:24–09:06:07), `81dcf60e3e56` (`b188cb8`, 09:16:47–09:25:45), `b8f29498b526` (`8966d6e`, 09:37:20–10:12:06; `8966d6e` = the spec re-export, docs-only); comparator unchanged at every tip. **Validity: 3/3 VALID** — `prompt_digest` = `d2d0d201f2c9e6dc…` on all three (the pre-registered P3 digest, ≠ row 60's); `offered_tools` 20 names, no raw name. **(1) Delegation: 0/3** — no `code_survey` (or any delegation) call in any run despite the trigger sentence. Histograms: run 1 (9 turns) `run_command`-led; run 2 `batches_run` 3 / `calls_parallelised` 10 (the parallel batch instead of children); run 3 `batches_run` 1 / `calls_parallelised` 2. **(2) Markup: 0** on all three. **(3) Task success: 3/3 `ok`**, one module per run (`mod_i`, `mod_i`, `mod_g`; numstat +1/−6, +1/−8, +5/−15), zero `def` lines changed; modules named explicitly 8/12, 4/12, 10/12. **(4)/(5) Ratios vs row 60 (`compare_arms.py --bar-wall 1.2 --bar-turns 1.0`, P2-0 as the baseline arm): mean turns 15.00 (9, 16, 20) vs 11.67 → turns_ratio 1.286 (MISS); mean wall 998.41 s (392.0, 527.5, 2075.8 contended) vs 1071.65 s → wall_ratio 0.932 (pass).** **(6) Reasoning chars: 13,869 / 25,818 / 330,351 (mean 123,346)** — run 3 carries a `truncated-turn` warning at step 14 (`finish_reason: length`, 310,725 reasoning chars in ONE turn, the model's reasoning ran to the output limit; the run still finished `ok`), and even excluding that run the P3 mean (19,844) sits above the control's 9,775. Stalls/guard trips: none (run 3's 35-minute wall was a single long generation under GPU contention, not a stream stall). **GPU tenancy (recorded, not inferred):** an external colleague run from another session shared the GPU during parts of the matrix — one (`notion-agent` plan t4, seen at 08:47) overlapping row 60's run 1, and a `colleague work --continue 5ffc0595d92c` process started 09:33:16 and still running at 10:19, overlapping row 60's run 3, row 61's run 3 and row 62's run 1; wall-clock cells for those runs are contended. **Fixture hygiene note:** the runner's `git add -A` committed `src/__pycache__/*.pyc` into each fixture base commit; every work branch shows them as removed binaries — harmless to every cell, recorded because the numstat shows it. **q3 promotion rule, applied as pre-committed: DOES NOT PROMOTE — all three clauses fail:** delegation rate is NOT up (0/3 vs 1/3), mean turns IS up (1.286), mean reasoning chars IS up (123,346 vs 9,775; 19,844 vs 9,775 without run 3). `prompttext._PURPOSE_TOOLS` and `BUILTIN_ROLES['writer'].prompt_fragment` are untouched; the overlay stays a staged instrument. **Reading (a negative result, written as one):** on the ONE brief where delegation has ever been observed, a single explicit size-trigger sentence on top of the truthful control paragraph produced zero delegation in three runs, and cost turns and reasoning. Honest caveats: n=3; the control itself sat at 1/3 today (and 3/3 yesterday under P2), so the brief's delegation rate is volatile day to day and a small prose effect is not detectable at this n; the trigger sentence names `code_survey` with backticks (as staged); and the model's in-seat mechanism (grep index + ranged `run_command` reads) remains cheaper than four ~300k-token children, which is the rational choice the numbers keep showing (c46). | #456 |
| 62 | delegation-follow-ups-a7-p3-hire (deviations d2/d3, 2026-08-30): **arm N — the NEMOTRON scout seat**: the large-surface brief with the lobes `associate` role (`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`) serving every read-only purpose child, a SEAT comparison against row 60 | `docs/live-testing/overlays/P0/writer.md`, `docs/live-testing/briefs/arm-large-surface.md`, `colleague/config.py` (associate resolution, plan t19), `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any run, while rows 59-61 were still running. **Why this arm exists (d2):** the operator's intended topology puts the scout/`code_survey` seat on the associate role, but on 2026-08-30 the gateway advertised `associate` `ready: false` and the session did not consume it (`config show` `not_consumed: [senses, muse, associate]`), so every purpose child in rows 59-61 ran on cortex (`sub_results[].model` = `unsloth/Qwen3.8-27B-NVFP4` on each child of run `8e49d9d936cd`). Rows 59-61 are finished AS PRE-REGISTERED (they state the cortex-scout condition); this row adds the associate condition without invalidating them. **Arming (d3 / plan t19):** the associate is consumed BY DEFAULT once t19 lands (a READY advertised associate fills the read-only purpose seats; absent/not-ready = a recorded cortex fallback; `COLLEAGUE_ASSOCIATE_MODEL=off` opts out); until t19 lands the explicit equivalent `COLLEAGUE_ASSOCIATE_MODEL=lobes` is set and RECORDED as such. **Precondition, verified at pre-registration (2026-08-30 09:2x):** the associate is NOT hosted on this rig — `~/.lobes/.env` declares `ASSOCIATE_FEASIBLE=false` and proxies the role to the Jetson AGX Orin (`ASSOCIATE_PEER_ORIGIN=…orin…:8000`, `ASSOCIATE_SERVED_NAME=associate`), so the gateway's `/capabilities` reports `associate` `feasible:false, ready:false, loaded:false, hosted_by: orin` — a LOCAL bookkeeping flag for a proxied role (`colleague/lobes.py` § ready semantics: ready/loaded may diverge for proxied roles), NOT the Orin's state. The Orin's `/v1/models` listed `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, and ONE probe completion through the gateway with `model: associate` answered HTTP 200 in 0.19 s from that model. `COLLEAGUE_ASSOCIATE_MODEL=lobes uv run colleague config show --json` resolves `associate: {served_model: …Nemotron-3.5-Lightning…, wire_model: associate, addressed_as_role: true}` and drops `associate` from `not_consumed` — no refusal on the proxy flag. So the run-time precondition is: `config show` (with the sentinel, or by default after t19) shows the associate consumed with that served model, pasted per run; the advert's `ready` value is pasted beside it but does not gate the run. **Validity clause:** every child in `sub_results[]` must carry `role: scout` (or reviewer/validator/planner) and `model` = the associate's served model; a run whose children ran on cortex is VOIDED as a fallback, not averaged in — the fallback itself is recorded. **Overlay — the seat-true one:** `docs/live-testing/overlays/P0/writer.md` (`effort: medium` + 'a seat that runs considerably quicker than the one acting now, cannot write to the repository, carries its reasoning switched off') — TRUE for a Nemotron-3.5-Lightning 30B-A3B scout at rung `off`, FALSE for a cortex scout; P2-0 ('same model family') is the reverse. So this arm and row 60 differ in TWO things by construction — the seat AND the seat-describing sentence — and the row says so: it is a SEAT comparison (does a fast associate change what cortex delegates and how the run performs), never a prose comparison, and it supports no promotion decision. **Digest clause:** every artifact's `prompt_digest` must equal the P0 digest composed on tip `9ec6760` — `7ad1f9fe8e898cf4f77876053e4fb07b7d763761cd0192d9ed771a9cfe5c6690`; a mismatch VOIDS the run (if t19 changes the composed prompt — e.g. the armed-scout sentence spliced onto `code_survey` (purpose-tools d8) — the digest is re-composed on the run tip and the new value recorded beside this one BEFORE the first run). **Surface:** purpose-only (no knobs); `offered_tools` must hold the six purpose names and neither raw name. **Fixture, brief, rig, comparator, scope line, cells (1)-(6):** exactly as rows 59-61, plus per child: served model, `usage` tokens (the only per-child statistic the artifact carries — no per-child turns/wall exist; recorded as NOT AVAILABLE, never inferred) and status. **Reference:** row 60 (P2-0, cortex scouts) for descriptive ratios with `--bar-wall 1.2 --bar-turns 1.0`; A5 (row 57) for the no-overlay absolute. **Pass bar:** validity + task success recorded; the delegation clause (>= 1 call on >= 2 of 3 runs) is REPORTED, not gated — a fast seat that cortex still declines to use is a finding (c46). n=3. **The hire arm moves to row 63 (d2).** **Result: RECORDED 2026-08-30.** Artifacts `94b753bfab07` (tip `8966d6e`, 10:12:40–10:54:05), `b0dd3084a35d` (`d09299e`, 10:54:06–11:05:53), `6e37a5cff268` (`cec3309`, 11:05:53–11:19:24) — docs/plan-state tips only; comparator unchanged. **Precondition pasted:** each run's log recorded the advert `associate → nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4, ready: False` and the arming `COLLEAGUE_ASSOCIATE_MODEL=lobes`; the artifacts' `offered_tools` = the 20-name purpose-only surface, `prompt_digest` = the P0 digest `7ad1f9fe…` on all three (VALID). **Validity of the seat:** every child that RAN dialed the associate by role name and is recorded as `model: associate` (the wire alias — the served id is attested by the config block and by the gateway probe, not on `sub_results`, which is a gap the artifact should close); no child ran on cortex. **(1) Delegation: 2/3 runs delegating — but 6 of the 10 `code_survey` calls were REFUSED at spawn.** Run 1: 0 calls (in-seat, 17 turns, 22 steps, `incomplete` / `write-no-changes` — a meta-finish with no edit, 502,000 reasoning chars, `batches_run` 1 / `calls_parallelised` 8). Run 2: 3 calls — child `474e45df82da` `ok` (394k tokens, a four-module digest with public functions + line ranges), child `e3dadc234d8c` `incomplete` (340k tokens, forced synthesis), call 3 **refused**: `HTTP 404 role_infeasible: The model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 is not feasible on this machine — its backend (worker) is declared hardware-infeasible`. Run 3: 7 calls — child `d96805aea6d2` `ok` (156k tokens, 10 steps — the fast shape), child `b0c73bcde885` `incomplete` (68k tokens, budget), **5 refused** with the same 404 (calls 2, 4, 5, 6, 7). **Mechanism (issue #460):** `associate.retry_role_alias` retries any 4xx on the role-name address by SERVED id, which this gateway refuses as `role_infeasible` (the `.env` rewrite trap), so a transient rejection of `model: associate` becomes a hard failure and the original error is lost; the lane itself answers a direct probe in 0.19 s. **Nemotron quirk:** run 2's second child opened with four `read_file /repo/src/mod_*.py` errors (an assumed `/repo` mount) before recovering with `list_dir .`. **(2) Markup: 0** on all three. **(3) Task success: 2/3 `ok`** (runs 2 and 3 changed `src/mod_i.py`, one module, zero `def` lines changed); run 1 `incomplete`, no change. **(4)/(5) vs row 60 (descriptive):** mean turns 13.67 (17, 12, 12) vs 11.67 → 1.171; mean wall 1320.7 s (2465, 697, 800) vs 1071.65 → 1.232 — both above the bars, driven by run 1; the two delegating runs alone: 697 s and 800 s, i.e. 1.8–2.0× the in-seat median (392 s) and no faster than cortex-scout delegating runs. **(6) Reasoning chars:** 501,996 / 12,620 / 7,374. **Caller behaviour (the cell rows 63/64 formalise):** after the children returned, run 2 spent 18 steps and run 3 16 steps re-reading the same eight duplicate-pair modules IN FULL (`read_file` on a, g, b, i, c, k, d, l) — the re-do pattern persists unchanged on the fast seat. **Per-child stats:** only `usage.total_tokens` and status exist on the artifact (recorded above); per-child turns/wall are NOT AVAILABLE. **Reading:** the fast seat did not make delegation faster here — one child in three finished in 10 steps, the others ran to their (unapplied, #458) budget or were refused before starting (#460), and the parent re-read everything anyway. A seat comparison, as pre-registered; no promotion decision rests on it. The delegation clause is REPORTED: 2/3 with the refusal caveat. **Refs:** #458 (child cap), #460 (alias retry), #459 (digest quality/scorer), t19 (default-ON), t20 (evidence trail). | #456 |
| 63 | delegation-follow-ups-a7-p3-hire (deviation d4, 2026-08-30): **arm R-cortex — delegation EXPLICITLY REQUESTED by the brief, children on cortex** (associate unarmed) | `docs/live-testing/briefs/arm-large-surface-requested.md`, `docs/live-testing/briefs/arm-large-surface.md`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any run, queued behind row 62. Everything not stated here is as rows 59-61 (fixture, rig, comparator freeze, scope line, the six cells, the h16 artifact-id rule) and as `docs/live-testing/briefs/arm-large-surface-requested.md` (the pass bar). **Brief:** that file's brief, verbatim — item 2 REQUESTS delegation (four `code_survey` calls, one per three-module group, verify only the cited lines afterwards). **No overlay; digest clause:** every artifact's `prompt_digest` must equal the no-overlay digest `b7491476a61238a4…` (the task text is not in the system prompt; verified on `9ec6760` that neither the add knob nor the armed associate changes it). **Extra cells:** compliance (>= 4 `code_survey` before the first module-body `read_file`); child wall per call from the parent step timestamps + `sub_results[].usage` + served model; post-digest reads classified ranged-verify vs full-module-redo; wall vs the pooled in-seat median 392 s (rows 57-61, 9 non-delegating runs; delegating runs' median 707 s). **Pooled reading these rows extend (d4):** A5+A6 (2026-08-29/30 a.m.) delegated 5/6; A7+P2-0+P3 (2026-08-30) 1/9 — same brief, fixture and served model, digests as pre-registered — the rate moved across a day with no lever the matrix credits, and in 5 of the 6 delegating runs the parent re-read the four duplicate-pair modules in full after the digests. n=3. **Arming:** `COLLEAGUE_ASSOCIATE_MODEL` unset (the pre-t19 opt-in default), so every child records `model` = the cortex id; a child on any other model voids the run. **Question:** what delegation costs when it is asked for, with today's (unbounded, #458) cortex children — the control for row 64. **Result: RECORDED 2026-08-30.** Artifacts `e3b34f4bd27c` (tip `cec3309`, 11:20:15–12:15:40), `77a8f51496d3` (`2e17abe`, 13:12:01–14:02:25), `8da050ce241c` (`648c24c`, 14:02:25–15:09:35); docs/plan-state tips only; comparator unchanged (sha `f7e25fdc…` at each). **Validity: 3/3** — `prompt_digest` = the no-overlay `b7491476…`, `offered_tools` = the 20-name purpose-only surface, no raw name; every child on cortex (`sub_results[].model` = the Qwen id). **Compliance: 3/3** — four `code_survey` calls at parent step 1, first module-body `read_file` at step 5, 0 refusals. **Children (cortex, #458 unapplied cap):** run 1 `ok`/`ok`/`incomplete`/`ok` at 453k / 468k / **1,089k** / 673k total tokens; run 2 `ok`/`incomplete`×3 at 522k / 488k / 572k / 574k; run 3 `ok`/`ok`/`incomplete`/`ok` at 614k / 612k / 793k / 577k — 5 of 12 children `incomplete` (forced synthesis at their budget). Per-child wall is NOT AVAILABLE on the artifact (no per-child timestamps); the parent's four calls occupied steps 1–4 of a 10-turn run whose wall was 3,315 / 3,009 / 4,019 s, so the four children account for the large majority of each run. **Post-digest reads — FULL REDO in 3/3:** after the fourth child returned, 17 / 16 / 17 further steps with full-module `read_file` of all eight duplicate-pair modules (a, g, b, i, c, k, d, l — the edited module up to 3×) and **0 ranged reads** (no `sed -n`/`head`/`tail` range commands) — the digests were used to pick the pairs and then verified by re-reading the bodies, exactly the rows 57–62 pattern. **(2) Markup: 0.** **(3) Task success: 3/3 `ok`**, one module each (`mod_k`, `mod_a`, `mod_i`), zero `def` lines changed. **(4)/(5) vs row 60 (`compare_arms.py --bar-wall 1.2 --bar-turns 1.0`, P2-0 baseline): mean turns 10.00 vs 11.67 → 0.857 (pass); mean wall 3,447.5 s vs 1,071.65 s → 3.217 (MISS).** vs the pooled in-seat median 392 s: 8.5–10.3× slower. **(6) Reasoning chars:** 4,364 / 5,016 / 8,426 — the parent reasons LESS when it delegates (cf. row 61's 123k mean); the cost moved into the children. `counts`: `batches_run` 2/2/3, `calls_parallelised` 11/10/12. **Reading (the control for row 64):** requested delegation on today's cortex children is fully complied with and fully **slower** — 50–67 min per run against 5–7 min in-seat — because each child re-reads whole modules to its budget (#458) and the parent then re-reads the pairs in full anyway; ~2.0–2.9M child tokens per run. The 'delegation speeds up results' bar is not applicable to this condition (it is the slow-child control) and is recorded as a miss on wall. Refs: #458, #459, #460. | #456 |
| 64 | delegation-follow-ups-a7-p3-hire (deviation d4, 2026-08-30): **arm R-nemotron — delegation EXPLICITLY REQUESTED by the brief, children on the associate (Nemotron 3.5 Lightning via the Orin proxy)** | `docs/live-testing/briefs/arm-large-surface-requested.md`, `colleague/associate_config.py`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any run, queued behind row 63. Everything not stated here is as rows 59-61 (fixture, rig, comparator freeze, scope line, the six cells, the h16 artifact-id rule) and as `docs/live-testing/briefs/arm-large-surface-requested.md` (the pass bar). **Brief:** that file's brief, verbatim — item 2 REQUESTS delegation (four `code_survey` calls, one per three-module group, verify only the cited lines afterwards). **No overlay; digest clause:** every artifact's `prompt_digest` must equal the no-overlay digest `b7491476a61238a4…` (the task text is not in the system prompt; verified on `9ec6760` that neither the add knob nor the armed associate changes it). **Extra cells:** compliance (>= 4 `code_survey` before the first module-body `read_file`); child wall per call from the parent step timestamps + `sub_results[].usage` + served model; post-digest reads classified ranged-verify vs full-module-redo; wall vs the pooled in-seat median 392 s (rows 57-61, 9 non-delegating runs; delegating runs' median 707 s). **Pooled reading these rows extend (d4):** A5+A6 (2026-08-29/30 a.m.) delegated 5/6; A7+P2-0+P3 (2026-08-30) 1/9 — same brief, fixture and served model, digests as pre-registered — the rate moved across a day with no lever the matrix credits, and in 5 of the 6 delegating runs the parent re-read the four duplicate-pair modules in full after the digests. n=3. **Arming:** `COLLEAGUE_ASSOCIATE_MODEL=lobes` (row 62's precondition: the lane answers from `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`; `config show` pasted per run); every child must record that served model — a cortex child is a recorded fallback and VOIDS the run. **The question this arm can answer and no earlier arm could:** does delegation speed the result up when it happens on a fast seat — the pass bar is in the brief file (mean wall < 392 s AND ranged post-digest reads); a miss is written as a miss. **The hire arm moves to row 65 (d4).** **Result: RECORDED 2026-08-30 — ONE run; the arm is INCOMPLETE and re-runs on the t22 tip (d5).** Run 1 artifact `23680ccfc1ad` (tip `2e17abe`, 12:55:34–13:12:01, after the operator's Orin restart; an earlier attempt was VOIDED at 3 min for that restart, runner log 12:21). Runs 2 and 3 were SKIPPED on the operator's decision at 13:20 (deviation d5): every associate child died the same way until #460 was fixed. **Validity:** `prompt_digest` `b7491476…`, `offered_tools` 20 purpose-only names; `config show` with the sentinel resolved the associate (served `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, wire `associate`); the gateway probe answered from that model in 0.26 s. **Compliance: yes** — four `code_survey` calls at step 1 before any module read. **Children: 0 of 4 ran to completion — all four calls REFUSED** with `HTTP 404 role_infeasible` on the served id, each preceded in the run log by `model pin refresh (call) — associate model 'associate' (pinned via call-time-role-alias-rejected) … refreshed to 'nvidia/NVIDIA-Nemotron-…'`: the child read 13 steps of modules, crossed the Orin's SERVED window (128,000 — `/tokenize` through the alias reports it; the advert claims 1,048,576, from which colleague derived a 768,000-token child budget), got a context-length 400, and `associate.retry_role_alias` turned it into the 404 (root cause on #460; deployment side lobes-cli#234). **Parent behaviour after the refusals: 32 steps, full `read_file` of all TWELVE modules (a–l, several twice), 0 ranged reads** — it did the whole survey itself. 14 turns, 977 s, reasoning 11,660, `batches_run` 4 / `calls_parallelised` 24; task `ok`, `mod_g` edited, zero `def` lines changed; markup 0. **Verdict: cannot be measured on this tip** — no associate child produced a digest, so neither the speed bar (mean wall < 392 s) nor the ranged-read bar applies; recorded as such, not as a miss of the seat. **Re-run precondition (pre-registered now):** the tip carrying t22 (served-window clamp + alias guard) AND t23 (the operator's measured profile: temperature 0.6, top_p 0.95, `enable_thinking: true`, no `max_tokens`), `config show` pasting the profile and the served window, the Orin's serving parameters pasted beside them, n=3, and the operator's explicit go (associate testing is stopped until then). Refs: #460, lobes-cli#234, #461, plan t22/t23, `docs/features/associate-validation.md`. **RE-RUN RESULT: RECORDED 2026-08-30 — n=3 on the t22/t23 tip `d0ff8c0`, operator go at ~19:00, associate armed (`COLLEAGUE_ASSOCIATE_MODEL=lobes`), Orin restarted and retuned by the operator (Orin-side serving parameters: to be pasted by the operator; gateway-visible facts per run: root `/tokenize` `max_model_len` 128,000, `config show` resolving `associate` → `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` with profile `depth` (temperature 0.6, top_p 0.95, thinking on, `max_tokens` omitted) — both captured beside each artifact as `Rn2-<n>.config.json` / `.tokenize.json`).** Artifacts `d5c57e32a644` (19:55:05–20:19:49), `a3e4b1726bf9` (20:19:49–20:54:46), `a56de2c569e6` (20:54:46–21:22:46); comparator unchanged (sha `f7e25fdc…`). **Validity: 3/3** — `prompt_digest` `b7491476…`, `offered_tools` the 20 purpose-only names, no raw name; every child `model: associate` (14 of 14 — zero cortex fallbacks, zero refusals, zero pin-refreshes: the #460 fix holds live). **Compliance: 3/3** — four `code_survey` calls at parent steps 1–4 in one batch, first module-body read at step 5–7; run 3 issued two further `code_survey` calls (six children). **Children (Nemotron, thinking on, #458 cap still unapplied):** run 1 `ok`/`ok`/`incomplete`/`incomplete` at 513k/304k/800k/709k total tokens (2.33M); run 2 `incomplete`/`ok`/`ok`/`ok` at 846k/633k/460k/718k (2.66M); run 3 five `ok` + one `incomplete` at 435k/254k/374k/800k/84k/455k (2.40M) — 10 of 14 `ok`, the incompletes are forced syntheses at the child budget, and EVERY digest was used by the parent. **Post-digest reads — RANGED VERIFY in 3/3 (the first arm to pass this bar):** 7 / 8 / 8 `read_file` calls, ALL with a line range (15–40 lines), plus 4 / 2 / 4 `grep_search`, **0 full-module reads in any run** — the parent's own narration: *"The digests are in. Now let me verify the cited lines before editing"*. **(2) Markup: 0.** **(3) Task success: 3/3 `ok`** (`mod_i`, `mod_k`, `mod_l` edited). **(4)/(5) vs row 60 (`compare_arms.py --bar-wall 1.2 --bar-turns 1.0`, P2-0 baseline `8e49d9d936cd,6d327403fd15,0efe5cf792ca`): mean turns 11.00 vs 11.67 → 0.943 (pass); mean wall 1,742.9 s vs 1,071.65 s → 1.626 (MISS).** Per-run wall 1,474 / 2,085 / 1,669 s. vs the pre-registered speed bar (< 392 s, the in-seat median): **MISS** at 3.8–5.3×. vs row 63 (cortex children, mean 3,447.5 s): **2.0× faster** (0.506). **(6) Reasoning chars:** 5,501 / 10,307 / 10,882 (the parent reasons little; the cost is in the children: 2.3–2.7M tokens per run, about the same as row 63's 2.0–2.9M — the Orin's ~80 tok/s is where the time went). `counts`: `batches_run` 3/2/3, `calls_parallelised` 9/8/12. **Reading:** on a fast, thinking-on associate the two things row 63 could not show both happen — delegation completes without refusal and the parent TRUSTS the digests (ranged verification, no redo) — but delegation is still slower than doing the survey in-seat on this brief, and the whole gap is child over-reading (thinking-on children read to their budget; #458's unapplied 12-step cap is the lever to test next, pre-registered as the row-64b condition). The speed bar is written as a miss; the ranged-read bar as a pass. Not a cortex-`low` vs associate head-to-head: row 63's children ran at the scout rung `off`; that comparison is #459's decision rule. Refs: #458, #459, #460, #461, PR #464. | #456 |

Tracking epic: [#128](https://github.com/agentculture/colleague/issues/128).

## purpose-tools-get-chosen — arc closing record (2026-08-30, plan t15)

The arm matrix of rows **52–58** is complete: 21 runs, all on tip `3b59d24`,
all `status: ok`, every run's `prompt_digest` matching the arm its row
pre-registered (**zero voided runs**) and `stats.counts.markup_tool_calls` = 0
on all 21 (so no zero is a #360 dropped call). `scripts/compare_arms.py` was
not modified by this arc. This section only *reads* rows 49–58; it changes no
measured number in them.

**Which lever moved the delegation rate: neither declared lever did.**

| Arm | Lever | Delegation | Wall ratio | Turns ratio |
| --- | --- | --- | --- | --- |
| A0 | none (decomposable baseline) | 0/3 | — | — |
| A1 | prose control, P0 overlay | 0/3 | 0.560 | 0.826 |
| A2 | prose lever, P1 overlay | 0/3 | 0.908 | 0.913 |
| A3 | prose lever, P2 overlay | 0/3 | 0.866 | 0.783 |
| A4 | surface lever, raw `subagent`/`subagents` restored | 0/3 | 0.522 | 0.783 |
| A5 | none (large-surface baseline) | 2/3, 6 calls | — | — |
| A6 | prose lever, P2 overlay, large surface | 3/3, 12 calls | 1.193 | 0.762 |

(Ratios for A1–A4 are against the A0 family baseline, as the comparator was
run; A6's are against A5. Both prose contrasts that isolate the paragraph —
A2-vs-A1 and A3-vs-A1 — read 0/3 against 0/3.)

**The decisive negative result.** A4 restored the raw `subagent`/`subagents`
pair to the acting seat, and **no `subagent` or `subagents` call occurred
anywhere in the entire 21-run matrix, including that arm**. So #443's removal
of the raw pair was not what suppressed delegation: the suppression predates
the removal and survives its reversal. The arc's founding hypothesis is
refuted, and this is recorded as the finding it is.

**What did move it was task shape.** 0 delegating runs of the 15 small-brief
runs (A0–A4); 5 of the 6 large-surface runs (A5–A6). Every delegation in the
matrix named `code_survey` — a typed purpose tool, chosen freely by the model.

**Mechanism.** Cortex substitutes the parallel read-only tool batch for
delegation. A0–A4 each show `batches_run` 1–2 and `calls_parallelised` 3–7
with zero delegation; the trade-off is visible *within* A5, where run 1
delegated 3 times with `batches_run` 0 while run 2 delegated 0 times with
`batches_run` 3 / `calls_parallelised` 10. It is not refusing concurrency; it
holds a cheaper form of it and prefers that form until the surface is genuinely
too large. This corroborates row 51.

**Delegating vs non-delegating success — equally often.** All 21 runs finished
`ok` and each changed exactly one module: the 5 delegating runs are 5/5 `ok`,
the 16 non-delegating runs are 16/16 `ok`. Delegating runs succeeded neither
more nor less often. Read with row 50 (the one delegating run that failed its
bar — budget consumed, step-stall, no module changed) and rows 49/51 (three
non-delegating runs each, all `ok` with the correct module and the correct
duplicate identified), the supported conclusion is the one claim c46 was
written to make reportable: **cortex was right not to delegate on a brief it
can hold.**

**Two honesty limits that bound every sentence above.**

1. **A3-vs-A1 is a FLOOR, not a null.** Every small-brief arm — A0, A1, A2,
   A3, A4 — sat at exactly zero delegating runs, so the decomposable brief has
   no room below it to detect a prose effect of any size. The isolated prose
   effect is recorded as **not detectable on this brief**; it must never be
   restated as "the prose does not work".
2. **A6-vs-A5 is CONFOUNDED and does not promote.** There is no P0 control on
   the large-surface brief, so A6-vs-A5 measures the P2 overlay *as a whole* —
   the imperative paragraph AND the replacement of
   `BUILTIN_ROLES['writer'].prompt_fragment` that any operator overlay performs
   — never the added paragraph in isolation. It does meet the q3 promotion
   numbers (delegation 6 → 12 calls, turns 0.762×, reasoning 10661 → 10852),
   and it is still **not promoted**. A clean test would need a P0-control arm
   on a brief that is not already at the delegation floor, run at the same tip,
   env and fixture, so the added paragraph is the only difference — i.e. an
   A3-vs-A1-shaped comparison on the large-surface brief.

**No encouragement shipped.** After t9 the default prompt's `Purpose tools
(optional).` section *describes* the six typed tools and explicitly says
"never delegate just to delegate". The imperative encouragement tested in this
arc lives only in the P1/P2 overlays under `docs/live-testing/overlays/`, which
are staged experiment instruments an operator copies to
`<repo>/.colleague/agents/writer.md` for the duration of an arm — never a
shipped default.

**Before-state, recomputed from source on this branch (not from the spec).**

- The prompt section t9 replaced was **174 words** (`_SUBAGENTS`, 1028 chars,
  read back from `git show 95c921b^:colleague/prompttext.py`); its replacement
  `_PURPOSE_TOOLS` is **165 words** (984 chars). The string `subagent` appears
  nowhere in the new section, and each of `web_survey`, `code_survey`,
  `review`, `validate`, `plan`, `handover_to_colleague` appears in it.
- Rendered acting-seat surface (`loop.resolve_role` → `loop.curated_schemas`,
  no `COLLEAGUE_*` set): **22 offered tools** at depth 0 — the base set plus
  the six purpose tools plus the raw `subagent`/`subagents` t11 restored. With
  the arm-0 knob `COLLEAGUE_ACTING_DROP_TOOLS=subagent,subagents` it is **20**.
- Rendered depth-1 child surface: **14 offered tools** — no purpose tool and
  no raw `subagent`/`subagents`; `depth-0 minus depth-1` is exactly
  `{code_survey, handover_to_colleague, plan, review, subagent, subagents,
  validate, web_survey}`. (Earlier prose in `purpose-tools.md` quoted 21 → 23
  and "15-tool"; those are **allow-list name counts**, not rendered surfaces —
  `deepthink` is unarmed and `web` is dropped by the writer role. Corrected in
  that doc in this same commit.)

**Deviations and issues raised during this arc.** `devague deviate --list`
records **d1** (t9 regenerates `tests/snapshots/prompttext_v1.txt`; c39's
no-change guarantee narrowed to the prose arms' P0/P1/P2 overlays), **d2** (t5
lets the three-tier worker seat's composed prompt gain the writer fragment) and
**d3** (t12's overlays were authored by a Claude subagent after two colleague
dispatches produced no files). Issues filed:
[#451](https://github.com/agentculture/colleague/issues/451) (an authoring run
can stall leaving no partial, artifact or WIP commit),
[#452](https://github.com/agentculture/colleague/issues/452) (no step-budget
headroom for the finishing commit),
[#453](https://github.com/agentculture/colleague/issues/453)
(`work --continue` re-bases on HEAD, discarding the interrupted WIP branch) and
[#454](https://github.com/agentculture/colleague/issues/454)
(`COLLEAGUE_UPDATE_SNAPSHOTS=1` was a silent no-op).

**Gaps, recorded rather than estimated.** `stream_guard_trips`, stalls-cut /
stalls-escaped per run, the memory distill counters (attempts/validated/
detached) and the rendered depth-0/depth-1 tool lists row 56 asked to be pasted
are not present in the t16 results extract, and are reported as not captured.

## Feels-alive baseline measurements

The "feels-alive" plan (devague specification) aims to reduce three operational frictions observed in the current colleague v1.44.0 runtime. This section records baseline measurements of each friction, captured live against the reference rig on **2026-07-10** during workforce task t1.

### Friction A: CLAUDE.md documentation size

**What matters.** The CLAUDE.md file at the repository root serves as comprehensive guidance for Claude Code on how to work in this codebase. A large guidance file must be loaded into every agent's context, consuming tokens before the actual work begins. The feels-alive arc aims to make coherence-gated doc refresh automatic, so CLAUDE.md can grow without manual gate-keeping.

**Baseline measurement (2026-07-10, t1):**

- File size: **158,454 bytes**
- Estimated token count: **39,613 tokens** (using bytes/4 heuristic)
- Impact: Every interaction with Claude/Colleague loads this full file into context; a 40k-token preamble before any work begins

### Friction B: Absent coherence noun

**What matters.** The coherence gate exists as a pre-finish inline check in the loop, but there is no operator-facing verb to inspect or manually run coherence scoring on a file or set of files. Operators cannot measure doc coherence independently of a work item completion.

**Baseline measurement (2026-07-10, t1):**

- Attempted command: `colleague coherence`
- Result: **Unknown command** — the noun does not exist
- Exit code: **1**
- Error message:

```text
error: argument command: invalid choice: 'coherence' (choose from learn, explain, overview, doctor, whoami, quickstart, cli, backends, wheels, feedback, commands, hooks, agents, skills, roles, telemetry, lobes, organs, config, learn-from, clean, livecheck, work, drive, plan, promote, flight, talk, experiment, session, tui, mcp)
hint: check usage with --help
```

- Impact: No operator-facing introspection surface for coherence scoring; the gate is invisible except through post-run artifact records

### Friction C: Full-turn silence during live run

**What matters.** During a live work item, when the model is processing a large completion (thinking hard, synthesizing, or compacting history), there is no feedback to the operator beyond phase notices (thinking…/synthesizing…/compacting…). The longest observed gap between output lines represents the "silence window" where the operator sees no progress indicator.

**Baseline measurement (2026-07-10, t1):**

A live work item was run against the reference rig to measure output timing:

```text
Task: "Read README.md and summarize it in one sentence."
Repo: Throwaway tmp repo (/tmp/t1-baseline-repo-1783696181)
Provider: vllm-openai at http://localhost:8001/v1
Cortex model: unsloth/Qwen3.6-27B-NVFP4 (Qwen 27B)
Senses model: coolthor/gemma-4-12B-it-NVFP4A16 (Gemma 4 12B, via lobes)
Rig reachability: PASSED (provider_reachable + provider_model_available)
```

**Timing results:**

- Total wall-clock: **13.62 seconds**
- Longest silent gap: **4.43 seconds** (between consecutive "thinking…" phase notices)
- Output lines: 25 total
- Result status: **incomplete** (the run produced no commit; task was read-only + simple enough to require no tool calls)

**Observations:**

- The longest gap occurs during model processing when the only feedback is repeated phase notices at the same timestamp
- No intermediate progress indicators or partial results are streamed between phase notices
- The operator experiences 4.43s of "silence" from the model's perspective, even though phase notices say "thinking…"
- Impact: Operators cannot easily distinguish between "model is busy" and "rig is unresponsive" when gaps exceed 2–3 seconds; a live presence lane (feels-alive senses feature) would provide intermediate status from senses while cortex thinks

---

**Cross-reference.** These three baseline measurements align with the feels-alive plan's three identified frictions:

1. (A) Large CLAUDE.md → **Coherence gate problem:** docs drift from code; → **Coherence noun solution:** allow operators to score + refresh docs independently
2. (B) No coherence noun → **Coherence noun solution:** make coherence introspectable and runnable on demand
3. (C) 4.43s silent gaps → **Senses live presence solution:** senses answers and gives status while cortex drives, eliminating operator uncertainty

The plan aims to land these three solutions incrementally, measuring improvement at each step.

## Procedures

Every procedure ends by updating this file's matrix row (status + `Last
validated` SHA/date + evidence drive id) and closing the linked issue.

### 0. Drive stats field audit

**Why it matters.** `DriveStats` (`colleague/contract.py`) is always-on and
populated runtime-side in `colleague/loop.py` (the all-engines rule), so the unit
suite proves it *exists* in every artifact. What unit tests cannot prove is that
its numbers are *faithful to a real drive*: that `bytes_written` equals the bytes
actually written, that `tool_counts`/`step_count` mirror the live step trace, and
that the token `usage` is the verbatim server count. This audits the block
against ground truth from one live drive.

**Procedure.**

1. Run a live drive that exercises several stat fields (a write + a command over
   several turns) in a throwaway git repo so this repo stays clean:

   ```bash
   WORK=$(mktemp -d); git -C "$WORK" init -q
   git -C "$WORK" config user.email a@b.c; git -C "$WORK" config user.name audit
   git -C "$WORK" commit -q --allow-empty -m init
   uv run colleague drive "Create greet.py with a greet(name) function and a \
     __main__ block that prints greet('world'), then run it with python3." \
     --repo "$WORK" --engine vllm-openai --no-pr
   ```

2. Open the artifact (path is echoed as `artifact:`) and read its `stats` +
   `usage` + `steps` + `changed_files`.
3. **Verify each field against ground truth, not the summary:**
   - `bytes_written` == exact UTF-8 byte size of the written file(s) (read the
     file from the drive branch: `git -C "$WORK" show <branch>:<file> | wc -c`).
   - `tool_counts` / `step_count` == the live `steps` trace; `files_changed` ==
     `len(changed_files)`.
   - `usage` tokens are present (verbatim from the response, never estimated);
     `started_at` is valid ISO-8601 and `duration_seconds` > 0.
   - `reasoning_*` / `answer_*` are char/byte lengths (no tokenizer) — a
     tool-calling model legitimately yields `answer_*` == 0 when it emits only
     reasoning + tool calls.

**Acceptance.** Every `stats` field matches ground truth from the live drive,
with `bytes_written` exact.

**Result — 2026-06-05 (validated).** Live drive `a6c5f0c1fd13` against the
reference rig (a write + a `python3 greet.py` run + finish, 3 turns) produced a
faithful block: `bytes_written` **101 — exact** match to the committed
`greet.py`; `tool_counts` `{write_file:1, run_command:1, finish:1}` mirrored the
`steps` trace; `step_count` 3 == `len(steps)`; `files_changed` 1 ==
`len(changed_files)`; `usage` `{prompt 7105, completion 309, total 7414}`
verbatim; `started_at` valid ISO-8601, `duration_seconds` 18.35. `reasoning`
487 chars/bytes (pure-ASCII CoT) with `answer` 0/0 — the honest tool-calling
shape (all output via `tool_calls`, `message.content` empty), not a bug. Row →
✅. Stats are engine-agnostic (`mock` and `vllm-openai` fill them identically,
pinned by `tests/test_e2e_mock.py`), so this audit confirms the contract the unit
suite already guards, now against a real model.

### 1. `outsource write` reliability

**Why it matters.** `explore`/`review` are read-only and validated. `write
--apply` lands a drive branch; `write --pr` opens a PR. The drive's
commit/summary can drop or misreport edits, so the result must be verified by
diff (and lint), never trusted from the summary.

**Procedure.**

1. Pick a small, well-scoped change with a clear target file.
2. `outsource write "<task>" --apply` (live backend).
3. **Verify by diff, not by the drive summary:** `git diff main...HEAD --stat`
   and inspect — confirm the target file changed, no stray files (e.g.
   `colleague-mock.md`) appeared, **and the diff is lint-clean** (run `flake8` on
   the touched file — a whole-file rewrite can drop the EOF newline or overshoot
   the line length).
4. Re-run the affected tests; confirm green.
5. Repeat 1–4 three times on different tasks.
6. Run `outsource write "<task>" --pr` once; confirm a real PR opens against the
   correct base.

**Acceptance.** 3 consecutive `write --apply` runs verified by diff + tests; one `write --pr`
opens a correct PR; the root cause of any prior "flake" is understood.

**Result — 2026-06-04 (validated).** 3 `--apply` drives (`b885fbb` tools.py,
`5bc48e7` subagents.py, `f51427e` vllm_openai.py) + 1 `--pr` drive (`221b4ce`,
opened **PR #130** against `main`), each a real docstring micro-improvement,
diff-verified.

- **Intent reliability: 4/4.** Every drive touched the right file with the right
  change on the live vLLM engine; no stray `colleague-mock.md`. `--pr` pushed +
  opened a correct PR against `main`.
- **Edit fidelity to lint: the weak spot.** 2 of 3 `--apply` outputs were
  lint-failing before cleanup — `f51427e` dropped the trailing newline (W292),
  `b885fbb` overshot 100 cols (E501). The lint gate + verify-by-diff catch these;
  a whole-file rewrite is the failure mode. **Mitigated** by a new `write.md` rule
  ("keep edits lint-clean: max line length + one trailing newline").
- **Commit subject was boilerplate.** Every write commit/PR title came out as
  `colleague: Implement the following task in this repository:` — `write.md` led
  with the preamble and `handoff._commit_subject` takes the instruction's first
  line. **Fixed** by leading `write.md` with `$ARGUMENTS` (locked by
  `tests/test_ask_colleague_skill.py`).
- **Prior "flake" evidence was confounded, not a write bug.** The rated-1 drive
  `1bcabd9095d3` is an `outsource explore` probe, misattributed via `feedback
  record last` (the `last_drive` pointer is shared across verbs). The stray
  `colleague-mock.md` files came from explicit `--engine mock` smoke drives
  (`8b8d43bd26cf` et al.); there is **no silent mock fallback** (`resolve_engine`,
  pinned by `tests/test_config.py`). The render-order bug (#63 #3) is **already
  fixed** here (single-pass `re.sub` in `ask-colleague.sh`).
  **Fixed (#132):** read-only probes (`explore`/`review`) no longer move `last`
  (the skill's `_preserve_artifact` stopped writing the pointer), so `last`
  tracks the most recent **write**; resolving `last` echoes the id + request to
  stderr, and `colleague feedback list` / `ask-colleague feedback list` surfaces
  every drive by request + grade so a drive is recoverable without trusting
  order. Locked by `tests/test_feedback*.py` + `tests/test_ask_colleague_skill.py`.

### 2. Subagents end-to-end live

**Evidence of the gap.** Across all live drive traces the model invoked only the
base five tools; `subagent`/`subagents` were never called. Worktree isolation and
the sequential merge child are unexercised against a real model.

**Procedure.**

1. Craft a task that *invites* delegation, e.g. "make two independent edits in
   parallel: rename X in file A and add a helper in file B."
2. `COLLEAGUE_SUBAGENT_CONCURRENCY=2 colleague drive "<task>" --repo . --no-pr`.
3. Confirm in the trace/artifact: ≥1 `subagent`/`subagents` call; children ran on
   `sub/<id>` branches in throwaway worktrees; the merge child integrated them;
   `sub_results` folded into the artifact.
4. Force a merge conflict (two children edit the same lines) and confirm the merge
   child **surfaces** the conflict rather than force-merging.
5. Confirm caps: `MAX_SUBAGENT_DEPTH=2` and `MAX_SUBAGENT_FANOUT=4` hold.

**Acceptance.** A live drive shows subagent delegation, worktree create+cleanup,
conflict surfaced, caps enforced, and `sub_results` in the artifact.

**Result — 2026-06-04 (validated).** Live drive `6c27147eb917` against the
reference rig delegated via the parallel `subagents` tool with
`COLLEAGUE_SUBAGENT_CONCURRENCY=2`: two children (`9eb32e45cacd`, `6a95f13eb2e7`)
ran in isolated `sub/<id>` worktrees, a sequential merge child
(`merge-d9b20b4d3896-0`) integrated both branches cleanly, the worktrees were
torn down, and `sub_results` was folded into the artifact. Pinned by the gated
`tests/test_vllm_live_subagents.py` (`COLLEAGUE_VLLM_E2E=1`,
`COLLEAGUE_SUBAGENT_CONCURRENCY=2`).

- **Delegation needs an explicit invite.** The improved `_DEFAULT_SYSTEM`
  subagents paragraph now names the parallel `subagents` tool (it previously
  described only the singular `subagent` and called delegation "sequential", so
  the live model had no signal the batch tool existed). A task that *explicitly*
  asks to "delegate as parallel subagents" reliably fires the tool. A purely
  *implicit* two-file task (drive `65ab1129dbe0`: "Make two changes: in x.py …; in
  y.py …") still did the work itself with the base five — **no spontaneous
  delegation**. So this row is ✅ for the *capability* — the machinery (tool
  choice → parallel worktrees → merge child → `sub_results` in the artifact) runs
  end-to-end against a real model — with the honest caveat that the live model
  does not yet delegate unprompted.
- **Caps + conflict-surfacing are unit-proven, not forced live.**
  `MAX_SUBAGENT_DEPTH=2` / `MAX_SUBAGENT_FANOUT=4` are enforced structurally
  (`colleague/config.py`, checked before any child work) and pinned by
  `tests/test_subagents.py` (`test_depth_cap_refuses_before_work`) and
  `tests/test_config_subagent.py`. The no-force-merge conflict path is pinned by
  `tests/test_subagents_parallel.py::TestMerge`
  (`test_conflicting_merge_surfaces_conflict`,
  `test_conflict_removes_worktree_but_RETAINS_branch`). Deterministically inducing
  two children that edit the *same lines* with a live model is unreliable, so the
  conflict checkbox rests on the unit proof rather than a flaky live trigger; the
  live drive above exercised a *clean* merge.

### 3. Gated configs enforcement live (approvals / hooks / per-model layers)

**Evidence of the gap.** No `approvals.json` / `hooks.json` / AGENTS layers in the
repo; `doctor` reports `0 AGENTS layer(s), 0 skill(s)`; none has fired live.

**Sub-checks (tick individually).**

- **3a Approvals — `run_command`:** add `.colleague/approvals.json` denying a
  program token (e.g. `curl`); run a drive that would call it; confirm
  `_deny_by_policy` blocks it. Then approve and confirm it runs.
- **3b Approvals — hooks/commands by checksum:** approve a hook script, then edit
  it; confirm the checksum mismatch voids the approval (denied).
- **3c Hooks fire:** add `.colleague/hooks.json` with a `pre_tool` hook that
  **rewrites** and another that **denies** a tool call; confirm both take effect
  live (first-deny / rewrite-wins).
- **3d Per-model hooks overlay:** add `.colleague/<sanitized-model>/hooks.json`;
  confirm per-model-first precedence over the base entries.
- **3e Per-model AGENTS/skills:** add `AGENTS.colleague.<model>.md` and a
  `.colleague/<model>/skills/*.md`; confirm both land in the system prompt
  (`colleague agents` / `colleague skills`, and a drive reflects them).

**Acceptance.** Each sub-check observed live; all config removed afterward (this
repo ships none by default — keep it that way).

**Result — 2026-06-04 (validated).** Gated live tests
(`tests/test_vllm_live_gated_configs.py`, `COLLEAGUE_VLLM_E2E=1`) prove the
config-present gates fire in a real drive; the engine-agnostic mechanics (3b
checksum-void, 3e prompt composition) are proven deterministically
(`tests/test_gated_configs_enforcement.py`). All validation config lives in
throwaway `tmp_path` fixtures — the repo still ships none.

- **3a Approvals `run_command` — ✅ LIVE.** Drive `324819918d83`: a real
  `run_command("curl …")` was blocked by `_deny_by_policy` (Step `ok=False`,
  "on the deny list"). Drive `21dff9b0fb93`: an allowed `echo` ran (Step
  `ok=True`, `exit=0`).
- **3b Checksum-void + command-expand-refused — ✅ DETERMINISTIC**
  (engine-agnostic). An approved deny-hook fires; editing the script voids the
  approval → `HookFiring(decision="skipped")` and the tool is no longer blocked;
  a drifted command template raises `CommandError` at expand time. Pinned by
  `tests/test_gated_configs_enforcement.py`. The live model adds no signal — the
  skip is model-independent loop mechanics.
- **3c Hooks deny + rewrite — ✅ LIVE.** Drive `a30324e89aa3`: a `pre_tool` hook
  denied a real `write_file` (`HookFiring` deny + Step `ok=False`, file not
  written). Drive `23fa581fc19a`: a rewrite hook swapped the `write_file` path
  (`HookFiring` rewrite + `rewritten.txt` in `changed_files`, original gone).
- **3d Per-model hooks overlay — ✅ LIVE.** Drive `5a590ffb360f`: a deny hook
  present ONLY in `.colleague/sakamakismile-Qwen3.6-27B-Text-NVFP4-MTP/hooks.json`
  (no base `hooks.json`) fired — proving `load_hooks(repo, model=config.model)`
  loads the overlay. Precedence/isolation unit-proven by
  `tests/test_hooks_per_model.py`.
- **3e Per-model AGENTS/skills — ✅ DETERMINISTIC** (per the #123 decision;
  colleague records the composed prompt nowhere). `system_prompt_for(repo, model,
  base=_DEFAULT_SYSTEM)` — the EXACT engine path (`engine.py`, parity locked by
  `tests/test_layers_engine_parity.py`) — folds the `AGENTS.colleague.<model>.md`
  marker + skill summary into the prompt; a sibling model sees neither
  (exact-path isolation). A soft live marker drive (`f41df9a91008`) saw the model
  echo the layer's requested summary, but that is advisory only.

### 4. Loop tools live — `culture` + `devague`

**Evidence of the gap.** 0 live calls to either tool.

**Sub-checks.**

- **4a `culture`:** a task that should reach for `agtag`/`devex`; confirm the tool
  shells out with `COLLEAGUE_IDENTITY` injected and the allow-list holds (a
  non-allow-listed CLI is rejected).
- **4b `devague`:** a vague/new task; confirm the model can `new`/`capture`/
  `converge`/`status`, and that `confirm`/`reject`/`export` are structurally
  **absent** from the allow-list. Confirm `destination`/`announcement` land in the
  artifact when set.

**Acceptance.** A live drive invokes each tool; identity injection + allow-list
exclusions verified; artifact carries the destination when one is set.

**Result — 2026-06-05 (validated).** Two gated live drives
(`tests/test_vllm_live_loop_tools.py`, `COLLEAGUE_VLLM_E2E=1`) prove the model
reaches each tool and it shells out to the real operator-installed CLI. The
**root-cause fix mirrored #122**: `_DEFAULT_SYSTEM` named `devague`/`subagent` but
never `culture`, so a "Culture tools (optional)" paragraph was added (pinned by
`tests/test_destination_loop.py::test_default_system_advertises_culture_tools`).

- **4a `culture` — ✅ LIVE.** Drive `2395f7d5d9b9`: the model called
  `culture(cli='devex', args=['--version'])` and it shelled out (`exit=0`, identity
  injected, cwd at repo root). Constrained to `--version` — zero side effects;
  `agtag` cannot post without an explicit `--repo` and the tmp repo has no remote.
- **4b `devague` — ✅ LIVE.** Drive `80cb15c5f9cd`: the model called
  `devague(move='new', …)` then `devague(move='status')`, both shelling out
  (`exit=0`). `new` wrote only a self-contained `.devague/` in the tmp repo (no
  global `~/.devague`, no network). **Bonus:** the model also declared
  `destination='users-can-export-their-dashboard-as-a-pdf'` on finish, so the
  artifact carried it (announcement was `None`) — a live confirmation on top of the
  deterministic proof.
- **DETERMINISTIC (cited, not re-proven live).** The allow-lists and the
  `confirm`/`reject`/`export` exclusions are enforced by the schema `enum` **and**
  in code, so a compliant model cannot emit a forbidden `cli`/`move` — these are
  reachable only deterministically, never live: culture allow-list/identity
  (`tests/test_culture_tools.py`, `tests/test_identity.py`); devague
  allow-list/exclusions/identity (`tests/test_devague.py`,
  `tests/test_devague_tool.py`); destination+announcement-in-artifact
  (`tests/test_destination_e2e.py`). The live drives prove the *positive* path
  (model calls the tool → it shells out); the gates are deterministic by construction.

### 5. Neighbours read-only clones live

**Evidence of the gap.** No `neighbours.json`; the feature has never run.

**Procedure.** Add `.colleague/neighbours.json` with one `{name, url}`; run a drive
that reads a neighbour file; confirm a shallow clone appears under
`.colleague/neighbours/<name>/`, is gitignored, and is cleaned up on drive finish.

**Acceptance.** Clone-on-demand + cleanup observed; empty-config default still a
no-op.

**Result — 2026-06-05 (validated).** A gated live test
(`tests/test_vllm_live_neighbours.py`, `COLLEAGUE_VLLM_E2E=1`) proves this
config-present-to-fire surface works end-to-end against a real model. The
neighbour is a hermetic local git repo (file:// URL), so the only live element is
the model performing the read.

- **Clone-on-start + read — ✅ LIVE.** Drives `711505cb4c3f` and `09d31abcf160`
  (two clean runs): with one `{name, url}` in `.colleague/neighbours.json`, the
  runtime shallow-cloned the neighbour into `.colleague/neighbours/sibling/`
  *before* the loop, and the model read a sentinel file out of it
  (`read_file(.colleague/neighbours/sibling/GREETING.txt)`, Step `ok=True`, the
  result carried the sentinel). A successful read of the sentinel proves the clone
  was present and readable mid-drive.
- **Cleanup-on-finish — ✅ LIVE.** After each drive `.colleague/neighbours/` was
  gone — `cleanup()` fires on every loop exit, before the handoff (asserted in the
  test).
- **Gitignored — ✅ LIVE.** The clone root is matched by the repo's `.gitignore`
  (`git check-ignore` exits 0) and never tracked (`git ls-files` empty), so a
  neighbour cannot leak into the drive branch commit.
- **No `_DEFAULT_SYSTEM` change needed (the honest distinction from #122/#124).**
  Neighbours is not a model-chosen tool: the clone is automatic (runtime-owned,
  all-engines rule) and the model consults it via the base `read_file` tool.
  Handing it the explicit path fired the read reliably — no prompt paragraph
  required, unlike the subagents (#122) and culture/devague (#124) gaps.
- **Empty-config no-op — ✅ DETERMINISTIC (cited, not re-proven live).** A drive
  with no `neighbours.json` never creates `.colleague/neighbours/` — purely
  model-independent loop mechanics, proven by
  `tests/test_clone_lifecycle.py::TestCleanupAtFinish::test_empty_allowlist_noop`.
  The clone/refresh/cleanup mechanics, path-traversal guards, and never-execute
  confinement are unit-proven (`tests/test_neighbours.py`,
  `tests/test_clone_lifecycle.py`). All validation config lives in throwaway
  `tmp_path` fixtures — the repo still ships no `neighbours.json`.

### 6. Telemetry end-to-end live

**Evidence of the gap.** Off by default; never run against a collector.

**Procedure.** `uv sync --extra otel`, run an OTLP collector (or point at a
file/debug exporter), then drive with telemetry on:

```bash
COLLEAGUE_OTEL_ENABLED=1 \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  colleague drive "<task>" --repo . --no-pr
```

Confirm root + per-tool + handoff spans and the metrics
`colleague.generated.chars` / `colleague.bytes_written`. Re-confirm that with the
flag off there are no spans and no SDK import (strict no-op).

**Acceptance.** Spans + metrics observed when on; verified no-op when off.

**Result — 2026-06-05 (validated).** Telemetry is **engine-agnostic** (the
all-engines rule): the spans/metrics fire identically for every backend, so the
core proof drives the full production `execute_drive` path with the `[otel]` SDK
installed and an in-memory (debug) exporter — the procedure's allowed
file/debug-exporter alternative to a wire collector. A gated live drive adds the
real-model composition stamp.

- **Full span tree + metrics — ✅ (engine-agnostic, runs in CI).**
  `tests/test_telemetry_e2e.py` drives `execute_drive` (mock backend) and captures,
  in one trace: the root `colleague.drive` span, per-tool `colleague.tool.*` spans,
  and the `colleague.handoff` span — every child parented under the drive span, and
  the handoff `committed=True`. Metrics emitted: `colleague.steps`,
  `colleague.tokens`, `colleague.generated.chars`, `colleague.bytes_written`,
  `colleague.tool.calls`, `colleague.tool.latency`, `colleague.drive.duration`. A
  second test exercises a `pre_tool` deny to emit the previously-untested
  `colleague.hook.denials`. (Before this, no test went through `execute_drive`; the
  handoff span, drive.duration, and hook.denials had no coverage at all.)
- **Live composition — ✅ LIVE.** Drives `eff14af763d4` and `02c811085cb6`
  (`tests/test_vllm_live_telemetry.py`, `COLLEAGUE_VLLM_E2E=1`) against the
  reference rig emitted the same span tree (`colleague.drive`, `colleague.tool.*`,
  and `colleague.handoff`; trace `36af5dd80d0f…`) and the headline metrics with
  **real** model usage — `colleague.tokens` from the response, `generated.chars`
  from real reasoning/answer text, `bytes_written` from a real `HELLO.txt` write.
- **Strict no-op when off — ✅ DETERMINISTIC (cited, not re-proven live).** With
  telemetry off (the default) there are no spans and the OTel SDK / `_otel` is never
  imported — even when the `[otel]` extra IS installed. Locked by
  `tests/test_zero_deps.py::test_no_third_party_imports` (loading `colleague.loop`/
  `colleague.telemetry`/`colleague.cli` introduces no third-party import) and
  `tests/test_telemetry.py::test_loop_default_telemetry_is_noop`. Config resolution
  and SDK-backed emission are unit-proven by `tests/test_telemetry.py`.
- **Honest limit.** Capture is via an in-memory/debug exporter, not a wire OTLP
  collector; OTLP-over-HTTP shipping is the SDK's concern (exporter construction is
  unit-proven, `tests/test_telemetry.py`). All telemetry config lives in env/
  fixtures — the repo ships telemetry off by default and no collector config.

### 7. Context-overflow graceful degradation live

**Evidence of the gap.** Step-budget termination has been seen live (drives
`99d1a4ee9572`, `901e9d61bf31`), but the **context-overflow trim+retry** path in
`colleague/context.py` has never triggered against a real model.

**Procedure.** Set a small `COLLEAGUE_CONTEXT_BUDGET` (e.g. a few thousand tokens)
and a multi-file task; confirm history windowing drops oldest turns with a
placeholder note, and that an induced overflow triggers a harder trim + bounded
retry, preserving a readable partial result instead of hard-failing.

**Acceptance.** The trim+retry path is exercised live and a partial result is
preserved; bound on retries holds (termination).

**Result — 2026-06-05 (validated).** Two gated live drives
(`tests/test_vllm_live_context_budget.py`, `COLLEAGUE_VLLM_E2E=1`) exercise both
degradation paths against the reference rig by spying on the engine's HTTP seam
(`vllm_openai._post_json`) — observe for the proactive path, inject for the
reactive one — without leaving the production `execute_drive` path.

- **Proactive windowing — ✅ LIVE.** Drives `36b022abc7f0` / `1e530fa42dd7`: a
  small `context_budget=1000` + a 4-file *chain* task (each file names the next, so
  the model must take sequential, content-pulling turns — `run_command` can't
  shortcut it and the reads can't be batched). After two chained reads the history
  blew past the budget, so every later real chat request was windowed to
  `[system, user, <placeholder>, assistant, tool]` — the placeholder
  (`context._PLACEHOLDER_TEXT`) landed in actual model requests and the message
  count stayed pinned at 5 across four reads (`[2, 5, 5, 5, 5]`) instead of growing.
  The drive finished OK — graceful degradation, no crash.
- **Reactive trim+retry → real recovery — ✅ LIVE (induced).** Drives
  `0323db53b1dd` / `242ee473debd`: the procedure's "induced overflow" — the first
  chat call raises a real-shaped overflow (matches `is_context_overflow`), the loop
  shrinks the budget and retries, and the retry **recovers against the real model**
  (3 chat calls: 1 raised + 2 served; `write_file` then `finish`, status OK).
- **Bounded termination + non-recoverable partial — ✅ DETERMINISTIC (cited).** The
  retry cap (`_MAX_OVERFLOW_RETRIES`) and the preserved partial on a never-recovering
  overflow are engine-agnostic loop mechanics, proven by
  `tests/test_loop_degradation.py` (`test_non_recoverable_overflow_preserves_partial`,
  retry-bound) and `tests/test_e2e_degradation.py` (full vLLM-engine path, partial
  JSON to stdout). Windowing primitives + overflow-phrase detection:
  `tests/test_context_window.py`.
- **Honest limit.** A real server-side 262k overflow is not deliberately induced
  (proactive windowing trims below the budget first, so it would be unreliable and
  costly to force); the overflow is injected at the HTTP seam — exactly the
  procedure's "induced overflow" — with the *recovery* served by the real model.
  No `COLLEAGUE_CONTEXT_BUDGET` ships in the repo; the budget is set per-test.

With this row validated, every feature in the [matrix](#validation-matrix) — and
the tracking epic [#128](https://github.com/agentculture/colleague/issues/128) — is
now validated live (or live + cited-deterministic where the model adds no signal).

## Mode profiles / backpressure / rig budget (spec 2026-07-01, issues #254–#259)

- **Validated (mock + deterministic).** `tests/test_mode_e2e_validation.py` runs the
  REAL mock-engine pipeline end-to-end with zero env tuning (`--mode explore` →
  artifact carries `mode`, run completes inside the profile); the seam-level proofs
  are `tests/test_work_mode_wiring.py` (profile → resolved config, precedence),
  `tests/test_loop_backpressure_integration.py` (fake-clock latency → shrink +
  throttle + advisory), `tests/test_rig.py` (cross-process slot semantics incl. a
  live `execute_work` hold/release), and `tests/test_loop_acceptance_selfcheck.py`
  (goal block + advisory self-check).
- **VALIDATED live — `bf6cf2d` · 2026-07-02.** The rig came back with tool
  calling (the 27B serves and the `doctor --probe` tool-calling round-trip
  passes), and `COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live_mode.py`
  **PASSED** (`test_mode_explore_live`, 30s): a live `--mode explore` run
  completed inside its profile. The profile *numbers* remain conservative
  defaults pending broader live tuning (plan risk r1 — tuning, not validity).

## Dual-model deepthink escalation (spec 2026-07-01, plan task t10)

- **Validated (mock + deterministic).** The config resolution
  (`tests/test_deepthink_config.py`), the one-shot windowed/degrading
  `make_complete` seam (`tests/test_deepthink.py`), the `TaskResult.deepthink`
  block shape (`tests/test_contract_deepthink.py`), the loop tool + role
  curation (`tests/test_deepthink_tool.py`), the loop wiring + all-engines
  forwarding + acceptance-selfcheck escalation (`tests/test_loop_deepthink.py`),
  the plan-mode proposal routing (`tests/test_plan_deepthink.py`), and the
  test-integrity reviewer default (`tests/test_deepthink_reviewer_default.py`)
  all pass against the `mock` engine and fixtures: a no-deepthink-config run is
  byte-identical to today, and a dual-config run against `mock` records a
  degraded no-op (the lint fix-turn precedent) instead of failing.
- **VALIDATED live — `bf6cf2d` · 2026-07-02.** The rig now serves multiple
  models on one endpoint, so the dual pair ran as main =
  `unsloth/Qwen3.6-27B-NVFP4` (tool-calling verified) +
  deepthink = `coolthor/gemma-4-12B-it-NVFP4A16` (tools-off bare completion —
  a deepthink target needs no tool parser). `COLLEAGUE_DUAL_E2E=1
  COLLEAGUE_DEEPTHINK_MODEL=coolthor/gemma-4-12B-it-NVFP4A16 uv run pytest
  tests/test_dual_live.py` — **both tests PASSED**:
  - *deepthink tool:* the main model escalated the judgment question —
    `read_file → deepthink → finish`, `DeepthinkCall(point='tool',
    tokens=825, duration=36.4s, degraded=False)` on the artifact.
  - *acceptance self-check:* `DeepthinkCall(point='acceptance_selfcheck',
    tokens=246, duration=2.0s, degraded=False)`.
  - *degrade path (bonus, proven live):* pointing the deepthink target at the
    endpoint's stale-listed `nvidia/Qwen3-14B-NVFP4` (models-list entry whose
    completions 404 — evidence commented on
    [#66](https://github.com/agentculture/colleague/issues/66)) produced a
    clean OK run with `DeepthinkCall(degraded=True, duration=0.019s)` — the
    dual run never fails because deepthink is unreachable, exactly as spec'd.
  Two test-infra fixes were needed to make the proof runnable at all,
  recorded honestly: the autouse conftest env-scrub hid the deepthink target
  from the gate (fixed with an import-time env snapshot), and the judgment
  task needed the #122-style explicit invite (the 27B happily answers without
  escalating; the row proves the escalation *plumbing*, not spontaneity).
  Residuals: the intended role-optimal pairing (wide-window main + stronger
  reasoner deepthink) awaits serving both with tool parsers, and the
  wall-clock/quality benchmark (`scripts/bench_dual.py`) has not been run —
  the mechanism rows above are what this validates.
- **Cross-machine retarget PROVEN (partial) — 2026-07-17, two-machines-two-minds
  arc A (t3).** Deepthink retargeted to **Gemma-4-31B on thor** via the lobes
  gateway's `muse` proxy: main = `unsloth/Qwen3.6-27B-NVFP4`
  (spark), deepthink = `nvidia/Gemma-4-31B-IT-NVFP4` (thor,
  `hosted_by http://thor.tail0be7e0.ts.net:8000`, proxied at the gateway
  origin `http://localhost:8001/v1` — same endpoint string as main, so the
  same-endpoint test-integrity reviewer default arms). Config-only on
  unpatched main: `context_budget 192000` (73.2% of thor's serving-side
  verified `max_model_len=262144` — vLLM's own over-ask rejection, identical
  direct and via proxy). `COLLEAGUE_DUAL_E2E=1
  COLLEAGUE_DEEPTHINK_MODEL=nvidia/Gemma-4-31B-IT-NVFP4 uv run pytest
  tests/test_dual_live.py`:
  - *deepthink tool:* **PASSED** (first run of the day, 110.5s pair) — the
    passing assert requires ≥ 1 NON-degraded `DeepthinkCall`, so the tool-point
    escalation demonstrably reached Gemma-31B through the proxy. (The
    artifact's exact tokens/duration were lost to pytest tmp GC before they
    were copied out — recorded as a process miss, not re-fabricated.)
  - *acceptance self-check:* **NOT yet proven on this pairing.** The bare
    read-and-report task produced a zero-step stop (the 27B answered with
    literal pseudo-tool-call markup; honestly recorded as
    `incompletion.reason: no-progress-zero-steps`), so the clean finish the
    self-check keys on never happened. `_ACCEPTANCE_TASK` now carries the
    #122-style explicit `read_file`+`finish` invite (the same fix the
    judgment task already documents).
  - *cortex-side flake (independent of the retarget):* from ~40 min after the
    pass, every rerun (5/5) zero-stepped: the 27B emits a malformed
    `<tool_call>` dialect the serving-side parser cannot convert. Offline
    bisect with the loop's captured payload: the full loop shape (≈4K system
    prompt + 15 tool schemas) intermittently collapses the format at ANY
    temperature, while dropping EITHER the system prompt OR the 13 extra
    schemas parses cleanly — and the identical payload had passed earlier.
    Same family as [#66](https://github.com/agentculture/colleague/issues/66)/
    [#109](https://github.com/agentculture/colleague/issues/109) (serving-side
    tool-call reliability, likely rig-load/MTP-nondeterminism-correlated;
    three vLLM EngineCores were sharing the GB10 by then); NOT a
    deepthink/thor regression — `doctor --probe`'s minimal round-trip stays
    green and a 2-tool replay parses throughout. Later the same day the
    contrast sharpened: full-featured CLI work items against the colleague
    repo itself (layered system prompt) succeeded 2/2 with clean tool calls,
    while every bare-loop run on the minimal calc.py fixture repo stayed
    zero-step (8/8) — the collapse correlates with the minimal-context
    request shape, not with the dual config. Filed as
    [#346](https://github.com/agentculture/colleague/issues/346).
- **Zero-model-id discovery PROVEN — 2026-07-17, two-machines-two-minds
  arc B (t7).** With the rig's user-level config reduced to ONLY
  `{"lobes": "http://localhost:8001"}` (explicit deepthink section moved
  aside; no `COLLEAGUE_DEEPTHINK_*` env), `colleague config show` resolved
  `deepthink.model = nvidia/Gemma-4-31B-IT-NVFP4`,
  `base_url = http://localhost:8001/v1` (muse's own advertised dial target),
  `context_budget = 192000` (derived from the advertised 262144 window at the
  48000/65536 ratio) — zero model ids anywhere in colleague config. A live
  judgment work item under that discovery-only config (`df50aea666ec`,
  driven via the CLI against the colleague repo) ran
  `read_file → read_file → deepthink → finish` and recorded
  `DeepthinkCall(point='tool', tokens=1415, duration=60.4s, degraded=False)`
  — the discovered thinker consulted mid-loop, non-degraded, through the
  gateway proxy to thor; `status: ok` with a substantive judgment summary.
  The rig's explicit config was restored afterwards.

## Substantial decomposed write (best-colleague arc h9, plan task t9)

The h9 protocol: hand the loop a genuinely multi-part assignment (a 3-module
Python package + per-module tests, explicit instruction to DELEGATE via
`subagents`), run it live, and record the outcome honestly — a model that
cannot land it decomposed is recorded as a model limit, never claimed solved.

- **Pre-fix run `4c6a96107269` (CRASH — real harness bug caught live).** The
  27B delegated correctly (4 folded sub_results) but at step 12 emitted a
  tool call with empty arguments; the bare `arguments["path"]` `KeyError`
  escaped the dispatch (which caught only `ToolError`) and aborted the whole
  run as `engine 'vllm-openai' failed: 'path'`. Fixed in `22adbb3` (two
  layers: per-tool `_require` validation + argument-shaped-error conversion
  at the dispatch boundary), pinned by `tests/test_tool_arg_errors.py`.
- **Post-fix run `55859cb1d605` (survived — honest `incomplete`, 460s).** The
  identical task re-run: the parent spawned 3 children + merge
  (`COLLEAGUE_SUBAGENT_CONCURRENCY=2`); malformed/err steps cost one step
  each and the run kept going (the fix, proven live). Child 0 (tokenizer)
  delivered module+tests; child 1 (counter) delivered module+tests but ALSO
  re-wrote `tokenizer.py`/`__init__.py` as its own dependency stubs; child 2
  (report) stalled emitting literal tool-markup and wrote nothing. The merge
  child integrated child 0, no-op'd child 2, and **surfaced (did not
  force-merge) the child-1 conflict** — exactly the designed behavior. The
  parent ran out of budget resolving it; forced synthesis fired but its own
  output was literal markup, so the terminal summary is honest-but-garbled.
  The delivered half is real: **13/13 tests pass** on the work branch
  (`python3 -m pytest tests/` on `colleague/55859cb1d605-…`).
- **Verdict.** Harness: VALIDATED — the crash class is fixed live; isolation,
  fan-out, conflict-surfacing, and honest `incomplete` all behaved. Model:
  the served 27B under concurrent self-load still cannot land a 3-way
  decomposed write end-to-end (markup-emission stalls + duplicate-dependency
  conflicts) — recorded per h9 as a model limit, not claimed solved.
- **Follow-ups filed from this run:**
  [#264](https://github.com/agentculture/colleague/issues/264) — forced-synthesis output can itself be
  literal markup (the t5 re-parse targets a *finish* shape, not synthesis
  text); [#265](https://github.com/agentculture/colleague/issues/265) — the
  WIP-on-stop sweep commits `.colleague/worktrees/` lock files and
  `__pycache__` residue onto the work branch — fixed post-review in this same
  PR: the admin lock + pid markers moved out of the working tree entirely
  (under the git common dir, shared across linked worktrees) and the sweep
  excludes `__pycache__`/`*.pyc`.

## Livecheck closing regression (best-colleague arc R7, 2026-07-02)

`colleague livecheck --repo . --json` ran as the arc's closing regression
(the verb's own first full live outing). Results, recorded honestly:

- **Passed live in the battery:** loop tools, live mode, neighbours, and the
  dual-model proof (4 rows).
- **Skipped by the runner:** the basic-drive, context-budget, and
  gated-configs proofs hit livecheck's then-fixed 120s per-proof cap — too
  tight for full drives on the reference 27B (each passed historically).
  Fixed post-review in this same PR
  ([#266](https://github.com/agentculture/colleague/issues/266)): the cap is
  now 600s by default, tunable via `COLLEAGUE_LIVECHECK_TIMEOUT`, and a skip
  names the configured cap + the knob.
- **Failed in the battery, passed on re-run — a serving-side window, proven
  byte-identical:** the telemetry and subagents proofs failed during a window
  where the endpoint emitted malformed literal tool-markup instead of parsed
  tool calls. Diagnosis: `COLLEAGUE_DUMP_REQUEST=1` captured the exact
  outgoing payload; a byte-for-byte identical request (same system prompt,
  same 13 tool schemas, `temperature: 0.0` greedy decoding) failed 3/3 in one
  window and passed 3/3 (curl) + end-to-end (CLI) minutes later. Identical
  greedy requests giving different outputs over time is endpoint-side
  nondeterminism (speculative-decoding/batching state on the MTP-served 27B —
  the #66 family), not a harness or test bug. Both proofs **passed** on
  re-run (`2 passed in 699.70s`). This is the same markup-emission pathology
  that limited the h9 substantial-write run — now isolated to the serving
  layer with wire-level evidence.

## Media attachment live proofs (spec 2026-07-02, plan task t13)

Two new `colleague/livecheck.py` checks prove the media arc's headline claim —
"colleague verifies the model actually saw \[an attachment] instead of trusting
a 200" — against a real rig. Unlike the pytest-file proofs in the
[matrix](#validation-matrix) above (each a *separate* gated test file the
runner subprocesses into), these two drive one real `engine.work()` call
directly (`VllmOpenAIEngine().work(task, config)`, the same seam
`tests/test_vllm_live.py` uses) because each needs a runtime-generated
fixture attachment rather than a pre-existing test file:

- **`run_media_image_check`** — hand-encodes a real solid-red PNG (stdlib
  `zlib`/`struct`, no third-party imaging library) at runtime, attaches it via
  the same `Task.attachments` shape `work --attach` builds, and asks "What
  color is the attached image? Answer with the color name only." **PASSES
  only when BOTH** the answer names "red" **AND** `TaskResult.media` records
  the attachment `delivered` — a 200 response whose media record says
  dropped/unknown/missing **always FAILS**, even if the (hallucinated)
  answer happens to say "red" (`classify_media_image_check`,
  `TestClassifyMediaImageCheck.test_dropped_with_red_answer_still_fails`
  pins the never-trust-a-200 rule). **Gating condition:** a live,
  media-capable serving path must be configured — as of 2026-07-02 that is
  Gemma4 (`coolthor/gemma-4-12B-it-NVFP4A16`; the reference 27B main model is
  text-only), reached by passing `model="coolthor/gemma-4-12B-it-NVFP4A16"`
  (or setting `COLLEAGUE_MODEL`).
- **`run_media_audio_check`** — generates a tiny valid mono WAV clip (stdlib
  `wave` module) and asks the model to describe it. **Gating condition:**
  gated on the rig actually *consuming* `input_audio`. As of 2026-07-02 the
  reference rig **silently drops** it (200 OK, ~0 prompt tokens contributed —
  the same silent-drop shape row 9/t9's delivered-vs-dropped verification
  classifies `dropped`), so this check **currently reports SKIP** with the
  reason `"rig silently drops input_audio (200 OK, ~0 prompt tokens
  contributed — see docs/live-testing.md)"` and **never reports pass** while
  that holds (`classify_media_audio_check`,
  `TestClassifyMediaAudioCheck.test_never_passes_while_dropped_even_with_a_plausible_answer`).
  The classification is written to flip automatically the day the rig
  changes: a `delivered` attachment is graded like any other proof (pass on
  a real answer, fail on none) instead of an unconditional skip — no plan
  task claims working audio (plan risk, task t13).
- Both checks degrade to `skipped` — never a traceback — when the configured
  endpoint is unreachable (`probe_endpoint` short-circuit, no fixture is even
  built) or when the live call itself raises mid-flight (network drop,
  malformed response); see
  `TestRunMediaChecksOffline`/`TestRunMediaChecksLiveCallErrors` in
  `tests/test_livecheck_media.py`.

**Result — deterministic (unit-proven), live run PENDING.** The
classification logic (`_attachment_status`, `classify_media_image_check`,
`classify_media_audio_check`), the fixture generation
(`_make_red_png`/`_make_test_wav`, structurally verified — CRC-valid PNG
chunks, `wave`-readable WAV), and the offline/error-degradation paths are all
pinned by `tests/test_livecheck_media.py` (30 tests, zero network — simulated
`TaskResult.media`/`summary` payloads only). Neither `run_media_image_check`
nor `run_media_audio_check` has been executed against the reference rig yet
— rows 15/16 in the [matrix](#validation-matrix) record this honestly (⚠️,
not ✅). Run them live with:

```bash
uv run python -c "
from colleague.livecheck import run_media_image_check, run_media_audio_check
print(run_media_image_check('.', model='coolthor/gemma-4-12B-it-NVFP4A16'))
print(run_media_audio_check('.'))
"
```

**Acceptance to flip row 15 to ✅:** a live `run_media_image_check` call
returns `status="passed"` (answer names red AND delivered recorded). **Row
16 stays ⚠️/expected-SKIP by design** until the rig itself changes to consume
`input_audio` — a `skipped` result with the silent-drop reason IS the correct
outcome today, not a gap to close.

## Cortex/senses role split (spec 2026-07-03, plan tasks t12/t13)

Rows 17–18 are **✅ LIVE-PROVEN (2026-07-03)** — the deterministic/mock-engine
pieces of the arc (role resolution, config precedence including the lobes rung,
intake/speak-back windowing + degradation, the `ContextPacket`
verbatim-preservation invariant, the structural cannot-act proof, the
media-bridge senses-preferred path, and the all-engines/byte-identical proofs)
are unit-proven across tasks t1–t11, AND the live comparison (t13's
`cortex-senses` livecheck scenario) ran end-to-end against the rebalanced rig:
`run_cortex_senses_check` drove the SAME task cortex-only and split on the
served Qwen 27B + Gemma senses and graded from artifact evidence (see the
measured numbers on rows 17–18). The honest-SKIP path is preserved for a rig
that does NOT serve the rebalanced stack — `probe_lobes_stack` returns a reason
and the scenario SKIPs rather than fabricating a pass.

**The rig now serves the rebalanced stack.** The 2026-07-03 live gateway
probe (`LOBES_LIVE_FINDINGS.md`, gateway `http://localhost:8001`) confirmed
`GET /capabilities` reports BOTH roles `ready`+`loaded`:
`cortex` = `unsloth/Qwen3.6-27B-NVFP4` @ 131072 (128K),
`senses` = `coolthor/gemma-4-12B-it-NVFP4A16` @ 32768 (32K, `mtp: true` —
multimodal). This is the stack task t13's livecheck scenario needs to run
live rather than SKIP — a rig without it should still report SKIP with a
reason, never a fabricated pass; a rig with it (like the one probed today)
can produce a real per-mode comparison.

- **Row 17 — cortex-only vs split comparison.** Acceptance to flip to ✅: the
  SAME task run twice — once with `--cortex-only`, once in split mode — each
  produces an artifact with `mode` set correctly (`"cortex-only"` /
  `"split"`), and the split run's `TaskResult.senses.records` carry real
  `{point, latency, tokens, degraded=False}` entries alongside a packet whose
  `original` matches the operator's input verbatim. The two artifacts'
  `stats`/`senses` fields are reported side-by-side as runtime facts only —
  no quality/correctness score.
- **Row 18 — lobes role discovery (live gateway).** Acceptance to flip to ✅:
  `colleague lobes show` (or a `COLLEAGUE_LOBES_URL`-armed `EngineConfig.resolve()`)
  against the real gateway reports `rung: "armed_reachable"` with both roles'
  live metadata (model id, context window, `ready: true`), and a from-scratch
  `.colleague/config.json` carrying **zero model ids** completes a real work
  item with cortex driving the loop.

Run them live with (mirrors the media-proofs recipe above):

```bash
COLLEAGUE_LOBES_URL=http://localhost:8001 uv run colleague lobes show --json
COLLEAGUE_LOBES_URL=http://localhost:8001 uv run colleague work "<task>" \
  --repo . --no-pr   # zero model ids in .colleague/config.json
```

Both rows now carry live evidence (2026-07-03) — this section documents the
acceptance that was met and the recipe to reproduce it; the next task (t13)
has the exact acceptance bar to clear.

## Senses live presence + voice (talk-to-colleague-while-it-works arc, task t10)

Probed live 2026-07-03 against the lobes gateway `http://localhost:8001`
(`cortex` = Qwen3.6-27B @ 128K, `senses` = gemma-4-12B @ 32K, `stt` =
`nvidia/parakeet-tdt-0.6b-v2`, `tts` = `ResembleAI/chatterbox`; all report
`ready: true` in `/capabilities`). The livecheck classifiers
(`colleague/livecheck.py` `classify_senses_latency_check` /
`classify_injection_reached_check` / `classify_voice_lane_check`) grade each
lane from recorded evidence — a lane with no evidence, or a rig-side 502, SKIPs
honestly and NEVER reports a fabricated pass.

- **Row 19 — concurrent senses latency during cortex load. ✅ PASS.** The crux
  honesty condition (h9): a senses answer issued WHILE cortex is mid-completion
  must still feel conversational on the shared single GPU. Measured directly —
  a senses (gemma) completion took **1.14s alone**, then **1.69–2.33s (p50
  2.33s, max 2.33s)** while a concurrent 27B cortex generation was loading the
  same GPU. Both percentiles clear the target (**p50 < 3s, p95 < 8s**), so the
  spec's cross-model-concurrency assumption HOLDS: the GPU is not
  head-of-line-blocked to failure, senses stays responsive under cortex load.
- **Row 20 — an operator injection reaches the next cortex turn. ✅
  (deterministic) · ⏭ SKIP (live cortex loop).** The loop-level proof
  (`tests/test_talk_lane.py`) shows an applied guidance injection appears
  VERBATIM in cortex's next-turn prompt AND lands as both a flight-feed line
  and a `TaskResult.senses.injections` record (#206-safe — no phantom step). A
  fully-LIVE cortex-loop injection SKIPs: the reference 27B emits its answer
  into `reasoning` with `content: null` (confirmed in this probe), so it does
  not drive a real tool-calling loop on this rig — the same standing rig gap as
  #66. The injection channel itself is proven; the end-to-end live loop waits
  on a tool-calling cortex backend.
- **Row 21 — both audiences (session human + flight-attach caller). ✅ (tests)
  · ⏭ SKIP (live end-to-end).** The session concurrent lane
  (`tests/test_session_talk_lane.py`) and the `colleague talk` attach verb
  (`tests/test_talk_cli.py`) each prove a typed message → labeled `senses:`
  answer + a `-> cortex:` relay landing on the shared flight plane. A live
  end-to-end demo across both audiences waits on the same tool-calling-cortex
  rig gap (#66).
- **Row 22 — stt round-trip (verbatim transcript in). ⏭ SKIP → ✅ PASS
  (2026-07-22).** The gateway's `POST /v1/audio/transcriptions` returned
  **HTTP 502** (probed 2026-07-03) even though `/capabilities` reports `stt`
  (parakeet) `ready: true` — the rig-side speech proxy was down (sibling of
  lobes-cli#87). `colleague/voice.py` `transcribe` degraded correctly (None +
  one notice); the classifier SKIPped honestly. **2026-07-22 re-probe: the
  proxy is fixed (lobes-cli#89/#92 closed) and the lane PASSES through
  colleague's own wire client** — `transcribe()` on a rig-synthesized wav
  returned `'The quick brown fox jumps over the lazy dog.'` **verbatim** in
  0.11s (the v1 verbatim invariant holds live, no trim/normalize).
- **Row 23 — tts spoken reply (audio out). ⏭ SKIP → ✅ PASS (2026-07-22).**
  The gateway's `POST /v1/audio/speech` returned **HTTP 502 `{"error":"TTS
  backend returned no audio"}`** (probed 2026-07-03). `colleague/voice.py`
  `synthesize` degraded to None + one notice, the resident/session/talk text
  reply stayed byte-identical (audio is strictly additive), and the classifier
  SKIPped honestly. **2026-07-22 re-probe: `synthesize()` wrote a real
  119,084-byte RIFF/WAVE file (24kHz mono PCM16, chatterbox) in 1.45s** — the
  wav file-link surface previously proven via a mocked `synthesize` now has
  live audio behind it.

Reproduce the latency measurement and the stt/tts probes:

```bash
# concurrent senses-during-cortex latency + stt/tts wire (records the numbers above)
python - <<'PY'
# fire a long 27B cortex generation, measure senses (gemma) latency during it,
# then probe /v1/audio/transcriptions (stt) and /v1/audio/speech (tts).
# See the arc's scratch probe for the full script.
PY
```

The voice lanes were the honest limit of this arc on the 2026-07-03 rig: the
code was complete and degraded cleanly, but the gateway speech proxy 502'd for
BOTH stt and tts, so those two rows SKIPped (never a fabricated pass) until the
rig-side proxy was fixed — exactly the degradation contract the spec requires.
**As of 2026-07-22 both rows PASS live** (see the dated section below, which
closes #304).

## Presence default everywhere (spec 2026-07-08, the fourth increment)

**✅ LIVE-PROVEN 2026-07-08 on the real rig — and it closes the #66 gap.** The
gateway (`http://localhost:8001`) now serves a **tool-calling cortex**:
`unsloth/Qwen3.6-27B-NVFP4` returns real `tool_calls`
(`finish_reason: "tool_calls"`) for a `list_dir`/`edit_file` request — the
standing #66 "rig has no tool-calling backend" gap that made prior cortex-loop
proofs SKIP is **closed**. Senses is `coolthor/gemma-4-12B-it-NVFP4A16`. Both
dial the gateway origin `:8001/v1` (the advertised `:8000` 404s — lobes-cli#92).

- **Presence is the DEFAULT.** With senses armed, `resolve_presence_rung`
  resolves to `loop` — no flag. A plain one-shot `colleague work "add a
  docstring…" --json` ran presence default-on.
- **Cortex (Qwen) did real repo work.** `list_dir → read_file → edit_file →
  read_file → finish`, and committed the docstring edit. Not a mock — the real
  27B drove the bounded tool loop end to end.
- **Senses (Gemma) narrated real progress, grounded in the feed.** Labeled
  `senses:` lines on stderr: *"Cortex has completed step 2 and successfully read
  the contents of greet.py."*, *"Cortex is currently at step 4, reading greet.py
  to verify the recent edits."* — the actual cortex progress, not a canned line.
- **`--json` stdout stayed machine-parseable** (presence rides stderr); the
  ack/update chat folded onto `TaskResult.senses` (`['ack','talk','talk']`); the
  loop-turn records landed (`senses-loop:dispatch_to_cortex`,
  `senses-loop:reply_to_operator`).
- **Machine-graded PASS.** `colleague/livecheck.py`
  `classify_work_presence_check` graded the run **PASSED** from the artifact +
  rendered lines alone: *"ack + narration observed; 5 record(s), 3 chat
  entr(ies)"* — no human judgment.

**Bugs the live proof surfaced (and fixed before the PR — commit `50fd6c2`):**
the first live run showed Gemma only ever emitting the fixed dispatch notice and
an empty `senses.chat`. Root causes: (1) a one-shot foreground engine has no
flight plane, so senses had an EMPTY feed and nothing to narrate — it re-picked
`dispatch_to_cortex` every boundary; (2) the loop prompt did not distinguish a
cadence tick (cortex already working → narrate) from an operator message
(→ dispatch); (3) the foreground chat had no flight log to fold from, so it was
lost from the artifact. Fixes: the progress sink now feeds real step/tool
progress into the engine's buffer, the loop prompt is boundary-aware, and
`fold_presence_snapshot(fold_chat=True)` carries the foreground chat onto the
artifact. The re-run (above) passed.

**Honest limits on today's rig:**

- A 12B senses model occasionally emits a near-miss move name at an early
  empty-feed boundary; the executor refuses it (recorded `senses-loop:refused`,
  no-op) and the loop self-corrects once feed accumulates. Honest, not silent.
- The dispatch-ack in senses' OWN words is best-effort — an empty `ack` field
  degrades to the fixed dispatch notice (never a fabricated understanding).
- tts narration of updates SKIPped at proof time (the gateway speech proxy
  502'd — lobes-cli#89/#92); the text lane is byte-identical. **2026-07-22:
  the proxy is fixed and the narration proof PASSES** (see the dated #304
  section below).
- The interactive "keep talking to senses while cortex works" session lane and
  the resident reply-to-origin lane are unit- + boundary-proven; a fully
  interactive live capture (typing mid-run over a TTY) is left to hands-on use.

Reproduce:

```bash
RIG=http://localhost:8001/v1
COLLEAGUE_BASE_URL=$RIG COLLEAGUE_MODEL=unsloth/Qwen3.6-27B-NVFP4 \
COLLEAGUE_SENSES_BASE_URL=$RIG COLLEAGUE_SENSES_MODEL=coolthor/gemma-4-12B-it-NVFP4A16 \
COLLEAGUE_ENGINE=vllm-openai COLLEAGUE_SENSES_UPDATE_STEPS=2 \
  uv run colleague work "Add a docstring to the greet function." --repo <repo> --no-pr --json
# stdout = JSON result; stderr = gemma's `senses:` ack + progress lines.
```

## 2026-07-10 — Feels-alive arc live proofs (t9)

Rig: lobes gateway at `http://localhost:8001` serving cortex
`unsloth/Qwen3.6-27B-NVFP4`, senses
`coolthor/gemma-4-12B-it-NVFP4A16`, embedder `Qwen/Qwen3-Embedding-0.6B`.
Baseline (t1, same day, above): a 13.62s full turn whose longest silent gap
was 4.43s.

- **Token streaming — colleague side proven, rig side SKIPs.** Colleague's
  SSE consumption is incremental by construction (the fake-SSE-server unit
  suite pins deltas arriving before the stream closes;
  `tests/test_vllm_stream.py`). LIVE through the gateway the proof
  (`tests/test_vllm_live_streaming.py`, livecheck row "token streaming
  (feels-alive)") observed 220 deltas ALL landing at 34.0s of a 34.0s turn —
  and a client-agnostic raw `curl -N` probe shows the same signature
  (21 frames, first=last=3.06s): **the gateway proxy buffers SSE**, so
  `classify_streaming_check` grades the rig **SKIP** ("stream delivered as
  one terminal burst … rig-side, not a colleague regression"). Filed as
  [lobes-cli#103](https://github.com/agentculture/lobes-cli/issues/103). The moment the
  gateway forwards frames incrementally, the same proof grades PASS with no
  colleague change.
- **Dead-server distinct state — PASSED.** An unreachable endpoint with an
  armed sink yields a legible connection error in ~0s with ZERO deltas —
  visually distinct from a live turn's stream (spec h13).
- **`colleague coherence` — live-proven.** `coherence score <small.md>`
  returns a real Meaning Gradient payload (meaning 0.3705, full `frame`
  provenance naming `Qwen/Qwen3-Embedding-0.6B` at
  `http://localhost:8001/v1`) through the lobes embed relay — after fixing
  `lobes.embed_env` to carry the advertised `/v1` path prefix (a bare-origin
  relay 404'd BOTH this verb and the #294 gate on the real rig).
  `coherence show last` resolves the real work item `44a9865c4be5` and
  reports honestly (no changed `.md` files in that work item). A file larger
  than the embedder's 8192-token window records an honest per-file error
  (400), never a crash.
- **CLAUDE.md cut — measured.** 158,454 → 25,564 bytes (~39,613 → ~6,391
  est. tokens at bytes/4): every session in this repo reclaims ~33K tokens of
  context.

## 2026-07-22 — Voice lanes live: stt/tts/presence-narration flip SKIP → PASS (closes #304)

The rig-side blocker behind rows 22/23 and the presence-narration proof is
gone: lobes-cli#89 closed, the gateway speech proxy serves both audio lanes,
and `/capabilities` reports `stt` (`nvidia/parakeet-tdt-0.6b-v2`, parakeet
runtime) and `tts` (`ResembleAI/chatterbox`, chatterbox runtime) as
`ready: true, loaded: true, feasible: true` — the stt role now also advertises
the `realtime_vad_session` responsibility (the gateway's `/v1/realtime`
WebSocket session capability, unconsumed by colleague today). All probes below
ran through colleague's OWN wire clients (`colleague/voice.py`), voice config
resolved via lobes discovery (both lanes dialing the gateway origin `/v1`), on
2026-07-22:

- **tts (row 23) — ✅ PASS.** `synthesize("The quick brown fox jumps over the
  lazy dog.")` → a real **119,084-byte** RIFF/WAVE file (24kHz mono PCM16) in
  **1.45s**. A raw curl probe agrees (`200 audio/wav`, 40,364 bytes for a
  two-word input).
- **stt (row 22) — ✅ PASS, verbatim.** `transcribe()` on that rig-synthesized
  wav returned `'The quick brown fox jumps over the lazy dog.'` — the server
  transcript **exactly**, in **0.11s**. The v1 verbatim invariant (never
  trim/normalize a transcript) holds live.
- **presence narration (#304, presence-default-everywhere t12) — ✅ PASS.**
  `run_presence_narration_check(".")` →
  `ProofResult(file='presence_narration', status='passed', detail='a rendered
  presence beat was narrated to a real .wav file')`. The SKIP-honestly
  classifier flipped to a real grade the day the rig served audio, exactly as
  designed — no colleague code change was needed.

Honest limits of this record:

- `run_presence_narration_check` has **no production caller** — the
  `colleague livecheck` verb runs only the `_KNOWN_PROOFS` pytest files
  (`select_proofs`), so this proof was driven directly
  (`python -c "from colleague.livecheck import run_presence_narration_check;
  print(run_presence_narration_check('.'))"`). Wiring the ProofResult runner
  checks into the verb is follow-up work (recorded in the realtime-speech
  scope frame).
- The stt round-trip input was rig-synthesized speech (chatterbox → parakeet),
  not a human microphone recording; a human-mic capture pass rides the
  `[voice]` extra and stays a hands-on check.

Reproduce:

```bash
uv run python - <<'PY'
from colleague.config import EngineConfig
from colleague.livecheck import run_presence_narration_check
from colleague.voice import transcribe, synthesize
import tempfile, pathlib
v = EngineConfig.resolve(repo_path=".").voice
with tempfile.TemporaryDirectory() as d:
    wav = synthesize("The quick brown fox jumps over the lazy dog.",
                     tts_model=v.tts_model, base_url=v.tts_base_url,
                     out_path=pathlib.Path(d) / "rt.wav", api_key=v.api_key)
    print("tts:", wav, wav and wav.stat().st_size)
    print("stt:", repr(transcribe(wav, stt_model=v.stt_model,
                                  base_url=v.stt_base_url, api_key=v.api_key)))
print(run_presence_narration_check("."))
PY
```

## 2026-07-22 — Realtime speech live proofs (plan t9): first real-microphone validation

Rig: lobes gateway `:8001` (Bearer-authed), realtime bridge with server VAD
(silero) + parakeet stt + chatterbox tts; cortex
`unsloth/Qwen3.6-27B-NVFP4`, senses
`coolthor/gemma-4-12B-it-NVFP4A16`. Audio: the **physical Reachy Mini USB
mic** captured via the pipewire layer (`COLLEAGUE_REALTIME_INPUT_DEVICE=
pipewire` — see the honest limits), stimuli and replies played aloud through
`reachymini_audio_sink` (speaker → air → mic, a genuine acoustic path).
This is the **first real-microphone validation of the whole realtime
stack** — lobes-cli's own acceptance evidence
(`docs/evidence/2026-07-22-accept-realtime-voice-to-voice-spark.txt`) lists
a real microphone as NOT VALIDATED (every rig-side run used synthesized
audio injected on the wire).

- **`run_realtime_check` — ✅ PASS live.** `ProofResult(file='realtime',
  status='passed')`: the ears-only session opened (101 + `session.update`)
  and a server event arrived within the bounded timeout. Its own honest bar:
  proves the handshake+event wire, NOT transcription.
- **Acoustic real-mic transcript (drill A) — ✅ PASS.** A chatterbox-spoken
  "The quick brown fox jumps over the lazy dog." played aloud was VAD-
  segmented (`speech_started` 0.38s into playback, `speech_stopped` 0.73s
  after it ended) and transcribed **0.79s after speech end** as `'A quick
  brown fox jumps over the lazy dog.'` — verbatim delivery of the server
  transcript, with one honest acoustic-path substitution (The→A).
- **10-turn E2E latency under cortex load (drill B, default reply shape) —
  ⚠️ p50 MISS / p95 met, measured honestly.** Ten spoken questions played
  aloud; per turn: VAD speech-end → transcript → senses answer (one spoken-
  style sentence, `max_tokens` 60) → chatterbox synth of the reply.
  **p50 = 5.63s (target < 5s: MISS), p95 = 8.28s (target < 10s: met)**,
  min 4.67s / max 8.28s, 10/10 turns transcribed. Breakdown: transcript
  ≈ 0.10s after VAD-end, senses answer by ≈ 2.3s — **reply-TTS synthesis
  (~3.3s) dominates**, exactly the frame-park/plan-risk r1 prediction. A
  1200-token cortex generation was in flight continuously (1 completed
  mid-run).
- **Drill C — the brevity lever, ✅ target met.** Same loop with the spoken
  reply capped ("AT MOST 8 words", `max_tokens` 24): **p50 = 4.60s,
  p95 = 5.48s** (min 3.92s), 10/10 transcribed, cortex generation in flight
  throughout. Verdict for success-signal c16/h13: the < 5s p50 is met
  **under a spoken-brevity reply shape**; the session's spoken replies do
  not apply that cap today — wiring a brevity knob into the spoken-reply
  path is a named follow-up, and the default shape's honest number is
  drill B's.
- **Degrade drills — ✅ live.** A dead dial target degrades instantly
  (`ConnectionRefusedError` → one `colleague:` notice, `open_session` →
  `None`, 0.00s); the extra-absent path raises the clean
  `pip install colleague[voice]` CliError (unit + live verified); a
  **mid-session WS kill** degrades with one notice — proven against the
  in-repo fake-server kill (`tests/test_realtime_client.py`), not re-proven
  live (no way to kill only the gateway's socket on a shared rig).

Honest limits of this record:

- **The Reachy Mini hw mic is 16kHz-native and `start_capture` has no
  resampler** — opening it directly at the wire's 24kHz degrades with the
  device-naming notice (itself verified live). Capturing via the pipewire
  device works (pipewire resamples to 24kHz); the feature doc should steer
  fixed-rate hw devices through a resampling layer, and an in-module
  resample is a follow-up candidate.
- Every spoken turn was **synthesized speech over the acoustic path** — a
  real mic and real air, but chatterbox prosody, not a human voice. Two of
  twenty turns garbled acoustically ("budget" → "battery"; one longer
  mid-run garble). A human-voiced session pass is still pending hands-on
  use.
- Still unvalidated rig-side (carried from lobes-cli's evidence + plan risk
  r2): the VAD-unavailable path, concurrent realtime sessions, barge-in
  (out of scope in v1 regardless — half-duplex).
- The measurement harness drives the same client modules the session uses
  (`open_session`/`start_capture`/`synthesize`) but not the interactive
  session loop itself; the session lane's own behavior is pinned by
  `tests/test_session_voice.py` (26 tests) including a real-PTY teardown
  proof.

Reproduce: the drill scripts live in the session scratchpad
(`t9_drill_a.py` / `t9_drill_b.py` / `t9_drill_c.py`, session
8295ced9); each resolves `EngineConfig` from the repo, arms
`COLLEAGUE_REALTIME_INPUT_DEVICE=pipewire`, plays stimuli through
`reachymini_audio_sink`, and measures from the `input_audio_buffer.
speech_stopped` event to reply-wav-ready. `run_realtime_check` reproduces
via `uv run python -c "from colleague.livecheck import run_realtime_check;
print(run_realtime_check('.'))"`.

## 2026-08-06 — three-tier execution: the live three-seat proof (t17, spec h1/h17)

Rig re-probed at proof time: cortex `unsloth/Qwen3.6-27B-NVFP4`, senses
`unsloth/gemma-4-12B-it-qat-w4a16`, worker `unsloth/Qwen3.6-35B-A3B-NVFP4`
all ready:true through the one `:8001` gateway (a stale muse advert lingers
ready:false; legacy discovery would still arm it — known, rig-side).

One live session, all three seats, recorded facts:

- **Worker acted (CLI level).** `COLLEAGUE_THREE_TIER=1 colleague work` on a
  throwaway fixture repo: status ok, 6 steps, real fix landed (suite green),
  artifact names the acting model `unsloth/Qwen3.6-35B-A3B-NVFP4` and carries
  `finish_states: [{seat: main, finish_reason: tool_calls, state:
  deliberate, truncated: false}]` — the t1 spine recording the real wire
  value.
- **Seat attribution.** The shipped surface renders `worker ▸ working…` under
  three-tier and the byte-identical `cortex ▸ working…` legacy line (t9).
- **Senses relayed the worker's actual answer (production lane, live).** The
  run's summary went through `run_senses_talk(worker_answer=…)`: senses
  paraphrased, the STRUCTURAL FALLBACK fired (`verbatim_presence=false,
  fallback=true`, degradation recorded) and the operator-visible answer
  contains the worker's answer verbatim — the t2 floor doing its job live
  (experiment A's 6/6 record is the fuller measurement).
- **Cortex configured between episodes (module level — deviation d3).**
  `chain.run_configurator_window(armed=True)` against the live cortex dial,
  fed the episode digest (docs-only follow-up queued): cortex proposed
  narrowing `worker.tools` to `["write_file", "finish"]` — a CORRECT
  narrowing for the described next episode — the unit validated and APPLIED
  at the sanctioned between-episodes window: events proposed → verified →
  applied, snapshot digest `43e085e7…` → `81ec1f24…`, application latency
  0.2 ms, review latency 27.0 s. Counters advanced; nothing reported alive
  from `armed` alone. (The work FRONT does not arm this plane yet — issue
  #366 / deviations d2+d3; this proof passes through the same sanctioned
  window functions the front will call.)
- **Byte-identical at wrap.** `tests/test_three_tier_gates.py` re-run: 12
  passed (no-config behavior + existing-field identity + sanctioned new
  fields, loud refusal on both fronts, five distinguishable finish states).

Promotion-gate verdicts backing this proof: experiment A SUPPORTING,
experiment B PROMOTES (the c23 performs-better gate), experiment C
SUPPORTING — all pre-registered under `docs/experiments/`.

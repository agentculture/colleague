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

Tracking epic: [#128](https://github.com/agentculture/colleague/issues/128).

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

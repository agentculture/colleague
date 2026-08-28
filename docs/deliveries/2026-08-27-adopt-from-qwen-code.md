# Delivery Summary — adopt-from-qwen-code

plan: `adopt-from-qwen-code` · run: `complete` · date: `2026-08-27`
baseline: `devague summary skeleton`

## Intent

Port the harness mechanics that let Qwen Code drive the same Qwen3.8-27B to
finished PRs on this rig — parallel read-only tool batches, an output-token
clamp, no per-turn `/tokenize` round-trip, grep/glob tools, paged reads,
tolerant edit matching, spill-to-disk truncation, rule-based microcompaction,
stream and loop guards, adopted prompt text — plus the opt-in `associate` seat,
credit Qwen Code and its Google Gemini CLI lineage in the provenance ledger, and
measure the result against a pre-registered bar. The plan executed was
`docs/plans/2026-08-27-adopt-from-qwen-code.md` (24 tasks / 9 waves) from the
converged spec `docs/specs/2026-08-27-adopt-from-qwen-code.md`, fanned out by
`/assign-to-workforce` on branch `spec/adopt-from-qwen-code` and delivered as
PR #441 (v1.64.0).

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — NOTICE + docs/adopted-from.md ledger + antigravity guard
- `t2` — colleague/toolbatch.py — partition + read-only shell checker (pure)
- `t3` — colleague/outputclamp.py — window-clamped `max_tokens` with per-seat ceilings (pure)
- `t4` — colleague/microcompact.py — rule-based blanking of old tool results (pure)
- `t5` — colleague/`search_tools.py` — `grep_search` + glob (ripgrep with stdlib fallback)
- `t6` — colleague/editmatch.py — tolerant edit match + prior-read set (pure)
- `t7` — Stream guards — idle + lifetime watchdog on the SSE path (`vllm_openai.py`)
- `t8` — Prompt text adoption — colleague/prompttext.py with per-model examples + variant knob
- `t9` — tools.py wiring A — `read_file` offset/limit + spill truncation
- `t10` — Measurement harness — scripts/`compare_arms.py` + pre-registration + before-state row
- `t11` — colleague/truncation.py — head+tail truncation with spill-to-disk (pure + fs)
- `t12` — Drop the per-turn /tokenize — run-start window discovery + `COLLEAGUE_EXACT_TOKENS`
- `t13` — tools.py wiring B — `edit_file` tolerant tier + prior-read enforcement
- `t14` — tools.py wiring C — register `grep_search` + glob, concurrency kinds, role curation
- `t15` — loop.py — batched tool execution (lifecycle split, pool, failure + stop semantics, convention change 6)
- `t16` — loop.py — clamp, microcompaction, loop guards, ledger event
- `t17` — mock engine batch scenario + all-engines pin
- `t18` — Associate seat A — opt-in resolution, role-name addressing, streaming, config/lobes show
- `t19` — Associate seat B — the enumerated consumers (scout child, compact summary, synthesis, digests, distill rung)
- `t20` — Observability — doctor rows, config show clamp/window, artifact counts, clean reaps spill
- `t21` — Continuation — no read-set across work --continue
- `t22` — Reversibility — one off-knob per mechanism, byte-identical pinning suite
- `t23` — Docs — feature doc, CLAUDE.md bullet + carve-outs, ledger rows, approval-gate + work-and-loop paragraphs
- `t24` — Run the arms — three model arms + temperature arm, ratios recorded, revert-or-flag

## Actual Delivery

Every task merged through the TDD gate (tests before and after each merge) on
`spec/adopt-from-qwen-code`; 24/24 merged. "Who" names the worker: colleague =
a `colleague work` dispatch (Qwen3.8-27B), sonnet/fork = a Claude task agent.

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `NOTICE`, `docs/adopted-from.md` (later filled by dogfood run `5e097e2aabf7`), `tests/test_adopted_from.py`; merge `57ca3ce` (sonnet; d1) |
| `t2` | delivered | `colleague/toolbatch.py` — partition, read-only checker, `run_batch` pool; thread allow-list + two mirrors; merge `df05509` (sonnet after colleague lane stop d8; d12) |
| `t3` | delivered | `colleague/outputclamp.py`; merge `e315b9b` (sonnet after d6; d7 corrected the plan's worked number to 49037) |
| `t4` | delivered | `colleague/microcompact.py`; merge `b0da80e` (sonnet; d10) |
| `t5` | delivered | `colleague/search_tools.py` + subprocess allow-list mirrors; merge `121d0fb` (sonnet; d9) |
| `t6` | delivered | `colleague/editmatch.py`; merge `60d33cb` (sonnet; d11) |
| `t7` | delivered | `colleague/streamguards.py` wired into `vllm_openai.py`, real-socket tests; merge `3b2eb93` (fork; d4) |
| `t8` | delivered | `colleague/prompttext.py`, one `loop.py` hunk, `engine.py` two lines; merge `9535d4f` (fork; d2, d3). **Default later flipped to `v1`** in `4dd0fec` (d25) |
| `t9` | delivered | `colleague/readpage.py`, `read_file` offset/limit, spill wiring; merge `d2554bb` (fork; d13) |
| `t10` | delivered | `scripts/compare_arms.py`, rows 41 (pre-registration) + 42 (before-state, ids filled in `b70d193`); merge `6c7ab10` (sonnet + operator runs) |
| `t11` | delivered | `colleague/truncation.py`; merge `7b85337` (sonnet) |
| `t12` | delivered | `colleague/tokenestimate.py`, run-start probe, CLAUDE.md carve-out text; merge `56b9672` (fork; d15) |
| `t13` | delivered | `colleague/editgate.py`, prior-read rule on `edit_file`; merge `8893f66` (fork; d14) |
| `t14` | delivered | `colleague/search_schemas.py`, legacy knob, role curation; merge `6c98cab` (fork; d17) |
| `t15` | delivered | `colleague/toolbatch_loop.py`, `_run_tool_call` lifecycle split, convention change (6) in CLAUDE.md; merge `e1a84f9` (fork; d19) |
| `t16` | delivered | `colleague/turnbudget.py`, `colleague/loopguards.py`, `max_tokens` on every payload; merge `c542db6` (fork; d21) |
| `t17` | delivered | `colleague/engines/mock_scenarios.py`, `tests/test_all_engines_batch.py`; merge `00d12b8` (sonnet; d20) |
| `t18` | delivered | `colleague/associate.py`, `associate_config.py`, `associate_cli.py`; merge `bef4b05` (fork; d5 — a ratchet-baseline bump was rejected and reworked net-zero) |
| `t19` | delivered | `colleague/associate_seats.py`, scout role, distill rung; merge `93ebac4` (fork; d16 **risky**) |
| `t20` | delivered | `colleague/runcounts.py`, `harness_cli.py`, `oilcheck/harness.py`, `lobes_context` stamp, `clean` reaps spill; merge `69377ff` (fork; d22) |
| `t21` | delivered | continuation preamble + `context_note`; merge `07d6213` (sonnet; d18) |
| `t22` | delivered | `tests/test_knobs_byte_identical.py` + fixtures from `ff7331e`, knob table; merge `ed647f4` (sonnet; d23) |
| `t23` | delivered | `docs/features/adopt-from-qwen-code.md`, CLAUDE.md bullet, ledger complete, approval-gate/work-and-loop paragraphs; merge `08a6944` (fork; d24) |
| `t24` | delivered | arms run (rows 43–46), `compare_arms` verdicts, Results section, prompt default flipped; commit `4dd0fec` (operator; d25 **risky**) |

## Mid-work Decisions

All 25 deviation records are **recorded but still `proposed`** (the operator
has not yet run `devague deviate --confirm`); they are quoted here as the
recorded decisions, not re-litigated, and their confirmation is listed under
Remaining Work.

- `d1` — t1's antigravity guard excludes `docs/specs/` and `docs/plans/` (they name the product to explain why it is not credited) — h13's literal `docs/` would fail on the arc's own files
- `d2` — t8 ships three tool-call example families, no `gemma4` — the qwen-direct-no-gemma guard forbids the literal in `colleague/*.py`
- `d3` — t8 touched `engine.py` (two one-line substitutions) — the model id is only known at `Engine.system_prompt()`
- `d4` — t7 put the guards in a new `streamguards.py`, `stallguard.py` untouched — the file-length ratchet forbids growth
- `d5` — t18 lands three extra new modules and touches the effort doc/boundary allow-list — ratchet + existing pins
- `d6` / `d8` — both wave-1 colleague lanes stopped (single turns > 15 min under GPU contention); modules went to sonnet agents; the baseline arm was given the GPU alone for measurement validity
- `d7` — the plan's worked example number (48934) was a transcription slip; the formula gives 49037
- `d9` — `glob()` has no brace expansion; `grep_search` uses Python's `re` dialect on both backends; `confine()` re-implements `_safe_path`
- `d10` — microcompaction blanks any old tool result rather than porting the allow-lists
- `d11` — the tolerant edit tier trims leading and trailing whitespace and folds the staged normalization into one pass
- `d12` — t2's thread allow-list entry required updating two mirror pins; the checker is stricter than upstream
- `d13` — `read_file` pages instead of head+tail; `COLLEAGUE_MAX_OUTPUT_CHARS` became a ceiling (decision c50 supersedes h8's wording)
- `d14` — the prior-read rule gates `edit_file` only (gating `write_file` broke the all-engines mock contract)
- `d15` — t12 left `config.py` untouched; `lobes_context` had no resolution rung until t20; CLAUDE.md reads "two per-turn carve-outs plus one run-scoped probe"
- `d16` — **risky**: unarmed associate = byte-identical to main (h1/c44 over c33's "absent = cortex@low"); cortex@low only when armed-but-unreachable
- `d17` — the legacy knob does not reach the raw engine `complete(tools=None)` path (plan-mode pin)
- `d18` — the continuation id is parsed back out of the task instruction
- `d19` — batch orchestration lives in `toolbatch_loop.py`; gates became decision-only verdicts; stop is honoured between batches
- `d20` — the payload diff-scope test asserts a subset of keys; `mock-batch:` is the first task-text recipe
- `d21` — the microcompaction ledger event is an `evidence` kind; counts land as warnings (artifact/contract at zero ratchet slack)
- `d22` — run counters live on an omit-when-zero `WorkStats.counts` dict
- `d23` — the byte-identical comparison is scoped to tool names + payload keys + prompt + steps (`read_file`'s schema params are additive)
- `d24` — the feature doc's Credit section explains decision q1 without the literal product name
- `d25` — **risky**: every arm misses the c28 bar; the adopted prompt text is the cost; per h21 it became opt-in (`COLLEAGUE_PROMPT_VARIANT=qwen`), `v1` is the default
- Not covered by a record: the four measurement arms were re-ordered mid-run (attribution arm first) and the runner was detached from the harness after two background jobs were reaped; three colleague review dispatches and one Claude fork handled the PR review (Qodo 15, Sonar 72); the review lane `qodo-a` lost its edits to an `incomplete`-run worktree reap (plan risk r12).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t1` (`d1`) | h13's literal `docs/` would fail on the arc's own spec/plan files; the guard still covers every shipped surface | acceptable |
| `t8` (`d2`) | `test_no_gemma_in_source_code` forbids the `gemma` literal in `colleague/*.py` | acceptable |
| `t8` (`d3`) | the model id is only known at `Engine.system_prompt()`; keeping `loop.py` to one hunk was preferred | acceptable |
| `t7` (`d4`) | the file-length ratchet fails any module that grows past baseline; every later task had to shrink-or-split | needs-follow-up |
| `t18` (`d5`) | ratchet forbids growth in config/loop/vllm_openai; existing pinning tests require the doc row and the builder entry | acceptable |
| `t3` (`d6`) | unbounded reasoning on the pre-arc harness under contention — the before-state pathology c26 describes | acceptable |
| `t3` (`d7`) | plan text error, not a design change — the formula is unchanged | acceptable |
| `t2` (`d8`) | same pathology as d6, plus measurement validity: the baseline arm must own the GPU | acceptable |
| `t5` (`d9`) | stdlib-only convention; `tools.py` frozen by the ratchet; parity proven with a real rg | acceptable |
| `t4` (`d10`) | shape and scope follow the confirmed brief; the loop task decides the trigger | acceptable |
| `t6` (`d11`) | the confirmed criterion requires indent-drifted `old_string` to land | acceptable |
| `t2` (`d12`) | pin tests mirror the sanctioned list; a stricter checker only costs parallelism | acceptable |
| `t9` (`d13`) | c50 was decided after h8; paging is the read tool's own truncation in the source design | acceptable |
| `t13` (`d14`) | the all-engines rule outranks an operator-brief extra; the plan's own criteria are met | acceptable |
| `t12` (`d15`) | honest wording; the `lobes_context` stamp and config-show line belonged to t16/t20 (landed in t20) | needs-follow-up |
| `t19` (`d16`) | two confirmed claims conflict; byte-identical-when-unarmed is the standing invariant — operator to confirm this reading | risky |
| `t14` (`d17`) | ratchet + two identity pins; t22's proof runs over curated `work` payloads | needs-follow-up |
| `t21` (`d18`) | all-engines for free, zero engine edits | acceptable |
| `t15` (`d19`) | inherent to the confirmed lifecycle split; ratchet | acceptable |
| `t17` (`d20`) | forward-compatible pin; ratchet | acceptable |
| `t16` (`d21`) | closed ledger kinds, ratchet slack, adapter-local retry keeps the loop unchanged | acceptable |
| `t20` (`d22`) | contract pins; counters can never disagree with the record | acceptable |
| `t22` (`d23`) | honest scope of "byte-identical"; the read schema addition is additive and stated | needs-follow-up |
| `t23` (`d24`) | the guard test is the arc's own; substance delivered | acceptable |
| `t24` (`d25`) | the plan's own revert-or-flag rule; numbers in rows 43–46 and issue #440 | risky |
| `t24` (c28) | the confirmed success signal (≤ 0.7× wall, ≤ 0.8× turns vs main) was **not met** by any arm — the branch with the `v1` prompt is at 1.10× / 1.07× (game) and 1.18× / 1.10× (repo); no record other than d25 covers the bar itself | needs-follow-up |

## Evidence

- tests: `uv run pytest -n auto -q` on `01971d4` — **9868 passed, 26 skipped, 0 failed** (skips are opt-in extras / live-rig gates)
- tests, per mechanism (all pass on the tip): `tests/test_toolbatch.py`, `tests/test_toolbatch_loop.py`, `tests/test_outputclamp.py`, `tests/test_turnbudget.py`, `tests/test_microcompact.py`, `tests/test_loop_microcompact.py`, `tests/test_search_tools.py`, `tests/test_search_schemas.py`, `tests/test_editmatch.py`, `tests/test_tools_edit.py`, `tests/test_readpage.py`, `tests/test_tools_read.py`, `tests/test_truncation.py`, `tests/test_stream_guards.py` (real-socket rig), `tests/test_tokenize_once.py` (counting rig), `tests/test_loopguards.py`, `tests/test_prompttext.py` (snapshots), `tests/test_associate_config.py`, `tests/test_associate_seats.py`, `tests/test_runcounts.py`, `tests/test_oilcheck_harness.py`, `tests/test_harness_cli.py`, `tests/test_clean_tool_output.py`, `tests/test_continuation_readset.py`, `tests/test_all_engines_batch.py`, `tests/test_knobs_byte_identical.py` (fixtures recorded from `ff7331e`), `tests/test_adopted_from.py`, `tests/test_compare_arms.py`, `tests/test_e2e_mock.py` (all-engines pin), `tests/test_file_length_ratchet.py`
- lint: `black --check`, `isort --check-only`, `flake8` on `colleague tests scripts` — clean; `bandit -c pyproject.toml -r colleague` — clean; `teken cli doctor . --strict` — PASS
- commits: `83606d1..01971d4` on `spec/adopt-from-qwen-code` (79 commits; base `main @ ff7331e`)
- measurement: `docs/live-testing.md` rows 41–46 (artifact ids per arm); `scripts/compare_arms.py` output pasted in the feature doc § Results and in PR #441's evidence comment
- PRs / issues: PR #441; follow-ups #435, #436, #437, #438, #439, anchor #440, evidence comment on #421; agentculture/lobes-cli#220
- review: 15 Qodo threads resolved (13 fixed, 2 pushbacks replied); SonarCloud PR-scoped issues 72 → **0** (analysis of `01971d4`, 2026-08-28T00:06Z; quality gate passed)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| All 24 plan tasks merged through the TDD gate; the full suite is green on the tip | high | commits `83606d1..01971d4` · `uv run pytest -n auto -q` 9868 passed |
| Every ported mechanism has an off-knob whose off-state matches `main` on tool names, payload keys, prompt and steps | high | `tests/test_knobs_byte_identical.py` (fixtures from `ff7331e`) — scope stated in d23 |
| Credit lands in `NOTICE`, `docs/adopted-from.md` (14 rows, no `pending`) and inline `adapted-from` markers | high | files present · `tests/test_adopted_from.py` |
| Convention change (6) — one bounded thread pool in `toolbatch.py` — is recorded in CLAUDE.md and the boundary allow-list | high | `CLAUDE.md` § v1 scope · `tests/test_boundary.py` + mirrors |
| The associate seat resolves by role name through the gateway proxy, streams like cortex, and serves in 0.6 s with thinking off | high | `tests/test_associate_config.py` · live-fire notes in the PR evidence comment (dogfood/NOTES) |
| The stream-lifetime guard bounds a gateway hang at 900 s (main: 5,400 s) | high | live: artifacts `91f300b0a858`, temp-default game-2 (`warnings[0].guard = stream-lifetime`) · `tests/test_stream_guards.py` |
| The pre-registered c28 bar (≤ 0.7× wall, ≤ 0.8× turns) is met | **not claimed** | every arm misses it — `docs/live-testing.md` rows 43–46, #440 |
| With the `v1` prompt the mechanics are at parity with main and more reliable (8/9 game runs finished vs 2/3) | medium | rows 42–44 (n = 2–3 per arm; main's spread 581–817 s) |
| The adopted prompt text costs ~2.3× wall / ~3× reasoning on Qwen3.8 | medium | rows 43 vs 44 (same code, prompt-only change); #437 |
| Batches / search tools cut turns on read-heavy work (13-file survey in 3 turns) | medium | dogfood runs `41bb8b0a9cf5`, `5e097e2aabf7`, review sweeps 6–14 turns (PR evidence comment) |
| Associate improves a real work item's wall-clock | unverified | the armed arm never called it (no delegation, memory unarmed) — not claimed |
| Temperature 0.6 helps | unverified | arm underpowered (2 of 3 game runs hung) — not claimed |
| SonarCloud PR-scoped issues are at 0 and the quality gate passes | high | Sonar analysis of `01971d4` (2026-08-28T00:06Z) · PR #441 checks |

## Remaining Work / Follow-up

- Operator: confirm or reject the 25 deviation records (`devague deviate --list`; d16 and d25 are marked risky) — the records are the ground truth this summary quotes
- Operator: merge PR #441 (human gate 3) — checks green, 0 unresolved threads, Sonar 0 open
- #437 — re-adopt the prompt sections one at a time under measurement (`COLLEAGUE_PROMPT_VARIANT=qwen` is opt-in today)
- #421 — the acting-seat thinking-effort arm: the other lever that moves wall-clock on this model
- #438 — stall recovery: guard gap on the blocking-fallback path (r11), retry-or-resume on a guard trip, disable backpressure's timeout self-raise when guards are armed, ignore SSE keepalives as activity
- lobes-cli#220 — gateway leaves streamed completions hanging (5 of 15 game runs; the rig's dominant failure); proxied advert `ready:false` / context mismatch; reranker calibration; unauthenticated `/tokenize` bursts from the resident
- #439 — per-seat effort on associate (scout off / distill low), thinking continuity (r8), memory arming in measurement repos
- #435 — delegation: cortex never hands over on the measured briefs (r9) — document, adjust, do not force
- #436 — associate drives WebGlass as the web scout (own arc)
- r4 / r6 — microcompaction step-index ordinals drift after head windowing; the escalation retry runs outside the recovery ladder (found by dogfood review `e9ab75938688`)
- r12 — an `incomplete` run's isolation worktree is reaped with its uncommitted edits, so `work --continue` restores the transcript but not the files: commit WIP to the `colleague/<id>` branch before teardown
- d4 / d17 / d23 (needs-follow-up) — the ratchet forces every future change into new modules; the legacy knob does not reach plan-mode's raw `SCHEMAS`; the byte-identical proof does not cover `read_file`'s additive schema params
- c28 not met — a clean rerun of the game brief after #438 and lobes-cli#220 land, with the temperature arm at n ≥ 3

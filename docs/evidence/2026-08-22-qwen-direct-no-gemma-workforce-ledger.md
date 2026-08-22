# Workforce ledger — qwen-direct-no-gemma (2026-08-22)

Measured facts only, one row per task per tick; recorded by the integrator on a
30-minute loop while the plan `docs/plans/2026-08-22-qwen-direct-no-gemma.md`
is built by colleague children (`ask-colleague write --apply`, cortex
`unsloth/Qwen3.8-27B-NVFP4` via lobes, effort medium, `--max-steps 40`,
`COLLEAGUE_TIMEOUT=300`, cap 2 concurrent).

**Baseline (TDD before-gate, HEAD `58b3fc0`):** `uv run pytest -n auto` →
9105 passed, 3 failed (exactly the #422 env-dependent lobes-unarmed tests), 23 skipped, 22.6 s.

**Pre-build lens record:** explores on code finished 2/2 (graded 4, 4); the two
spec reviews + the planner explore stalled 3/3 after reading the spec-md
(silent synthesis turn, heartbeats stopped, 300 s timeout not cut) — plan risk r5.

## Ticks

| tick (local) | task | state | steps | dispatch→now | stalls / resumes / deviations | tests before → after | grade / review | notes |
|---|---|---|---|---|---|---|---|---|
| 09:57 | t1 | running (pid 2466954) | 14 | started 09:48:22 | — | baseline 9105/3 → pending | — | reading the 4 target test files by range |
| 09:57 | t2 | running (pid 2467123) | 20 | started 09:48:27 | — | baseline 9105/3 → pending | — | reading session.py by range (_talk_senses, _run_frontdoor) |
| 09:57 | t5,t6,t8 | queued (cap 2) | — | — | — | — | — | dispatch after t1/t2 land |
| 09:57 | t3,t9 / t4 / t7 / t10 / t11 | waves 2–6 | — | — | — | — | — | blocked on deps |
| 10:14 | t1 | running | 33 | 09:41 → (33 min) | last tool 10:07:49 (edit_file tests/test_config_lobes.py), then a silent model turn 6.5 min so far | baseline → pending | — | edits landed in 4 test files + config.py per feed |
| 10:14 | t2 | running, pre-finish gates | 38 | 09:41 → (33 min) | none; the test-integrity reviewer child ran (5 steps, `finish Reviewed flagged symbol _talk_lane_enabled`) | baseline → pending | — | session.py edited at step 27; now in lint/test-integrity/affected-tests gates |

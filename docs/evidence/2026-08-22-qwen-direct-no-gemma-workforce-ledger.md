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
| 10:27 | t2 | **merged** e7a4eb0 (branch colleague/29e08f89d9e6) | 42 (35 + 5 test-integrity reviewer child) | 09:41 → 10:18 (37 min) | none; honest finish | 32 → 34 on the 3 files; full suite 9106/4 → ratchet fix → 9114/3 (baseline) | grade 4; review pending (wave batch) | merge grew session.py 4029→4052 → tests/test_file_length_ratchet.py FAILED; integrator extracted _act_*/_CONFIG_ACTIONS (115 lines) to _session_actions.py (d759050, deviation d1); session.py 3945 |
| 10:27 | t1 | SIGTERM'd at 10:22 after 15-min silent turn, **resumed** (flight 5cbbb1dc8e07, pid 2671321) | 33 at cut | 09:41 → cut 10:22 | 1 stall→resume (deviation d2): stderr showed backpressure escalation (turns avg 356 s, timeout raised ×2 to 600 s) — a long legit request, not a hang; salvaged artifact status=interrupted | pending | — | continuation carries the 33 prior steps |
| 10:27 | t5 | running (pid 2667515) | 0 | 10:21 → (6 min) | first model turn not yet back (GPU shared with t1 resume) | pending | — | — |
| 10:27 | t6,t8 | queued (cap 2) | — | — | — | — | — | — |
| 10:45 | t1 | **merged** 93f4988 (+ follow-through b07fbbe) | 33 colleague + integrator finish | 09:41 → 10:43 (62 min; colleague 41 min, integrator 21 min) | stall 1 → resume (d2); the continuation sat 15 min in one socket read with 0 steps (the #409 shape) → stall 2 → integrator finished from the SIGTERM WIP commit 5988f98 (config.py +78, test_config_lobes.py +68) | 4 files 117/1 → 120/1 (the 1 = #422); full suite 8 failed post-merge → 3 (baseline) after: ratchet (config.py 4394 > 4358 → compacted to 4351) + 4 discovery-by-default pins flipped (eval_mode ×2, worker, voice_config) | grade pending; colleague's WIP design was correct (lobes sentinel on both rungs); integrator simplified to `resolved.model == "lobes"` | deviation d2 extended: 2 stalls → integrator |
| 10:45 | t5 | SIGTERM'd 10:42 after 15-min silent turn at step 11 (last read: oilcheck/provider.py — off the brief's files); resume attempt 1 REFUSED (dirty tree during integrator edits) → re-resumed now | 11 at cut | 10:21 → cut 10:42 | stall 1 → resume | pending | — | — |
| 10:45 | t6 | running (pid 2738082) | 25 | 10:42 → | none | pending | — | step 19 grepped headings of the spec-md (head -4 only) |
| 10:45 | t6 | running (pid 2738082) | 31 | 10:42 → (3 min of run; dispatched 10:42 after t1 freed the slot) | none; last tool 10:44:38 | pending | — | reading work.py flag registration by range |
| 10:45 | t5 | resume attempt 2 running (pid 2837090, flight 7502171211a5) | 0 | re-resumed 10:44 | — | pending | — | continuation carries 11 prior steps |
| 11:05 | t5 | **merged** 34d0bbc (integrator) | 11 colleague + integrator | 10:21 → 11:00 (39 min; colleague 21 min incl. 15-min silent turn, integrator 18 min) | stall 1 → resume REFUSED (dirty tree) → resume 2 sat 10 min at 0 steps → stall 2 → integrator (d3) | affected files 56/3 → 56/3 (+4 new tests in tests/test_cli_not_consumed.py) | colleague's 11 steps read oilcheck (off-brief); no grade (no deliverable) | not-consumed lines on config show + lobes show + `--json not_consumed`; helpers later moved to _listing.py under the ratchet |
| 11:05 | t6 | **merged** d244f5c + follow-through (integrator) | 44 colleague (0 edits) + integrator | 10:42 → 11:05 (23 min colleague wasted, 18 min integrator) | colleague budget-exhausted reading (work.py, config.py, spec-md headings), killed at step 44 in a 4-min silent turn (d3) | full suite 9133/4 → after boundary fix: pending full rerun | colleague graded 1; integrator: _listing.py (pure renderers), --model/--effort nargs=?, 6 tests | two ratchet hits fixed by compaction (work.py 2879→2849, cli/config 223→177, cli/lobes 266→253, effort.py 300→274); apply_operator_effort moved into effort.py (thinking-effort boundary test) |
| 11:05 | t8 | running (pid 2855873) | 6 | 10:50 → | last tool 11:02:07 (read docs/plans/… plan-md — a spec-shaped file; stall risk r5) | pending | — | 0 edits yet |
| 11:14 | t8 | running (pid 2855873) | 9 | 10:50 → (24 min) | none recorded; the silent gap after the plan-md read resolved itself (step 7 at ~11:10: reading the 7 feature docs; step 8 markdownlint config) | pending | — | 0 edits yet |
| 11:14 | t3 | running (pid 2961577, worktree iso-b6dd1ffaf0e6) | 22 | 11:07 → (7 min) | none | pending | — | reading test_session_cockpit + lobes._RESOLVED_ROLES; 0 edits yet |
| 11:14 | t9 | queued (cap 2) | — | — | — | — | — | unblocked (t1 merged) |
| 11:14 | suite | — | — | — | — | full suite at HEAD eb12b2c: 9134 passed / 3 failed (#422 trio) / 23 skipped | — | baseline preserved after t1, t2, t5, t6 |

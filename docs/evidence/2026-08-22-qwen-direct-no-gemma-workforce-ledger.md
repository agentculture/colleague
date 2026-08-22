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
| 09:57 | t2 | running (pid 2467123) | 20 | started 09:48:27 | — | baseline 9105/3 → pending | — | reading session.py by range (`_talk_senses`, `_run_frontdoor`) |
| 09:57 | t5,t6,t8 | queued (cap 2) | — | — | — | — | — | dispatch after t1/t2 land |
| 09:57 | t3,t9 / t4 / t7 / t10 / t11 | waves 2–6 | — | — | — | — | — | blocked on deps |
| 10:14 | t1 | running | 33 | 09:41 → (33 min) | last tool 10:07:49 (edit_file tests/test_config_lobes.py), then a silent model turn 6.5 min so far | baseline → pending | — | edits landed in 4 test files + config.py per feed |
| 10:14 | t2 | running, pre-finish gates | 38 | 09:41 → (33 min) | none; the test-integrity reviewer child ran (5 steps, `finish Reviewed flagged symbol _talk_lane_enabled`) | baseline → pending | — | session.py edited at step 27; now in lint/test-integrity/affected-tests gates |
| 10:27 | t2 | **merged** e7a4eb0 (branch colleague/29e08f89d9e6) | 42 (35 + 5 test-integrity reviewer child) | 09:41 → 10:18 (37 min) | none; honest finish | 32 → 34 on the 3 files; full suite 9106/4 → ratchet fix → 9114/3 (baseline) | grade 4; review pending (wave batch) | merge grew session.py 4029→4052 → tests/test_file_length_ratchet.py FAILED; integrator extracted `_act_`*/`_CONFIG_ACTIONS` (115 lines) to `_session_actions.py` (d759050, deviation d1); session.py 3945 |
| 10:27 | t1 | SIGTERM'd at 10:22 after 15-min silent turn, **resumed** (flight 5cbbb1dc8e07, pid 2671321) | 33 at cut | 09:41 → cut 10:22 | 1 stall→resume (deviation d2): stderr showed backpressure escalation (turns avg 356 s, timeout raised ×2 to 600 s) — a long legit request, not a hang; salvaged artifact status=interrupted | pending | — | continuation carries the 33 prior steps |
| 10:27 | t5 | running (pid 2667515) | 0 | 10:21 → (6 min) | first model turn not yet back (GPU shared with t1 resume) | pending | — | — |
| 10:27 | t6,t8 | queued (cap 2) | — | — | — | — | — | — |
| 10:45 | t1 | **merged** 93f4988 (+ follow-through b07fbbe) | 33 colleague + integrator finish | 09:41 → 10:43 (62 min; colleague 41 min, integrator 21 min) | stall 1 → resume (d2); the continuation sat 15 min in one socket read with 0 steps (the #409 shape) → stall 2 → integrator finished from the SIGTERM WIP commit 5988f98 (config.py +78, test_config_lobes.py +68) | 4 files 117/1 → 120/1 (the 1 = #422); full suite 8 failed post-merge → 3 (baseline) after: ratchet (config.py 4394 > 4358 → compacted to 4351) + 4 discovery-by-default pins flipped (eval_mode ×2, worker, voice_config) | grade pending; colleague's WIP design was correct (lobes sentinel on both rungs); integrator simplified to `resolved.model == "lobes"` | deviation d2 extended: 2 stalls → integrator |
| 10:45 | t5 | SIGTERM'd 10:42 after 15-min silent turn at step 11 (last read: oilcheck/provider.py — off the brief's files); resume attempt 1 REFUSED (dirty tree during integrator edits) → re-resumed now | 11 at cut | 10:21 → cut 10:42 | stall 1 → resume | pending | — | — |
| 10:45 | t6 | running (pid 2738082) | 25 | 10:42 → | none | pending | — | step 19 grepped headings of the spec-md (head -4 only) |
| 10:45 | t6 | running (pid 2738082) | 31 | 10:42 → (3 min of run; dispatched 10:42 after t1 freed the slot) | none; last tool 10:44:38 | pending | — | reading work.py flag registration by range |
| 10:45 | t5 | resume attempt 2 running (pid 2837090, flight 7502171211a5) | 0 | re-resumed 10:44 | — | pending | — | continuation carries 11 prior steps |
| 11:05 | t5 | **merged** 34d0bbc (integrator) | 11 colleague + integrator | 10:21 → 11:00 (39 min; colleague 21 min incl. 15-min silent turn, integrator 18 min) | stall 1 → resume REFUSED (dirty tree) → resume 2 sat 10 min at 0 steps → stall 2 → integrator (d3) | affected files 56/3 → 56/3 (+4 new tests in tests/test_cli_not_consumed.py) | colleague's 11 steps read oilcheck (off-brief); no grade (no deliverable) | not-consumed lines on config show + lobes show + `--json not_consumed`; helpers later moved to `_listing.py` under the ratchet |
| 11:05 | t6 | **merged** d244f5c + follow-through (integrator) | 44 colleague (0 edits) + integrator | 10:42 → 11:05 (23 min colleague wasted, 18 min integrator) | colleague budget-exhausted reading (work.py, config.py, spec-md headings), killed at step 44 in a 4-min silent turn (d3) | full suite 9133/4 → after boundary fix: pending full rerun | colleague graded 1; integrator: `_listing.py` (pure renderers), --model/--effort nargs=?, 6 tests | two ratchet hits fixed by compaction (work.py 2879→2849, cli/config 223→177, cli/lobes 266→253, effort.py 300→274); apply_operator_effort moved into effort.py (thinking-effort boundary test) |
| 11:05 | t8 | running (pid 2855873) | 6 | 10:50 → | last tool 11:02:07 (read docs/plans/… plan-md — a spec-shaped file; stall risk r5) | pending | — | 0 edits yet |
| 11:14 | t8 | running (pid 2855873) | 9 | 10:50 → (24 min) | none recorded; the silent gap after the plan-md read resolved itself (step 7 at ~11:10: reading the 7 feature docs; step 8 markdownlint config) | pending | — | 0 edits yet |
| 11:14 | t3 | running (pid 2961577, worktree iso-b6dd1ffaf0e6) | 22 | 11:07 → (7 min) | none | pending | — | reading test_session_cockpit + lobes.`_RESOLVED_ROLES`; 0 edits yet |
| 11:14 | t9 | queued (cap 2) | — | — | — | — | — | unblocked (t1 merged) |
| 11:14 | suite | — | — | — | — | full suite at HEAD eb12b2c: 9134 passed / 3 failed (#422 trio) / 23 skipped | — | baseline preserved after t1, t2, t5, t6 |
| 11:42 | t3 | **merged** 0fbe90e (branch colleague/b6dd1ffaf0e6) | 57 (budget 40 + continue nudges) | 11:07 → 11:38 (31 min) | none; honest finish ("nothing left undone") | 95 → 105 on touched files; full suite 9142/3 (baseline) | grade 5 | 8 new tests; /model no-arg listing + `min(window, current)` budget rule; session.py +8/−0 within ratchet |
| 11:42 | t9 | dispatched (pid 3122856) | 0 | 11:41 → | — | pending | — | — |
| 11:42 | t8 | running (pid 2855873) | 37 | 10:50 → (52 min) | silent since the step-14 markdownlint run (see mtime above) | pending | — | 16 edits landed |
| 11:58 | t8 | **merged** 6d078fb (integrator) | parent 9 steps + children ≈37 steps/16 edits (LOST) | 10:50 → 11:58 (68 min; colleague 55 min, integrator 13 min) | parent SIGTERM'd after a 15-min silent turn at step 9; its subagent children's 16 doc edits were reaped with it (#410 salvage = parent WIP only; artifact changed_files=[]); deviation d4 (needs-follow-up) | markdownlint 10 files 0 errors; acceptance grep: 0 unmarked lines; suite 9142/3 | no grade (no deliverable) | CLAUDE.md bullet + fifth convention change; 8 feature docs opt-in notes; new docs/features/qwen-direct.md |
| 11:58 | t9 | running (pid 3122856) | 14 | 11:41 → | none | pending | — | reading conftest/config loaders; 0 edits yet |
| 11:58 | t4 | dispatching now (dep t3 merged) | — | — | — | — | — | — |
| 11:48 | (correction) | — | — | — | the tick-8 rows above are stamped "11:58" but were written at ≈11:47 wall clock (the integrator estimated instead of reading the clock); subsequent ticks use `date` | — | — | — |
| 11:48 | t9 | running (pid 3122856) | 14 (+1 child started) | 11:41 → (7 min) | none; last tool 57 s ago (reading test_presence_pin_breaks + repo config) | pending | — | 0 edits yet |
| 11:48 | t4 | running (pid 3179655) | 0 | 11:47 → | first model turn | pending | — | — |
| 12:06 | t9 | **merged** 1b21696 (integrator) | 14 colleague (0 edits) + integrator | 11:41 → 12:06 (colleague 18 min incl. 15-min silent turn; integrator 12 min) | stall → SIGTERM (no child worktrees present) → integrator (d5) | 74 passed on the 5 target files; **full suite 9149 passed / 0 failed / 23 skipped** — the #422 trio fixed (hermetic --repo tmp_path) | colleague graded 1 | tests/test_single_model_default.py: one model on the default path, sentinel-only fallbacks (text guard), artifact has no senses key |
| 12:06 | t4 | running (pid 3179655) | 40 | 11:47 → | none; 0 edits at the 40-step budget (continue nudges may extend) | pending | — | exploring tests for the vllm engine import pattern |
| 12:14 | t4 | **merged** 710625e (branch colleague/d71b3fb02989, WIP committed on stop + integrator 1-line lint fix) | 40+ (budget exhausted, honest finish) | 11:47 → 12:14 (≈55 min colleague, 5 min integrator) | none | 97 → 111 on touched files; **full suite 9160 passed / 0 failed** | grade 4 | /effort no-arg table via resolve_effort/effort_of, switch via effort.apply_operator_effort (session-only), 11 tests; session.py +7 within ratchet |
| 12:14 | t7 | dispatched (pid 3316332) | 0 | 12:14 → | — | pending | — | voice/realtime honest 'senses not armed' line |
| 12:16 | t10 (integrator) | check 1 default arm DONE: piped session "what model are you running on?" → rc 0, wall 12.45 s, 2 requests, both to unsloth/Qwen3.8-27B-NVFP4 (0 non-cortex); senses-opted-in comparison arm running | — | — | — | checks 2–4 green (9160/0; #422 trio on this lobes-armed checkout; config show + lobes show + bare --model/--effort print the not-consumed lines/tables — evidence dir t10-evidence) | — | shell still carries CONVERTIBLE_MODEL=Qwen3.6 (stale pin refresh fires, harmless); unset for the session runs |
| 12:16 | t7 | running (pid 3316332) | 0 | 12:05 → | first model turn (err written 91 s ago) | pending | — | — |
| 12:17 | (correction) | — | — | — | t7's child process started 12:14:12 (ps lstart), not 12:05 as the tick-11/12 rows say — the integrator again estimated; speed columns for t7 use 12:14 | — | — | — |
| 12:17 | t10 | **done** 0c412f1 (integrator, as planned) | — | 12:08 → 12:17 (9 min) | none | all four c24 checks green; h17 measured 1.83× (≤ 2×) | — | docs/live-testing.md row 40 + docs/evidence/2026-08-22-qwen-direct-no-gemma-results.md |
| 12:17 | t7 | running (pid 3316332, started 12:14:12) | 0 | 12:14 → | first model turn | pending | — | — |
| 12:38 | t7 | **merged** 76a7108 (integrator) | 22 colleague (0 edits) + integrator | 12:14 → 12:38 (colleague 22 min incl. 15-min silent turn; integrator 8 min) | stall → SIGTERM (no child worktrees) → integrator (d6) | 67 passed on voice/realtime/ratchet files; full suite green (see line above) | colleague graded 1 | dormant lines for /voice, /speak, --voice (ANSI only); voice.py/realtime.py unchanged |
| 12:38 | waves | ALL code waves merged: t1 t2 t3 t4 t5 t6 t7 t8 t9 t10; t11 (version bump) next | — | plan dispatched 09:41 → 12:38 | colleague delivered t2, t3, t4 (+ t1's config.py core); integrator finished t1 and wrote t5, t6, t7, t8, t9, t10 after stalls/budget exhaustion (d1–d6) | — | colleague grades: t2 4, t3 5, t4 4, t1 3, t6 1, t9 1, t7 1 | — |
| 12:39 | t11 | **done** 72007d4 (integrator, version-bump skill) | — | — | — | 1.62.1 → 1.63.0; CHANGELOG entry; CI gates green locally (black/isort/flake8/bandit/teken doctor --strict) | — | — |
| 12:39 | review (r1) | colleague code review of main...HEAD under colleague/ running (pid 3406146, --effort low, 25 steps) | 0 so far | 12:39 → | — | — | findings fold in as a follow-up commit on the PR | — |
| 12:42 | PR | **opened** https://github.com/agentculture/colleague/pull/426 (devex pr open, 49 commits) | — | — | — | CI: version-check pass, GitGuardian pass, lint FAIL (triaging), test pending | Qodo + /agentic_review requested automatically | — |

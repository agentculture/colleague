# Delivery Summary — prove self-learning (#387)

plan: `prove-self-learning-387` · run: `partial` · date: `2026-08-07`
baseline: `devague summary skeleton`

## Intent

Execute the #387 proof plan: two falsifiable experiments measuring whether
colleague's self-learning pipeline changes behavior — the self-taught
warm-vs-cold (experiment 1) and the #378 correction-diff ablation over the
Transformer game benchmark (experiment 2) — with every outcome, supporting
or falsifying, recorded in the live-testing ledger. Executed as a 9-task /
5-wave plan by Fable as operator/integrator with colleague (35B worker) as
both workforce and experimental subject, per the operator-approved split.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — t1: Preconditions + one clean baseline run on the 35B worker
- `t2` — t2: Verify the webglass usable-bar (the 7 items of webglass-cli#9) and pin consumption to `run_command`
- `t3` — t3: Experiment-1 setup — throwaway operator repo, fail-cold task, cortex-pinned distill author
- `t4` — t4: Experiment-1 execution — cold fail, distill, gated warm rerun, WorkStats comparison
- `t5` — t5: Author the Transformer game plan + pre-commit the integrator correction rules
- `t6` — t6: Scaffold the two arm repos identically from the game template
- `t7` — t7: Run the ON arm first — N game tasks, learning armed
- `t8` — t8: Run the OFF arm — the identical task list with `COLLEAGUE_MEMORY`=0
- `t9` — t9: Metrics, adjudication, recording — rows 32/33, delivery-claim flips, close #387

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | Baseline clean on the 35B worker (`90dc348dea06`: 14 turns / 66.3s / status ok, tests pass on the branch; WorkStats names `unsloth/Qwen3.6-35B-A3B-NVFP4`); rig-quiet recorded (serving fleet + idle mesh resident, zero active loops); stale `CONVERTIBLE_MODEL=27B` env pin caught and overridden |
| `t2` | delivered | Usable-bar checked: webglass verbs pre-implementation (`page`/`session` = invalid choice) → game lane HELD per plan risk r1; status posted (webglass-cli#9 comment); consumption stays `run_command`-only, zero colleague code diff |
| `t3` | delivered | `pipeline-sim` fixture: colleague(35B) wrote all 18 files to spec in an eidetic-less staging repo (graded 5/5); assembled with cold store + cortex distill pin (`wins: deepthink` verified); grep-resistant hidden fact; task brief committed; hardened to v2 (config-file indirection + third decoy) at shared base `8c3fdf7` after attempts #1–#2 proved the v1 task below the 35B's cold competence |
| `t4` | delivered | The measured pair ran with ALL c26 gates enforced — outcome **FALSIFYING per the confirmed c20 bar** (ledger row 34): COLD `bf3c9b411a91` budget-exhausted (5 turns / 13.4s / no deliverable, honest-cold verified) → rung-2 distilled a validated `origin=model` process lesson → WARM `f19a83e1f7bb` with the lesson verifiably injected (recalled 3, +891 chars) produced an IDENTICAL step trace (5 turns / 15.6s / no deliverable). Four prior attempts discarded with artifacts retained (see drift) |
| `t5` | delivered | Transformer template repo (`~/git/transformer`): devague frame + 8-task plan (browser-verifiable acceptance, standing agent-access invariant) exported + committed `a6bd8f7`; correction rules FROZEN (blob `0438ec4`); colleague dogfood review (graded 4/5) caught 2 missing deps + the KeyX collision → 3 operator-approved amendments re-exported at `c30ca2c` |
| `t6` | blocked | Arms need the webglass usable-bar (t2 hold, plan risk r1) — webglass M0–M2 committed but not yet shipped |
| `t7` | blocked | Downstream of t6 (same hold) |
| `t8` | blocked | Downstream of t7 (same hold) |
| `t9` | partial | Experiment-1 evidence fully recorded: ledger row 34 + row-32 benchmark-exists note + the memory.md self-taught counterpoint (commit `d6f1709`); result posted to #387; full suite green (7870 passed). The #378/#377 delivery-claim flips did NOT happen — those claims stay honestly `unverified` until the held arms run; #387 stays OPEN for experiment 2 |

## Mid-work Decisions

No `devague deviate` records were needed — the two in-flight departures fell
inside lanes the confirmed spec pre-authorized. Captured directly:

- The c7 boundary's recorded-fix lane was exercised once: the eidetic-0.13
  recall envelope bug (every armed run silently `recalled=0`) was fixed as a
  separately-recorded commit naming the defect (`163574d`) + a regression
  test — without it the warm arm was structurally vacuous, for both arms
  equally. Issue #389 tracks the residual (doctor churn guard).
- The c27 assumption's adjust-and-record lane was exercised three times: the
  fail-cold task was re-sized (cap 10 → 5 → repo hardening + cap 6 → cap 4)
  until the cold leg failed by its own accounting; every discarded attempt
  retained its artifact and grade.
- The game-plan amendments (2 deps, KeyE binding, measurable jump arc) were
  applied pre-arms with explicit operator approval — the correction-rules
  freeze governs the arms and was untouched.
- Integrator error, recorded: attempt #2's store record was deleted on a
  misread (its output looked like a success; its status was `incomplete`)
  BEFORE inspection — a legitimate rung-1 failure record and its lesson were
  destroyed. The discard itself was recorded either way; the misread is the
  error. The final measured pair post-dates and supersedes it.
- Dispatch-runtime discovery: `uv run` from inside the fixture repo resolves
  the INSTALLED colleague (1.56.0, no fix), not the checkout — attempts
  #3/#4/warm-1 ran on the stale runtime. The measured pair was rerun
  same-runtime from the checkout (the known stale-PATH gotcha, now with a
  concrete failure signature).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t4` | Ran to a valid measured pair only on the 5th cold attempt: #1 `c8d6a6f88577` (too easy at cap 10), #2 `41a658e6b757` (incomplete-but-correct; store record lost to the integrator misread), #3 `6469dfdcda19` (child-race store contamination + turn-batching beat cap 6), warm-1 `18ef817069be` (vacuous — recalled 0 on the stale CLI, aborted per h17) — all retained as evidence; the c27/h18 adjust-and-record lane covered each | acceptable |
| `t4` (outcome) | The experiment itself returned FALSIFYING — the self-taught process-level lesson did not change step-capped behavior (vs the hand-seeded answer-level 5×). Recorded unspun per c20/h13; lesson specificity named as the operative variable | acceptable |
| `t6`–`t8` | webglass M0–M2 not yet shipped — the plan's own risk r1 gate (t2) fired exactly as designed; arms hold, benchmark committed and ready | needs-follow-up |
| `t9` | Partial by dependency: rows 32/33 delivery-claim flips require the held arms; experiment-1's row 34 + docs landed; #387 stays open | needs-follow-up |

## Evidence

- tests: full suite `uv run pytest -n auto` — **7870 passed, 20 skipped, 0 failed** (post-fix)
- tests: `tests/test_memory.py::TestRecallHappyPath::test_recall_parses_eidetic_013_envelope` — pass (the regression pin)
- commits: `f2bca91..d6f1709` on `spec/prove-self-learning-387` (spec, challenge re-export, plan, recall fix, evidence docs)
- template repo: `~/git/transformer` commits `a6bd8f7`, `c30ca2c` (plan + frozen rules blob `0438ec4`)
- artifacts: `pipeline-sim/.colleague/` — `bf3c9b411a91` (cold), `f19a83e1f7bb` (warm), + 4 discarded attempts with grades
- ledger: `docs/live-testing.md` row 34 (new), row 32 (updated)
- issues/PRs: #387 (result comment), #388 (ellipsis-lesson hole, filed), #389 (recall envelope, filed+fixed), webglass-cli#9 (consumer brief + fold-in ack + hold status)
- grades: 6 work-item grades this session (5/5 ×2, 4/5 ×1, 2/5 ×2 honest-failure grades, plus the baseline 5/5) — teacher data for the arc

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| The healthy-backend precondition held: a clean 35B-worker baseline preceded every measured run | high | artifact `90dc348dea06` · rig-quiet record in row 34 |
| Experiment 1 ran end-to-end self-taught — nothing hand-seeded, every c26 gate enforced | high | ledger row 34 · marker `done` · store record `distill: validated, origin: model` · warm `recalled=3` |
| Experiment 1's outcome FALSIFIES the behavioral claim for process-level lessons at a tight cap (n=1 pair) | high | WorkStats verbatim: 5/13.4s/0-deliverable vs 5/15.6s/0-deliverable, identical traces · row 34 |
| The recall pipeline was silently broken for every armed run before this session | high | #389 · fix `163574d` · pre-fix artifacts showing `recalled: 0` against matching stores |
| The #378 ablation benchmark exists and is challenge-hardened, ready for the arms | high | `~/git/transformer` `c30ca2c` · frozen rules `0438ec4` · row 32 note |
| Learning ON reduces integrator-correction volume (#378) | unverified | arms held on webglass — not claimed |
| Recall measurably reduces strive attempts-to-success (#377) | unverified | NEBULA benchmark still pending — not claimed |

## Remaining Work / Follow-up

- `t6`–`t8`: run the two game arms when webglass ships its M0–M2 slice
  (webglass-cli#9 thread is the signal; the seven-item bar re-runs first) —
  then flip the #378 delivery claim per the row-32 recipe and close #387.
- #377/row 33: unchanged — needs the NEBULA benchmark + rig hours.
- #388: harden `lessons.validate_lesson` against placeholder ellipses.
- #389 residual: the doctor recall round-trip churn guard.
- The arc's next-delta from the falsifying result: distillation should
  capture *task-level* substance (what was learned about the territory), not
  only process morals — the row-34 contrast is the design brief.
- PR gate next (cicd): spec + plan + fix + evidence docs on
  `spec/prove-self-learning-387`; Qodo starts 0 — re-poll; Sonar triage.

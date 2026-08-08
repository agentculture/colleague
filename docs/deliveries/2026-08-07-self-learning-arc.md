# Delivery Summary — self-learning arc

plan: `self-learning-arc` · run: `complete` · date: `2026-08-07`
baseline: `devague summary skeleton`

## Intent

Colleague learns from its own runs: rung-2 lesson distillation on the
remember-after seam, repo-anchored code-lessons grown from correction diffs
and gate fixes, and the bounded `strive` necessity loop — the ninth
sanctioned increment (spec `docs/specs/2026-08-07-self-learning-arc.md`),
executed as 19 tasks across 5 dependency waves by a mixed workforce
(colleague 27B/35B, sonnet subagents, Fable as integrator), landing v1.56.0
on `spec/self-learning-arc`.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Rung-1 completion: fold lint/test-integrity/affected-tests substance into `compose_lesson_text`
- `t2` — Distillation lesson schema + strict validator (pure module)
- `t3` — Feedback author provenance: operator vs cortex records side by side
- `t4` — Flywheel exclusion filter: cortex-authored records out of export by default
- `t5` — Handoff persists the colleague/`<id>` branch tip SHA onto TaskResult
- `t6` — Plan-mode raw-capture on total claim-parse failure (#376 diagnosability)
- `t7` — Correction-diff capture module: tip vs merge commit, scoped to changed files
- `t8` — Code-lesson record type + builders
- `t9` — Rung-2 seam in the loop: distillation pass + attempts/validated counters + independent kill switch
- `t10` — Distillation author-by-role + bounded observable background child
- `t11` — Doctor surfaces the distillation alive-counter
- `t12` — Seamless auto-trigger lane: grade-time + colleague-action capture, observable
- `t13` — Strive core: verb + episode driver + four enforced phases + hypothesis ledger
- `t14` — Strive measure execution: approval-gated, episode-worktree cwd
- `t15` — 35B plan-grammar fix: the claim proposal parses on the worker model (#376 fix)
- `t16` — INTEGRATION: wire the lanes end-to-end + behavior-level e2e gate
- `t17` — Live proofs + ablations: distillation on the rig, #378 correction ablation, #377 NEBULA strive ablation
- `t18` — Docs + ninth-increment scope line + version bump
- `t19` — Boundary + invariant pins: verbs allow-list, remember/recall invariants

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | colleague(35B): `compose_lesson_text` folds all three report kinds, byte-identity pinned; merged unmodified (`d21b7ce`) |
| `t2` | delivered | colleague(35B): `colleague/lessons.py` refuse-whole validator + 34 tests; integrator dropped its out-of-scope version bump (`fc4a89a`) |
| `t3` | delivered | sonnet (per `d1`): author field, per-`(task_id, author)` sibling files, legacy back-compat, CLI `--author` (`2f1716f`) |
| `t4` | delivered | colleague(27B) + `--continue` + integrator finish: export defaults operator-only, explicit `Flag` for `--include-cortex-authored`, deduped test block (`3a1e1e0`) |
| `t5` | delivered | sonnet: `TaskResult.tip_sha` omit-when-None, populated at all three handoff commit sites (`01e6cd8`) |
| `t6` | delivered | sonnet: raw proposal text persisted under `.colleague/plan/` before the ValueError; message stable (`33dbc36`) |
| `t7` | delivered | colleague(27B): `colleague/correction.py` (gh mergeCommit, file-scoped diff, honest no-diff records) + 400-line suite; zero integrator corrections (`6378cfe`) |
| `t8` | delivered | colleague(27B), clean ok finish: code-lesson builders, distinct id namespace, bounded confidence (`acae06a`) |
| `t9` | delivered | Fable: injectable `distill_fn` seam, schema-gated lesson fold, `distill_attempts`/`distill_validated`, `COLLEAGUE_MEMORY_DISTILL` kill switch (`0be77c9`) |
| `t10` | delivered | colleague(27B): `colleague/distill.py` scaffolding (author-by-role, markers, detach, upsert) + 28 tests; the child's main was missing — built by the t17 probe follow-through (see drift) (`e535c40`, `1280be0`) |
| `t11` | delivered | colleague(27B), clean ok finish: `colleague/oilcheck/distillation.py` alive-counter group; integrator later added artifact-side counting (h23 hole) (`0efa6d1`) |
| `t12` | delivered | sonnet: shared `maybe_capture_correction`, grade-time + work-start triggers both fully wired, observable sidecar, never blocks the grade (`9d42d02`) |
| `t13` | delivered | colleague(27B), write-first retry after a thor-killed first attempt: `strive.py` + CLI + ledger + novelty stall + chain pin; integrator flake8 finish (`8fea0c5`) |
| `t14` | delivered | colleague(27B): measure through the approval gate, episode-worktree cwd pinned (`f51f934`) |
| `t15` | delivered | Fable, live: the failing invocation reran to a parsed CONVERGED frame (5 items, exit 0) — no code change needed beyond t6's seam; ledger row 30 |
| `t16` | delivered | Fable: author injection via `from_config`, detached-vs-refused semantics (the t9/t10 composition seam), strive's REAL episode dispatch, `tests/test_e2e_selflearning.py` behavior gate (`0641...` in range) |
| `t17` | delivered | Fable, live 4-round probe: 3 integration defects found + fixed (dead child verb, artifact race, doctor marker-blindness); pipeline proven end-to-end (`status: done`, lesson upserted, doctor `4 attempts, 1 validated`); ablation legs recorded as executable-pending recipes per the task's own acceptance (ledger rows 31–33) (`1280be0`) |
| `t18` | delivered | colleague(27B) clean ok finish (feature doc) + Fable (CLAUDE.md ninth increment, memory.md, CHANGELOG, v1.56.0) (`dda058e`, t18-operator commit) |
| `t19` | delivered | colleague(27B): 365-line invariants suite + boundary pins; work complete at the meta-finish cut (`130fe8d`) |

## Mid-work Decisions

- `d1` — t3 reassigned colleague(35B)→sonnet after two thor 503 mid-run
  deaths; remaining colleague dispatches pinned to the local 27B until thor
  proves stable — the peer hosting the 35B went 503 mid-run twice (steps 9
  and 14), both attempts zero-write (recorded via `/deviate`, issue #385;
  record still `proposed`, awaiting operator confirm).
- Colleague concurrency was serialized to 1 loop during the thor incident,
  then restored to the memory-calibrated 2-loop cap once dispatches moved to
  the local 27B — operational pacing, no plan-content change.
- `work --continue` was used for t4 per the operator's mid-run directive
  (prefer continuation over integrator takeover when substantive work
  remains); the continuation improved 5 red tests to 2, and the integrator
  finished the rest.
- t16 reconciled a real composition mismatch the plan didn't foresee: t9's
  sync seam semantics vs t10's detached-child design — resolved with the
  `distill: detached` marker state so the artifact's validated count stays
  honest-at-return (no deviation record; captured here).
- The eidetic store conflicted twice at merge time (both sides mutating the
  committed jsonl); resolved by id-level union, no lesson lost — a recurring
  operational cost of the in-repo store, not plan drift.
- t2's out-of-scope version bump was dropped at merge; t18 owned the bump
  (recorded in t2's grade as correction-diff teacher data).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t3` (`d1`) | the peer hosting the 35B (thor) went 503 mid-run twice (attempt 1 step 9, attempt 2 step 14), both attempts zero-write; the approved split assigned t3 to colleague on the 35B | acceptable |
| `t10` | shipped scaffolding-complete but the child entry (`python -m colleague.distill` main + completion call) did not exist — green tests could not catch it; built by Fable after the t17 live probe exposed it (rounds 1–2: dead verb, then artifact race) | needs-follow-up (closed within the run — the fixes are in `1280be0`; follow-up is upstream: the muse lingering-advert that 404'd round 3) |
| `t17` | the #378 and #377 ablations were recorded as executable-pending recipes instead of run — rig hours and the NEBULA benchmark repo were not available within the arc; the task's own acceptance names this fallback explicitly | needs-follow-up |

No other task diverged: the task-by-task accounting above is 19/19 delivered
against their confirmed acceptance criteria.

## Evidence

- tests: full suite `uv run pytest -n auto` — **7865 passed, 20 skipped, 0 failed** (post-t17)
- tests: `tests/test_e2e_selflearning.py` (6 behavior e2e, incl. the teaching
  loop: a failed run's lesson reaches run 2's first turn verbatim) — pass
- lint: `black --check colleague tests` — 602 files unchanged; `flake8` — clean;
  `bandit -c pyproject.toml -r colleague` — clean
- commits: `5ed12055..1280be0` (45 commits on `spec/self-learning-arc`)
- live: `docs/live-testing.md` rows 30–33 (the #376 rerun, the 4-round
  distillation probe, the two pending ablation recipes)
- deviations: `devague deviate --list` → `d1` (proposed)
- grades: 14 work-item grades in `.colleague/*.feedback.json` (5/5 ×4, 4/5 ×6,
  3/5 ×2, infra-failure 1–2/5 ×3) — the arc's own teacher data
- issues: #385 (`deviate:` record), #384 (flywheel serving, parked), #383 (the
  umbrella worklist)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A failed run's record now carries its failure substance verbatim and teaches the next run | high | test `tests/test_e2e_selflearning.py::test_second_run_recalls_first_runs_lesson_verbatim` · live store record `work-lesson-c3667a57fe5d` |
| Rung-2 distillation works end-to-end on the live rig, anti-fabrication intact | high | ledger row 31 · live marker `status: done` + doctor `4 attempts, 1 validated` · no invalid lesson ever landed across 4 rounds |
| The 35B plan-mode parse failure (#376) no longer reproduces; raw capture stands as the net | high | ledger row 30 · `converged: True, plan items: 5, exit 0` |
| `strive` drives real episodes, approval-gated, with an honest ledger | high | `tests/test_e2e_selflearning.py::test_strive_cli_dispatch_runs_real_episode_in_worktree` · `tests/test_strive.py` (26) + `tests/test_strive_measure.py` |
| Cortex-authored feedback cannot silently become training data | high | `tests/test_feedback_export.py` (default-exclusion pins) |
| Learning ON reduces integrator-correction volume (#378) | **falsified** (2026-08-08 run) | ledger row 32: ON 57 vs OFF 38 correction lines on the full 8-task benchmark — equal-or-worse per the c20 bar; class-level transfer observed but the volume claim fails; evidence in docs/experiments/2026-08-08-prove-self-learning-387-arms/ |
| Recall measurably reduces strive attempts-to-success (#377) | unverified | ablation recorded as pending recipe (ledger row 33) — not claimed |

## Remaining Work / Follow-up

- `d1` awaits operator `devague deviate --confirm d1` (the record is
  `proposed`; issue #385 carries the evidence).
- The #378 correction ablation and #377 NEBULA strive ablation: run the
  recorded recipes (ledger rows 32–33) in a future session with rig hours —
  both success signals stay honestly `unverified` until then.
- The muse lingering-advert steered both the plan-mode deepthink proposal and
  the distillation author at an unserved model (404) — the degrade floors
  held, but the advert bug is upstream (lobes-cli; the known
  discovery-ignores-`ready` issue).
- The 27B zero-step collapse (#346) reproduced on all four probe runs
  (steps=0) — the probe's own distilled lesson names the pre-flight check
  idea; #346 stays open.
- Flywheel adapter serving is deliberately parked as #384.
- PR gate next: cicd PR → Qodo triage → SonarCloud iteration (this artifact
  is the review map).

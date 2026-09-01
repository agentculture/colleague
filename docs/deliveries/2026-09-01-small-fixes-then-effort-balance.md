# Delivery Summary — small-fixes-then-effort-balance

plan: `small-fixes-then-effort-balance` · run: `partial` · date: `2026-09-01`
baseline: `devague summary skeleton`

## Intent

Land the four validity/observability fixes (#480–#483) that came out of live-testing
rows 67/68, build the #484 effort-spike machinery dark behind an opt-in in the same
arc, prove the fixes on a live rerun of the row-67 failure shape, and run the
pre-registered A/B/C measurement arms that decide #484's disposition. Executed as a
13-task / 6-wave workforce fan-out from the converged plan
`docs/plans/2026-09-01-small-fixes-then-effort-balance.md`, delivered on PR #486
(v1.75.0).

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Gate warnings on non-finished outcomes (#480, incl. test-integrity)
- `t2` — TaskResult.`task_text` recording (#481)
- `t3` — Importability check module (#482) with worktree resolution
- `t4` — Wire `delta_heartbeat` into the work path (#483)
- `t5` — Spike table + opt-in + drift boundary test
- `t6` — Wire importcheck into pre-finish on EVERY outcome + row-67 fixture
- `t7` — Continuation propagates the original brief
- `t8` — Pre-mutation decision barrier
- `t9` — Gate-failure escalation + fill-line spike wiring
- `t10` — Docs + the recorded invariant amendment
- `t11` — Byte-identical off-knob assertion suite
- `t12` — Live validation: row-67 rerun demonstrating all four fixes
- `t13` — A/B/C measurement arms + #484 disposition

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `affected-tests-failed` / `test-integrity-flagged` warnings on non-finished outcomes; new `loop_testgates_warnings.py` sibling (merge `d8e05b18`) |
| `t2` | delivered | `TaskResult.task_text` + `colleague/tasktext.py` (16KB cap, marker, on-by-default, off-knob), omit-when-None beside `prompt_digest` (merge `bd4771fa`) |
| `t3` | delivered | `colleague/importcheck.py` with the worktree-resolution anti-vacuous-pass proof; subprocess allow-list entry + 2 pinned mirrors (merge `b0076856`) |
| `t4` | delivered | `colleague/loop_deltaheartbeat.py` — arm at `ContextControls.from_config`, bind in `run()`; blocking-path gap documented (merge `7ce6417d`) |
| `t5` | delivered | `colleague/effortspikes.py` — pinned 3-point table, `COLLEAGUE_EFFORT_SPIKES` opt-in, `SpikeRecord`, drift boundary test (merge `51d082cf`) |
| `t6` | delivered | importcheck as the fifth pre-finish gate on every non-aborted outcome; `importcheck_report` field; the real-shape row-67 fixture (merge `bb08061e`) |
| `t7` | delivered | continuation/chain/session propagate the ORIGINAL brief, never the synthesized seed (merge `06aae37e`) |
| `t8` | delivered | `colleague/loop_barrier.py` — barrier replaces the intercepted turn, at-most-once, counts as a normal step, `effort_spikes` artifact field (merge `dd1ff342`) |
| `t9` | delivered | `colleague/loop_gateescalation.py` — repeated-gate-failure medium replan + the fill-line declaring turn as the live `DESIGN_SITE_TABLE['fillline.split']` consumer (merge `58d66c5f`) |
| `t10` | delivered | recorded convention change (7), `docs/features/effort-spikes.md` + `import-check.md`, four-fix doc updates (merge `2b1cd5e8` + pin fix `8d0b91a6`) |
| `t11` | delivered | `tests/test_offknob_byte_identity.py` — all-knobs artifact + wire byte-identity, no violations found (merge `43b425ce`) |
| `t12` | delivered | live rerun `39661f2af608`: row-67 failure shape reproduced; all four fixes fired on the artifact; `docs/live-testing.md` row 69 (commit `e96e62f7`) |
| `t13` | blocked | arm-A dispatches externally stopped twice (`3a87abc231b1` → `b702d8249dea`, both resumable); arms HELD per approved deviation `d1` |

## Mid-work Decisions

- `d1` — t13 A/B/C arms HELD; PR opens with waves 0-4 + t12/row-69 evidence; arms
  resume later via `work --continue b702d8249dea` — arm-A dispatches externally
  stopped twice in a row (`3a87abc231b1`, `b702d8249dea`) while t12 ran 57 min
  undisturbed — operator approved holding the arms and opening the PR now
  (pre-recorded risk r1: arms may span sessions).
- Challenge finding c19 was corrected during execution (frame scope entry s15):
  `EngineConfig` is NOT frozen (`config.py:256` is `SeatDials`), and
  `dataclasses.replace` would not have composed — t4 wired the heartbeat via
  in-place `on_delta` assignment at the `from_config` seam, matching the existing
  cockpit arming pattern. No deviation record; captured on the frame and here.
- t9 mechanism deviation (frame scope entry s16): `gate.repeat_failure` and
  `fillline.decision` cannot use t8's tools-off seat (their turns need the real
  curated tool surface), so the rung is push/popped on the live acting config
  (`SeatEscalator`), sanctioned explicitly in `test_thinking_effort_boundary`'s
  assign-files list; the fill-line has NO separate split completion, so the
  DECLARING turn consumes the design-site rung.
- t6 records `importcheck_report` on both pass and fail (mirroring
  `lint_report`'s always-visible convention, unlike the findings-only siblings) —
  a stated judgment call.
- t8 pre-completed part of t10's amendment (thinking-effort.md line 11 + the
  CLAUDE.md bullet); t10 verified rather than duplicated, and added convention
  change (7) + the drift-test wording pin.
- Post-PR: all 17 SonarCloud issues fixed in one pass (commit `8ccf808d`),
  including the `Lineage` NamedTuple bundling `continued_from`+`task_text`
  (S107) and the `_effort_spikes_from_dict` extraction (S3776).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t13` (`d1`) | arm-A dispatches externally stopped twice in a row (`3a87abc231b1`, `b702d8249dea`) while t12 ran 57 min undisturbed — operator approved holding the arms and opening the PR now (pre-recorded risk r1: arms may span sessions) | needs-follow-up |
| `t4` | instruction's premise wrong (frozen `EngineConfig` / `dataclasses.replace`); composed via in-place assignment at the `from_config` seam instead — acceptance criteria met unchanged | acceptable |
| `t9` | seat mechanism differs from t8's pattern (`SeatEscalator` push/pop on the live config; declaring-turn wiring for fill-line) because the escalated turns need the real tool surface — boundary pinned, honest docs | acceptable |

No other task drifted: t1–t3, t5–t8, t10–t12 delivered to their confirmed
acceptance criteria (task-by-task accounting above).

## Evidence

- tests: full suite `uv run pytest -n auto -q` — **11,788 passed, 51 skipped
  (expected: live-vLLM/extras gates), 0 failed** at `8ccf808d`
- tests: `tests/test_offknob_byte_identity.py` (17 with fidelity) — pass;
  `tests/test_import_check_gate_wiring.py`, `tests/test_barrier_pre_mutation.py`
  (34), `tests/test_gate_escalation.py` (30), `tests/test_continuation_task_text.py`
  (14), `tests/test_effortspikes_boundary.py`, `tests/test_delta_heartbeat_wiring.py` — pass
- lint: `black --check` / `isort --check-only` / `flake8` / `bandit -c pyproject.toml -r colleague` — clean; `teken cli doctor . --strict` — PASS
- commits: `7c375ed8..8ccf808d` (spec `652c7873`, challenge `5051ddfd`, plan
  `22066107`, 13 task merges, v1.75.0 `f86a80cc`, row 69 `e96e62f7`, d1
  `704bc06c`, sonar `8ccf808d`)
- PRs / issues: PR #486 (CI all green; SonarCloud quality gate OK; Qodo
  summary×2, inline×0); issues #480 #481 #482 #483 #484
- live artifacts: run `39661f2af608` (t12) at the `sf-t12-target` worktree —
  `warnings: [affected-tests-failed, import-check-failed]`, `task_text`
  verbatim, `importcheck_report: failed` naming
  `cannot import name '_build_initial_content'`; `docs/live-testing.md` row 69

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A failing affected-tests/test-integrity gate on a budget-exhausted run warns the operator | high | run `39661f2af608` warnings · `tests/test_loop_testgates_gate_warnings.py` · merge `d8e05b18` |
| A non-importing changed module is named before handoff, on every outcome | high | run `39661f2af608` `importcheck_report` · `tests/test_import_check_gate_wiring.py` (real row-67 shape) · merges `b0076856`/`bb08061e` |
| The artifact records the brief verbatim; continuations carry the original | high | run `39661f2af608` `task_text` · `tests/test_contract_task_text.py` + `tests/test_continuation_task_text.py` · merges `bd4771fa`/`06aae37e` |
| A bare streamed run shows mid-turn liveness | high | 650+ heartbeat records in run `39661f2af608`'s flight feed · `tests/test_delta_heartbeat_wiring.py` · merge `7ce6417d` |
| Spike machinery unarmed is byte-identical (wire + artifact) | high | `tests/test_offknob_byte_identity.py` + the unarmed call-for-call test in `tests/test_barrier_pre_mutation.py` |
| The spike surface is enumerated and content-blind | high | `tests/test_effortspikes_boundary.py` drift test · `tests/test_thinking_effort_boundary.py` sanctioned-assign sweep |
| Spikes improve the correctness/cost balance | unverified | arms A/B/C not run (t13 blocked, `d1`) — not claimed |
| #484's disposition (close vs arm-by-default) | unverified | decided by the held arms; pre-registered rule: default-arming requires C to beat B |

## Remaining Work / Follow-up

- `t13` — resume arm A (`COLLEAGUE_MAX_STEPS=90 uv run colleague work --continue
  b702d8249dea --repo /home/spark/git/worktrees/sf-t12-target --no-pr`), then arm B
  (`COLLEAGUE_EFFORT_SPIKES=1` + `COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION=low`)
  and arm C (`COLLEAGUE_EFFORT_SPIKES=1`, barrier `medium` from the table) on the
  same recorded brief; record rows; post the #484 disposition. Owner: operator +
  main agent, when the rig frees.
- `ask-colleague review` of the PR #486 diff — the standing diverse-second-opinion
  reflex was skipped because the rig was contested; run before merge if possible.
- Reap the t12 target worktree (`sf-t12-target`) after the arms complete — it
  holds the resumable run state and the recorded brief until then.
- Parked from the frame: the model-invoked `unsure` reset (v2, follow-up); the
  blocking-path liveness gap (v3, documented as uncovered).

# Build Plan — small-fixes-then-effort-balance

slug: `small-fixes-then-effort-balance` · status: `exported` · from frame: `small-fixes-then-effort-balance`

> colleague lands four small validity/observability fixes (#480-#483), then runs the pre-registered null-hypothesis arm before building #484 effort spikes

## Tasks

### t1 — Gate warnings on non-finished outcomes (#480, incl. test-integrity)

- instruction: Owns colleague/`loop_testgates.py` + its tests. The zero-retry branch at line 290 (and 197 for test-integrity) is where the warning lands; mirror the step-stall/loop-guard warning dict shape from `loop_outcomes.py`
- covers: c3, h2
- acceptance:
  - A budget-exhausted run whose affected-tests gate reports failed carries a {'kind':'affected-tests-failed'} warning naming the selection on TaskResult.warnings, printed once in the post-run line
  - Same treatment for the test-integrity gate's identical pattern; passing/disabled gates on the same outcome are byte-identical; `_EXIT_FINISHED` fix-turn behaviour unchanged

### t2 — TaskResult.`task_text` recording (#481)

- instruction: Owns colleague/contract.py, `contract_taskresult_io.py` (serialize beside `prompt_digest`, lines 227-231), and the knob resolution. Recording ON by default per decision c15
- covers: c4, h3
- acceptance:
  - A run records its brief verbatim on the artifact under a ~16KB cap; over-cap briefs carry an explicit truncation marker, never a silent cut
  - `COLLEAGUE_RECORD_TASK_TEXT`=0 yields an artifact byte-identical to today; serialization is omit-when-None mirroring `prompt_digest`

### t3 — Importability check module (#482) with worktree resolution

- instruction: New module (e.g. colleague/importcheck.py), pure function surface — loop wiring is t6's job. Subprocess runs with the worktree root ahead on sys.path (affectedtests precedent: cwd=`repo_path`, affectedtests.py:414)
- covers: c5, c20, h13
- acceptance:
  - `py_compile` + subprocess importlib smoke of changed .py files; a module importing a non-existent symbol yields a warning naming the module and ImportError
  - Resolution is against the RUN WORKTREE: a test makes the worktree module differ from the installed package and asserts the WORKTREE version's error is reported (no vacuous pass)
  - The module joins tests/`test_boundary.py`::`_SUBPROCESS_ALLOWED` with a stated reason; no Python change = strict no-op; off-knob restores today byte-for-byte

### t4 — Wire `delta_heartbeat` into the work path (#483)

- instruction: EngineConfig is FROZEN (config.py:256) — compose via dataclasses.replace (or wrap where the loop hands config to the engine), chaining `delta_heartbeat`(ctx) with any pre-armed config.`on_delta`. Owns the loop-side composition seam + tests; do not touch vllm transport
- covers: c2, h1
- acceptance:
  - A bare work run on a genuinely slow streamed completion writes flight-feed liveness records mid-turn at <=3.5s spacing; `step_count` never advances from them; an armed cockpit sink still receives every chunk
  - tests/`test_boundary.py` thread allow-list unchanged; streamguards bounds unchanged; a missing or raising sink stays a no-op; the blocking path's gap stays documented

### t5 — Spike table + opt-in + drift boundary test

- instruction: New sibling module (e.g. colleague/effortspikes.py) beside efforttables.py under the file-length ratchet; opt-in env/config flag; artifact record shape (point, rung, seat) defined here for t8/t9 to emit
- covers: c18, c8, h5
- acceptance:
  - A fixed table maps exactly the three lean points (pre-mutation barrier, repeated-gate-failure replan, fillline) to rungs; no effort parameter reachable from the model
  - A drift test mirroring tests/`test_deepthink_boundary.py` enumerates the surface and fails when a point is added without updating the list; with the opt-in unset, outgoing payloads are byte-identical

### t6 — Wire importcheck into pre-finish on EVERY outcome + row-67 fixture

- instruction: Touches `loop_testgates.py` (after t1 merges, avoiding same-wave collision); the fixture reproduces the Policy/ToolCall defect pair from docs/live-testing.md row 67
- depends on: t1, t3
- covers: h4
- acceptance:
  - The check fires on finished, budget-exhausted and stalled outcomes alike; best-effort wrapped so it can never abort run()
  - Asserted against the real cc5d1f1a2c5f shape: a hallucinated import name AND a lost re-export breaking a downstream importer — not synthetic stubs

### t7 — Continuation propagates the original brief

- instruction: Owns colleague/continuation.py + chain path; read the prior artifact's `task_text` and carry it onto the resumed run's result
- depends on: t2
- covers: c22, h15, h3
- acceptance:
  - work --continue of a run with recorded `task_text` produces an artifact whose `task_text` equals the ORIGINAL brief verbatim, asserted in a continuation test — never the synthesized seed

### t8 — Pre-mutation decision barrier

- instruction: Loop turn seam (`loop_turn.py`/`loop_toolexec.py` area); mutation detection via the existing read-only tool classification (tools.py:905 / roles.`is_read_only`); rung from t5's table only
- depends on: t5
- covers: c18, h7
- acceptance:
  - Armed: one bounded tools-off completion interposes before the first mutating tool call after a read-only phase, with its own output ceiling and timeout; it never mutates and counts as a normal step (budget + WorkStats)
  - The trigger is tool-NAME based (existing read-only classification), never content; each firing lands on the artifact as (point, rung, seat); unarmed = byte-identical payloads

### t9 — Gate-failure escalation + fill-line spike wiring

- instruction: Touches `loop_testgates.py` fix-turn path (after t6) and the fillline seam; rungs only from the fixed tables
- depends on: t5, t6
- covers: c18
- acceptance:
  - First gate repair runs at the seat's ordinary rung; a REPEATED failure gets one medium replan with retry count as the signal; fired escalations land on the artifact
  - The fill-line point consumes the existing `DESIGN_SITE_TABLE`\['fillline.split'\] contract rather than duplicating policy; `test_design_call_site` updated to name the live consumer

### t10 — Docs + the recorded invariant amendment

- instruction: Docs-only task; cite issues #480-#484 and this spec; keep the CLAUDE.md bullet a pointer, detail in the feature doc (trim discipline c17/h4)
- depends on: t5, t8, t9
- covers: c21, h14
- acceptance:
  - docs/features/thinking-effort.md line 11, the CLAUDE.md effort bullet, and the spike drift test all carry the amended wording ('never per turn FROM CONTENT — per enumerated point from a fixed table') in the same PR; the amendment is listed as a recorded convention change
  - Feature docs for the four fixes updated (work-and-loop.md, artifact.md, affected-tests.md, test-integrity.md) naming the new warnings/keys/knobs

### t11 — Byte-identical off-knob assertion suite

- instruction: One test module comparing serialized TaskResult artifacts and captured wire payloads under all-off knobs against baseline fixtures
- depends on: t2, t4, t6, t8, t9
- covers: h12, c14
- acceptance:
  - With every off-knob set (`COLLEAGUE_RECORD_TASK_TEXT`=0, importcheck off, heartbeat off, spikes unarmed), serialized artifacts and outgoing payloads compare byte-identical to the pre-arc baseline — asserted by comparison, not code review

### t12 — Live validation: row-67 rerun demonstrating all four fixes

- instruction: Use the reconstructed row-67 brief; dispatch via uv run colleague work in a throwaway worktree; grade the work item before reaping (standing practice)
- depends on: t7, t11
- covers: h10, h11, c12, c13, c11, h9
- acceptance:
  - A rig rerun of the row-67 failure shape shows: the gate warning on the artifact, the importability warning naming the ImportError, `task_text` recorded (rerun dispatchable from it alone), and mid-turn liveness records — recorded as a docs/live-testing.md row citing rows 66-68

### t13 — A/B/C measurement arms + #484 disposition

- instruction: Pre-registered readings from #482's comment apply verbatim; do not choose the reading after the fact. GPU serializes — run arms sequentially, `COLLEAGUE_TIMEOUT`=300
- depends on: t12
- covers: c1, h8
- acceptance:
  - Arms A (low + feedback), B (A + barrier), C (B with medium at the barrier) run on the same brief with the ordinary work budget fixed; correctness (import + pins + affected tests) primary, spend secondary; each arm a docs/live-testing.md row with a miss written as a miss
  - Each of #480-#483 landed as its own revertible commit; the arms' result decides what arms by default (arming any spike by default requires C to beat B) and the #484 disposition is posted to the issue

## Risks

- [unknown_nonblocking] Rig availability + GPU serialization bound the live arms; arms run sequentially and may span sessions
- [unknown_nonblocking] Prose-shape confound: rows 51-58 showed brief wording moves outcomes more than some effect sizes — arms must reuse the recorded `task_text` verbatim (task t13)

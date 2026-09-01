# small-fixes-then-effort-balance

> colleague lands four small validity/observability fixes (#480-#483), then runs the pre-registered null-hypothesis arm before building #484 effort spikes
> instruction: Ship the four fixes as independent, individually revertible commits; build the spike surface dark behind an opt-in in the same arc; then run the A (feedback) / B (+decision barrier) / C (+medium at the barrier) arms — arming any spike by default requires C to beat B

## Audience

- Colleague operators dispatching live runs on the rig, and the measurement arcs recorded in docs/live-testing.md — the people who read post-run lines, artifacts, and rerun briefs
  - instruction: Spec names both readers; each fix's acceptance is stated from the operator's observable surface (warning line, artifact key, flight feed record)

## Before → After

- After: A run can no longer know something the operator does not: a failing gate on any outcome lands a warning; a non-importing branch is named before handoff; every artifact carries the brief that produced it; a long streamed turn shows liveness — and the #484 spike question is answered by the pre-registered null arm, not assumption
  - instruction: Verify each clause against its issue's acceptance criteria (#480 AC1, #482 AC1, #481 AC1, #483 AC1, #484 comment ordering)

## Why it matters

- Row 67 shipped a non-importing branch while the harness had already run the failing gate and told no one, and row 67's own measurement was unreproducible because the brief was gone — the four fixes close both, and cheaply instrument the experiment that decides #484
  - instruction: docs/live-testing.md rows 66-68 + issues #480-#482 are the evidence trail

## Requirements

- \#483 wiring: compose `delta_heartbeat`(ctx) INSIDE the loop (where `_Work` ctx exists) with any pre-armed config.`on_delta` — bare work already streams (`_headless_streaming_enabled` default True, `vllm_openai.py`:364 routes via `_delta_sink` to `_noop_delta`), so no transport change; the cockpit/session sink armed by `_work_support`.`_arm_delta_stream` must keep receiving chunks
  - honesty: A bare work run on a genuinely slow streamed completion writes flight-feed liveness records mid-turn; `step_count` never advances from them; an armed cockpit sink still receives every chunk; tests/`test_boundary.py` thread allow-list unchanged; streamguards bounds unchanged
- \#480 fix: in `loop_testgates`.`_maybe_run_affected_tests_gate`, when report.status=='failed' and outcome != `_EXIT_FINISHED`, append a {'kind':'affected-tests-failed',...} dict to ctx.result.warnings (matching the existing step-stall/loop-guard warning shape) and surface it in the post-run line; finished runs unchanged
  - honesty: Budget-exhausted + failing gate = one warning naming the gate and selection, printed once; passing/disabled gate on the same outcome = byte-identical; `_EXIT_FINISHED` behaviour (fix turns) unchanged
- \#481 fix: TaskResult.`task_text` with omit-when-None serialization mirroring `prompt_digest` (`contract_taskresult_io.py`:227-231), a truncation cap with an explicit marker, and an off-knob `COLLEAGUE_RECORD_TASK_TEXT`=0 — the verbatim brief today exists ONLY on the opt-in #411 agents ledger (`operator_request` events), never on the default artifact
  - honesty: A rerun dispatched from the recorded `task_text` reproduces the brief with no operator memory; over-cap briefs carry a discoverable truncation marker; off-knob artifact byte-identical; work --continue carries the original brief through
- \#482 fix: a new small module (`py_compile` + subprocess importlib smoke of changed .py files) running pre-finish on EVERY outcome incl. budget-exhausted, advisory warning-only, best-effort wrapped, off-knob; the module joins tests/`test_boundary.py`::`_SUBPROCESS_ALLOWED` with a stated reason
  - honesty: The check fires on finished, budget-exhausted and stalled outcomes alike; asserted against the real hallucinated-import + broken-downstream-importer shape; no Python change = strict no-op; best-effort wrapped so it can never abort run(); off-knob byte-identical
- Spike machinery: a fixed table maps each of the three lean points to a rung; opt-in arming (unarmed = byte-identical, every outgoing payload matches today key for key); the decision barrier is a bounded tools-off completion with its own output ceiling and timeout; each fired spike is recorded on the artifact (point, rung, seat) with absence reading as did-not-fire; a drift boundary test mirrors `test_deepthink_boundary.py` and fails on any un-listed point
  - instruction: Table beside `PURPOSE_TABLE` in efforttables.py or a sibling module (file-length ratchet); no effort parameter reachable from the model; artifact key follows the effortrecord conventions
  - honesty: With the opt-in unset, outgoing payloads are byte-identical to v1.74.0; armed, the drift test enumerates exactly three points and fails on a fourth; the barrier completion is tools-off, bounded by its own output ceiling + timeout, and never mutates; no code path inspects turn content or a model-supplied value to choose a rung; each fired spike lands on the artifact as (point, rung, seat)
- \#482's import smoke must resolve changed modules against the RUN WORKTREE, not the installed package: the subprocess needs the worktree root ahead on sys.path (affectedtests precedent: pytest runs with cwd=`repo_path`, affectedtests.py:414) — self-hosting runs (colleague editing colleague) otherwise import the installed harness and pass vacuously
  - honesty: A test changes a module inside a throwaway worktree so it differs from the installed package and asserts the check reports the WORKTREE version's ImportError — proving resolution is not vacuous
- The spike increment AMENDS the recorded thinking-effort invariant in docs/features/thinking-effort.md ('resolved where each seat is built, never per turn', line 11): the new wording is 'never per turn FROM CONTENT — per enumerated point from a fixed table'; the doc, CLAUDE.md bullet, and the drift test must all carry the amended line or docs and code drift silently
  - honesty: docs/features/thinking-effort.md, the CLAUDE.md effort bullet, and the spike drift test all carry the amended wording in the same PR that lands the machinery; the amendment is listed as a recorded convention change, not a silent breach
- `task_text` on a CONTINUED run must propagate the ORIGINAL brief from the prior artifact, not the synthesized continuation seed (continuation.py builds preamble+record+request as the new task text) — otherwise #481 AC4 records the wrong text and a chained rerun is still unreproducible
  - honesty: A work --continue of a run with recorded `task_text` produces an artifact whose `task_text` equals the ORIGINAL brief verbatim, asserted in a continuation test

## Honesty conditions

- Each of #480-#483 lands as its own revertible commit with its acceptance criteria asserted in tests; the spike machinery merges dark (opt-in) in the same arc; the A/B/C arms are recorded in docs/live-testing.md with a miss written as a miss
- A drift test enumerates any spike surface and fails on an un-listed addition; no code path reads turn content or a model-supplied value to pick a rung
- Every fix's acceptance test asserts the operator-observable surface (a warning line, an artifact key, a flight-feed record) — not only internal state
- A rerun of the row-67 failure shape demonstrates all four fixes at once: the gate warning, the importability warning, the recorded brief, and mid-turn liveness records
- The arc's live-testing rows cite rows 66-68 as the motivating evidence and the rerun uses the recorded `task_text`, closing the reproducibility gap the arc exists for
- The byte-identical clause is asserted by comparing serialized artifacts/payloads with every off-knob set, not by code review alone
- With the opt-in unset, a byte-comparison of outgoing payloads against v1.74.0 passes; with it armed, the drift test enumerates exactly three points; the barrier turn never mutates and never advances `step_count` past its own bounded completion; no code path inspects turn content to choose a rung

## Success signals

- On a rerun of the row-67 failure shape: the artifact carries >=1 warning of kind affected-tests-failed AND >=1 importability warning naming the ImportError; a rerun is dispatchable from TaskResult.`task_text` alone; a slow streamed turn yields liveness records at <=3.5s spacing; with all off-knobs set, artifacts are byte-identical to v1.74.0
  - instruction: Assert against the real cc5d1f1a2c5f defect shape (hallucinated Policy import + lost ToolCall re-export), not synthetic stubs — #482 AC6

## Scope / boundaries

- \#484 must stay the deepthink/`PURPOSE_TABLE` shape: rungs from a FIXED table at points enumerated in code and pinned by a boundary test (mirror tests/`test_deepthink_boundary.py`); no model-supplied rung, nothing reading turn CONTENT to pick a rung — that would be the excluded router; the thinking-effort invariant 'resolved where each seat is built, never per turn' survives
  - instruction: Boundary test enumerates the spike surface module-level descriptor list (mirror tests/`test_deepthink_boundary.py`); grep-level assertion that no spike resolution reads message content; rung values only from the fixed table

## Assumptions

- \#484 is GATED on the small fixes: the pre-registered null-hypothesis arm (low effort + #482 importability check + #480 surfaced gate + one bounded fix turn, vs flat low and the 40k-planning-turn arm) decides whether spikes are needed at all — if cheap feedback reaches the same correctness, #484 closes
- One #484 spike point already has policy but no consumer: `DESIGN_SITE_TABLE`\['fillline.split'\]='xhigh' (effort.py:110) with no live call site (`test_design_call_site`) — wiring the existing design-seat contract beats adding duplicate spike policy for the fill-line point
- \#480 acceptance asks to check whether lint and test-integrity gates share the silent-failure shape on non-finished outcomes — `loop_testgates.py`:197 shows test-integrity uses the identical 'retries if `_EXIT_FINISHED` else 0' pattern, so yes for test-integrity
- EngineConfig is a frozen dataclass (config.py:256) — the loop cannot assign config.`on_delta` at ctx time; #483's composition must wrap via dataclasses.replace or wire the heartbeat at the seam where the loop already owns the callback flow, keeping the armed cockpit sink chained

## Scope exploration

- `s1` — `colleague/loop_progress.py + tests/test_delta_heartbeat.py`: `delta_heartbeat` exists, throttled (`COLLEAGUE_DELTA_HEARTBEAT_INTERVAL` 3.0s), thread-free, proven against genuinely slow generators — zero production callers; grep shows only tests reference it
  - seeds: `c2`
- `s2` — `colleague/cli/_commands/_work_support.py::_arm_delta_stream + colleague/engines/vllm_openai.py:322-364`: `on_delta` armed only for cockpit/session sinks; bare work leaves it None but transport still streams headlessly (default True, `COLLEAGUE_STREAM`=0 disables) into `_noop_delta` — wiring point must be in-loop where `_Work` ctx exists, composing with (not replacing) an armed sink
  - seeds: `c2`
- `s3` — `colleague/loop_testgates.py:246-300`: affected-tests gate runs and records report on every outcome but grants fix turns only on `_EXIT_FINISHED` (line 290); no warning lands on result.warnings for a failed report on non-finished outcomes; test-integrity gate (line 197) shares the identical pattern
  - seeds: `c3`, `c10`
- `s4` — `colleague/contract.py + contract_taskresult_io.py + colleague/agents/state/ledger.py`: TaskResult has `prompt_digest` with omit-when-None serialization (io lines 227-231) but no task text field; the verbatim brief is persisted only as `operator_request` events on the opt-in `COLLEAGUE_AGENTS` ledger — default artifacts carry no brief, confirming #481
  - seeds: `c4`
- `s5` — `tests/test_boundary.py::_SUBPROCESS_ALLOWED`: any new importability-check module using subprocess must join the explicit allow-list with a stated reason — the sanctioned-consumer convention
  - seeds: `c5`
- `s6` — `colleague/effort.py:105-112 + colleague/efforttables.py`: `DESIGN_SITE_TABLE` already assigns fillline.split=xhigh with no live consumer; `PURPOSE_TABLE` draws the 'model cannot pick a rung' line; `resolve_effort` precedence c32 is where any spike table would slot
  - seeds: `c7`, `c8`
- `s7` — `tests/test_deepthink_boundary.py`: the four deepthink escalation points are pinned by a module-level descriptor list + drift test — the exact mirror #484 acceptance criterion 1 asks for on any spike surface
  - seeds: `c8`
- `s8` — `gh issues #480-#484 incl. comments`: \#482's comment pre-registers the deciding arm: low + importability check + fed-back fix turn vs flat low vs the planning-turn arm; #484's own comments correct the low-vs-medium evidence (both arms ran low; step budget was the variable) and retract the rotating quota — the null hypothesis (feedback, not depth) must run before spike work
  - seeds: `c6`, `c9`
- `s9` — `challenge pass / adjacent-systems lens: colleague/config.py EngineConfig`: frozen=True at line 256; naive config.`on_delta` assignment in the loop would raise — composition mechanism is a design point, not free
  - seeds: `c19`
- `s10` — `challenge pass / hidden-dependency lens: colleague/affectedtests.py:414 + site-packages resolution`: pytest gate already runs cwd=worktree; a bare importlib subprocess would NOT inherit that resolution for package imports — the vacuous-pass failure mode is real for self-hosted runs
  - seeds: `c20`
- `s11` — `challenge pass / unstated-assumption lens: docs/features/thinking-effort.md line 11`: the spec as exported builds machinery that contradicts the invariant's literal wording; an explicit recorded amendment is required — this is a convention change to record, not a silent breach
  - seeds: `c21`
- `s12` — `challenge pass / lifecycle lens: colleague/continuation.py seed synthesis`: the resumed Task's text is the built seed, not the operator brief; propagation from the prior artifact's `task_text` is the fix
  - seeds: `c22`
- `s13` — `challenge pass / security lens: .gitignore:247-249 + .colleague artifact dir`: artifacts (and thus `task_text`) are local-only — .colleague/\* ignored except commands/ and skills/; residual exposure is feedback export and manual artifact copies, bounded by the off-knob
- `s14` — `challenge pass / failure-mode lens: colleague/tools.py:905 + roles.is_read_only`: a read-only tool/role classification already exists — the barrier's first-mutation trigger can be tool-NAME based, satisfying the never-content-routed boundary; clean pass on the router risk for this trigger
  - seeds: `c18`

## Decisions

- `task_text`: ~16KB cap, truncation marker, ON by default, `COLLEAGUE_RECORD_TASK_TEXT`=0
- This arc ships the four fixes AND the #484 spike machinery (opt-in, unarmed = byte-identical); the pre-registered arms then measure feedback vs barrier vs rung on the same brief
- Spike surface v0 = the lean set: (a) pre-mutation decision barrier, (b) repeated-gate-failure escalation to one medium replan (retry count as the signal), (c) fill-line via the existing `DESIGN_SITE_TABLE`\['fillline.split'\] consumer; forced synthesis EXCLUDED from the spike surface
- Barrier completion counts as a normal step (budget + WorkStats); never hidden from the declared bound

## Open parks

- [unknown_nonblocking] Whether the fill-line spike point should be delivered by finally wiring the dormant `DESIGN_SITE_TABLE`\['fillline.split'\] consumer rather than any new spike table — depends on the null arm's outcome
- [unknown_nonblocking] Blocking (non-streaming, `COLLEAGUE_STREAM`=0) path keeps no in-flight liveness — stays documented as uncovered per #483 AC5; revisit only if operators actually run blocking
- [follow_up] Model-invoked 'unsure' reset tool (closed reason vocabulary, table-fixed rung, rate-limited) — after the harness-side arms are measured

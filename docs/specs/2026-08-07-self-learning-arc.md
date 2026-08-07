# self-learning arc

> Colleague now learns from its own runs: every work item's remember-after can distill a validated cause-to-lesson record (never fabricated filler), ordinary coding tasks grow a per-repo code-lesson ledger from correction diffs and gate fixes, and a bounded strive mode turns repeated failure into recalled lessons and testable hypotheses with an executable measure.

## Audience

- Colleague operators who dispatch and grade work items; colleague itself as the recall consumer of every future run; and the graded ROI/flywheel lane that trains on lesson-bearing records

## Before → After

- Before: remember-after writes telemetry stubs (41 live specimens in .eidetic/memory, e.g. work-lesson-598d9fafc7b1); attempts are operator-driven with no autonomous retry-differently; a genuinely new idea is not representable, so novelty is undetectable
- After: A failed run leaves a recallable record naming what failed and why; ordinary coding tasks grow a per-repo conventions ledger consulted by recall-before; a strive goal either reaches its measure or leaves a hypothesis ledger recording exactly what was tried and refuted

## Requirements

- Rung 2 of #379: a gated lesson-distillation pass at remember time — ONE bounded completion riding the `_maybe_remember_lesson` seam in colleague/loop.py, schema-validated {cause, lesson, `next_delta`}, recorded ONLY when it validates; otherwise the rung-1 deterministic record stands alone with an honest no-lesson-extracted marker; the record is marked origin=model
  - instruction: Implement at the `_maybe_remember_lesson` seam in colleague/loop.py; validate against a fixed schema {cause, lesson, `next_delta`} with bounded field lengths; test with the mock engine + a scripted distillation seam
  - honesty: A lesson field lands ONLY when schema validation passes; a malformed distillation leaves the rung-1 record plus an honest no-lesson-extracted marker — pinned by a test feeding a garbage completion
- Rung-1 completion: `compose_lesson_text` in colleague/memory.py folds the remaining #379-named failure substance — lint-gate fixes (TaskResult.`lint_report`), test-integrity findings (`test_integrity_report`), affected-tests failures (`affected_tests_report`) — which exist structured on TaskResult and are dropped from the lesson today
  - instruction: Extend `compose_lesson_text` in colleague/memory.py; assert byte-identity for a report-less result in tests/`test_loop_memory.py`
  - honesty: A run carrying lint/test-integrity/affected-tests reports folds each into the lesson bounded per field; a run without them stays byte-identical to the rung-1 record shape (same upsert id)
- Repo-anchored code-lessons (#378 core): a code-lesson record type distinct from work-lesson — {area/file, convention-or-gotcha, evidence, confidence} — written to the SAME in-repo eidetic store via the same two allow-listed verbs; teachers: lint-gate fixes, in-run test failures, ROI grades and notes
  - honesty: code-lesson records carry their own type and id namespace and never collide with work-lesson upserts; a store-less repo remains a zero-subprocess no-op
- The integrator-correction diff (colleague's landed colleague/<id> branch vs what actually merged) is captured as a code-lesson teacher — the richest currently-discarded signal per #378
  - honesty: The correction diff is computed only from persisted facts (tip SHA + resolved merge commit + `changed_files` scope); any missing fact yields an honest no-diff record, never a diff against the wrong base
  - honesty: A code-lesson derived from a correction diff quotes the hunk verbatim as its evidence field; any WHY interpretation is marked origin=model and schema-validates like a rung-2 lesson — the teacher itself cannot fabricate
- The necessity loop (#377): an operator-invoked bounded strive verb reusing chain.py episode machinery, with four enforced phases — recall, delta declaration, execute+measure, lesson-grade remember — a per-goal hypothesis ledger as the novelty detector, and novelty stalls recorded honestly, never as fabricated progress
  - honesty: Each strive attempt records its delta declaration BEFORE execution; an attempt that cannot name a delta or new hypothesis is recorded as exactly that — learning-from-recall stays observable, never assumed
- The strive measure command is operator-supplied shell and runs under the approval gate (colleague/policy.py `run_command` token allow-list) — never an ungated escape hatch
  - honesty: The measure command routes through the same approval-gate check as `run_command`; the spec documents it as a policy gate, not a sandbox (D2), with the absent-file default unchanged
- \#376 diagnosability: a plan-mode claim-parse TOTAL failure captures the raw proposal text (artifact or stderr) so a model-format mismatch like the 35B's is diagnosable — today only the terminal message survives
  - instruction: Persist the raw proposal text from the `make_propose_claims` total-failure path (colleague/plan/`cli_driver.py`) into the plan artifact directory before raising
  - honesty: On a total claim-parse failure the raw proposal text is persisted (artifact or stderr) and a test asserts its presence
- Lesson distillation (rung 2) is authored by the strategist/cortex seat via the deepthink surface, as a background effort off the run's critical path — not by the run's main model; with cortex/deepthink unarmed the rung-1 deterministic record stands alone (the degrade floor)
  - honesty: With cortex/deepthink unarmed, remember-after output is byte-identical to the rung-1 record; the background effort never blocks the run's return
- The feedback lane gains a second author: cortex can observe a finished work item and record feedback alongside the operator's — operator feedback stays first-class, and every feedback record carries author provenance (operator vs cortex)
  - honesty: Every feedback record carries author provenance; a cortex-authored record lands beside an operator record, never overwriting it
- Correction capture is seamless auto-improve: it fires at feedback-record time AND is auto-triggered by colleague's own actions (post-merge observation), never only on operator command
  - honesty: Every auto-triggered capture is observable in the artifact (what fired and why); a capture failure never blocks or fails the triggering action
- colleague plan run with the 35B worker model produces a parseable claim proposal — the claim grammar, prompt, or parse tolerance is adapted so the 35B converges as the 27B does (#376 fix, not just diagnosability)
  - instruction: rerun the t14 failing invocation (colleague plan run --model unsloth/Qwen3.6-35B-A3B-NVFP4 --no-workforce --review --yes) and get a parsed frame, or a diagnosable raw capture + documented limitation
  - honesty: The t14 failing invocation reruns to a parsed frame, or the raw capture diagnoses the format gap and the limitation is documented honestly
- Rung-2 distillation carries an alive-counter: distillation attempts vs validated lessons land on TaskResult.memory (and surface in doctor) — armed is not evidence the tier is alive, a counter that increments is (#363 T1/T2 lesson); a rig whose model never validates the schema is visible within one run
  - honesty: A run whose distillations never validate shows attempts>0, validated=0 on the artifact — pinned by a test with an always-invalid distillation seam; the feature doc states plainly that armed is not alive, the counter is
- Rung 2 has its own arm/disarm knob independent of the memory gate — distillation can be disabled without losing rung-1 records or recall-before
  - honesty: With rung 2 disarmed and memory armed, remember-after output is byte-identical to rung-1 — pinned by a test
- The background distillation child is bounded and observable: it writes within a bounded window, its outcome (or absence) is diagnosable afterward (pending / done / dead), and a killed child never leaves a partial record
  - honesty: A killed or hung distillation child leaves no partial record, and a reader can distinguish pending / done / dead from the artifact or store marker — never silently absent
- A strive attempt's measure command runs in the episode's worktree — it scores the tree the attempt produced, never the operator tree
  - honesty: A test asserts the measure subprocess cwd is the episode worktree, not the operator tree

## Honesty conditions

- Each of the three legs carries its own falsifiable proof (rung-2 validation test, #378 ablation, #377 recall ablation) — a leg whose proof is missing or negative is reported unproven or falsified, never claimed shipped
- A test pins chain `CONTINUABLE_REASONS` == {budget-exhausted} after the arc; strive's retry policy lives in its own decision layer
- A test feeds an unparseable or schema-invalid distillation and asserts no lesson field lands while the honest marker does
- `ALLOWED_VERBS` stays frozenset({recall, remember}); the boundary test proves no new eidetic verb is reachable
- A remember failure (absent CLI or non-zero exit) still returns the work-item result unchanged, and a recall failure injects nothing and never raises — both pinned by tests
- The spec names both lesson consumers explicitly: future runs via recall-before, and the graded ROI/flywheel lane
- Verified against the live store after the arc: a deliberately failed run's record carries cause/lesson substance, not only telemetry
- The before-state is reproducible evidence: the stub specimens stay quotable from .eidetic/memory history
- The test asserts record content verbatim (reason + evidence), not merely that a record exists
- The ablation runs the SAME task sequence in both arms; a non-declining result is recorded as falsifying, never explained away
- Both strive arms share goal, measure, seeds, and attempt cap; only recall differs
- Training-pair extraction defaults to operator-authored records; including cortex-authored ones requires an explicit opt-in flag — pinned by a test on the filter

## Success signals

- After a deliberately failed run in a test repo, recall surfaces >= 1 record carrying the incompletion reason and evidence verbatim (mock engine, no LLM); with rung 2 armed the same record carries a validated lesson field
  - instruction: pytest with the mock engine + a fake eidetic CLI on PATH; assert the remembered text contains IncompletionRecord.reason verbatim, and a lesson field ONLY when distillation validates
- Across the same sequential task set run twice (learning ON vs OFF), integrator-correction diff lines per task are lower with ON: `lines_ON` < `lines_OFF`
  - instruction: the #378 ablation: one repo, N real tasks, both arms the same tasks; record both runs via the experiment noun
- On the NEBULA smart-bot benchmark, strive with recall ON reaches the goal in fewer attempts than recall OFF (`attempts_ON` < `attempts_OFF`); an equal-or-worse result is recorded as falsifying the memory link
  - instruction: run colleague strive twice on the same goal/measure/seeds/attempt-cap, only recall differing; compare attempts-to-success

## Scope / boundaries

- chain.py `CONTINUABLE_REASONS` stays exactly {budget-exhausted} for ordinary runs — strive's retry-differently policy is its own decision layer, never a widening of the work/drive chaining allow-list
- Anti-fabrication: a distilled lesson lands only when it schema-validates; an inarticulate run records no-lesson-extracted — the same stance as the fill-line's validated compaction (capacity-standard)
- colleague/memory.py `ALLOWED_VERBS` stays exactly {recall, remember}; every new record kind rides those two verbs; eidetic remains a subprocess-launched operator CLI, never imported
- Existing memory invariants hold through rung 2: recall stays advisory (never a precondition) and a remember failure never masks the work-item result
- Cortex-authored feedback is excluded from the #291 flywheel training-pair extraction by default (explicit opt-in to include) — a model grading its own work must never silently become its own training signal

## Non-goals

- Fixing #372/#373/#374 (stall legibility, SIGTERM leaving no `last_work` pointer) stays outside this arc per resolved q1 — the spec records them as known experience-stream quality limits a learner inherits

## Assumptions

- A correction-diff computation that shells git either reuses an already-sanctioned module (handoff.py / worktrees.py) or joins tests/`test_boundary.py` `_SUBPROCESS_ALLOWED` with a stated reason
- Squash-merge matching recipe: handoff persists the colleague/<id> branch TIP SHA onto TaskResult (branch name + `pr_url` are persisted today, the tip SHA is not, and colleague clean reaps colleague/\* refs); the PR's squash commit resolves via gh (mergeCommit); the correction diff = tip vs merge commit, scoped to TaskResult.`changed_files` so unrelated main-line churn cannot pollute the delta
- The background distillation effort rides the already-sanctioned background one-shot detach (colleague/background.py, Popen `start_new_session`) or a post-run deepthink call — the sanctioned-threads line (subagents.py + the input-line reader) stays untouched; which shape wins is a /think interrogation point
- Distillation resolves its author BY ROLE, reconciling c16 with the three-tier line (deepthink is ABSENT in three-tier mode): the lobes cortex role when armed, the deepthink/muse target in dual-model mode, the rung-1 floor otherwise

## Scope exploration

- `s1` — `colleague/memory.py (compose_lesson_text, rung 1 @ 5ed1205)`: Rung 1 landed today: deterministic lesson text folds incompletion {reason,evidence,recommendation}, error, and stale-pin warnings — but NOT the lint-gate fixes, test-integrity findings, or affected-tests failures #379 also named; `RECALL_BLOCK_CAP`=4000 and `build_lesson_record` upserts by work-lesson-<`task_id`>
  - seeds: `c2`, `c3`
- `s2` — `colleague/loop.py (_maybe_recall_memory / _maybe_remember_lesson / _memory_armed)`: The remember-after seam is best-effort and triple-gated (config.memory + .eidetic/ dir + eidetic CLI present); `memory_root` targets the OPERATOR repo so isolated worktrees do not swallow lessons; this is the exact seam a rung-2 bounded completion rides
  - seeds: `c2`, `c11`
- `s3` — `.eidetic/memory/colleague__public.jsonl (live store)`: 41 work-lesson records live; specimen work-lesson-598d9fafc7b1 is verbatim the telemetry stub #379 quotes (steps=43, tools=..., no why, no lesson) — the content gap is confirmed in the durable store, not just the issue text
  - seeds: `c2`
- `s4` — `docs/features/memory.md (Honest limits)`: The feature doc already parks rung 2 by name: the lesson record is deterministic run-facts, and mining WHY stays with the reader or 'a future bounded reflection turn, a named follow-up' — this arc is that named follow-up
  - seeds: `c2`
- `s5` — `colleague/contract.py (TaskResult)`: `lint_report`, `test_integrity_report`, `affected_tests_report`, incompletion, and warnings are all structured, omit-when-empty fields — the rung-1 substance to fold exists on the result already; no contract change needed for c3
  - seeds: `c3`
- `s6` — `colleague/chain.py (chain driver core)`: A pure decision layer over persisted TaskResult facts — no git, no subprocess, no loop imports; `CONTINUABLE_REASONS` is a frozenset of exactly {budget-exhausted} with an explicit anti-catch-all rationale; the halt vocabulary is enumerated — strive can reuse the episode machinery but must carry its own retry policy
  - seeds: `c6`, `c8`
- `s7` — `colleague/feedback.py (ROI store)`: FeedbackRecord is {`task_id`, rating 1-5, notes} plus a `last_work` pointer; no diff capture exists anywhere — grade time is the natural correction-diff hook since the operator grades after merge, but nothing computes it today
  - seeds: `c4`, `c5`
- `s8` — `colleague/plan/cli_driver.py (parse_claims / _extract_json_object / make_propose_claims)`: The extractor is already tolerant (fence-wrapped JSON, truncation repair, required-key selection) and the honesty-recovery pass was tuned against the 27B (#215/v1.22.0); a TOTAL parse failure raises ValueError with NO raw-text capture — the 35B mismatch (#376) is undiagnosable from what survives
  - seeds: `c15`
- `s9` — `colleague/deepthink.py (enumerated escalation surface)`: Every escalation carries a DeepthinkCall with a point= label and the module is the ONE deepthink surface; a novelty-stall escalation for strive would be a NEW enumerated point — it must be listed in this re-spec or left out, never implicit
  - seeds: `c13`
- `s10` — `CLAUDE.md v1 scope line (eight sanctioned increments)`: Every increment past v0 landed as a re-spec'd, FIXED, ENUMERATED surface, never a routing policy; #377 itself says 'this issue is that proposal, not a license' — strive is a new bounded mode and this frame is its re-spec vehicle
  - seeds: `c6`, `c13`
- `s11` — `tests/test_boundary.py (_SUBPROCESS_ALLOWED)`: memory.py is already on the sanctioned subprocess list; a new module shelling git for the correction diff must either reuse handoff.py/worktrees.py or join the list with a stated reason — the boundary test is the authority
  - seeds: `c14`
- `s12` — `colleague/policy.py (approval gate)`: `run_command` is allow-listed by token and an absent approvals.json is a strict no-op; the strive measure command is operator-supplied shell, so it must ride this gate — a policy gate, not a sandbox, per the documented D2 trust model
  - seeds: `c7`
- `s13` — `colleague/contract.py + colleague/handoff.py (branch/pr_url persistence)`: TaskResult persists branch NAME and `pr_url` but no tip commit SHA; cleanup-reap deletes colleague/\* refs — by grade time the colleague side of a squash-merge diff can be gone unless handoff persists the SHA (or the diff itself) at handoff time
  - seeds: `c19`
- `s14` — `colleague/background.py (sanctioned one-shot detach)`: The daemonless line already sanctions a detached session-leader child with no wait/poll — a background distillation child fits this shape without extending the sanctioned thread list
  - seeds: `c20`, `c16`
- `s15` — `challenge pass / adjacent-systems lens: feedback store + #291 flywheel`: Cortex-authored grades entering the same store the QLoRA flywheel trains on means a model grading its own work becomes training signal; seeded the default-exclusion boundary
  - seeds: `c30`
- `s16` — `challenge pass / observability lens: #363 seam-trap lessons T1/T2 vs rung-2`: Embodiment's live finding — armed==True with every counter at zero and no error anywhere — maps exactly onto a distillation pass whose model never validates the schema; #376 is live counter-evidence that served Qwens fail prompted-JSON; seeded the attempts-vs-validated counter and the independent kill switch
  - seeds: `c28`, `c29`
- `s17` — `challenge pass / failure-mode lens: background.py detach + in-repo store writes`: A detached child writes the committed store at an arbitrary later moment — racing the next run's recall, the operator's own commits, and the dirty-tree UX; seeded the bounded-window observable-outcome requirement
  - seeds: `c31`
- `s18` — `challenge pass / hidden-dependency lens: CLAUDE.md three-tier line vs c16`: The three-tier increment declares deepthink ABSENT in three-tier mode while c16 routes distillation via the deepthink surface — reconciled by resolving the author BY ROLE (cortex when lobes armed, muse/deepthink in dual-model, rung-1 floor otherwise)
  - seeds: `c32`
- `s19` — `challenge pass / lifecycle lens: strive episodes x worktrees`: Episodes run in worktrees based on the prior episode tip; the measure must score the attempt's tree, not the operator tree — unstated in #377; seeded the worktree-cwd requirement
  - seeds: `c33`
- `s20` — `challenge pass / counter-evidence lens: correction-diff attribution`: Integrator rewrites happen for reasons unrelated to colleague's mistakes (scope creep, style, rebase fallout) — diff volume is a noisy teacher; seeded the verbatim-hunk evidence honesty on c5
  - seeds: `c5`
- `s21` — `challenge pass / security lens: recall block as injection surface`: The committed store is writable by anyone with commit access and its text is injected into future runs' context; advisory labeling + `added_by` are the current mitigations — parked as residual risk (v2), not solved this arc
- `s22` — `challenge pass / clean lenses: migration + reversibility`: No migration: new record kinds are additive and the rung-1 prefix stays stub-compatible; reversibility rides eidetic supersedes/shadowing plus the rung-2 kill switch — residual risk is store bloat, parked (v3)
- `s23` — `challenge pass / #380 absorption`: The workforce-method lesson (explicit integration task + behavior-level e2e gate) stays OUTSIDE this arc per resolved q1 — it is plan-authoring guidance for the coming /spec-to-plan leg, which should cite #380 when decomposing
- `s24` — `challenge pass / cheap probe deferred: live schema-validity of cortex JSON`: Whether the served Qwen cortex emits valid cause/lesson/`next_delta` JSON is testable with one live completion; deferred to the plan's live-proof task rather than run mid-pass (the rig serializes, and #376 already documents the 35B prompted-JSON wall)
  - seeds: `c28`

## Open parks

- [unknown_nonblocking] Novelty-detection semantics for the hypothesis ledger: how 'matches no prior hypothesis' is computed (exact key, lexical, or semantic via the embedder role) is undecidable until the ledger schema exists
- [unknown_nonblocking] Recall injection surface: .eidetic/memory is repo-committed and writable by anyone who can commit (mesh peers, PRs); a planted lesson is injected into future runs' context. Mitigations today: advisory labeling + eidetic `added_by` provenance; deeper provenance filtering is future work
- [unknown_nonblocking] In-repo code-lesson dedup and aging (the same convention learned repeatedly bloats the store and contends for the 4000-char recall cap): eidetic supersedes/shadowing is the mechanism, the criteria are undecided this arc

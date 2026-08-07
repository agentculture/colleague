# Build Plan — self-learning arc

slug: `self-learning-arc` · status: `exported` · from frame: `self-learning-arc`

> Colleague now learns from its own runs: every work item's remember-after can distill a validated cause-to-lesson record (never fabricated filler), ordinary coding tasks grow a per-repo code-lesson ledger from correction diffs and gate fixes, and a bounded strive mode turns repeated failure into recalled lessons and testable hypotheses with an executable measure.

## Tasks

### t1 — Rung-1 completion: fold lint/test-integrity/affected-tests substance into `compose_lesson_text`

- instruction: Extend `compose_lesson_text` in colleague/memory.py ONLY (keep the telemetry prefix stub-compatible); bound each folded field like the existing incompletion folds (120/200-char caps); tests in tests/`test_loop_memory.py`
- covers: c3, h3
- acceptance:
  - A result carrying `lint_report` / `test_integrity_report` / `affected_tests_report` folds each into the lesson text, bounded per field, substance verbatim
  - A result without those reports produces byte-identical lesson text to the current rung-1 shape, same work-lesson-<`task_id`> upsert id — pinned in tests/`test_loop_memory.py`

### t2 — Distillation lesson schema + strict validator (pure module)

- instruction: New pure-stdlib colleague/lessons.py + tests/`test_lessons.py`; tolerant JSON extraction may mirror plan/`cli_driver`'s balanced-object approach but validation is strict refuse-whole (the lattice's unknown-key stance); no I/O, no subprocess
- covers: c9, h9
- acceptance:
  - `validate_lesson` accepts only {cause, lesson, `next_delta`} — non-empty strings within bounded lengths; missing key, extra key, empty, over-length, or non-JSON input refuses the WHOLE lesson
  - An invalid distillation yields the honest no-lesson-extracted marker, never a partial or repaired lesson — pinned by a garbage-completion test

### t3 — Feedback author provenance: operator vs cortex records side by side

- instruction: colleague/feedback.py: author field (operator|cortex), storage shape that lets both coexist per `task_id`; feedback record gains --author defaulting to operator; do not touch export filtering here (next task)
- covers: c17, h14
- acceptance:
  - FeedbackRecord carries an author field (default operator); legacy records without it load as operator — back-compat pinned
  - A cortex-authored record lands beside an operator record for the same `task_id`, never overwriting it; both readable via feedback show

### t4 — Flywheel exclusion filter: cortex-authored records out of export by default

- instruction: feedback export gains the author filter (default operator-only, explicit --include-cortex-authored opt-in); document in the export docstring WHY (a model grading its own work must not train itself)
- depends on: t3
- covers: c30, h25
- acceptance:
  - `export_work_items` defaults to operator-authored records only; including cortex-authored requires an explicit opt-in flag — pinned by a test on the filter

### t5 — Handoff persists the colleague/<id> branch tip SHA onto TaskResult

- instruction: colleague/handoff.py records the branch tip at handoff time; colleague/contract.py gains the optional field following the omit-when-None convention (mode/memory/media precedent)
- covers: c5
- acceptance:
  - TaskResult gains an omit-when-None tip commit SHA field populated at handoff; old artifacts load unchanged (round-trip pinned)
  - The field survives artifact JSON round-trip and is present after a successful handoff in the e2e mock flow

### t6 — Plan-mode raw-capture on total claim-parse failure (#376 diagnosability)

- instruction: colleague/plan/`cli_driver.py` `make_propose_claims` total-failure path; keep the existing ValueError message stable, append the capture location
- covers: c15, h12
- acceptance:
  - A total claim-parse failure persists the raw proposal text (plan artifact dir or stderr) before raising; a test asserts its presence and the error names where it landed

### t7 — Correction-diff capture module: tip vs merge commit, scoped to changed files

- instruction: New colleague/correction.py: resolve the squash commit via gh pr view --json mergeCommit when `pr_url` is present (degrade offline to the honest no-diff record); git diff <tip>..<merge> -- <`changed_files`>; no daemon, no polling
- depends on: t5
- covers: c5, h5, h28
- acceptance:
  - Given tip SHA + resolved merge commit + `changed_files`, returns per-file hunks scoped to exactly those files; ANY missing fact yields an honest no-diff record naming the missing fact — never a diff against a guessed base
  - A code-lesson built from a hunk quotes the hunk verbatim as its evidence field; interpretation fields are marked origin=model
  - tests/`test_boundary.py` `_SUBPROCESS_ALLOWED` gains the module with a stated reason (or the module reuses handoff.py helpers)

### t8 — Code-lesson record type + builders

- instruction: colleague/memory.py builders only (no loop wiring here); evidence is verbatim substance (a lint-fix line, a failing-test name, a diff hunk); confidence is a bounded enum/float, honest default low
- depends on: t1
- covers: c4, h4
- acceptance:
  - `build_code_lesson_record` produces type=code-lesson records with an id namespace that can never collide with work-lesson-<`task_id`> upserts; fields {area, convention, evidence, confidence}
  - A store-less repo remains a zero-subprocess no-op (the triple gate is untouched)

### t9 — Rung-2 seam in the loop: distillation pass + attempts/validated counters + independent kill switch

- instruction: colleague/loop.py `_maybe_remember_lesson` + colleague/config.py only (validator comes from t2's lessons.py); the distillation call is an injectable seam for tests; effective only when an author seat resolves (t10), else the rung-1 floor
- depends on: t1, t2
- covers: c2, h2, c28, h23, c29, h24
- acceptance:
  - With rung 2 armed and a valid distillation, the remembered record carries the lesson; with validation failing, the rung-1 record plus the no-lesson-extracted marker (garbage-completion test)
  - TaskResult.memory carries `distill_attempts` / `distill_validated`; a never-validating seam shows attempts>0, validated=0 — the armed-is-not-alive counter
  - Rung 2 disarmed while memory stays armed = byte-identical rung-1 output, via its own knob (config `memory_distill` / `COLLEAGUE_MEMORY_DISTILL`), pinned

### t10 — Distillation author-by-role + bounded observable background child

- instruction: New colleague/distill.py child entry (re-reads the persisted artifact, distills, validates via lessons.py, upserts the SAME work-lesson id with the lesson folded, writes distill.json outcome next to the artifact); reuse background.py's detach helper; role resolution mirrors deepthink/lobes precedence (env/config always win)
- depends on: t9
- covers: c16, h13, c31, h26
- acceptance:
  - The author resolves BY ROLE: lobes cortex when armed, the deepthink/muse target in dual-model mode, unarmed = no completion and the rung-1 floor byte-identical — pinned
  - The child detaches via the sanctioned one-shot pattern (`start_new_session`, no wait/poll — boundary test extended); outcome diagnosable as pending/done/dead from an outcome marker; a killed child leaves no partial record (validate-then-single-remember, atomic)
  - The run's return is never blocked by distillation

### t11 — Doctor surfaces the distillation alive-counter

- instruction: Extend the doctor usage/memory group; read-only over artifacts + distill.json markers; no network
- depends on: t10
- covers: c28
- acceptance:
  - doctor reports distillation attempts vs validated from recent artifacts/outcome markers and WARNS when attempts>0 with validated=0 — armed-is-not-alive made operator-visible

### t12 — Seamless auto-trigger lane: grade-time + colleague-action capture, observable

- instruction: Wire at feedback record time (colleague/feedback.py) + a best-effort check at work start; both write code-lessons via t8 builders from t7 hunks; keep every trigger observable in the artifact or feedback record — nothing silent
- depends on: t3, t7, t8
- covers: c18, h15
- acceptance:
  - feedback record auto-triggers correction-diff capture when the graded artifact carries `pr_url` + tip SHA; the outcome (fired / skipped and why) is recorded observably
  - A capture failure never blocks or fails the grade (pinned)
  - A work item's start can detect an uncaptured merged predecessor and capture it (colleague's own action as trigger), same observability

### t13 — Strive core: verb + episode driver + four enforced phases + hypothesis ledger

- instruction: New colleague/strive.py + colleague/cli/`_commands`/strive.py (`register_into` pattern, host command); reuse `execute_work_chain`-style episode dispatch, do NOT touch chain.py's allow-list; novelty match v1 = normalized exact match (semantic matching stays parked per the frame park); ledger rides eidetic via memory.remember plus a local .colleague/strive/<goal-id>.json working file
- covers: c6, h6, c8, h8
- acceptance:
  - colleague strive <goal> --attempts N --measure <cmd> drives bounded attempts via the episode machinery; the delta declaration is recorded BEFORE execution; an attempt that cannot name a delta or new hypothesis is recorded as exactly that
  - A per-goal hypothesis ledger persists schema-enforced records {goal, attempt, score, hypothesis, test, result supported|refuted, cause, lesson, next-delta}; K consecutive refuted-recombinations = a recorded novelty stall, never fabricated progress
  - chain.`CONTINUABLE_REASONS` is pinned unchanged == {budget-exhausted}; strive's retry policy lives in its own module

### t14 — Strive measure execution: approval-gated, episode-worktree cwd

- instruction: Measure runs after each episode inside that episode's worktree; route the command string through colleague/policy.py exactly as `run_command` does; score = exit code or last printed number, recorded per attempt
- depends on: t13
- covers: c7, h7, c33, h27
- acceptance:
  - The measure command routes through the same approval-gate check as `run_command` (policy gate, not a sandbox, absent-file default unchanged — documented)
  - A test asserts the measure subprocess cwd is the episode worktree, never the operator tree

### t15 — 35B plan-grammar fix: the claim proposal parses on the worker model (#376 fix)

- instruction: Use t6's raw capture to see what the 35B actually emits, then adapt `CLAIMS_`\* prompts or parse tolerance in colleague/plan/`cli_driver.py`; never weaken the anti-fabrication stance (skipped hallucinated entries stay skipped)
- depends on: t6
- covers: c27, h22
- acceptance:
  - The t14-failing invocation (colleague plan run --model unsloth/Qwen3.6-35B-A3B-NVFP4 --no-workforce --review --yes) reruns to a parsed frame, OR the raw capture diagnoses the format gap and the limitation is documented honestly — either outcome recorded

### t16 — INTEGRATION: wire the lanes end-to-end + behavior-level e2e gate

- instruction: This task OWNS composition: read every prior task's seam and wire what is dangling; the e2e lives in a new tests/`test_e2e_selflearning.py`; the #380 lesson is the reason this task exists — behavior, not properties
- depends on: t9, t10, t12, t14
- covers: c1, h1, c22, h17, c24, h19
- acceptance:
  - One behavior-level e2e (mock engine + fake eidetic CLI + scripted distillation seam): a deliberately failed run produces a rung-1+rung-2 record, a SECOND run's recall-before surfaces it, and the assertion checks record CONTENT verbatim (incompletion reason + evidence + lesson), not mere existence
  - Every lane (rung-1 fold, rung-2 seam, code-lessons, auto-trigger, strive) is reachable from its front — no green-but-unwired module (#380: composition is explicit work)

### t17 — Live proofs + ablations: distillation on the rig, #378 correction ablation, #377 NEBULA strive ablation

- instruction: Rig serializes: run sequentially, cap concurrency at 1; the NEBULA goal is 'make `smart_bot` beat `dumb_bot` by margin M across S seeded runs' per #383; record everything in docs/live-testing.md ledger rows + the artifacts
- depends on: t16
- covers: c25, h20, c26, h21
- acceptance:
  - A live failed-run distillation on the rig validates, or the schema-validity gap is recorded (the deferred probe from the challenge pass) — either outcome recorded
  - The #378 ablation recipe is recorded via the experiment noun and evaluated (`lines_ON` < `lines_OFF`), or honestly recorded as pending with the recipe executable
  - The NEBULA strive ablation runs recall-ON vs recall-OFF (same goal, measure, seeds, attempt cap) and records `attempts_ON` vs `attempts_OFF`; equal-or-worse is recorded as FALSIFYING the memory link

### t18 — Docs + ninth-increment scope line + version bump

- instruction: Follow the trim discipline (few lines + pointer doc); fix the flywleel typo in this instruction when writing (flywheel); use the version-bump skill
- depends on: t16
- covers: c21, h16, c23, h18
- acceptance:
  - docs/features/memory.md updated (rung 2, counters, kill switch, author-by-role); a new feature doc covers strive + the learning lanes with Honest limits; CLAUDE.md gains the architecture bullet and records strive as the NINTH sanctioned increment with its FIXED enumerated surface
  - The docs name both lesson consumers (recall-before + the flywleel lane) and quote the before-state stub specimens as reproducible evidence
  - Version bumped + CHANGELOG entry (version-check CI gate)

### t19 — Boundary + invariant pins: verbs allow-list, remember/recall invariants

- instruction: Tests only (tests/`test_boundary.py` + a new tests/`test_memory_invariants.py` to avoid t1 file contention); runs with no deps — good early wave filler
- covers: c10, h10, c11, h11
- acceptance:
  - `ALLOWED_VERBS` pinned frozenset({recall, remember}) and the boundary test proves no new eidetic verb is reachable from any new module
  - A remember failure (absent CLI / non-zero exit) still returns the work-item result unchanged; a recall failure injects nothing and never raises — both pinned

## Risks

- [unknown_nonblocking] Live schema-validity of the served cortex JSON for distillation is unproven (#376 shows the 35B fails prompted-JSON); the degrade floor + alive-counter contain it, t17 measures it
- [unknown_nonblocking] Concurrent eidetic writes: a detached distillation child upserting while the next run recalls/remembers is unverified under the jsonl store; bounded child window + atomic validate-then-remember mitigate
- [unknown_nonblocking] gh / mergeCommit resolution is unavailable offline or on non-GitHub remotes — correction capture degrades to the honest no-diff record
- [unknown_nonblocking] Novelty detection v1 is normalized exact-match on hypotheses; semantic matching stays parked with the embedder lane (#277) per the frame park
- [unknown_nonblocking] Rig time + NEBULA benchmark availability gate t17's ablations; a pending-but-executable recipe is the honest fallback
- [follow_up] Flywheel adapter serving (which models get the QLoRA layer) is deliberately out of this arc - parked as colleague#384

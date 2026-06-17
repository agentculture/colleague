# Build Plan — colleague's write/TDD hands back tests that can actually fail — a test no longer passes just because it mirrors the implementation's own bug. Fixtures match the real API shape, suspicious test/impl mirroring is flagged, and a diverse second mind can vet the test before it's trusted.

slug: `colleague-s-write-tdd-hands-back-tests-that-can-ac` · status: `exported` · from frame: `colleague-s-write-tdd-hands-back-tests-that-can-ac`

> colleague's write/TDD hands back tests that can actually fail — a test no longer passes just because it mirrors the implementation's own bug. Fixtures match the real API shape, suspicious test/impl mirroring is flagged, and a diverse second mind can vet the test before it's trusted.

## Tasks

### t1 — Detection core + contract report shape: new colleague/testintegrity.py (pure-stdlib mirror-detection heuristic) + TestIntegrityReport/MirrorFinding types + TaskResult.test_integrity_report field (omit-when-None)

- covers: c9, h2
- acceptance:
  - colleague/testintegrity.py is pure stdlib (zero-deps guard passes; no new sanctioned subprocess consumer)
  - Given a changed test file and a changed module-under-test, the heuristic flags an unusual identifier (attribute access OR string-literal dict key) co-introduced in BOTH yet found nowhere else in the repo
  - Flags response_error AND TotalEstimate on the two #203 examples; records findings (advisory), never raises
  - TaskResult.test_integrity_report defaults to None and is omitted from to_dict() when None (tests/test_e2e_mock.py shape unchanged)

### t2 — Test-integrity GATE in the loop: _maybe_run_test_integrity_gate sibling to _maybe_run_lint_gate — runs post-loop on changed files regardless of model, best-effort wrapped, attaches report; never blocks handoff, no network

- depends on: t1
- covers: c16, c14, h6, h13
- acceptance:
  - Gate runs on every non-aborted loop exit for BOTH mock and vllm-openai (all-engines), on the work item's changed files only
  - Wrapped so any exception is swallowed and never aborts the work item; the git handoff always proceeds
  - Records TaskResult.test_integrity_report; makes no network/socket call (boundary test enforces)
  - A no-finding run is byte-identical (report omit-when-None); e2e mock shape test passes

### t3 — Bounded re-examine turn: on a flagged finding + clean _EXIT_FINISHED + live backend, inject ONE bounded model re-examine turn (reuse lint-fix-turn pattern; save/restore terminal summary+status); knob COLLEAGUE_TESTINTEGRITY_FIX_RETRIES on EngineConfig forwarded via ContextControls by both backends

- depends on: t2
- covers: c17, h7
- acceptance:
  - On a flagged finding + clean finish + live backend, exactly one bounded re-examine turn fires; default keeps behavior conservative
  - The re-examine turn's own finish cannot clobber the real terminal summary/status (saved+restored, lint-fix-turn precedent)
  - Strict no-op on mock / no live backend; both backends forward the knob identically (all-engines)

### t4 — Diverse-model reviewer subagent + non-load-bearing nudge: on a flagged finding auto-spawn a DIFFERENT-model reviewer via colleague.subagents (no new worktree/merge code) to independently re-derive the fixture; degrade to record-only without a 2nd model; add one non-load-bearing test-integrity nudge line to _DEFAULT_SYSTEM

- depends on: t3
- covers: c18, h8
- acceptance:
  - Reviewer reuses colleague.subagents (make_batch_spawn/batch_spawn or single subagent path) with NO new worktree/merge code, bounded by existing MAX_SUBAGENT_DEPTH/FANOUT caps
  - Degrades to record-only when no second model is configured; never blocks handoff
  - A single non-load-bearing nudge line is added to _DEFAULT_SYSTEM; removing/ignoring it does not change gate enforcement (harness is source of truth)

### t5 — Model-callable check_test_integrity loop tool in colleague/tools.py, reusing the SAME detection from colleague/testintegrity.py; offered to every backend (all-engines); optional/model-judged, the gate enforces regardless

- depends on: t1
- covers: c19, h9
- acceptance:
  - check_test_integrity tool added to colleague/tools.py and exposed to every backend identically (all-engines)
  - Reuses t1 detection (one detection implementation; no duplicate logic)
  - e2e mock shape test + zero-deps guard still pass

### t6 — #203 acceptance fixtures: reproduce both scenarios (AWS exc.response_error vs exc.response; Cost Explorer TotalEstimate vs Total) as runnable tests asserting the gate flags the co-introduced novel symbol so the false positive is CAUGHT not shipped

- depends on: t1, t2
- covers: c1, c3, c4, c15, h4, h5, h14
- acceptance:
  - Both #203 scenarios encoded as fixtures; the heuristic/gate flags response_error and TotalEstimate (present in both test+impl, nowhere else)
  - A 'before' assertion demonstrates the mirrored test would pass today while the gate now flags it — 'a test can actually fail' is mechanically shown
  - Fixtures are deterministic, stdlib-only, and pass under pytest -n auto

### t7 — Feature doc docs/features/test-integrity.md: audience, before/after, why it matters, the two #203 examples, and honest limits (advisory, non-blocking, Python-only v0, not a correctness oracle)

- depends on: t2
- covers: c2, c5, h10, h11, h12
- acceptance:
  - Doc names the audience (operators/agents trusting a green colleague suite) and why it matters (TDD false-assurance erodes delegation trust)
  - Doc cites the two real #203 false positives (response_error/response; TotalEstimate/Total) and notes #203 was filed by this audience (ec2-cli)
  - Doc states the before-state (grep shows no test-first guidance today) and the honest limits/boundary

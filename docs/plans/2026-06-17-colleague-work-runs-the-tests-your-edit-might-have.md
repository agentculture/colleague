# Build Plan — colleague work runs the tests your edit might have broken — not just the ones it was told to run — before handing back

slug: `colleague-work-runs-the-tests-your-edit-might-have` · status: `exported` · from frame: `colleague-work-runs-the-tests-your-edit-might-have`

> colleague work runs the tests your edit might have broken — not just the ones it was told to run — before handing back

## Tasks

### t1 — [Claude — risky core] colleague/affectedtests.py: bounded-depth transitive reverse-import selection + pytest execution + AffectedTestsReport

- covers: c8, h8, c9, h3, h1
- acceptance:
  - ast graph collects ALL imports incl. function-local/lazy ones (ast.walk over the whole tree), so an edge created by a lazy import inside a function (e.g. colleague.cli register()) is present
  - select_affected_tests(changed) returns test files whose bounded-depth (default N>=3) transitive import closure reaches a changed module; a test reaching it only via a depth-3 lazy chain IS selected; vendored trees (.venv/.git/node_modules) pruned
  - selection capped at a max-files limit; on overflow the report records selected X of Y with capped=True, never silently dropping
  - run_affected_tests runs pytest only on the selected files and returns AffectedTestsReport{status,passed,failed,selected,total,capped,reason}; pytest unavailable -> status='skipped' with a reason, never raises

### t2 — [colleague] colleague/contract.py: TaskResult.affected_tests_report (omit-when-None)

- covers: c10, h4
- acceptance:
  - TaskResult gains affected_tests_report; when None the serialized dict OMITS the key entirely (like lint_report/test_integrity_report)
  - a populated report round-trips through TaskResult serialization with no runtime import cycle (TYPE_CHECKING annotation)

### t3 — [colleague] colleague/config.py: EngineConfig affected-tests knobs + resolution precedence

- covers: c12
- acceptance:
  - EngineConfig resolves affected_tests (default True), affected_tests_fix_retries, affected_tests_depth (default >=3), affected_tests_max_files, and the --test override; precedence flag > env (COLLEAGUE_AFFECTED_TESTS*) > .colleague/config.json > default
  - affected_tests=False resolves cleanly and is the single switch the gate consults to no-op

### t4 — [Claude — spine] colleague/loop.py: _maybe_run_affected_tests_gate wiring + bounded model fix-turn + ContextControls

- depends on: t1, t2, t3
- covers: c4, c9, c10, c6, h13, h11
- acceptance:
  - _maybe_run_affected_tests_gate runs after a non-aborted loop and before handoff (sibling to _maybe_run_lint_gate); populates TaskResult.affected_tests_report and NEVER blocks the handoff (handoff proceeds on failures)
  - on failures after a clean finish, up to affected_tests_fix_retries bounded model fix-turns run and re-run the gate, saving/restoring the work item's terminal summary/status; 0 retries = detect-and-record only
  - strict no-op (report None, byte-identical TaskResult) when disabled / no files changed / no affected tests selected

### t5 — [colleague] colleague/cli/_commands/work.py: --no-affected-tests + --test override flags

- depends on: t3
- covers: c2, h9
- acceptance:
  - colleague work exposes --no-affected-tests and --test "<pytest args>"; flags override env/config (precedence flag > env > config), applied post-resolve like --no-lint

### t6 — [colleague] tests/test_boundary.py: add affectedtests.py to the sanctioned subprocess allow-list

- depends on: t1
- covers: c11, h5
- acceptance:
  - tests/test_boundary.py adds colleague/affectedtests.py to the sanctioned subprocess allow-list and still FAILS if any OTHER module imports subprocess; pyproject 'dependencies' stays []

### t7 — [colleague] engines/mock.py + engines/vllm_openai.py: forward affected-tests config (all-engines)

- depends on: t3, t4
- covers: c12, h6
- acceptance:
  - both mock and vllm_openai forward the affected-tests config into ContextControls identically (all-engines)
  - tests/test_e2e_mock.py passes byte-identical with the gate disabled

### t8 — [Claude — correctness proof] tests: #210/t2 transitive regression + before/after + gap-not-covered

- depends on: t4, t1
- covers: c7, c3, h1, h10, h12, h14, h6
- acceptance:
  - a regression test reproduces the #210/t2 shape — a module reachable from a sibling test ONLY via a transitive (incl. lazy) import chain — and asserts the gate selects that sibling test and its failure appears in the report
  - a before/after test shows gate-absent the sibling test is never run (green-on-scope) and gate-present its failure is surfaced; plus a test asserting neither lint #200 nor test-integrity #203 selects a cross-file test

### t9 — [colleague] docs/features/affected-tests.md + CLAUDE.md runtime bullet

- depends on: t4
- covers: c1, c5
- acceptance:
  - docs/features/affected-tests.md documents selection/execution/config/honest-limits and CLAUDE.md gains a runtime bullet consistent with the lint/test-integrity bullets

## Risks

- [unknown_nonblocking] Exact pytest invocation inside the isolated worktree (uv run pytest vs PATH pytest vs python -m pytest); the worktree shares .git but not necessarily an installed .venv — v0 degrades to 'skipped' when pytest is not runnable, but the preferred invocation is open (task t1)
- [unknown_nonblocking] Numeric defaults for affected_tests_depth (>=3) and affected_tests_max_files + an overall wall-clock budget — the CLI-hub transitive fan-out makes the file cap load-bearing; chosen conservatively, tunable via env (task t3)

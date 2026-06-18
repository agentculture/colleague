# colleague work runs the tests your edit might have broken — not just the ones it was told to run — before handing back

> colleague work runs the tests your edit might have broken — not just the ones it was told to run — before handing back

## Audience

- An agent/operator delegating a scoped edit to 'colleague work' (and via 'ask-colleague write --apply'); and the human integrator who is currently the ONLY backstop that re-runs the broader suite

## Before → After

- Before: The two pre-handoff gates — lint (#200, colleague/lint.py) and test-integrity (#203, colleague/testintegrity.py), both wired in colleague/loop.py after the loop and before handoff — operate ONLY on the work item's changed FILES; nothing runs tests in OTHER files that exercise the changed module, so green-on-scope can hide red-on-suite (the #210/t2 instance: green on tests/test_plan_cli_driver.py, 3 failures in tests/test_cli_plan.py)
- After: Before the git handoff, colleague auto-selects the test files that import the changed module(s) and runs them; failures are surfaced advisory + non-blocking on TaskResult and stderr, so a scoped edit that regresses a sibling test file is flagged by colleague itself, sooner — not only by the integrator's re-run

## Why it matters

- colleague's pre-handoff safety net is incomplete: a delegated work item can hand back code that is green on its own scoped test yet red on the broader suite, relying entirely on the human to notice. colleague should give the signal itself

## Requirements

- Selection: a reverse-import scan via stdlib 'ast' over the repo's test files (test_*.py / *_test.py), selecting those that import the changed module(s); prune vendored trees (.venv/.git/node_modules/...) reusing the testintegrity repo-scan pattern; bounded by a cap on the number of selected files
  - honesty: Selection = BOUNDED-DEPTH transitive reverse-import. Build the repo module import graph with stdlib ast collecting ALL imports (function-local/lazy included, via ast.walk over the whole tree — NOT just module-level: colleague's CLI registers every command via a lazy import inside register(), and the motivating edge colleague.cli -> colleague.cli._commands.plan is exactly such a lazy import). Select a test file iff a changed module is within DEPTH N of its import closure. Default N must reach the motivating case: cli_driver sits 3 edges from tests/test_cli_plan.py, so default N>=3 (tunable). The selected set is bounded by a file cap; on overflow report 'selected X of Y (capped)' honestly, never silent truncation.
- Execution: run pytest on the selected files via subprocess, pre-handoff, after the tool loop, inside the isolated worktree (a sibling to colleague/loop.py _maybe_run_lint_gate / _maybe_run_test_integrity_gate); degrade to a recorded 'skipped' (never crash) when pytest or the env is unavailable
  - honesty: pytest runs only on the selected files, inside the work item's isolated worktree, and a missing/unrunnable pytest degrades to report.status='skipped' with a reason — never a traceback and never a blocked handoff
- Reporting: results recorded on TaskResult.affected_tests_report (omit-when-None, like lint_report / test_integrity_report) and surfaced on stderr; the gate is ADVISORY and NON-BLOCKING — the git handoff always proceeds even on failures
  - honesty: affected_tests_report is omitted entirely (key absent) when the gate did not run, matching lint_report/test_integrity_report; failures appear on stderr + in the artifact but never change the work exit code or block the handoff
- Boundary/conventions: a NEW sanctioned subprocess consumer module (e.g. colleague/affectedtests.py) is added to tests/test_boundary.py's allow-list and no other module gains subprocess; zero new runtime deps (stdlib ast/subprocess/json only)
  - honesty: tests/test_boundary.py is updated to add the new module to the sanctioned subprocess allow-list and still fails if ANY other module imports subprocess; pyproject 'dependencies' stays []
- All-engines + strict no-op: runtime-owned, fires identically for mock and vllm-openai (both backends forward config via ContextControls); a run with the gate disabled, no affected tests selected, or no pytest available is byte-identical to today's TaskResult
  - honesty: tests/test_e2e_mock.py still passes with the gate disabled (byte-identical TaskResult) and both mock + vllm-openai forward the new config field via ContextControls

## Honesty conditions

- The #210/t2 case (edit colleague/plan/cli_driver.py, green on tests/test_plan_cli_driver.py) actually surfaces the 3 tests/test_cli_plan.py failures pre-handoff once the gate runs — i.e. the reverse-import scan selects test_cli_plan.py because it imports the changed module
- The feature changes the experience for a delegator of a scoped colleague work item (incl. ask-colleague write --apply) and shrinks what the human integrator must catch by hand; it does not target the interactive session user (session keeps its in-place path).
- On main TODAY (gate absent), editing colleague/plan/cli_driver.py and running only tests/test_plan_cli_driver.py finishes status: ok while tests/test_cli_plan.py is red — the gap is reproducible, not hypothetical.
- After the change, the same scoped edit selects + runs tests/test_cli_plan.py before handoff and the report carries its failures, so the model/operator sees them without the integrator re-run.
- The gap is real and not already covered: neither lint #200 nor test-integrity #203 runs any test living in a file other than the changed ones — verifiable by reading colleague/lint.py + colleague/testintegrity.py (both scope strictly to changed files).
- The implementation never runs the full suite unconditionally, never blocks the handoff, opens no socket/daemon, adds no runtime dep, and touches no language other than Python/pytest — each enforceable by a test (boundary + e2e shape + non-blocking).
- A regression test reproduces the #210/t2 shape (a changed module reachable only TRANSITIVELY from a sibling test) and asserts the gate selects + reports that sibling test's failure; and tests/test_e2e_mock.py stays byte-identical with the gate disabled.

## Success signals

- The #210/t2 replication (edit cli_driver.py, green on test_plan_cli_driver.py) now surfaces the 3 test_cli_plan.py failures in the report + stderr BEFORE handoff; and a run with the gate disabled / no affected tests / no pytest available is a strict no-op (byte-identical TaskResult); fires identically for mock and vllm-openai

## Scope / boundaries

- NOT a full-suite runner (never always run everything — slow, out of scope of a scoped task); NOT a CI replacement or correctness oracle (best-effort selection); NOT a blocking gate (advisory, non-blocking, handoff always proceeds, like lint/test-integrity); NOT a router/sandbox/daemon; Python/pytest only (other languages a follow-up); the integrator re-run stays the backstop

## Decisions

- DEFAULT POSTURE = DEFAULT-ON with opt-out (matches lint #200 / test-integrity #203 posture). Disable via --no-affected-tests / COLLEAGUE_AFFECTED_TESTS=0 / .colleague/config.json {affected_tests:false}. Rationale: maximize 'colleague gives the signal sooner'; the file cap + advisory/non-blocking nature bound the cost.
- SELECTION = bounded-depth transitive reverse-import via ast over ALL imports (nested/lazy included); default depth bound >=3 (reaches the motivating case), tunable via env; plus a cap on the number of selected test files. Direct-only and name-matching are rejected (both miss the #213 case).
- ON FAILURE = record + surface AND a bounded model fix-turn (like the lint gate's COLLEAGUE_LINT_FIX_RETRIES): on failures after a clean finish, inject one bounded model turn to fix, re-run the gate (saves/restores the work item's terminal summary/status). Knob COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES on EngineConfig; non-blocking; needs a live backend (no-op on mock).
- CONFIG SURFACE = an enable/disable toggle (flag/env/.colleague config) PLUS an explicit override knob --test "<pytest args>" to run a caller-chosen selection instead of/in addition to the auto selection; precedence flag > env > config, matching the lint gate.

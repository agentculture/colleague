# affected-tests — run the tests that transitively import your changed module(s)

> `colleague work` (and `drive`, and `ask-colleague write --apply`) runs the tests
> that **transitively import** the work item's changed module(s) before the git
> handoff, so a scoped edit cannot hide a regression in another file the model
> never ran. Born from #210/t2, where a change to `colleague.plan.cli_driver`
> broke `tests/test_cli_plan.py` but the model never ran that test — it only
> touched `cli_driver.py` and the test reaches it only through a depth-3 lazy
> CLI-register import chain.

The affected-tests gate is an **advisory, non-blocking pre-handoff check** (#213)
that runs on every work item by default. It is **non-blocking**: the handoff
always proceeds; any failure is surfaced (stderr + the `affected_tests_report` in
the JSON artifact), never wedging the work item.

## What it does

After the tool loop, before the git handoff, the gate selects the test files
whose **bounded-depth transitive import closure** reaches a changed module and
runs `pytest` on them. This catches regressions in files the model never
touched — the gap between "I edited module X" and "test Y imports X
transitively and now fails."

## Bounded-depth transitive reverse-import selection (`colleague/affectedtests.py`)

The gate builds the repo's module import graph with `ast`, collecting **all**
imports — including **function-local / lazy** ones (`ast.walk` over the whole
tree, not just the module body). This matters: colleague registers every CLI
command via a lazy `from colleague.cli._commands import <cmd>` **inside**
`register()`, so a module-level-only graph would dead-end at the `colleague.cli`
hub and miss every transitively-affected test.

For each test file, the gate computes the modules reachable within `depth` hops
of its import closure and selects it iff a changed module is in that set. The
default depth (`_DEFAULT_DEPTH` = 3) reaches the #210/t2 motivating case:
`tests/test_cli_plan.py` imports only `colleague.cli` but transitively reaches
the changed `colleague.plan.cli_driver` at depth 3
(`test_cli_plan → colleague.cli → (lazy) _commands.plan → cli_driver`).

### File cap (honest, never silent)

Because the CLI hub fans out widely, the selected set is **capped**
(`_DEFAULT_MAX_FILES` = 20). On overflow the report records `total` vs the
capped `selected` honestly (`capped=True`) — never a silent truncation.

## Execution via pytest

The gate runs `pytest` on the selected files via `subprocess`. A missing or
unrunnable pytest degrades to `status='skipped'` with a reason — never a
traceback and never a blocked handoff. Zero runtime dependencies beyond the
stdlib; this is a sanctioned `subprocess` consumer.

### The `--test` override

Passing `--test <pytest-args>` bypasses the transitive selection entirely and
uses the explicit pytest arguments verbatim. This lets the operator target
specific tests without running the full transitive fan-out.

## The affected-tests GATE (`colleague/loop.py` `_maybe_run_affected_tests_gate`)

The gate is a **deterministic, code-locked** post-loop check, sibling to the
lint and test-integrity gates. It runs on every non-aborted loop exit for
**both** `mock` and `vllm-openai` backends (the all-engines rule) — the model
cannot skip it.

The gate is **best-effort wrapped** so any exception is swallowed and never
aborts the work item. The git handoff always proceeds.

### Bounded model fix-turn

On a `failed` status after a clean finish, the runtime injects **one bounded
model fix-turn** per remaining retry (capped by
`COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES`, default `1`) asking the model to
investigate and fix the regression in the implementation (not weaken or delete
the tests), then re-runs the gate.

With the knob at `0`, only the detection and recording happen. The fix-turn
needs a live backend; on the `mock` backend it is a no-op.

## Opt-out (default-ON)

The gate is **ON by default**. Disable it with:

- the `--no-affected-tests` flag,
- `COLLEAGUE_AFFECTED_TESTS=0`, or
- `.colleague/config.json` `{"affected_tests": false}`.

**Precedence:** flag > env > config > default-on.

## Where the report lands

`TaskResult.affected_tests_report` — an `AffectedTestsReport` with `status`,
`selected`, `total`, `capped`, `passed`, `failed`, and `reason`. The field is
**omitted** from the artifact when the gate did not run (omit-when-None), so a
no-op run is byte-identical to a run without the gate.

## Worked example

The gate runs quietly inside the work item. The only thing it prints (to
**stderr**) is the affected-tests summary; the full record is in the artifact's
`affected_tests_report`.

The common case — all affected tests pass:

```text
$ colleague work "refactor the plan CLI driver" --repo .
… (work item runs; the gate runs affected tests) …
affected-tests: passed — 3 file(s): 12 passed
status: ok
task: a1b2c3d4e5f6
```

When tests fail, the failure is surfaced on stderr and recorded — but the
handoff still proceeds (non-blocking):

```text
affected-tests: failed — 2 file(s): 8 passed, 1 failed
```

Disable the gate for a run with `--no-affected-tests`.

## Honest limits

- **Python/pytest only.** The gate requires a runnable `pytest` in the isolated
  worktree; when unavailable it is recorded as `skipped` and the handoff
  proceeds. The integrator re-run stays the backstop.
- **Best-effort selection.** The AST-based import graph is a best-effort
  approximation: it captures all `ast.Import` and `ast.ImportFrom` nodes
  (including function-local / lazy ones) but cannot resolve dynamic imports
  (`importlib.import_module`, `__import__`) or string-based imports.
- **Advisory and non-blocking.** The gate flags failing tests but never blocks
  the git handoff. It reduces hidden regressions; it does not guarantee
  correctness.
- **Capped selection.** The file cap bounds handoff time; overflow is reported
  honestly (`capped=True`) but the unselected tests are not run.
- **Not a CI replacement.** The gate is a developer convenience; it does not
  substitute for CI test checks.

## See also

- [`docs/features/lint-gate.md`](lint-gate.md) — the sibling pre-finish lint gate (#200)
- [`docs/features/test-integrity.md`](test-integrity.md) — the sibling test-integrity gate (#203)
- [`docs/features/ask-colleague.md`](ask-colleague.md) — the `ask-colleague write --apply` path that triggers the gate
- [`docs/features/agent-cli.md`](agent-cli.md) — `colleague work` and `colleague drive` entry points

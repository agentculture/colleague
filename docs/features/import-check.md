# import-check — the importability gate that runs on every outcome

> `colleague work` (and `drive`, and `ask-colleague write --apply`) smoke-imports
> every changed `*.py` file after the tool-loop, on **every exit outcome** —
> finished, budget-exhausted, stalled — closing the gap the sibling gates leave:
> their bounded fix-turn only runs on a clean finish, but their FAILURE
> detection already ran on every outcome; import-checking had neither until
> this arc. Born from #482, filed against run `cc5d1f1a2c5f`
> (`docs/live-testing.md` row 67), which shipped a branch that did not import —
> a hallucinated `from colleague.hooks import Policy` and a lost `ToolCall`
> re-export breaking `colleague/engines/vllm_transport.py` — on a
> budget-exhausted outcome that told no one.

The import-check gate is the **fifth** pre-finish gate (sibling to lint,
coherence, test-integrity, affected-tests), and the first with **no bounded
fix-turn** at all — it is pure detection, always attempted, self-disabling.

## Why neither `black`/`flake8` nor `py_compile` alone catches it

`black`/`isort`/`flake8` never execute the module; a syntax-only `py_compile`
catches malformed syntax but not a missing symbol. `from colleague.hooks
import Policy` where `Policy` does not exist, or a re-export a downstream
module relies on silently vanishing, both compile cleanly and only fail at
**import time**. Only actually importing the module catches that.

## Two-stage check (`colleague/importcheck.py` `run_import_check`)

For each changed `*.py` file (repo-relative to the run's worktree):

1. **`py_compile.compile(path, doraise=True)`** — a fast syntax gate.
2. **A subprocess `python -c "import <dotted.module.name>"`** — the actual
   import smoke, the stage that catches #482's shape (a module that compiles
   but raises `ImportError`/`AttributeError` at import time).

### Worktree resolution (c20) — self-hosting must not pass vacuously

colleague is frequently used to edit its own installed package (colleague
editing colleague). If the import-smoke subprocess resolved `colleague` off
the ambient `sys.path` (an editable/site-packages install pointing
elsewhere), it could import the **installed** copy instead of the **worktree**
copy under test, and pass even though the worktree copy is broken. The fix:
the subprocess runs with `cwd=repo_path` (the `affectedtests.py` precedent)
**and** with `repo_path` prepended to the child's `PYTHONPATH`, ahead of
everything else — `sys.path[0]` wins module resolution over site-packages, so
the worktree copy is what actually gets imported.
`tests/test_importcheck.py` proves this is not vacuous: it makes an installed
`colleague` package differ from the worktree copy and asserts the *worktree*
version's error text is what gets reported.

## The gate (`colleague/loop_testgates.py` `_maybe_run_import_check_gate`)

Wired into `colleague/loop_gates.py`'s `_run_pre_finish_gates`, at the SAME
point the lint/coherence/test-integrity/affected-tests gates sit — after the
shared chain-episode deferral (#335, the same deliberate choice the
affected-tests gate makes: a mid-chain episode's tree is about to be rewritten
by the next episode, so a mid-chain import-check would grade intermediate
state the chain's final episode re-grades anyway).

**Unlike its four siblings, it takes no `outcome` argument** — it runs
identically regardless of the exit shape (mirrors `_maybe_run_coherence_gate`'s
`(ctx, aborted)` signature), because that IS the fix: the affected-tests gate
already caught run cc5d1f1a2c5f's broken import (reported `failed`), but a
non-finished outcome got zero fix turns and — before #480 — no
`TaskResult.warnings` entry either. #480 fixed the warning half for
affected-tests/test-integrity's own non-finished-outcome silence; this gate
closes the equivalent gap for import-checking specifically, by never
depending on a clean-finish path to surface the failure at all.

**No `ContextControls` enable flag.** Unlike the other three test gates, there
is no `ctx.*_enabled` toggle to check — `run_import_check` is already
self-disabling (`COLLEAGUE_IMPORT_CHECK=0`, an empty or non-`.py` changed set,
or an internal error all degrade to `status="skipped"` without spawning a
subprocess), so "always attempted, self-disabling" is the whole gate —
mirroring `colleague.lint`'s stance more than the enable-flag'd gates.

**No bounded fix-turn.** Out of scope for #482/t3; the gate is detection-only.

**Best-effort wrapped**, like every sibling gate: any exception is suppressed
and can never abort `run()` or block the git handoff.

## Opt-out (default-ON)

`COLLEAGUE_IMPORT_CHECK=0` disables the gate entirely — `run_import_check`
returns a `status="skipped"` report before spawning any subprocess. There is
no CLI flag (unlike affected-tests' `--no-affected-tests`); the env knob is
the only opt-out.

## Where the report lands

`TaskResult.importcheck_report` — an `ImportCheckReport` with `status`
(`"passed"` / `"failed"` / `"skipped"`), `checked` (the files actually
smoke-imported), `findings` (a list of `ImportCheckFinding`: `module`, `path`,
`stage` — `"compile"` or `"import"` — and `error`), and `reason` (the skip
cause). **Set on both `"passed"` and `"failed"`** — mirroring `lint_report`/
`coherence_report` (not `test_integrity_report`/`affected_tests_report`, which
stay `None` on a clean pass with no findings) — so a clean import-check run is
still visible on the artifact. Left `None`/omitted (omit-when-None
serialization) when the gate never ran at all (`status="skipped"`, or no
changed files reached the gate).

The `import-check-failed` warning
(`{"kind": "import-check-failed", "findings": [...], "count": N}`, naming
every failing module + its exact error text) is appended to
`TaskResult.warnings` **only** on `"failed"` — on every outcome the gate fails
on, finished included, since there is no clean-finish path that already
surfaces the failure a different way (contrast the affected-tests/
test-integrity warnings, below, which are non-finished-outcome-only because a
clean finish already gets a fix-turn).

## Worked example

```text
$ colleague work "refactor the vLLM transport module" --repo .
… (work item runs; the gate smoke-imports every changed .py file) …
import-check: failed — 1/3 file(s): colleague.engines.vllm_transport (import)
status: incomplete
task: a1b2c3d4e5f6
```

The failure is surfaced on **stderr** and recorded in
`importcheck_report`/`warnings` — but the handoff still proceeds
(non-blocking, like every pre-finish gate).

## Honest limits

- **Detection only — no fix-turn.** The gate names a broken import; it never
  attempts to repair it.
- **Python-only.** Only `*.py` files are checked; a broken non-Python import
  path (e.g. a native extension) is out of scope.
- **Subprocess overhead per changed file.** Each smoke-import is its own
  `python -c` subprocess (30 s timeout each); a large changed set costs
  proportionally more wall time than the AST-only affected-tests selection.
- **Not a correctness oracle.** A clean import proves the module *loads*; it
  says nothing about whether the code inside it is correct — the sibling gates
  and the tests themselves still own correctness.
- **Sanctioned `subprocess` consumer** — `colleague/importcheck.py` joins
  `tests/test_boundary.py`'s `_SUBPROCESS_ALLOWED` allow-list with a stated
  reason, alongside `affectedtests.py`/`lint.py`.

## See also

- [`docs/features/affected-tests.md`](affected-tests.md) — the sibling gate
  whose non-finished-outcome warning gap (#480) motivated this gate's
  "always warn, never depend on a fix-turn" design.
- [`docs/features/test-integrity.md`](test-integrity.md) — the other #480
  sibling gate.
- [`docs/features/lint-gate.md`](lint-gate.md) — the pre-finish gate whose
  "always attempted, self-disabling" stance this gate mirrors.
- [`docs/features/work-and-loop.md`](work-and-loop.md) — the loop that runs
  every pre-finish gate.

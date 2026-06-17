# test-integrity — mirror-signature detection for colleague-authored tests

> `colleague work` (and `drive`, and `ask-colleague write --apply`) runs the
> mirror-detection heuristic on the work item's **changed files** after the
> tool-loop, flagging identifiers co-introduced in both a test and its module
> under test yet found nowhere else in the repo — the mechanical signal that a
> test merely mirrors the implementation's own (possibly wrong) assumption.
> Born from #203, where a real caller (ec2-cli) trusted a green colleague-authored
> test suite as evidence of correctness and shipped two real bugs.

The test-integrity gate is an **advisory, non-blocking detection** (#203) that
runs on every work item by default. It is **non-blocking**: the handoff always
proceeds; any finding is surfaced (stderr + the `test_integrity_report` in the
JSON artifact), never wedging the work item.

## Audience

Operators who delegate `colleague write` and agents calling `ask-colleague
write` — anyone who trusts a green colleague-authored test suite as evidence the
change is correct.

## Before → After

- **Before:** Today there are zero test-quality guardrails. No test-first
  instruction exists anywhere (`_DEFAULT_SYSTEM` and `write.md` say nothing
  about tests), so the model derives a mock's shape from its own (possibly wrong)
  mental model of an external API, writes code that agrees, and both pass — a
  self-confirming false positive that ships the bug.
- **After:** The harness flags the mirror signature: a novel identifier
  co-introduced in both the changed test and the changed module-under-test, yet
  found nowhere else in the repo. The finding is recorded and surfaced, so the
  operator sees the red flag before trusting the green suite.

## Why it matters

These are exactly the bugs TDD exists to prevent. A self-confirming suite turns
colleague's green check into false assurance and erodes trust in delegated
field-work — the opposite of what "hand it to colleague" is supposed to buy.

## The two #203 examples

Issue #203 was filed by a real caller (ec2-cli) who trusted a green
colleague-authored test suite as evidence the change was correct. The report
documents two shipped false positives:

1. **AWS error mapping** — the implementation reads `exc.response_error` but
   botocore uses `exc.response`. The test mocks the same wrong attribute, so
   both pass.
2. **Cost Explorer** — the implementation sums `TotalEstimate` but the real API
   key is `Total`. The test asserts the same wrong key, so both pass.

Both are API-shape errors that TDD is meant to catch. In both cases, the test
passed because it mirrored the implementation's own wrong assumption — not
because the code was correct.

## Detection (`colleague/testintegrity.py` `detect_mirror`)

The heuristic detects the **mirror signature**: an identifier (attribute access
or string-literal dict key) that appears in **both** a changed test file and a
changed module-under-test, yet is found **nowhere else** in the repository.

The detection is pure stdlib (no new runtime dep, no new sanctioned subprocess
consumer beyond the lint-gate boundary):

- **AST-based extraction** — `ast.Attribute` nodes for attribute accesses
  (e.g. `exc.response_error`) and `ast.Subscript` / `ast.Dict` nodes for
  string-literal dict keys (e.g. `data["TotalEstimate"]`).
- **Repo-wide "nowhere else" scan** — walks the repo's `.py` files (skipping
  `.git`, `.venv`, `__pycache__`, `node_modules`, etc.) to gather the universe
  of identifiers. A symbol is only flagged if it is co-introduced in the changed
  test and impl but absent from all other repo files.
- **Partitioning** — changed files are split into test files (`test_*.py`,
  `*_test.py`, or under `tests/`) and module-under-test files. If either set is
  empty, the gate is a no-op.

**No changed `.py` pair → the gate is a strict no-op.** It never flags a
work item that does not touch both a test and an implementation file.

## The test-integrity GATE (`colleague/loop.py` `_maybe_run_test_integrity_gate`)

The gate is a **deterministic, code-locked** post-loop check, sibling to the
lint gate. It runs on every non-aborted loop exit for **both** `mock` and
`vllm-openai` backends (the all-engines rule) — the model cannot skip it.

The gate is **best-effort wrapped** so any exception is swallowed and never
aborts the work item. The git handoff always proceeds.

### Bounded re-examine turn

On a flagged finding, a clean `_EXIT_FINISHED` exit, and a live backend, the
runtime injects **one bounded model re-examine turn** (reusing the lint-gate
fix-turn pattern) asking the model to verify the flagged symbol against the real
API shape. The work item's terminal summary and status are saved and restored so
the re-examine turn cannot clobber the real result.

The re-examine turn is a strict no-op on the `mock` backend. The knob
`COLLEAGUE_TESTINTEGRITY_FIX_RETRIES` on `EngineConfig` is forwarded via
`ContextControls` by both backends.

### Diverse-model reviewer

On a flagged finding, the gate auto-spawns a **different-model reviewer** subagent
(via `colleague.subagents`, no new worktree/merge code) tasked to independently
re-derive the flagged fixture from the real API shape. The diverse mind is the
robust guard — the same-model re-examine turn can re-confirm its own mirror.

The reviewer degrades to record-only when no second model is configured. It is
bounded by existing `MAX_SUBAGENT_DEPTH` / `MAX_SUBAGENT_FANOUT` caps and never
blocks the handoff.

### Model-callable self-check

The `check_test_integrity` loop tool (in `colleague/tools.py`) lets the model
self-check a test proactively mid-work. It reuses the **same** detection logic
as the gate (one implementation, no duplicate). It is optional and model-judged;
the deterministic gate enforces regardless of whether the model calls it.

## Opt-out (default-ON)

The gate is **ON by default**. Disable it by passing
`ContextControls(testintegrity=False)` to `colleague.loop.run()`.

## Where the report lands

`TaskResult.test_integrity_report` — a `TestIntegrityReport` with a `findings`
list of `MirrorFinding` objects (symbol, kind, test_file, impl_file). The field
is **omitted** from the artifact when the gate found nothing (omit-when-None),
so a no-finding run is byte-identical to a run without the gate.

## Worked example

The gate runs quietly inside the work item. The only thing it prints (to
**stderr**) is a flagged mirror signature; the full record is in the artifact's
`test_integrity_report`.

The common case — no suspicious mirroring detected:

```text
$ colleague work "add AWS error handling to services/ec2.py" --repo .
… (work item runs; the gate finds no mirror signature) …
status: ok
task: a1b2c3d4e5f6
```

The branch lands with no test-integrity findings. When the heuristic flags a
co-introduced novel symbol, it is surfaced on stderr and recorded — but the
handoff still proceeds (non-blocking):

```text
test-integrity: possible self-confirming test(s) — mirror signature flagged:
response_error (attribute) co-introduced in tests/test_ec2.py & services/ec2.py
```

## Honest limits

- **Advisory and non-blocking.** The gate flags the mirror signature but never
  blocks the git handoff. It reduces self-confirmation; it does not guarantee
  correctness.
- **No network call.** The heuristic is pure stdlib and makes no socket or
  network connection. It cannot verify a mock against the live SDK in v0.
- **Python-only in v0.** The AST-based extraction and lint-adjacent check are
  Python-only, like the existing lint gate.
- **Not a correctness oracle.** The heuristic flags suspicious co-introduction;
  it does not prove a test is wrong. A symbol may be genuinely novel and correct
  (e.g. a new internal attribute). The operator or the diverse-model reviewer
  makes the final call.
- **Changed-files scope.** The gate only examines the work item's changed files.
  A mirror signature in unchanged files is not detected.

## See also

- [`docs/features/lint-gate.md`](lint-gate.md) — the sibling pre-finish lint gate (#200)
- [`docs/features/ask-colleague.md`](ask-colleague.md) — the `ask-colleague write --apply` path that triggers the gate
- [`docs/features/agent-cli.md`](agent-cli.md) — `colleague work` and `colleague drive` entry points

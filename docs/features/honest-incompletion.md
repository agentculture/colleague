# honest-incompletion — structured no-deliverable reporting

> `colleague work` (and `drive`, and `ask-colleague write`) detects when a work
> item finished without producing its expected deliverable and hands back a
> non-ok status with a structured `{reason, evidence, recommendation}` record,
> instead of reporting `ok` with an empty diff. Born from PR #312 (the t4 build),
> where a write task meta-finished with 0 changed files and reported status `ok`.

The honest-incompletion detector is a **post-loop classification** (colleague#313)
that runs on every work item. It is **runtime-owned** (all-engines rule): the
same pure classifier fires identically for `mock` and `vllm-openai` backends.

## What it is

When colleague cannot finish a work item, it now hands back `status: incomplete`
plus an `IncompletionRecord` with a `reason`, `evidence`, and `recommendation` —
instead of reporting `status: ok` with an empty diff. The record is advisory:
the handoff still proceeds, but the caller knows the work item did not deliver.

### The soft rule

The detector uses a **soft** deliverable-present check: a clean `finished`
outcome paired with a substantive, non-meta summary counts as a deliverable
even when zero files changed. This covers the legitimate "the code is already
correct — no change needed" case. Only an **empty** or **meta** finish (a summary
that admits it is unfinished), a budget/stop exit, or zero steps is flagged.

## How it works

### Classifier (`colleague/incompletion.py` `classify_incompletion`)

A pure, deterministic, IO-free function:

```python
classify_incompletion(
    outcome: str,
    write_intent: bool,
    changed_files: int,
    summary: str,
    step_count: int,
    finish_recovered: Optional[str] = None,
) -> Optional[IncompletionRecord]
```

Returns `None` when a deliverable is present; otherwise an `IncompletionRecord`
with `reason`, `evidence`, and `recommendation`.

**Deliverable-present checks (return `None`):**

- `changed_files >= 1` — files changed (even if wrong, that is not absence).
- `outcome == "finished"` and the summary is substantive and non-meta — a
  legitimate "no change needed" conclusion.
- Read-only role with a substantive summary — the summary itself is the
  deliverable, regardless of outcome.

**Meta-finish detection (`_is_meta`):** A summary is "meta" when it contains any
of the following case-insensitive substrings:

```python
_META_MARKERS = (
    "need to continue",
    "remaining work",
    "i have read",
    "i will ",
    "next i ",
    "to be implemented",
    "not yet implemented",
    "need to implement",
)
```

A meta summary admits the work is unfinished — it describes a report rather
than producing one.

### Reasons and recommendations

| Reason | When it fires | Recommendation |
|---|---|---|
| `write-no-changes` | Write intent, 0 changed files, empty/meta summary or non-finished outcome | Re-scope or take over: colleague finished without changing any files. |
| `empty-deliverable` | No substantive summary survived (not write-no-changes, not budget, not zero-steps) | Re-run with a tighter scope or take over: the finish produced no usable deliverable. |
| `budget-exhausted` | Outcome is `budget` — ran out of steps before delivering | Split the task or raise `--max-steps`: colleague ran out of steps before delivering. |
| `no-progress-zero-steps` | `step_count == 0` — no tool-calls at all | Check backend tool-calling or escalate to another model: colleague made zero tool-calls. |

Priority order: `no-progress-zero-steps` > `budget-exhausted` > `write-no-changes` > `empty-deliverable`.

### Contract (`colleague/contract.py`)

```python
@dataclass
class IncompletionRecord:
    reason: str
    evidence: str
    recommendation: str
```

Recorded on `TaskResult.incompletion: Optional[IncompletionRecord] = None`. The
field is **omit-when-None**: a delivering run serialises byte-identically to a
run without the feature.

### Loop integration (`colleague/loop.py` `_maybe_flag_incompletion`)

Wired after `_resolve_terminal_summary` in the terminal path. When the
classifier returns a record:

1. `result.incompletion = record`
2. If `result.status == OK`, downgrade to `INCOMPLETE` (the #313 core case:
   a clean finish with no deliverable).

### Caller display (`ask-colleague.sh`)

On a non-ok run carrying an incompletion record, the script prints a diagnostic
to stderr:

```text
incomplete: write-no-changes — re-scope or take over: colleague finished without changing any files.
```

The `grade:` hint is **not** suppressed on a non-ok run: a failed/incomplete but
gradable drive still gets the grade hint (a failure rated 1/5 is the ROI signal,
per #139). Only the `NO_RESULT_PRODUCED` sentinel suppresses it (#192).

## Role/intent awareness

`write_intent` is derived from the work item's role:

```python
write_intent = not is_read_only(result.role)
```

A legitimately read-only run (e.g. `explorer`, `reviewer`) that changes nothing
is **not** flagged — its summary is the deliverable. Only write-intent roles
(writer, default) are subject to the no-changes check.

## Composition with forced synthesis

The detector composes with `finish_recovered` / forced-synthesis: it fires only
when **no deliverable survives** synthesis. If forced synthesis produced a
substantive summary, the run is considered delivered (the summary is the
deliverable for read-intent, or the substantive summary satisfies the soft rule
for write-intent).

## Runtime-owned (all-engines rule)

The classifier is pure Python with no backend imports. It fires identically for
`mock` and `vllm-openai` — the result shape is the same regardless of which
engine ran the work item.

## Behaviour change

A clean `finished` outcome on a write task with 0 changed files and an empty or
meta summary now reports `status: incomplete` (previously `ok`). This is the
deliberate, documented change from colleague#313.

## Honest limits

- **Detects absence, never incorrectness.** A wrong-but-present change is not
  flagged. The detector only catches when no deliverable survived.
- **Does not fix #289 (tool-call-parsing) or #237 (reach).** Those are separate
  issues; the `no-progress-zero-steps` reason surfaces the symptom but does not
  resolve the root cause.
- **Fixed deterministic recommendation.** The `recommendation` comes from a
  static `_REASON_ADVICE` map, not a model deciding to escalate.
- **Soft-rule trade-off.** Because a substantive non-meta finish counts as
  delivered, the detector does **not** catch a confident-false "Done!" summary
  paired with 0 changes. This is a deliberate trade-off to avoid false-positives
  on legitimate "no change needed" runs. It **does** catch the meta-finish,
  empty finish, budget/stop, and zero-step cases.
- **Advisory only.** The handoff always proceeds; the record informs the caller
  but does not block the git handoff.

## See also

- [`docs/features/lint-gate.md`](lint-gate.md) — the sibling pre-finish lint gate (#200)
- [`docs/features/test-integrity.md`](test-integrity.md) — mirror-signature detection (#203)
- [`docs/features/ask-colleague.md`](ask-colleague.md) — the `ask-colleague` wrapper that surfaces incompletion diagnostics

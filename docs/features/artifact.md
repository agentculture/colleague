# Result artifact (the run report)

> Every work item writes its full result as JSON plus a per-step trace — the handoff
> payload and the operator's record.

The artifact (`colleague/artifact.py`) is the **run report**: a durable,
machine-readable record of what a work item did. Every work item produces two files under
an artifact directory (`.colleague/` in the repo by default):

| File | Contents |
|------|----------|
| `<task-id>.json` | The full `TaskResult` as pretty-printed JSON — the handoff payload for Guildmaster / Taskmaster / Steward. |
| `<task-id>.trace.jsonl` | One JSON line per loop step, for the operator. |

The JSON is simply `TaskResult.to_dict()` serialized; reloading it via
`from_dict` yields an equal object (lossless round-trip). `write()` sets
`result.artifacts_path` to the result-JSON path so the location travels *inside*
the artifact itself.

## What's in the result JSON

The serialized `TaskResult` carries the task id and status, the finish summary,
`changed_files`, the full `steps` trace, token `usage`, the handoff `branch` /
`pr_url`, every `hook_firings` entry (event, matched command, decision, exit
code, reason), and the originating `command` template name. See
[work-and-loop.md](work-and-loop.md#the-task-contract) for the field table.

### `task_text` — the verbatim brief (#481)

`TaskResult.task_text` records the run's brief (`Task.instruction`) verbatim,
beside the existing `prompt_digest` (which proves WHICH prompt arm ran but
never the text itself) — so replaying a measurement run no longer means
trusting whatever the operator remembered typing. Recording is **ON by
default** (decision c15); `COLLEAGUE_RECORD_TASK_TEXT=0` disables it, leaving
the key absent (omit-when-None, mirroring `prompt_digest`'s serialization). A
brief over 16384 chars (`colleague.tasktext.MAX_CHARS`) is truncated with a
literal `[truncated: original N chars]` marker, never a silent cut.

**A continuation propagates the ORIGINAL brief, never the synthesized seed**
(c22/h15/h3): `work --continue` builds the resumed run's `Task.instruction`
from a synthesized seed (preamble + continuation record + original request).
Left alone, the loop's own stamp would record that seed as `task_text` — not
the brief a human actually wrote. `colleague.continuation.prior_task_text`
reads the prior artifact's own `task_text` (already the propagated original,
however many continuations deep) and
`colleague.tasktext.apply_continuation_task_text` overrides the resumed
result's `task_text` with it, at the same seam `continued_from` is stamped —
wired through `work --continue`, the session's `/continue`, and
`--until-done` chain episodes alike. A prior artifact with no `task_text`
(pre-#481, or recorded with the knob off) propagates `None` — a seed is never
a brief, so nothing is recorded rather than the seed.

### `importcheck_report` (#482)

The importability-check pre-finish gate's `ImportCheckReport`, or `None`
(omitted) when the gate did not run (`COLLEAGUE_IMPORT_CHECK=0`, no changed
`.py` files, or an aborted run). Unlike `test_integrity_report`/
`affected_tests_report`, this field is set on **both** `"passed"` and
`"failed"` — mirroring `lint_report`/`coherence_report` — so a clean
import-check run stays visible on the artifact. See
[import-check.md](import-check.md).

### `effort_spikes` (#484)

`TaskResult.effort_spikes` — a list of `{"point", "rung", "seat"}` dicts, one
per opt-in effort spike that fired this run. **Omit-when-empty**: the key is
absent on every unarmed run and on an armed run where nothing fired, so both
are byte-identical to a pre-#484 artifact. Absence of an entry for a given
point reads as did-not-fire. See [effort-spikes.md](effort-spikes.md).

## Always written — even on failure

`write()` always succeeds for any result it is given, **including a failed run**
(`status == "error"`). A crash never leaves an empty run report: the CLI builds an
error result via `failed_result(task_id, error)` and still calls `write()` before
exiting non-zero. The originating command is persisted on the failure path too.

## Usage

The artifact is written automatically by `colleague work` and
`colleague session`; there is no separate artifact verb. To consume it:

```bash
colleague work "..." --repo . --engine mock --no-pr
cat .colleague/<task-id>.json        # the full result
cat .colleague/<task-id>.trace.jsonl # one line per step
```

The `--json` flag on `work` additionally streams the same result to stdout for
inline consumption.

## Key files

- `colleague/artifact.py` — `write()`, `failed_result()`, `artifact_dir()`.
- `colleague/contract.py` — the `TaskResult` shape that is serialized.

## See also

- [work-and-loop.md](work-and-loop.md) — the `TaskResult` field reference.
- [hooks.md](hooks.md) — hook firings recorded in the artifact.
- [telemetry.md](telemetry.md) — the live-observability complement to the
  per-run artifact.
- [affected-tests.md](affected-tests.md) and [test-integrity.md](test-integrity.md)
  — the sibling gate reports + their #480 non-finished-outcome warnings.
- [import-check.md](import-check.md) — the fifth pre-finish gate (#482).
- [effort-spikes.md](effort-spikes.md) — the `effort_spikes` field's producer.

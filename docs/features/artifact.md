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

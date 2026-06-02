# Subagents (the convoy)

> Mid-drive, an engine can delegate a scoped sub-task to a nested in-process
> child drive — same loop, optional different engine/model, bounded and
> sequential.

Subagents (the "convoy") let an engine, *while driving*, hand a scoped sub-task
to a nested child drive via the `subagent` loop tool. The child runs the **same**
bounded tool-loop the parent runs; its result is returned to the parent as the
tool result and appended to `TaskResult.sub_results` (the field is omitted when
empty). Delegation lives in the **chassis** (`colleague/tools.py` owns the tool
schema, `colleague/subagents.py` owns the launcher), so the tool is offered to
every engine identically (the all-engines rule) — no engine module re-implements
it.

## Key properties

- **In-process, synchronous.** A child drive is *a drive without handoff* — a
  plain function call into `engine.drive(child_task, child_config)`. No thread,
  process, asyncio, socket, or fork; zero new runtime dependencies (the
  no-socket / no-daemon convention holds).
- **Engine/model switch.** Optional `engine` and `model` parameters let the child
  run on a different wheel or model. Resolution goes through
  `registry.load` + `EngineConfig` inheritance (`dataclasses.replace` with only
  the model overridden) — a config-level switch, never an engine code change.
- **Bounded.** `MAX_SUBAGENT_DEPTH=2` (recursion cap, checked *before* any child
  work starts) and `MAX_SUBAGENT_FANOUT=4` (per-drive fan-out cap). A child
  refused at the depth cap does zero work and returns an error immediately, so
  there is no unbounded recursion and no growing call stack.
- **Engine-judged, optional.** The model decides whether to delegate per call,
  exactly like the [`devague` destination tool](destination.md). It is never a
  forced gate.
- **No per-subagent handoff.** Only the top-level drive branches, commits, and
  opens a PR — the git/PR handoff lives in the CLI `execute_drive` path, never in
  `Engine.drive`. Sub-drives run purely in-process.
- **Sequential only in v0.** Parallel/concurrent subagents and per-subagent
  worktree isolation are a parked follow-up that would require a re-spec.

## Tool parameters

The `subagent` loop tool takes:

| Parameter | Meaning |
|-----------|---------|
| `instruction` (required) | The sub-task to hand to the child drive. |
| `engine` (optional) | Engine wheel name; defaults to the parent's engine. |
| `model` (optional) | Model override; defaults to the parent's model. |

## Cost accounting

A subagent's cost stays in its own `SubResult.usage` (nested-only, matching the
existing usage rule). Rolling sub-results into a parent total is a parked
follow-up — see [stats-and-feedback.md](stats-and-feedback.md).

## NOT the gearbox

This is **not** the out-of-scope multi-engine router/"gearbox": there is no
operator-configured policy that automatically routes a task to a particular
engine. Delegation is always the model's choice at call time. (The gearbox
remains deliberately out of v0 scope.)

## Usage

The tool fires mid-drive, not from the CLI — there is no `subagent` verb. Read
its full contract with:

```bash
colleague explain subagent      # aliases: subagents, convoy
```

## Key files

- `colleague/subagents.py` — `run_subagent` / `make_spawn`; the depth-bound
  launcher and engine/model resolution.
- `colleague/tools.py` — the `subagent` tool schema + dispatch.
- `colleague/config.py` — `MAX_SUBAGENT_DEPTH`, `EngineConfig.subagent_spawn`.
- `colleague/contract.py` — `SubResult` and `TaskResult.sub_results`.

## See also

- [drive-and-loop.md](drive-and-loop.md) — the bounded tool-loop a child reuses.
- [destination.md](destination.md) — the other engine-judged, optional loop tool.
- [stats-and-feedback.md](stats-and-feedback.md) — where a sub-drive's cost lands.

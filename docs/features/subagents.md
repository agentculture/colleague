# Subagents

> Mid-work, a backend can delegate a scoped sub-task to a nested in-process
> child work item — same loop, optional different backend/model, bounded and
> sequential.

Subagents let a backend, *while driving*, hand a scoped sub-task
to a nested child work item via the `subagent` loop tool. The child runs the **same**
bounded tool-loop the parent runs; its result is returned to the parent as the
tool result and appended to `TaskResult.sub_results` (the field is omitted when
empty). Delegation lives in the **runtime** (`colleague/tools.py` owns the tool
schema, `colleague/subagents.py` owns the launcher), so the tool is offered to
every backend identically (the all-engines rule) — no backend module re-implements
it.

## Key properties

- **In-process, synchronous.** A child work item is *a work item without handoff* — a
  plain function call into `engine.work(child_task, child_config)`. No thread,
  process, asyncio, socket, or fork; zero new runtime dependencies (the
  no-socket / no-daemon convention holds).
- **Backend/model switch.** Optional `engine` and `model` parameters let the child
  run on a different backend or model. Resolution goes through
  `registry.load` + `EngineConfig` inheritance (`dataclasses.replace` with only
  the model overridden) — a config-level switch, never a backend code change.
- **Bounded.** `MAX_SUBAGENT_DEPTH=4` (recursion cap, checked *before* any child
  work starts) and `MAX_SUBAGENT_FANOUT=4` (per-work-item fan-out cap), with a
  single global `MAX_SUBAGENT_TOTAL=24` agent budget across the whole work item.
  A child refused at a cap does zero work and returns an error immediately, so
  there is no unbounded recursion and no growing call stack. (Depth was deepened
  from 2 to 4 and the global total added by the typed-subagent-roles feature.)
- **Engine-judged, optional.** The model decides whether to delegate per call,
  exactly like the [`devague` destination tool](destination.md). It is never a
  forced gate.
- **Chain-safe child configs** (#337): `run_subagent` resets `until_done` to
  `False` in child configs alongside the `chain_episode`/`chain_prior_changed`
  resets — `chain_armed` keys on `until_done`, so children of an armed run no
  longer arm fill-line chain consumers.
- **No per-subagent handoff.** Only the top-level work branches, commits, and
  opens a PR — the git/PR handoff lives in the CLI `execute_work` path, never in
  `Engine.drive`. Sub-drives run purely in-process.
- **Sequential only in v0.** Parallel/concurrent subagents and per-subagent
  worktree isolation are a parked follow-up that would require a re-spec.

## Tool parameters

The `subagent` loop tool takes:

| Parameter | Meaning |
|-----------|---------|
| `instruction` (required) | The sub-task to hand to the child work item. |
| `engine` (optional) | Backend plugin name; defaults to the parent's backend. |
| `model` (optional) | Model override; defaults to the parent's model. |

## Cost accounting

A subagent's cost stays in its own `SubResult.usage` (nested-only, matching the
existing usage rule). Rolling sub-results into a parent total is a parked
follow-up — see [stats-and-feedback.md](stats-and-feedback.md).

## Not a router

This is **not** the out-of-scope multi-backend router / routing policy: there is no
operator-configured policy that automatically routes a task to a particular
backend. Delegation is always the model's choice at call time. (That router
remains deliberately out of v0 scope.)

## Usage

The tool fires mid-work, not from the CLI — there is no `subagent` verb. Read
its full contract with:

```bash
colleague explain subagent      # alias: subagents
```

## Key files

- `colleague/subagents.py` — `run_subagent` / `make_spawn`; the depth-bound
  launcher and engine/model resolution.
- `colleague/tools.py` — the `subagent` tool schema + dispatch.
- `colleague/config.py` — `MAX_SUBAGENT_DEPTH`, `EngineConfig.subagent_spawn`.
- `colleague/contract.py` — `SubResult` and `TaskResult.sub_results`.

## See also

- [work-and-loop.md](work-and-loop.md) — the bounded tool-loop a child reuses.
- [destination.md](destination.md) — the other engine-judged, optional loop tool.
- [stats-and-feedback.md](stats-and-feedback.md) — where a sub-work item's cost lands.

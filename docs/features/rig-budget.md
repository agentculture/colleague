# Rig budget — cooperative concurrency across colleague processes + scaled child budgets

> Tracking: [colleague#258](https://github.com/agentculture/colleague/issues/258) ·
> spec R5 in
> [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md).

One served endpoint is shared by every colleague process on a machine. Two
concurrent `colleague work` invocations know nothing of each other — a single
serializing GPU gets double-booked and both runs starve toward the request
timeout (the interference class in #239). This feature adds two
complementary pieces: a **rig-level file-based concurrency budget** across
top-level work items (`colleague/rig.py`), and **child budget scaling** for
in-run subagent fan-out (`colleague/subagents.py`, t12) — so a fan-out never
schedules W full-sized budgets against one model.

## Rig-level concurrency budget (`colleague/rig.py`)

An operator declares `.colleague/rig.json` `{"concurrency": N}` naming the
endpoint's sustainable concurrency. Each top-level work item then holds **one
file-based slot** for the duration of its loop — a cooperative, atomic-`mkdir`
lock under `.colleague/rig-slots/slot-<i>` (`i` in `[0, N)`).

- **`load_rig_concurrency(repo_path)`** — reads `rig.json` (configdir-resolved:
  repo over user, legacy `.convertible` honored). Missing file, malformed
  JSON, a non-dict payload, a non-int/bool `concurrency`, or a non-positive
  value all resolve to `None` — never raises.
- **`rig_slot(repo_path, *, on_wait=None, max_wait=300.0, poll=0.5)`** — a
  context manager. Yields `False` immediately (no slot files ever created)
  when the rig is unconfigured — the strict no-op floor. When configured, it
  tries every `slot-<i>` in turn:
  - **Atomic take** — `Path.mkdir(parents=True, exist_ok=False)`; the OS
    guarantees only one caller wins a given index.
  - **PID stamping** — the winning process writes its own PID into
    `slot-<i>/pid` immediately after taking the slot.
  - **Stale-slot self-heal** — if `mkdir` raises `FileExistsError`, the holder
    PID is read and probed with `os.kill(pid, 0)`. A `ProcessLookupError`
    means the holder is gone — the slot is reaped (`pid` file removed, dir
    removed) and retried once in the same pass. A live PID, or one this
    process can't signal (`PermissionError`), is treated as **alive and never
    stolen** — a live holder is never preempted, even by a process that
    merely can't confirm it.
  - **Degrades open, never wedges** — if every slot is busy, the caller polls
    (`poll` seconds) until `max_wait` (default 300s), then **proceeds without
    a slot** rather than deadlocking the operator's run. `on_wait` (when
    given) is called with a human-readable line the first time the caller
    starts waiting, and again on the degrade-open — the progress-feed
    visibility hook (`work.py` wires it to `emit_diagnostic`).
  - **Release** is idempotent (`missing_ok=True` on unlink, `OSError`
    suppressed on `rmdir`) — a released-twice or already-gone slot is fine.

No daemon, no socket, no threads — stdlib `os`/`json`/`pathlib`/`time` only;
atomicity comes entirely from `mkdir` semantics, not from any locking
primitive colleague implements itself.

### Wiring: `execute_work`, ONE slot per top-level work item

`colleague/cli/_commands/work.py`'s `execute_work` holds exactly one rig slot
around the whole `engine.work(task, config)` call:

```python
try:
    with rig.rig_slot(repo, on_wait=emit_diagnostic):
        result = engine.work(task, config)
```

**Deliberately NOT taken per subagent child.** A parent holding a slot for the
duration of its own loop, and then also trying to acquire one per child, would
deadlock by composition: a rig configured for concurrency 1 would have the
parent hold the only slot while waiting for children who also need one. In-run
fan-out is governed by two *other* mechanisms instead — the width-scaled child
budgets below (t12) and the backpressure fan-out throttle
(`docs/features/backpressure.md`, t6). The rig budget's job is strictly
**cross-process**: coordinating separate top-level `colleague work`/`drive`
invocations sharing one endpoint, not the in-process fan-out inside one of
them.

## Child budget scaling (`colleague/subagents.py`, t12)

A batch child used to inherit the parent's **full** `EngineConfig` unchanged —
at concurrency width 3, three children could each try to consume the parent's
whole context/step budget against one served model at once.

- **`_child_budget_share(parent_config, width)`** — `(None, None)` at
  `width <= 1` (the sequential path is byte-identical, h5). At `width > 1`
  each concurrent child's share is:

  ```python
  steps = min(parent.max_steps, max(_MIN_CHILD_MAX_STEPS, parent.max_steps // width))
  budget = min(parent.context_budget_tokens,
               max(_MIN_CHILD_CONTEXT_BUDGET, parent.context_budget_tokens // width))
  ```

  clamped at floors `_MIN_CHILD_MAX_STEPS = 10` and
  `_MIN_CHILD_CONTEXT_BUDGET = 16000` so scaling can never hand a child an
  unworkably small budget, and never above the parent's own value.
- **Per-item override wins.** `_run_one` (inside `_spawn_children`) resolves
  each child's actual budget as
  `item.get("max_steps") or share_steps` /
  `item.get("context_budget_tokens") or share_budget` — an explicit per-item
  value (e.g. from a caller that already knows a child needs more) always
  wins over the width-scaled default share.
- **Read-only batches skip the merge slot.** Normally
  `effective_concurrency` clamps fan-out to `MAX_SUBAGENT_FANOUT - 1`,
  reserving one slot for the sequential merge child. `_batch_all_read_only`
  checks whether **every** child's effective role (its own `"role"`, falling
  back to the batch-level role) is a read-only builtin
  (`colleague.roles.is_read_only`) — a read-only child provably cannot write,
  so its merge is structurally a no-op over an empty diff. When true,
  `_resolve_batch_width` frees the reservation and the batch may use the full
  `MAX_SUBAGENT_FANOUT`. The same check is duplicated in exactly two places
  that must agree: `_resolve_batch_width` (`subagents.py`, governs actual
  fan-out width) and the `subagents` tool's own cap in `colleague/tools.py`
  (`_batch_cap = MAX_SUBAGENT_FANOUT if all_read_only else MAX_SUBAGENT_FANOUT - 1`,
  the model-facing tool-call limit) — both read the same
  `is_read_only`/role-fallback logic so they can't drift apart silently.

## Honest limits

- **Cooperative, not admission control.** Only colleague processes that call
  `rig_slot` are governed. A non-colleague client hitting the same endpoint
  (or a colleague process from before this feature) is invisible to the
  budget.
- **Same-host PID probe.** `_pid_alive` uses `os.kill(pid, 0)`, which only
  makes sense when the rig's declared concurrency and every colleague process
  taking a slot are on the same host — a rig is one host by definition here;
  there is no cross-machine liveness check.
- **Degrades open under contention**, never wedges a run — but that means a
  genuinely oversubscribed rig (more concurrent work items than the declared
  concurrency, sustained) will eventually let everyone proceed without a slot
  once `max_wait` is reached, rather than queuing indefinitely. The budget is
  an advisory backstop, not a hard admission gate.
- **Missing/absent `rig.json` is a strict no-op** — no slot directories are
  ever created, so a repo that never opts in pays zero cost.
- **Child budget scaling only fires at width > 1** — a sequential batch
  (`COLLEAGUE_SUBAGENT_CONCURRENCY=1`, the default) is byte-identical to
  before this feature.

## Spec + plan

- Spec: [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
- Plan: [`docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
  (tasks t12-t13)

## Deviation from the plan

The plan's t13 acceptance criterion frames the rig slot as covering "spawns"
generally; the built wiring holds the slot **only at the `execute_work`
level**, once per top-level work item — never around an individual subagent
spawn. This is a deliberate choice (deadlock-by-composition, above), not an
oversight: the plan's own risk notes anticipated in-run fan-out needing a
*different* mechanism, which is exactly what t12 (child budget scaling) and
t6 (the backpressure throttle) provide.

## See also

- [`docs/features/backpressure.md`](backpressure.md) — the in-run,
  per-work-item concurrency throttle this feature's rig budget complements
- [`docs/features/subagent-roles.md`](subagent-roles.md) — the read-only role
  contract `_batch_all_read_only` depends on
- [`docs/features/parallel-subagents.md`](parallel-subagents.md) — the batch
  fan-out + merge-child mechanism child budget scaling extends

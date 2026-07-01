# Three-tier visibility parity (capacity · phase · goal · mode)

> **Status: landed** (colleague-side) — the two colleague-owned pieces below
> (tasks t7 + t9) are built and merged. The upstream TAUIState schema bump
> (task t8, agentfront#48) is still pending; see "Still pending upstream"
> below for exactly what remains gated on it.

Tracking: [colleague#256](https://github.com/agentculture/colleague/issues/256) ·
spec R3 in
[`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md).

The goal: capacity/fill-line state, the #206 phase notices
(thinking/synthesizing/compacting), the task goal, and the driving mode are
visible on all three surfaces — the human ANSI cockpit, the agent
markdown/TAUI render, and the bot JSON (artifact, events.jsonl, MCP result) —
each rendered from ONE shared state, never recomputed per-renderer.

## Upstream-first (the #249 pattern)

The TAUI state/schema additions ship in agentfront first; colleague stays
consumer-side only. The upstream ask is filed as
**[agentfront#48](https://github.com/agentculture/agentfront/issues/48)**
(TAUIState `capacity` block, `phase`, `goal`; `mode`/`phase` event kinds).

## Landed independently of the upstream bump

- **`TaskResult.mode` recorded in the artifact** (t7), omit-when-None —
  `colleague/contract.py` `TaskResult.mode`, set on both the success and
  failure paths in `colleague/cli/_commands/work.py`'s `execute_work` before
  every artifact write. A mode-less work item's artifact is byte-identical to
  before mode existed. See [`docs/features/mode-profiles.md`](mode-profiles.md).
- **Capacity/phase/goal panels in the session cockpit** (t9), via the
  existing generic panel walk — no agentfront schema bump needed:
  - The **Capacity panel** (`colleague/cli/_commands/session.py`
    `_capacity_panel`) shows the resolved context budget, the active mode's
    constraint profile, and the latest fill-line/backpressure signal
    (`TaskResult.capacity_warning`, surfaced the moment a work item
    completes — captured in `_dispatch_work` *before* `_refresh_context()`
    rebuilds the panel, so it is never stale).
  - The **goal line** (`_with_goal`) shows the running work item's
    instruction for the duration of the run, cleared unconditionally in the
    `finally` of `_run_tracked` on both the success and error paths — a goal
    never lingers past the work item that set it.
  - The **#206 live-cockpit phase status is now resolved for both cockpit
    consumers.** `fold_phase` (`colleague/cli/_commands/_tui_sink.py`) folds
    a phase notice (a progress event with an empty tool name — `thinking…` /
    `synthesizing…` / `compacting…`, or a t6 backpressure advisory, all fired
    through `colleague.loop._emit_phase`) onto the cockpit's **status**
    surface (`state.status.message`) rather than dropping it — used by both
    `CockpitProgressSink` (the plain `work --tui` cockpit) and the session's
    `_WorkSink`. The #206 invariant still holds regardless: a phase notice
    never creates a work step (`work_item.step_count` untouched, no
    conversation/feed line added), so `tui replay`/`snapshot` — which never
    see this sink — stay step-only. A real step always clears the phase text
    back to the baseline status.
  - Because Panel/PanelItem is agentfront's existing generic shape, all three
    new panels (and the goal item) carry to Markdown + the TAUI JSON mirror
    for free via the same generic panel walk Policy/Context already use — no
    per-renderer code.

## Still pending upstream

- **`TAUIState.capacity`/`.phase`/`.goal` as first-class state fields** —
  today's Capacity panel and goal line ride the existing generic
  `Panel`/`PanelItem` shape rather than a dedicated schema field; a genuine
  TAUIState schema addition needs agentfront#48 to land first (the #249
  upstream-first pattern — colleague never ships a schema change agentfront
  hasn't accepted).
- **`mode`/`phase` event kinds in `events.jsonl`** — gated on the same
  upstream bump; today's events stream stays step-only.
- **`mode` in an MCP result** — `colleague work` (the only verb that sets
  `mode`) is a **host command** (`app.add_command`, custom exit codes), which
  the single-dispatch MCP `run` tool's catalog structurally excludes
  (`tests/test_cross_surface_parity.py` pins registry-tools == MCP catalog ==
  `learn` catalog, with host commands absent from all three) — so `mode`
  currently has no MCP call-result path to reach at all, independent of the
  agentfront#48 schema bump. An MCP consumer sees `mode` only by reading the
  written JSON artifact directly.

## Parked

- MCP **streaming** progress (a bot following a live run over MCP rather than
  tailing `events.jsonl`) — separate re-spec.

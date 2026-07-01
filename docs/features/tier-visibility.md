# Three-tier visibility parity (capacity · phase · goal · mode)

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

## Landing independently of the upstream bump

- `TaskResult.mode` recorded in the artifact, omit-when-None (plan task t7).
- Capacity/phase/goal panels in the session cockpit via the existing generic
  panel walk — no schema bump needed; markdown + TAUI mirror carry panels for
  free (plan task t9).

## Parked

- MCP **streaming** progress (a bot following a live run over MCP rather than
  tailing `events.jsonl`) — separate re-spec.
- events.jsonl `mode`/`phase` event kinds — gated on agentfront#48.

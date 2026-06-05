# Auto-split — split too-large assignments before degradation

> When an assignment is too large for one context window, colleague recommends
> splitting it into up to ~4 coherent child assignments (via the existing
> `subagents` tool) instead of degrading lossily or failing. The recommendation
> is advisory and backend-judged; the model decides whether and how to split.

## The problem

A work item larger than one context window faces a hard ceiling:

- **Lossy windowing** — graceful degradation drops oldest history with a
  placeholder, preserving termination but losing context.
- **Escalation** — when even retries cannot recover, the work item escalates to
  a continuation issue filed post-failure, leaving no path for the model to
  proactively *split* the work itself.

For a ~1M-token assignment on a 256k-window model, neither path is ideal: one
silently loses information; the other surfaces a fix outside the work loop.

## The solution — reactive advisory split

When the bounded overflow retries (`_MAX_OVERFLOW_RETRIES`) are exhausted,
**before escalation fires**, the loop detects overflow and injects one structured
recommendation message:

```text
This assignment is too large to complete in one context window. The current
context has overflowed and cannot be recovered by trimming alone.

Consider splitting the work into at most 3 coherent, independently-scoped
sub-assignments, each sized to fit within 250000 tokens per child context window.

Use the `subagents` tool to delegate these sub-assignments...
```

The model then gets bounded additional turns to act. If it calls `subagents` with
a coherent split, the runtime fans out the children via the existing subagent
machinery (isolated per-child git worktrees on `sub/<id>` branches, optional
parallel concurrency, sequential merge-subagent for integration). If the model
declines or the split still doesn't fit, escalation follows as the final fallback.

### Up-front hint

Before the loop starts, if a coarse estimate of the task instruction alone
already exceeds one window, the loop injects a softer early advisory hint
(optional suggestion, not a hard block) so the model can preemptively consider
splitting. This estimate sees only the instruction text, not the repo surface —
so it may over/under-trigger, but it provides an early nudge when plausible.

## How it works — reusing subagents

The actual split execution reuses the existing `colleague.subagents` machinery
verbatim:

1. **Detection:** when `_MAX_OVERFLOW_RETRIES` is exhausted, the loop calculates
   the per-child budget and max child count.
2. **Recommendation:** one structured message is injected with concrete numbers
   (per-child budget, max children).
3. **Fan-out:** if the model calls `subagents`, the existing
   `make_batch_spawn`/`batch_spawn` runs the children in isolated worktrees.
4. **Merge:** the sequential merge-subagent integrates branches and surfaces
   conflicts.

No new merge/worktree/fan-out code is added — the feature is a policy that
sequences an advisory *recommendation* before escalation.

## Configuration

| Setting | Value | Notes |
|---------|-------|-------|
| `COLLEAGUE_AUTOSPLIT_TARGET` | Tokens | Environment variable; effective total capacity (default ≈ 1M tokens ≈ 4 children × 250k each). |
| `EngineConfig.autosplit_target_tokens` | Config object | Resolved via standard precedence (explicit > env > default). |
| Child count clamp | ≤ `MAX_SUBAGENT_FANOUT - 1` | Structurally capped to 3 children (reserves 1 slot for merge). |

The default ~1,000,000 tokens assumes a 256k-window model with a 250k per-child
budget; adjust `COLLEAGUE_AUTOSPLIT_TARGET` for smaller budgets or different
window sizes.

```bash
# Use default 1M-token split capacity:
colleague work "large task" --engine vllm-openai

# Adjust split capacity for a smaller model:
COLLEAGUE_AUTOSPLIT_TARGET=500000 colleague work "large task" --engine vllm-openai
```

When `autosplit_target_tokens` is not set (≤ 0 or unset), the feature is
dormant — no up-front estimate, no reactive recommendation. Graceful degradation
and escalation still work.

## Honest limits

1. **Advisory, not guaranteed.** The runtime recommends a split and the model
   decides whether/how to act. A model may ignore the recommendation and keep
   drowning in context. The runtime cannot force a split, only recommend one.

2. **Wall-clock speedup requires concurrent-request support.** Real speedup on
   parallel children depends on the served model handling concurrent requests
   independently (same caveat as parallel-subagents). On a serializing server,
   the gain is effective context + overlapped I/O, not compute parallelism.
   Set `COLLEAGUE_SUBAGENT_CONCURRENCY=1` (the default) to avoid thread overhead
   on a serializing server.

3. **Up-front estimate is coarse.** The estimate only sees the task instruction
   text, not the repo surface the work will touch. So it can over-trigger
   (pessimistic estimate) or under-trigger (instruction is small but repo scope
   is large). Ensuring the model reliably acts on the recommendation is a
   follow-up measurement goal.

## Runtime-owned (all-engines rule)

The feature lives in `colleague/loop.py` and `colleague/autosplit.py`:

- `_autosplit_armed` — checks if split detection is enabled.
- `_append_split_recommendation` — injects the structured message.
- `estimate_instruction_tokens` — coarse up-front estimate.
- `build_split_recommendation` / `build_upfront_hint` — message templates.
- `child_count` — calculates split child count (thin wrapper to
  `autosplit_children`, clamped by `MAX_SUBAGENT_FANOUT`).

Both backends (`mock` and `vllm-openai`) inherit the feature identically. When
no trigger fires, no extra model turn is added and `TaskResult` shape is
unchanged (guarded by `tests/test_e2e_mock.py`).

## Key files

- `colleague/autosplit.py` — split helpers (estimate, recommendation builders,
  child-count calculation).
- `colleague/loop.py` — reactive trigger point (overflow exhaustion, before
  escalation) + up-front hint injection.
- `colleague/config.py` — `autosplit_target_tokens`, `autosplit_children`,
  `COLLEAGUE_AUTOSPLIT_TARGET` env resolution.
- `colleague/subagents.py` — unchanged; the split reuses
  `make_batch_spawn`/`batch_spawn`.

## See also

- [Graceful degradation — context budgets](graceful-degradation.md) — the
  proactive windowing and reactive trim-and-retry that lead to the split
  trigger point.
- [Parallel subagents](parallel-subagents.md) — the existing fan-out machinery
  the split reuses.
- [Work and loop](work-and-loop.md) — the loop lifecycle and termination
  guarantees.

## Specification & plan

- Specification: `docs/specs/2026-06-05-colleague-auto-splits-a-too-large-assignment-into.md`
- Build plan: `docs/plans/2026-06-05-colleague-auto-splits-a-too-large-assignment-into.md`

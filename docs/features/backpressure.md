# Adaptive backpressure — the loop tightens toward safety when turns slow down

> Tracking: [colleague#255](https://github.com/agentculture/colleague/issues/255) ·
> spec R2 in
> [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md).

The reference rig is a single serializing GPU — when the served model gets
busy (a big context, concurrent load, a slow completion), successive turns
drift toward the request timeout. Before this feature the loop had no signal
for that until a turn actually timed out. Backpressure measures per-turn
wall-clock latency and, when turns are trending slow, proactively tightens
**before** a timeout happens: it shrinks the next completion's context window
(the #229 move) and throttles subsequent subagent fan-out — bounded,
advisory-first, and it only ever tightens toward safety.

## The pure classifier (`colleague/backpressure.py`)

A leaf module: no clock, no threads, no I/O, and no import from
`colleague.loop` or `colleague.config` (the loop is the caller, not the
other way around). Three functions:

- **`assess(turn_latencies, timeout, *, arm_fraction=0.5, escalate_fraction=0.75, window=3)`**
  — classifies the mean of the last `window` latencies against
  `timeout * arm_fraction` / `timeout * escalate_fraction`:
  - mean `>= escalate_fraction * timeout` → `ESCALATED`
  - mean `>= arm_fraction * timeout` → `ARMED`
  - otherwise → `CLEAR`

  Both comparisons are inclusive (`>=`). Fewer than `window` samples is fine
  (the mean is over whatever is there); zero samples or a non-positive
  `timeout` is always `CLEAR` (nothing to react to, never a `ZeroDivisionError`).
- **`shrink_fraction(state)`** — the recommended context-window multiplier:
  `CLEAR` → `1.0`, `ARMED` → `0.75`, `ESCALATED` → `0.5`. An unrecognized state
  degrades to `1.0` (never invents a tightening). The caller composes this with
  its own minimum-window floor — this module doesn't know or enforce one.
- **`throttled_concurrency(state, configured)`** — the recommended subagent
  concurrency cap: `CLEAR` → `configured` unchanged, `ARMED` → `configured - 1`
  (floored at 1), `ESCALATED` → `1`. A non-positive `configured` is floored to
  1 first.

Backpressure never raises a shrink fraction above `1.0`, never raises
concurrency above what was configured, and never selects a different model or
backend — the no-router scope line holds structurally, not just by convention.

## Loop integration (`colleague/loop.py`)

### Measuring latency: `_timed_complete`

`_timed_complete(ctx, complete)` wraps every model completion. Dormant (a
plain call, no clock) unless `ctx.request_timeout` is a positive number — a
direct `run()` caller with no `request_timeout` set is byte-identical. When
armed, it times the call and records the latency in a `finally` — so a
completion that itself raises (above all a request **timeout**, which costs
the full window) is exactly the slow turn the classifier needs to see.

### Recording + reacting: `_record_turn_latency`

Folds the new latency into `ctx._turn_latencies`, re-classifies via
`backpressure.assess`, and on a **state transition**:

- retunes the fan-out throttle (`ctx.fanout_throttle(state)`, when wired) —
  `CLEAR` restores the operator's originally configured concurrency, so
  recovery is automatic, not just tightening;
- on the **first** departure from `CLEAR`, records **one**
  `TaskResult.capacity_warning` advisory (appended to any existing warning,
  never replacing it) and fires a phase-notice line (`_emit_phase`) so the
  tightening is visible in the live cockpit/session, not silent. The advisory
  fires at most once per work item (a single-element mutable cell,
  `ctx._backpressure_advised`, the same pattern `_split_recommended` and
  `_fillline_offered` already use).

### Tightening the window: `_complete_with_degradation`

Before the phase notice for the turn fires, if the current backpressure state
is not `CLEAR`, the effective context budget for *this* turn is multiplied by
`backpressure.shrink_fraction(state)` (floored at 1 token) — composing with
(never replacing) the existing reactive shrink-on-overflow/timeout retry loop
(`#154`/`#157`). A healthy-latency run never enters this branch, so it is a
strict no-op there (byte-identical to before the feature).

### Throttling fan-out: `_make_fanout_throttle`

Built once per work item from the resolved `EngineConfig` in
`ContextControls.from_config`:

```python
throttle_fanout=_make_fanout_throttle(config)
```

The closure captures the operator's **original** `subagent_concurrency` and,
on each state change, sets `config.subagent_concurrency =
backpressure.throttled_concurrency(state, configured)` — mutating the shared
`config` object retunes the already-bound `batch_spawn` closures (they read
`subagent_concurrency` at call time), so a subsequent `subagents` tool call
sees the throttled width immediately. `CLEAR` always restores exactly the
configured value; the throttle can only ever tighten below it, never exceed
it.

## `ContextControls.from_config` forwarding

Two new fields, forwarded by **every** backend through the one shared mapping
(the all-engines rule — a backend that diverges here is a bug):

```python
request_timeout=config.timeout,
throttle_fanout=_make_fanout_throttle(config),
```

`request_timeout` is `config.timeout` (`EngineConfig.timeout`, itself
mode-profiled — see `docs/features/mode-profiles.md`) — the reference the
rolling per-turn latency is classified against. `None`/`<= 0` leaves
backpressure dormant, a strict no-op (no timing, no shrink, no throttle) —
so a direct `run()` caller with no `request_timeout` is unaffected.

## Timeout escalation (#268)

Backpressure's sibling move: when the harness has evidence turns are running
out of road, it raises the per-turn request timeout ONCE per work item,
bounded x2 (`colleague/loop.py` `_make_timeout_escalator`, built in
`ContextControls.from_config` — all-engines). Two triggers, whichever fires
first (the escalator closure enforces once-only, so double-firing is
structurally impossible):

- **proactive** — the first departure from CLEAR (the same moment the
  advisory + shrink arm): the harness saw the timeout coming, so it raises the
  cap in flight instead of pushing "raise COLLEAGUE_TIMEOUT" to the caller
  after the work is lost;
- **reactive** — a timeout-classified degraded retry (`_plan_degraded_retry`):
  the raise lands BEFORE the single #154 retry, so that retry runs with real
  headroom (the observed irc-lens abort had both attempts hit the same 120s
  wall — a shrunken window alone cannot help a saturated server).

The engine's completion closure reads `config.timeout` per call, so the raise
reaches the very next attempt. The raise is recorded on
`TaskResult.capacity_warning` and a phase-notice line; subsequent backpressure
classification runs against the raised cap (`_effective_timeout`). The
documented worst case on a genuinely dead server grows from `2 x timeout` to
`timeout + 2 x timeout` and no further. The effective timeout + its source
(env / default) surface in `colleague doctor` (`provider_timeout`),
`colleague work --help`, and `colleague learn`.

## Streaming re-verification — thresholds KEPT, not re-keyed ([#393][bp393])

[bp393]: https://github.com/agentculture/colleague/issues/393

Issue #393 armed SSE streaming by default for headless work
([`engines.md`](engines.md)), which changes what `config.timeout` — the
reference every fraction above is taken of — actually measures. This section
records the decision consciously rather than inheriting it silently.

**What changed.** `config.timeout` is handed to `urlopen(..., timeout=...)`.
Blocking, that is a whole-completion budget, so a turn's wall-clock latency
could never exceed it. Streaming, it is a **per-read** budget — the socket
only has to produce *some* bytes within the window — so it measures silence
between chunks, and a healthy turn may legitimately generate for far longer
than `timeout`. `_timed_complete` still measures total wall-clock latency, so
under streaming `assess` can read `ARMED`/`ESCALATED` on a turn that is
generating perfectly well, just slowly.

**The decision: keep `arm_fraction=0.5` / `escalate_fraction=0.75` / `window=3`
exactly as they are.** Reasons:

- Every backpressure action is **tighten-only and advisory** — a smaller
  context window, less subagent fan-out, one bounded timeout raise. A false
  `ARMED` under streaming costs throughput, never correctness, and never
  fails a run. Under-reacting to a genuinely saturated rig is the more
  expensive error.
- A rig whose mean turn is past 75% of the configured budget *is* under
  pressure whether or not the bytes now arrive incrementally. The signal
  degraded in precision, not in direction.
- Re-keying honestly would mean classifying against **time since the last
  chunk**, and the loop cannot see that: `complete` hands back only a finished
  `ModelResponse`, and `colleague.backpressure` is a leaf module with no
  clock and no I/O by design. Threading a stall clock from the engine into
  the loop is a new runtime surface — a separate re-spec, not a threshold
  tweak.

**#268 escalation is likewise kept.** Under streaming the once-only x2 raise
widens the *stall* budget rather than a generation budget, which is a weaker
lever than it was — but it is still tighten-only, still bounded, and still
correct for the case it was built for (a saturated or stuck server).

**A streaming stall still classifies as a request timeout.**
`_post_json_stream` wraps a read-phase `TimeoutError` through the SAME
`_raise_legible_timeout` the blocking path uses, keeping the "timed out"
phrase, so `colleague.context.is_request_timeout` /
`classify_degradable` match identically and the #268 survival path fires
exactly as before. A stall is also deliberately **not** eligible for the
mid-stream → blocking fallback (it has its own bounded retry at the loop
level), so one turn can never spend three full timeout windows. Both are
pinned in `tests/test_headless_streaming.py`
(`test_streaming_stall_still_classifies_as_a_request_timeout`,
`test_a_mid_stream_stall_is_not_swallowed_by_the_blocking_fallback`).

## Honest limits

- **Per-process and cooperative, not a scheduler.** Backpressure reacts to
  *this* work item's own observed latency; it has no visibility into other
  colleague processes sharing the same served endpoint. The **rig-level
  concurrency budget** (`docs/features/rig-budget.md`, #258) is the
  cross-process complement — backpressure tightens *within* one run,
  the rig budget coordinates *across* concurrent runs.
- **A dead/unreachable server is still bounded, not fixed.** Backpressure
  shrinks the window to make the *next* turn faster, which only helps a
  context-bloat-induced slowdown. A genuinely stuck or unreachable server
  still burns through the existing `_MAX_TIMEOUT_RETRIES` bounded retries
  per #154 before the run preserves its partial — the #268 escalation does not
  change that cap, it widens each window once (worst case
  `timeout + 2 x timeout`, documented above).
- **Under streaming the latency signal is coarser.** With SSE armed by
  default (#393) a long *generation* is legitimate, so a mean latency past
  the arm/escalate fraction no longer implies the turn was close to dying —
  see the re-verification section above for why the thresholds were kept
  anyway, and what re-keying would actually require.
- **Advisory + tighten-only, never an error.** A run that never crosses the
  arm threshold is byte-identical; crossing it never fails the run, never
  switches model/backend, and always composes with (never replaces) the
  existing degradation retry loop.
- **This is the mechanism behind #229's "shrink the window" recommendation**
  — #229 named the move informally; this feature is the concrete, tested
  implementation of it (`shrink_fraction` + the window-tightening branch in
  `_complete_with_degradation`).

## Spec + plan

- Spec: [`docs/specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../specs/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
- Plan: [`docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md`](../plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md)
  (tasks t5-t6)

## See also

- [`docs/features/graceful-degradation.md`](graceful-degradation.md) — the
  reactive shrink-on-overflow/timeout retry loop this feature composes with
- [`docs/features/mode-profiles.md`](mode-profiles.md) — where `timeout` (the
  classification reference) itself comes from
- [`docs/features/rig-budget.md`](rig-budget.md) — the cross-process
  concurrency complement

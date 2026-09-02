# Delivery Summary — effort-floor-and-decay-arms

plan: `effort-floor-and-decay-arms` · run: `complete` · date: `2026-09-02`
(amended after `d1`: the default flip landed in the same PR)
baseline: `devague summary skeleton`

## Intent

Answer the two floor questions the #484 measurement left open — does an `off`
floor with a `medium` spike hold, and does a built effort decay
(`medium → low → off` after a spike) earn its keep — on the same preserved
brief, with the #487 trigger fix so a shell-first survey can still reach the
barrier. Plan
[`docs/plans/2026-09-02-effort-floor-and-decay-arms.md`](../plans/2026-09-02-effort-floor-and-decay-arms.md)
from spec
[`docs/specs/2026-09-02-effort-floor-and-decay-arms.md`](../specs/2026-09-02-effort-floor-and-decay-arms.md);
built and run by the main agent, arms sequential on the rig.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — t1 #487 trigger fix in `loop_barrier.should_fire` (file-writing name set) + tests
- `t2` — t2 effort decay module + wiring + artifact record + boundary tests
- `t3` — t3 docs: invariant amendment (8) in thinking-effort.md + CLAUDE.md, effort-spikes.md decay + trigger sections, CHANGELOG, version bump minor
- `t4` — t4 arm D0 (off floor, spikes off, v1.75.1 harness) — running; verify + row 74
- `t5` — t5 arms D, E, F on the build tip (HARNESS worktree), sequential; verify; rows 75-77
- `t6` — t6 disposition + PR: post on #484 (or successor) applying the pre-stated win condition; PR via cicd; delivery ledger + summary

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `FILE_WRITE_TOOLS` precondition/trigger in `loop_barrier.should_fire`; `tests/test_barrier_trigger_487.py` (commit `6e5139c3`); proven live — arm F opened shell-first and its barrier fired at step 32 |
| `t2` | delivered | `colleague/effortdecay.py`, `loop_gateescalation.decayed_turn`/`note_reset`/`make_decay`, `TaskResult.effort_decay` (commit `6e5139c3`); the artifact mirror was missing until `1f0eb2a2` (arm E's artifact lacks the record; ledger `e3` fail) |
| `t3` | delivered | convention change (8) in CLAUDE.md + `thinking-effort.md`, `effort-spikes.md` sections, CHANGELOG, v1.76.0 (`bd89f144`, extended at `03dda713`, `c9581e93`) |
| `t4` | delivered | row 74: arm D0 `569ebacc3790` — budget-exhausted, 91 survey turns, zero files, FAIL (`cfb2b2b0`) |
| `t5` | delivered | rows 75-77: D `1fe80683ca44` FAIL (loop-guard exit, no write ever requested); E `2e38475f1f1a` PASS at the highest spend of any arm; F `77e350cbffbc` PASS at 24,279 chars / 1,286 s — the pre-stated win condition met at n=1 (`a4803abd`, `1f0d3c6a`, `44d276ef`) |
| `t6` | delivered | ledger o1-o7 / e1-e7 / b1-b2 adjudicated; this summary; #484 round-2 disposition (comment `5505730293`); PR #491 via `devex pr open`; an `ask-colleague` review of the code diff runs alongside and is triaged into the PR |

## Mid-work Decisions

No `/deviate` records; every decision went through the frame's `question`
loop or the operator's mid-run answers, recorded as decisions on the frame.

- `c13` — after rows 74-75 showed a decision-point spike cannot reach a run that never requests a write, a FOURTH enumerated point `stall.no_write` (10 acting turns with no file write → the barrier's tools-off decision turn at `medium`, max 3/run) was built into the same arc; the drift test re-pinned. The operator chose count-keyed over random.
- `c14` — a FIFTH point `start.first_turn` (turn 1 at `medium`, tools on) added at the operator's ask so arm F is the full stack; both new points reset the decay clock.
- arm F's first launch (`6fba6801bfd3`, at `03dda713`) was stopped at step 3 to pick up the decay-record mirror fix; relaunched at `1f0eb2a2` — an operational restart, not a model attempt.
- arm E's missing `effort_decay` record was diagnosed from the reasoning sidecar (49 sidecar turns vs 87 model turns; all-`off` arms have no sidecar file) rather than re-run; the row says so.
- #489 filed (flow-keyed effort table over the devague legs) at the operator's ask.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t2` (`e3`) | `TaskResult.effort_decay` was declared but never mirrored from the run state until after arm E — E's artifact carries no record | needs-follow-up (fixed at `1f0eb2a2`; E's evidence is sidecar-based) |
| `t2` (`b1`) | two spike points beyond the plan's scope (`stall.no_write`, `start.first_turn`) — needed to make the off-floor question answerable at all | acceptable (decisions c13/c14, drift test re-pinned, docs carry them) |
| `t5` (`b2`) | arm F changed four files: it also bumped `pyproject.toml` and wrote a CHANGELOG entry the brief did not ask for | risky (correct on the pre-registered measure; wider than asked — a scope-discipline signal for `off`-floor runs) |
| `t6` (`d1`) | after the arms, the operator made arm F's shape the DEFAULT (spikes + decay ON, cortex floor `off`) — beyond the plan's measure-only scope; recorded as deviation d1 with follow-up #490 | risky (n=1; reverting is three defaults in one commit) |

## Evidence

- tests: `uv run pytest -n auto -q` at `1f0eb2a2` — 11,868 passed, 51 skipped (incl. `test_effortdecay_boundary.py`, `test_effort_decay_wiring.py`, `test_barrier_trigger_487.py`, `test_stall_spike.py`, `test_start_spike.py`, `test_effortspikes_boundary.py` re-pinned to five, `test_thinking_effort_boundary.py`)
- result branches (fresh worktrees): `colleague/2e38475f1f1a-…` and `colleague/77e350cbffbc-…` — import OK, six pins, 11,226 passed each; `569ebacc3790` / `1fe80683ca44` — zero changed files
- artifacts: F `effort_spikes` [start, stall, stall, barrier] + `effort_decay {resets: [1, 12, 23, 33], turns: {low: 4, off: 54}}`; E sidecar 49/87 turns
- sha256 of every arm's `task_text` == `815f5c3f…1ac9`
- commits: `d04c3f3b..c9581e93` on `feat/effort-decay-487`
- issues: #484, #487 (fixed here), #489 (filed)
- ledger: o1-o7, e1-e7 (`e3` fail), b1-b2 — adjudicated

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| the barrier fires after a shell-first survey (#487 fixed) | high | `test_barrier_trigger_487.py` · row 77 (opened shell-first, fired at step 32) · `e1` |
| effort decay runs the post-spike tail `low` then `off` and records it | high | `test_effort_decay_wiring.py` · row 77 record · `e2` |
| an `off` floor alone does not deliver on this brief | high | rows 74-75 · `e6` (n=1 each, two different exits, one outcome) |
| `low` + decay lands correct but saves nothing (spend is pre-spike) | medium | row 76 · `e6` — n=1; barrier fired late because a heredoc write bypassed it |
| the full stack on the off floor lands correct at 16% of A's reasoning | medium | row 77 · `e6`/`e7` — n=1, one brief, one model; F also edited two unasked files |
| no default changed; everything stays opt-in | high | `effortspikes.spikes_enabled` / `effortdecay.decay_enabled` unchanged defaults · `e4` |
| the start spike's own contribution | unverified | inseparable from the stall spikes in F — a G arm (off + stall only) would isolate it; not claimed |

## Remaining Work / Follow-up

- PR #491 — triage the `ask-colleague` review and any Qodo threads; human merge.
- #490 — replicate F (n≥3), G/H arms, a second brief and model, scope discipline at `off`: the readings that keep or revert the default are pre-stated there.
- G arm (off + stall spikes only, no start spike, no decay) — isolates which of the three levers in F did the work.
- replicate F (n=2) before any default-arming proposal; the row's win condition is n=1.
- scope discipline at `off`: F edited `pyproject.toml`/CHANGELOG unasked — worth a row-77-style note in the brief or a gate.
- rig hygiene: `sf-arms` now holds nine `colleague/*` result branches; grade, then reap.

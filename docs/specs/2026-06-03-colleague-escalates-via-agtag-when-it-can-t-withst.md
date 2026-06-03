# colleague escalates via agtag when it can't withstand a request — opening one tracked continuation issue with what it finished, what's needed, and a suggested split

> colleague escalates via agtag when it can't withstand a request — opening one tracked continuation issue with what it finished, what's needed, and a suggested split

## Audience

- an agent or operator who outsourced a task to colleague that hit a limit (timeout, step/context exhaustion) and needs the work tracked and continued, not silently dropped

## Before → After

- Before: when a drive can't withstand a request it fails hard (aborted: TimeoutError) or under-delivers; the degradation layer preserves a partial result and DriveStats quantify the cost, but that signal is thrown away instead of escalated
- After: on a limit, colleague recognizes the wall and (when escalation is enabled) opens a tracked agtag issue carrying continuation (what it finished / artifact id), what's-needed (more budget / longer timeout / smaller context / a split), and a suggested pre-process & split with why + concrete suggestions

## Why it matters

- turns a dead-end into actionable, tracked continuation — the AgentCulture mesh pattern (agents file issues and request help) — instead of discarding what the drive already knew at failure time

## Requirements

- a finalize-time escalation seam in loop.py (the DriveAborted / not-finished branches, ~loop.py:778-790) that, when enabled and a limit was hit, builds a continuation record from the preserved partial result + DriveStats and posts it via the culture/agtag path
  - honesty: the finalize seam fires on BOTH the DriveAborted and the not-finished branches, reads the already-preserved partial result + DriveStats, and posts via the existing culture/agtag subprocess path (no new dep/socket/daemon)
- gating: escalation is opt-in (env/flag), offline/CI-safe (skips like handoff), respects the approval gate, and never fires from a throwaway-worktree audit or in tests
  - honesty: in CI/offline or a throwaway worktree, escalation is a strict no-op; an agtag invocation not allowed by the approval gate is denied; default-off unless the operator opts in
- idempotency: a given task escalates at most one issue; a retry of the same task updates or skips rather than filing a duplicate
  - honesty: running the same failing task twice files one issue total, not two (idempotency keyed on task_id or equivalent)
- a structured continuation-issue contract with five sections: continuation/state, remaining, what's-needed, suggested split, why
  - honesty: the filed issue body contains all five sections (continuation/remaining/needs/split/why) and reads as a tracked, continuable task

## Honesty conditions

- a deliberately-capped drive (tiny step budget / forced timeout) with escalation enabled files exactly ONE agtag issue carrying its preserved partial result; with escalation disabled the run is byte-identical to today (no post)
- the beneficiary is whoever outsourced the failed task and needs it tracked/continued — the escalation serves them, not colleague's own logs
- today the partial result + DriveStats exist at failure time but become no outward tracked artifact — verifiable by inspecting the abort / not-finished paths
- on a limit with escalation enabled, exactly one tracked issue appears carrying continuation + needs + suggested split + why, all derived from real drive state, not boilerplate
- the escalation produces an actionable, continuable artifact a human/agent can pick up — not merely a failure notification
- escalation never fires unless explicitly enabled and is a strict no-op offline / in CI / in tests / in a throwaway worktree — provable by those paths posting nothing
- concrete acceptance: a timed-out full doc-review leaves exactly one continuation issue, and a second identical run files zero additional issues (idempotent)

## Success signals

- a full-repo doc-review that times out on the local 27B leaves behind one tracked continuation issue stating what was covered, what remains, and how to split it — and a repeat run of the same task does not file a duplicate

## Scope / boundaries

- not an always-on auto-poster: an outward issue-post is a side effect, so it is opt-in/gated (like handoff's offline/CI guard + the approval gate) and idempotent (one issue per task, no duplicates across retries)

## Non-goals

- not the lightweight prompt-level self-escalation seed (in-report INCOMPLETE: covered/remaining/split) — that already shipped in the #104 doc-review template and posts nothing outward

## Decisions

- runtime-auto finalize-hook escalation (deterministic, fires on the degraded/aborted branch) is preferred over model-judged prompt-only escalation (the drive calling the culture tool itself), because the local model unreliably calls tools at the wall (#109/#104)

## Open / follow-up

- depends on #109 (result fidelity): escalation needs the partial result captured, not lost — until a drive reliably surfaces its partial state at the wall, the continuation body has nothing to carry

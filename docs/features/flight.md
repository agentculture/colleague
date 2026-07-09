# `colleague flight` — pilot a watchable work item

A work item dispatched with `colleague work --watch` (or `ask-colleague --watch`)
becomes a **flight** — a watchable, pilotable work item backed by a file-based
control plane.

> The flight plane is armed **by default** on every run (`--no-watch` /
> `COLLEAGUE_WATCH=0` to opt out), armed in the **operator repo** so it survives
> worktree cleanup, carries a **liveness heartbeat** during long completions, and
> is steerable on **every mode including plan** — see
> [`pilotable-runs.md`](pilotable-runs.md) (#307–#311).

## Control-plane files

- **`.colleague/flight/<task_id>.feed.jsonl`** — live feed. The bounded loop
  appends one JSONL record at each turn boundary, so the caller can watch
  progress without blocking.
- **`.colleague/flight/<task_id>.control.json`** — stop + guidance. The pilot
  writes directives here; the loop reads them at the next turn boundary.

## Verbs

| Verb | What it does |
|------|-------------|
| `colleague flight status <id>` | Show the latest feed record (current step, progress). |
| `colleague flight guide <id> "<msg>"` | Inject guidance the model picks up on its next turn. |
| `colleague flight stop <id>` | Cooperative stop — preserves a partial result. |
| `colleague flight list` | List active flights. |
| `colleague flight overview` | Surface description of the flight noun. |

The `ask-colleague` skill wraps these as `ask-colleague monitor <id>`,
`ask-colleague guide <id> "<msg>"`, and `ask-colleague stop <id>`, and adds
`--watch` to `explore`/`review`/`write` to arm a flight.

## Cooperative, not preemptive

Control is **cooperative**: directives land at the loop's next turn boundary,
never mid-model-call or mid-tool. A runaway process is killed by the OS/harness,
not this feature. The control plane uses file-polling (~one-turn latency), not
a live socket.

## Bounding a run: prefer a cooperative stop over a hard `timeout` (#222)

A hard external **`timeout` (SIGTERM) is the wrong tool to bound a colleague
run.** A SIGTERM that lands mid-loop is the *graceful* signal — colleague now
catches SIGTERM/SIGINT on the isolated work path and commits the model's
work-in-progress to the `colleague/<id>` branch before exiting, so a wrapped
`timeout 300 colleague work …` no longer strands a near-complete run as
uncommitted files in an orphan worktree (the interrupt commit lands on the
branch; the worktree is then reaped). An uncatchable **SIGKILL** (e.g.
`timeout -s KILL`, OOM, power loss) still can't be caught — it leaves an orphan
`.colleague/worktrees/iso-*` worktree, which **`colleague clean` now reaps** (it
removes orphaned `iso-*` worktrees before the `colleague/*` branch reap, so a
checked-out branch becomes deletable in one command).

The **documented graceful way to bound a run** is `colleague work --watch` plus a
cooperative `colleague flight stop <id>` (or `ask-colleague stop <id>`): the loop
stops at the next turn boundary and — on the isolated path — its WIP is committed
to `colleague/<id>` the same way, so a piloted stop is non-destructive.

A heartbeat/elapsed progress signal and a soft `--deadline` flag (a graceful
commit at the deadline instead of a hard external SIGTERM) are a **parked
follow-up**, not yet built.

## Depth cap

Nested flights are guarded by `COLLEAGUE_FLIGHT_DEPTH` (default 1) — a
fork-bomb guard that prevents infinite nesting of watchable flights.

## Lifecycle

Flight files are reaped on work-item finish and by `colleague clean`.

## See also

- [`docs/features/ask-colleague.md`](ask-colleague.md) — the `ask-colleague` skill
  and its piloting surface.
- Spec: `docs/specs/2026-06-13-colleague-flights-are-now-piloted-after-ask-collea.md`
- Plan: `docs/plans/2026-06-13-colleague-flights-are-now-piloted-after-ask-collea.md`

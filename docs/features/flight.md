# `colleague flight` — pilot a watchable work item

A work item dispatched with `colleague work --watch` (or `ask-colleague --watch`)
becomes a **flight** — a watchable, pilotable work item backed by a file-based
control plane.

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

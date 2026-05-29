# Destination

> Convertible's destination tells the engine where it's going, not just where it
> is. An engine MAY set a curated `devague` loop tool to open and converge a
> goal-frame when a task warrants one, drive toward it, and declare the
> announcement on arrival — so convertible knows its destination before it drives.

## Before → after

**Before** this feature, a `convertible drive` had only one compass:

- GPS/telemetry reported *where the drive was* (execution trace, step count,
  time elapsed).
- But there was no shared notion of *where it was going* — a vague task was
  driven straight on vibes; 'done' just meant the loop finished or hit its step
  budget, not that a stated goal was reached.
- The engine and operator had no converged, persisted goal-frame to agree on
  before changes began.

The destination feature unlocks predictable execution for vague tasks: **converge
before driving**.

**After** this feature:

- When a task warrants it, the engine can set a destination — capture and
  converge a devague goal-frame via a curated `devague` loop tool — before
  changing the repo.
- The engine drives toward that goal, and when it arrives, declares the framed
  announcement.
- The destination (frame slug + declared announcement) is recorded in the JSON
  artifact as lightweight metadata — so convertible knows where it's going, and
  there's a clear arrival signal.
- Convergence is *advisory* — the engine can inspect gaps via `status`, but only
  operator-confirmed claims are authoritative.
- Setting a destination is *optional and engine-judged* — a clear task just
  drives; only vague/new tasks that benefit from goal-setting open a frame.

## The GPS + Destination metaphor

Convertible has two compasses:

- **GPS** (telemetry): tells convertible *where it is* right now — execution
  trace, metrics, live step count. Off by default (the `[otel]` extra).
- **Destination**: tells convertible *where it's going* — the converged goal-frame
  and the announced arrival. Off by default (only set when the engine judges it
  necessary).

Together they bound the drive: destination = the goal, GPS = the journey.

## How it works

### The `devague` loop tool

The chassis offers a single `devague` tool (registered in `convertible/tools.py`,
exactly like the `culture` tool) that shells out to the operator-installed
`devague` CLI. An engine can:

- **`new`** — open a fresh goal-frame.
- **`capture`** — record a claim into the current frame.
- **`interrogate`** — probe a claim (ask for evidence, reasoning, etc.).
- **`park`** — defer a claim thread (mark it unsolved for now).
- **`converge`** — signal that the frame is ready to converge (check for gaps).
- **`status`** — inspect the current frame (list claims, gaps, convergence status).
- **`show`** — display the full frame.

### The curated allow-list

The tool structurally **excludes** three devague moves:

- **`confirm` / `reject`** — these are *user-only decisions*. The engine must
  never confirm its own claims, enforcing devague's epistemic discipline (you
  can't be sure about your own ideas in isolation).
- **`export`** — this is *operator-only*. The engine does not write spec files.
  Arrival is recorded as a lightweight announcement (a string), not a full frame
  dump.

### Identity and subprocess launch

Each devague call:

- Runs with `cwd` pinned at the repo root so the CLI sees `culture.yaml` (for
  auto-signing).
- Injects the resolved process identity via `CONVERTIBLE_IDENTITY` (exactly as
  the `culture` tool does) so the CLI inherits the drive's nick.
- Launches as a subprocess — no socket, no daemon, no Python import of devague.
- Maps a missing CLI (`FileNotFoundError`) to a clean `ToolError` fed back to
  the model — never a traceback.
- Caps output at 20,000 chars and enforces a 300-second timeout.

### Convergence is advisory

The engine can call `converge` to signal the frame is ready and inspect gaps
(uncovered claims), but:

- The engine's own proposed claims are *never self-confirmed* — they remain
  advisory without human review.
- Only operator-confirmed claims (set up front by the user) carry authoritative
  convergence weight.
- The destination is recorded in the artifact; the user can inspect it and
  decide to confirm/reject it outside the drive loop.

### Lightweight arrival and the artifact

When the engine finishes (via the `finish` tool), it MAY declare:

```json
{
  "destination": "frame-slug",
  "announcement": "The refactor is complete: models.py has been split into..."
}
```

The JSON artifact then records:

```json
{
  "destination": "frame-slug",
  "announcement": "The refactor is complete: models.py has been split into..."
}
```

Without a destination, both keys are **omitted entirely** (not `null`) —
`TaskResult.to_dict()` drops them when unset, so the artifact is byte-identical
to drives without the feature.

## Enabling it

An operator enables this feature by **installing the `devague` CLI** — no
bespoke wiring:

```bash
uv tool install devague
```

If the engine's system prompt (via layered AGENTS/skills config) encourages
destination-setting (which it does in the v0 guidance), the engine will have the
tool available to use when a task warrants it.

## A worked example: vague task benefiting from a destination

**Scenario:** A task comes in: *"Improve the test suite."*

Without a destination, the engine:

1. Drives straight into the repo, adds a few tests, maybe refactors a test helper.
2. Runs out of steps. Finishes with a summary: "Added 5 tests to test_foo.py."
3. No one (human or AI) knows what "improve" means — the work was ad-hoc.

**With a destination:**

1. The engine recognizes the task is vague and decides to set a destination.
2. Opens a new frame: `devague new --origin engine`. Now there's a persisted goal.
3. Captures a claim: `devague capture "Test coverage for the auth module should
   reach 85% (currently 62%)."` Another: `"Refactor test_helpers.py to reduce
   duplication — 3 helpers can share one base."` Another: `"Add integration
   tests for the login flow."` The claims are persisted and versioned.
4. Calls `devague status` to see gaps. The frame shows three claims. The engine
   can interrogate them: `devague interrogate "Test coverage..." --ask "How do
   we measure 85%?"` The CLI feeds back a clarification.
5. When ready, calls `devague converge` to signal "the goal is clear." The frame
   records a convergence signal (advisory, from the engine's perspective).
6. Drives: writes tests, refactors helpers, hits each claim, reaches the goal.
7. On finish: declares the announcement: `destination: "improve-test-suite"`,
   `announcement: "Auth module coverage: 87% (was 62%). Refactored test_helpers.py
   (3→1 base). Added login integration suite."`
8. The artifact records both the goal-frame and the announcement.
9. The operator (or a reviewing human) reads the artifact, sees the converged
   goal, and sees the declared arrival — the work is measured against the goal,
   not vibes.

The difference: *without* the destination, "improve" is undefined; *with* the
destination, everyone agrees on what "better" means before the work starts.

## Boundaries that still hold

- **No new runtime dependency.** `convertible/devague.py` is stdlib-only (just
  `subprocess`, `pathlib`, `os`). The zero-deps guard and `dependencies = []`
  still hold.
- **No live devague client.** The devague tool shells out to the operator-installed
  CLI — no socket, no daemon, no library import. Convertible reads no devague
  Python API.
- **Setting a destination is optional and engine-judged.** A clear task just
  drives; only vague/new tasks benefit from goal-setting. The engine (via
  system-prompt guidance) decides when a destination is warranted — convertible
  never forces convergence.
- **Convergence remains user-authoritative.** The engine's own convergence signal
  is advisory; only human-confirmed claims carry weight. The user-only discipline
  is enforced structurally (the allow-list excludes `confirm` / `reject`).
- **The destination tool belongs to the chassis.** `convertible/tools.py` owns
  the tool schema and dispatch; `convertible/devague.py` owns the subprocess
  launch, identity injection, and allow-list enforcement. No engine module touches
  devague directly. The all-engines rule applies: every engine sees the tool
  identically.
- **Arrival is lightweight, not a file commitment.** The announcement is a
  string recorded in the artifact, not a spec file exported to `.devague/`.
  The frame lives under `.devague/`, but arrival does not commit or push it.

## Key files

- `convertible/devague.py` — `run_devague()`, `ALLOWED_MOVES`, `normalize_args()`.
- `convertible/tools.py` — `devague` tool schema in `SCHEMAS`; `_devague`
  dispatch in `ToolExecutor`.
- `convertible/contract.py` — `TaskResult` fields `destination` + `announcement`.
- `convertible/artifact.py` — JSON artifact includes the destination + announcement.

## See also

- [drive-and-loop.md](drive-and-loop.md) — the bounded tool-loop and the full
  tool surface.
- [layered-config.md](layered-config.md) — how the engine's system prompt
  (AGENTS instructions) provides guidance on destination-setting.
- [mesh-member.md](mesh-member.md) — the `culture` tool, a sibling chassis-owned
  tool following the same shell-out + allow-list pattern.
- The spec and plan that converged this feature:
  [`docs/specs/2026-05-29-convertible-knows-its-destination-before-it-drives.md`](../specs/2026-05-29-convertible-knows-its-destination-before-it-drives.md)
  and [`docs/plans/2026-05-29-convertible-knows-its-destination-before-it-drives.md`](../plans/2026-05-29-convertible-knows-its-destination-before-it-drives.md).

# Every run is pilotable, alive, and steerable

**Talk to, watch, and steer any colleague run — from a second terminal.** The
flight-control plane (`colleague talk` / `colleague flight` / senses
live-presence) is armed **by default**, in the **operator's repo** (not a
throwaway worktree), shows a **live heartbeat** even during a long completion,
takes **steering at every mode's natural checkpoint** (including plan), and
records **every senses turn** — dispatched *and* senses-direct — as an auditable
artifact.

This is the smooth-piloting arc: five interlocking fixes (#307–#311) so the
talk/watch/steer capability the senses arcs promised actually works on the
batch/agent surfaces it was built for. It stays inside the runtime conventions —
no daemon, no socket, no new thread, no new base dependency; the plane is an
append-only side file, cooperative, and a strict no-op when nobody attaches.

## The load-bearing fix — #310: arm the plane in the operator repo

`colleague work` isolates every run in a throwaway `iso-<id>/` git worktree
(#196/#201), and `_setup_isolation` reassigns `task.repo_path` to it. The loop
armed the flight plane at `task.repo_path` — so the feed/control landed **inside
the worktree** and were destroyed when it was cleaned up, while `colleague talk`
/ `colleague flight` resolved the **operator repo**, a different directory. The
two never connected: piloting was silently dead for `colleague work` /
`--background` (only the in-place `session` path worked).

The fix decouples the plane's location from the work CWD:

- `Task.flight_repo_path` (`colleague/contract.py`) — the operator-repo path the
  plane arms at, distinct from `repo_path` (the work CWD). Omit-when-None: a
  non-isolated task serializes byte-identically.
- `colleague/loop.py` `_flight_repo_path(task)` = `task.flight_repo_path or
  task.repo_path` — the single source of truth; `_arm_flight` and
  `_fold_flight_chat` both use it.
- `_setup_isolation` stamps `flight_repo_path=str(repo)` on the isolated task, so
  the loop runs in the worktree while the plane lives in the operator repo — and
  survives worktree cleanup.

The in-place `session` path leaves `flight_repo_path=None` (arm at `repo_path` =
operator repo), byte-identical. Writing `.colleague/flight/` into the operator
repo does not trip the #149 dirty-tree guard (`.colleague/*` is gitignored), and
distinct-`<id>` files never collide between concurrent runs.

## #307 — armed by default (opt-in → opt-out)

Every run (`work` / `drive` / `session`) arms the plane by default so the senses
talk/watch/steer lane is discoverable, not hidden behind a flag.

- `EngineConfig.watch` (default `True`), resolved **flag > env
  (`COLLEAGUE_WATCH`) > `.colleague/config.json` `{"watch": false}` >
  default-on** — the lint-gate precedent.
- `colleague work` keeps `--watch` as the explicit alias and adds `--no-watch`
  as the opt-out. The `session` default-arms the file plane too (decision c18),
  so a second terminal can `colleague talk` into a running interactive session.
- **Nesting-safe**: a default-on watch at the flight depth cap degrades to
  no-watch *silently* — only an *explicit* `--watch` at depth is a hard error —
  so a nested run is never broken.
- The flight-attach handle is emitted from `execute_work` **after** every guard
  (dirty tree, unknown engine), so a refused run never prints a stray handle
  before its `error:` line.

This is a **deliberate, recorded default flip**. Stdout and the `TaskResult`
artifact stay byte-identical (the feed is a side file); only the presence of the
side-file plane changes.

## #308 — a liveness heartbeat during a long completion

A reasoning cortex can spend minutes on its first completion with no tool call.
The feed only got a line on a `WorkStep`, so it was empty and `colleague talk` /
senses could only answer "I don't know" — the run looked dead while thinking.

- `colleague/flight.py` gains `append_run_start` and `append_heartbeat` — distinct
  `type`-tagged markers (`{"type": "run-start" | "heartbeat", ...}`). A step
  record has **no** `type` key (byte-identical), so a consumer that must count
  steps or replay step-only filters markers by `record.get("type")`. Markers
  still carry the common `step_index`/`intent` keys, so existing feed readers
  render them as informative liveness, never a `KeyError`.
- `colleague/loop.py` writes a **run-start marker** before the first completion
  (so senses can say "cortex started, working on `<goal>`" immediately) and folds
  the #206 pre-completion phase notice into the feed as a **heartbeat**
  (`phase`, elapsed since a stored monotonic start, `step N/max`) in
  `_emit_phase`.

The **#206 step-only invariant holds**: a marker never advances `step_count`, and
`tui replay` / `tui snapshot` read the *events* sink (not the flight feed), so
they are structurally unaffected — proven by
`test_206_invariant_watch_does_not_change_the_step_trace`.

## #309 — steering on every mode, including plan

Mid-run steering (`colleague flight guide` / `colleague talk … cortex:`) applied
only inside the bounded tool loop. Plan mode drives the model via
`Engine.make_complete` **outside** the loop, so it had no plane and could not be
steered at all.

`colleague/plan/orchestrator.py` `run_plan_mode` gains an optional `flight`
plane and cooperative injection checkpoints at its **natural boundaries** —
before the spec stage, before plan-item proposal, before each wave:

- A `stop` halts the plan cooperatively (the partial `OrchestratorResult` is
  returned, `"stopped at <boundary>"` recorded on `OrchestratorResult.steering`).
- `guidance` is drained, recorded on `steering`, written to the feed as a
  `tool="steering"` record, and — at the pre-spec boundary — threaded into the
  request the spec stage proposes from (so the next proposal is actually steered).

`colleague plan run --watch` arms the plane at the **operator repo** (plan runs
in-place, not the #310 worktree case). `flight=None` (no `--watch`) is a strict
no-op, byte-identical to a pre-#309 plan run. Steering is now uniform across
`work` / `drive` / `explore` / `review` / `plan`.

## #311 — an auditable record for senses-direct turns

A **senses-direct** turn (the front door answering a non-repo turn itself) has no
`Task`/`TaskResult`, so a direct answer — or a misroute — was unauditable from
artifacts alone (the dispatched path already records
`senses-frontdoor:<route>` on `TaskResult.senses.records`).

`colleague/frontdoor.py` `run_frontdoor` now writes a lightweight
`.colleague/senses-direct/<id>.json` `SensesDirectRecord`
(`{route, text, answer, latency, tokens, degraded, at}`) for **every**
senses-direct route — a clean answer **and** a degraded/misroute fallback — with
the operator's **verbatim** text. Centralized in the one shared decision function
so both fronts (the session and the mesh resident pass `record_repo`) get it
(decision c19: a standalone file, not a session ledger). A strict no-op when the
front door does not fire / senses is unarmed / `--cortex-only` / no `record_repo`,
and it changes **no** routing decision.

## Honest limits

- **Cooperative granularity, not preemption.** Steering lands at the next
  boundary, never mid-completion. #308's heartbeat exists to make the wait
  *visible*, not to eliminate it. This is by design.
- **Heartbeat cadence** (parked, r1): a heartbeat fires per pre-completion phase
  notice; an elapsed-threshold / interval knob is a documented follow-up.
- **Plan steering depth** (parked, r2): v1 exposes the top-level orchestrator
  stage/batch boundaries; steering individual workforce children (each in its own
  subagent worktree) is a follow-up. Per-wave guidance is recorded and fed but the
  already-built frame is fixed.
- **Rig-dependent live proof.** The unit tests encode each repro red-before /
  green-after (`test_flight_operator_repo.py`, `test_flight_heartbeat.py`,
  `test_plan_steering.py`, `test_senses_direct_record.py`); the served-rig
  livecheck classifiers (`colleague/livecheck.py`
  `classify_flight_reachable_check` / `classify_flight_liveness_check`) SKIP
  honestly when the rig cannot serve or senses is unarmed.
- **senses-direct / observability unification** (parked, r6, follow-up): the
  standalone record could later be unified with the flight-feed / `TaskResult`
  surfaces into one query path for every senses turn.
- Not a daemon, socket, transport, or routing policy — the plane stays the
  existing append-only file surface and cortex stays the only repo actor.

## Spec + plan

- Spec:
  `docs/specs/2026-07-09-every-colleague-run-is-pilotable-alive-and-steerab.md`
- Plan:
  `docs/plans/2026-07-09-every-colleague-run-is-pilotable-alive-and-steerab.md`

Related: `docs/features/flight.md` (the piloting/flight plane),
`docs/features/senses-live-presence.md` (the talk lane),
`docs/features/talking-to-one-teammate.md` (the senses front door).

# Every colleague run is pilotable, alive, and steerable — you can talk to it, watch it, and redirect it from a second terminal on work, drive, session, plan, and background runs, because the flight plane is armed by default in the operator's repo (not a throwaway worktree), shows a live heartbeat even during a long completion, accepts steering at each mode's natural checkpoint including plan, and records every senses turn (dispatched or direct) as an auditable artifact

> Every colleague run is pilotable, alive, and steerable — you can talk to it, watch it, and redirect it from a second terminal on work, drive, session, plan, and background runs, because the flight plane is armed by default in the operator's repo (not a throwaway worktree), shows a live heartbeat even during a long completion, accepts steering at each mode's natural checkpoint including plan, and records every senses turn (dispatched or direct) as an auditable artifact

## Audience

- operators driving colleague from a second terminal (interactive + agent/batch callers) and senses live-presence consumers — colleague talk, colleague flight status|guide|stop, piloting agents, and the resident appserver

## Before → After

- Before: the flight plane is opt-in and, for colleague work, armed INSIDE the throwaway isolation worktree (loop.py arms at task.repo_path, which _setup_isolation reassigned to iso-<id>/) so talk/flight/steer resolve a different directory and the feed is destroyed on worktree cleanup; the feed is silent during a long completion (senses says 'I don't know' for minutes); plan mode has no flight plane and cannot be steered at all; and a senses-direct front-door turn produces no Task/TaskResult, so it is unauditable from artifacts alone
- After: every run (work / drive / session / plan / background) arms a reachable flight plane in the OPERATOR repo by default; the feed shows a run-start marker and a live heartbeat during long completions; guidance is steerable at each mode's natural checkpoint including plan; and every senses turn — dispatched OR senses-direct — leaves an auditable artifact

## Why it matters

- talk/watch/steer + senses live-presence is the whole point of the senses-live-presence and talking-to-one arcs, yet it is silently non-functional today for exactly the batch/agent surfaces (colleague work, --background) it was built for — only the in-place session path works; an operator cannot rely on a capability that works in some modes and silently dies in others

## Requirements

- [#310] the flight plane (FlightSession / feed / control) is armed at the ORIGINAL operator repo path, threaded separately from the isolation-reassigned task.repo_path, so the loop executes in the iso-<id> worktree while the plane lives in the operator repo — decoupling the flight-plane location from the work CWD
  - honesty: a mock 'colleague work --watch' (a write run, so it isolates) leaves .colleague/flight/<id>.feed.jsonl in the OPERATOR repo and it survives worktree cleanup (the issue's repro #5 flips to passing)
  - honesty: colleague talk / flight status|guide|stop and the loop's read_control/append_feed/append_guidance resolve the SAME operator-repo files, so injected guidance actually drains into the running loop (issue repro #4 flips to guidance-applied)
- [#307] the flight plane is armed by DEFAULT for work / drive / session, opt-out via --no-watch and/or COLLEAGUE_WATCH=0 and/or .colleague/config.json {watch:false} on the established flag>env>config>default precedence; --watch is kept as an explicit alias
  - honesty: a run with NO pilot attached is byte-identical on stdout and in TaskResult/artifact shape — the e2e mock shape test still passes and the feed is a pure side file
  - honesty: precedence resolves flag>env>config>default: --no-watch, COLLEAGUE_WATCH=0, and .colleague/config.json {watch:false} each disarm; --watch stays an accepted explicit alias; colleague clean still reaps the always-armed residue
- [#308] the loop writes a run-start marker to the feed at task start and folds the #206 pre-completion phase notice (thinking/synthesizing/compacting, with elapsed + step N/max) into the flight-feed sink as a distinct heartbeat feed record consumed by the live lane (colleague talk, run_senses_talk/update grounding, flight status) but ignored by tui replay/snapshot
  - honesty: the heartbeat/run-start feed record does NOT advance step_count and does NOT appear in tui replay/snapshot (the #206 step-only invariant holds) — pinned by a test
  - honesty: fires identically for mock and vllm-openai (all-engines) and is a strict no-op when no plane is armed
- [#309] plan mode gets a flight plane and cooperative injection checkpoints at the orchestrator's natural boundaries (between spec/plan/workforce stages, per claim-proposal batch, per plan-item batch), so an operator can steer a plan mid-run; steering is uniform across work/drive/explore/review/plan and stays cooperative + strict no-op when nobody steers
  - honesty: plan-mode injection is cooperative: guidance is applied only at an orchestrator stage/batch boundary, never mid-completion, and a plan run with nobody steering is byte-identical
  - honesty: the same operator command (colleague flight guide / talk 'cortex:') steers uniformly across work/drive/explore/review/plan, and the plan plane is armed at the operator repo path (composes with #310)
- [#311] each senses-direct front-door turn emits a lightweight standalone JSON record {route, text (verbatim), answer, latency, tokens, degraded, at} in the SensesRecord shape family, beside the .colleague/ artifacts, so direct answers and misroutes are measurable from artifacts alone; strict no-op when the front door does not fire / senses is unarmed / --cortex-only
  - honesty: the record's text field is verbatim operator text, never derived from model output (the v1 verbatim invariant), and it is a strict no-op when the front door doesn't fire / unarmed / --cortex-only — pinned by a test
  - honesty: it does NOT change routing: a dispatched (cortex) front-door turn still records senses-frontdoor:<route> on TaskResult.senses.records exactly as before

## Honesty conditions

- on the served rig, all four issue repros flip from broken to working AND a no-pilot / plane-off run stays byte-identical (e2e mock shape test green)
- each named consumer (colleague talk, flight status|guide|stop, piloting agents, resident appserver) actually reads/writes the flight files, so arming the plane in the operator repo makes all of them functional on a work/background run
- the after_state is demonstrable end-to-end: all four issue repros pass on the served rig and a plane-off/no-pilot run is byte-identical (e2e mock shape green)
- the described breakage is code-confirmed today: loop.py arms at task.repo_path (661-666), _setup_isolation reassigns it to iso-<id>/ (work.py:278), the worktree is removed on finish (work.py:764) — the #310 repros reproduce as written
- today only the in-place session path (isolate=False) works; a colleague work/--background run verifiably reports 'no active flight' and never drains guidance — the capability is dead on exactly the batch/agent surfaces
- test_boundary.py and test_zero_deps.py still pass: no new subprocess/socket/daemon/thread, no new base dep, and a no-attach run is byte-identical on stdout + TaskResult
- the #206 step-only invariant test passes (heartbeat adds no step, replay/snapshot unchanged) and no task->model routing is introduced anywhere in the arc
- each of the four success repros is captured as a check that was red before and green after (livecheck and/or unit tests), so success is measured, not asserted

## Success signals

- the exact live repros in the issues flip from broken to working: a backgrounded colleague work run's feed is reachable in the operator repo and survives worktree cleanup; colleague talk during a long first completion returns a real 'cortex started, ~Ns elapsed, N/max steps, thinking' status instead of 'I don't know'; colleague flight guide lands and drains guidance in a plan run; and a senses-direct turn writes a standalone JSON record — all verifiable on the served rig and byte-identical when the plane is off

## Scope / boundaries

- stays file-based and cooperative: NO daemon, NO socket, NO new thread, and no new base dependency; the flight plane remains an append-only side file, steering is applied only at a mode's natural checkpoint (never preempting a completion mid-stream), and it is a strict no-op — byte-identical stdout + TaskResult — when nobody attaches or steers
- NOT a change to routing or to any model-selection policy: #311 only records what senses-direct already decided (no new task->model routing), the heartbeat is a separate feed record type that does NOT advance step_count and does NOT appear in tui replay/snapshot (the #206 step-only invariant holds), and plan-mode steering adds checkpoints at existing orchestrator stage/batch boundaries, not preemptive mid-completion interrupts

## Non-goals

- not a colleague-owned daemon, server-mode, socket, or transport (that stays the excluded router/daemon line in v1 scope); the plane stays the existing append-only file surface
- not preemptive steering — colleague will NOT interrupt a completion mid-stream; the cooperative-granularity limit (guidance lands at the next boundary) is acknowledged, and #308's heartbeat exists precisely to make the wait visible rather than to eliminate it
- not a fix for rig/model slowness itself — a reasoning cortex genuinely taking minutes per completion is orthogonal; this arc only makes that liveness visible and the run steerable at boundaries
- does not change any routing/model-selection decision — #311 is observability only (records what senses-direct already decided); still no automatic task->model routing policy

## Decisions

- session also arms the file-based flight plane by default (in addition to keeping its in-place stdin talk lane), so a second terminal can 'colleague talk' into an interactive session too — resolving #307's open interaction toward 'both'
- the senses-direct record lands as a standalone JSON file under .colleague/ (e.g. .colleague/senses-direct/<id>.json), NOT folded into a session-scoped ledger — matching where .colleague/ artifacts already live and keeping the offline-audit read a simple directory glob

## Hard questions

- does writing .colleague/flight/ into the operator repo during an isolated run trip the #149 dirty-tree guard or collide between two concurrent runs? (expect: .colleague/ is gitignored side state, files are keyed by distinct <id>, no collision — must be verified not assumed)

## Open / follow-up

- whether the senses-direct standalone record should later be unified with the flight-feed/TaskResult observability surfaces (one query path for all senses turns) — a consolidation follow-up, not needed for v1 auditability

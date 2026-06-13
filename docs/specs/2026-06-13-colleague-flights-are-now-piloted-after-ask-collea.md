# Colleague flights are now piloted: after ask-colleague dispatches a task, the calling agent can watch it work over a live feed, send mid-flight guidance to change its course, and call it back cleanly — a steerable delegation, not a black box you wait on — all over plain files, no daemon or socket.

> Colleague flights are now piloted: after ask-colleague dispatches a task, the calling agent can watch it work over a live feed, send mid-flight guidance to change its course, and call it back cleanly — a steerable delegation, not a black box you wait on — all over plain files, no daemon or socket.

## Audience

- The agent (usually Claude) that dispatched a colleague work item via ask-colleague, plus the operator watching the run.

## Before → After

- Before: Today ask-colleague explore/review/write run synchronously and opaquely: the caller blocks until the single final TaskResult, with no way to see progress, redirect, or stop a running work item short of killing the process.
- After: After dispatching a flight, the caller can read a live progress feed, inject guidance the running loop picks up at its next turn boundary, and request a cooperative stop — instead of blocking blind until the one final result.

## Why it matters

- A wrong-but-running delegation today burns its whole step/token budget before the caller learns it went off course; piloting lets the caller catch and correct it early, raising the ROI of delegating to a different (often weaker) mind.

## Requirements

- The loop writes an incremental live-progress feed (per-turn: step index, last tool + intent, running WorkStats) to a per-flight file at each turn boundary, readable WHILE the work item is still running.
  - honesty: A test runs a multi-turn mock flight and asserts the live-progress file gains a new turn record at each boundary, parseable mid-run (not only written at the end).
- At each turn boundary the loop reads a per-flight control file and honors two directives: 'stop' (cooperative — preserves a partial result exactly like the degradation give-up path) and 'guidance' (injects a user-role message into the running history so the model incorporates it on the very next turn).
  - honesty: A test drops a 'stop' control file mid-flight and asserts the loop ends cooperatively with a preserved partial result; a second test drops a 'guidance' file and asserts the injected message appears in the next model prompt.
- The flight-control plane is runtime-owned in colleague/loop.py and fires identically for the mock and vllm-openai backends (the all-engines rule); with no flight/control file present it is a strict no-op — byte-identical TaskResult and step trace to today.
  - honesty: tests/test_e2e_mock.py still passes unchanged with no flight files present (strict no-op), and a parallel mock-vs-vllm shape assertion shows the control plane is wired in the shared loop, not a backend.
- A watchable dispatch prints the task_id AND the flight-file paths IMMEDIATELY on launch (before the work completes), so the pilot can attach; ask-colleague gains monitor/guide/stop verbs and a matching 'colleague flight' CLI noun with status/guide/stop/list plus an overview.
  - honesty: An ask-colleague launch in watch mode prints a resolvable task_id + flight-file path to stdout BEFORE completion; 'colleague flight overview' and 'colleague flight status <id>' exist and pass the CLI rubric (teken doctor --strict).
- Flight files live under .colleague/flight/<task_id>.* and are reaped on finish and by 'colleague clean', scoped strictly to .colleague/flight/ (never an unrelated path), like neighbours and worktrees.
  - honesty: A test asserts flight files are created under .colleague/flight/<task_id>.* and removed on finish, and that 'colleague clean' reaps an orphaned flight file while leaving unrelated paths untouched.
- Piloting is caller-agnostic and symmetric: a colleague work-loop can ITSELF dispatch and pilot a sub-flight (the 'Colleague calls ask-colleague' path), not only Claude. No code path special-cases the caller being Claude; the watchable dispatch + 'colleague flight' verbs are the shared substrate, reached from a colleague run via the loaded ask-colleague skill + run_command over the same CLI.
  - honesty: A test/demo shows a NON-Claude caller piloting: a colleague work-loop (mock engine) dispatches a sub-flight, reads its feed, and writes a guidance directive via the 'colleague flight' CLI — proving the pilot path has no Claude-specific assumption.
- Recursion/termination safety: a colleague piloting a sub-flight (which is itself a colleague that could pilot a sub-sub-flight) is structurally bounded by a depth cap (akin to MAX_SUBAGENT_DEPTH) so nested flights cannot fork-bomb; the flight CLI is gated by the approval gate when invoked via run_command, like any other program token.
  - honesty: A test asserts a nested-flight depth cap is enforced before any sub-sub-flight starts (fork-bomb guard), mirroring the MAX_SUBAGENT_DEPTH check-before-work semantics.

## Honesty conditions

- End-to-end, the announcement is demonstrable: a single recorded session shows dispatch -> live watch -> mid-flight guidance changes course -> cooperative stop with preserved partial, using only files under .colleague/ (no socket/daemon).
- The pilot surface is documented for the dispatching-agent audience: docs/features/ask-colleague.md gains a piloting section and 'colleague flight overview' names this audience.
- The before-state is provable: today's ask-colleague explore/review/write block until the final result with no progress/redirect/stop verb — confirmed by the absence of any such verb in the current CLI surface.
- All three caller affordances are exercised end-to-end against a running mock flight: a test reads the live feed mid-run, injects a guidance directive that appears in the next prompt, and requests a cooperative stop that yields a preserved partial result.
- A worked example shows an early correction saving budget vs a blind run (e.g. a flight redirected at turn 3 instead of burning all 40 steps), demonstrable in the demo from c9.
- A test proves a stop/guidance directive written DURING a turn takes effect only at the NEXT boundary (cooperative), never mid-turn — and that no code path opens a socket or forks a daemon (boundary test extended).
- tests/test_zero_deps.py and the boundary tests are extended to assert the flight feature uses only stdlib (json/pathlib), opens no socket, and forks no daemon — and both still pass.
- The c9 demo is captured as a reproducible script/recording (steps: dispatch, observe wrong course, guide, observe course change, stop, inspect preserved partial).
- A test confirms colleague-as-caller does NOT block on the sub-flight: the detached-launch + poll-across-turns pattern is exercised (or documented as the supported pattern), and run_command's detached launch is shown gated by the approval gate.

## Success signals

- A live demo: Claude dispatches a flight, sees from the live feed it is heading the wrong way, sends one guidance message, the work item visibly changes course on its next turn, then is cleanly stopped with a preserved partial result.

## Scope / boundaries

- Control is cooperative and checkpoint-based — directives are applied only at per-turn loop boundaries, never preemptively; it cannot interrupt an in-flight model call or a long-running run_command. A runaway is killed by the OS/harness, not by this feature.
- No daemon, no socket, no server, zero new deps: the control plane is plain files under .colleague/flight/, polled at turn boundaries — consistent with colleague's conventions (like hooks, telemetry, neighbours).
- Honest concurrency limit for colleague-as-caller: colleague's loop is single-threaded and run_command blocks, so to pilot a sub-flight colleague launches it DETACHED via the shell (nohup/&) through run_command (gated by the approval gate) and polls the feed file across its own subsequent turns. This honors 'backgrounding is the caller's job' (c15) — colleague backgrounds via the shell, not a --detach feature — and is NOT true in-process parallelism.

## Decisions

- Backgrounding is the caller's responsibility: colleague work stays a single foreground process; the harness (run_in_background) or shell & runs it in the background. No --detach fork, no daemon.
- Pilot controls live under a new 'colleague flight' CLI noun (status/guide/stop/list/overview); ask-colleague gains monitor/guide/stop verbs that wrap it (agent-first, matches every other colleague surface).
- v0 ships exactly two control directives: 'stop' (cooperative) and 'guidance' (inject message); pause/resume is parked as a follow-up, not built in v0.
- v0: Colleague-as-pilot works via the loaded ask-colleague skill + run_command over the 'colleague flight' CLI (launch detached, poll feed, guide/stop) — no dedicated loop tool. Symmetric with Claude-as-pilot by construction; gated by the approval gate.

## Open / follow-up

- Relationship to issues #188/#191/#192 (no-result / forced-synthesis on step-budget exhaustion): a cooperative stop must report status honestly (not 'ok' with no result) — compose with that work rather than duplicate it.
- Follow-up: a dedicated curated 'flight' loop tool (flight_dispatch/status/guide/stop) so a colleague backend pilots a sub-flight first-class without shell-backgrounding through run_command. Deferred from v0.

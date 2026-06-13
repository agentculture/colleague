# Build Plan — Colleague flights are now piloted: after ask-colleague dispatches a task, the calling agent can watch it work over a live feed, send mid-flight guidance to change its course, and call it back cleanly — a steerable delegation, not a black box you wait on — all over plain files, no daemon or socket.

slug: `colleague-flights-are-now-piloted-after-ask-collea` · status: `exported` · from frame: `colleague-flights-are-now-piloted-after-ask-collea`

> Colleague flights are now piloted: after ask-colleague dispatches a task, the calling agent can watch it work over a live feed, send mid-flight guidance to change its course, and call it back cleanly — a steerable delegation, not a black box you wait on — all over plain files, no daemon or socket.

## Tasks

### t1 — Flight control-plane primitives (colleague/flight.py): paths strictly under .colleague/flight/<id>.{feed.jsonl,control.json} via configdir; FlightSession dataclass; feed-record append (step idx + last tool/intent + WorkStats snapshot) as one JSONL line per call; control read/parse into stop|guidance directives with guidance-consumed tracking; reap helper + orphan-lister scoped to .colleague/flight/; depth-cap helper over COLLEAGUE_FLIGHT_DEPTH. Pure stdlib (json/pathlib/os).

- covers: c10, c11, c14, c20, h14
- acceptance:
  - feed-append writes exactly one JSONL-parseable record per call, readable mid-run
  - control parse returns a stop directive and an UNCONSUMED guidance, then marks the guidance consumed so it is not re-read next turn
  - path + reap helpers operate strictly under .colleague/flight/ and refuse/ignore any path outside it
  - depth helper denies arming when COLLEAGUE_FLIGHT_DEPTH >= cap (default 2, like MAX_SUBAGENT_DEPTH), before any work
  - colleague/flight.py imports only stdlib (json/pathlib/os) - no third-party, no socket, no threading

### t2 — Loop integration of the control plane (colleague/loop.py + colleague/contract.py): add optional Task.watch field; in run() build a FlightSession from the EXISTING task param when task.watch (NO new run() param - S107 13-ceiling); at the per-turn boundary in _work_loop append a feed record, read control, honor stop (cooperative finish reusing the degradation preserve-partial path) and guidance (inject a user-role message for the next turn, mark consumed); reap flight files on finish; strict no-op when not armed.

- depends on: t1
- covers: c4, c6, c12, h1, h2, h3, h9, h15
- acceptance:
  - a multi-turn mock flight appends one feed record per turn boundary, each parseable mid-run (not only at the end)
  - a stop control file dropped mid-flight ends the loop cooperatively with a preserved partial result; a guidance file injects its message into the very next model prompt
  - a directive written DURING a turn takes effect only at the NEXT boundary, never mid-turn (cooperative, not preemptive)
  - tests/test_e2e_mock.py passes unchanged with no flight files present (strict no-op, byte-identical TaskResult); the control plane lives in the shared loop, identical for mock and vllm-openai

### t3 — colleague work --watch dispatch (colleague/cli/_commands/work.py): add --watch; when set, mark Task.watch, create the flight feed file, and emit the flight handle (task_id + feed + control paths) at LAUNCH before work runs, on a documented machine-parseable stream (+ --json); read COLLEAGUE_FLIGHT_DEPTH, refuse arming at >= cap, and export depth+1 into os.environ so nested run_command flights inherit it.

- depends on: t2
- covers: c13
- acceptance:
  - colleague work --watch prints a resolvable task_id + feed/control paths BEFORE completion, machine-parseable
  - without --watch, work output and side effects are byte-identical to today (no handle, no feed file)
  - arming is refused with a CliError when COLLEAGUE_FLIGHT_DEPTH >= cap; otherwise os.environ carries depth+1 to children

### t4 — colleague flight CLI noun (colleague/cli/_commands/flight.py + register in colleague/cli/__init__.py + explain entry): flight status|guide|stop|list|overview; status reads the latest feed snapshot, guide writes a guidance directive, stop writes a stop directive, list reports active flights from .colleague/flight/. Agent-first: each supports --json, errors via CliError to stderr, results to stdout.

- depends on: t1
- covers: h4
- acceptance:
  - flight overview + status/guide/stop/list all exist, each with --json, and the noun passes teken cli doctor . --strict
  - flight guide <id> writes a guidance directive the loop control-reader parses; flight stop <id> writes a stop directive
  - flight list reports active flights discovered under .colleague/flight/; flight overview names the dispatching-agent audience

### t5 — Reap flight files via colleague clean (colleague/cli/_commands/clean.py): colleague clean reaps ORPHANED flight files (no live run) scoped strictly to .colleague/flight/, never an unrelated path; --dry-run reports without deleting. Reuses the t1 reap/orphan helpers (no subprocess in clean.py).

- depends on: t1, t2
- covers: h5
- acceptance:
  - a test runs a mock flight and asserts its flight files exist under .colleague/flight/<id>.* during the run and are removed on finish
  - colleague clean reaps an orphaned flight file while leaving an unrelated file under .colleague/ untouched; --dry-run changes nothing

### t6 — Colleague-as-caller symmetry proof + depth guard at integration (tests/test_flight_symmetry.py, test-only): prove a NON-Claude caller pilots - a colleague mock work-loop dispatches a sub-flight (run_command launching colleague work --watch detached) and reads its feed + writes a guidance directive via the colleague flight CLI; assert the caller does NOT block (detached + poll-across-turns); assert the detached run_command launch is gated by the approval gate; assert a sub-sub-flight is refused by the depth cap (fork-bomb guard).

- depends on: t1, t2, t3, t4
- covers: c18, c19, h12, h13
- acceptance:
  - a colleague mock work-loop dispatches a sub-flight and reads its feed + writes guidance via colleague flight, with no Claude-specific assumption in the pilot path
  - the colleague caller does not block on the sub-flight (detached-launch + poll-across-turns pattern exercised); the detached run_command launch is shown gated by the approval gate
  - a nested sub-sub-flight is refused before any work by the depth cap, mirroring MAX_SUBAGENT_DEPTH check-before-work

### t7 — ask-colleague skill: piloting verbs (.claude/skills/ask-colleague/scripts/ask-colleague.sh + SKILL.md): add --watch passthrough to explore/review/write (arms the flight, surfaces the handle to the caller); add monitor <id> / guide <id> "msg" / stop <id> verbs wrapping colleague flight status|guide|stop with resolved identity; update usage, exit-code policy, and the SKILL.md trigger description.

- depends on: t3, t4
- covers: c2
- acceptance:
  - ask-colleague --watch on explore/review/write surfaces a resolvable flight handle to the caller
  - ask-colleague monitor/guide/stop wrap colleague flight, forwarding args + the resolved identity; the CLI resolver still works inside the checkout
  - SKILL.md documents the piloting verbs and the dispatching-agent audience

### t8 — Docs: piloting feature (docs/features/ask-colleague.md piloting section + new docs/features/flight.md): document the dispatching-agent audience and the monitor/guide/stop surface; state the before-state (today no progress/redirect/stop verb exists); document the honest limits (cooperative-not-preemptive, one-turn latency, colleague-as-caller backgrounds via shell + polls across turns - not in-process parallelism); include a worked example where an early redirect at turn 3 saves budget vs a blind 40-step run.

- depends on: t3, t4, t7
- covers: c3, c5, h6, h7, h8
- acceptance:
  - docs/features/ask-colleague.md gains a piloting section naming the dispatching-agent audience; flight overview cross-referenced
  - docs prove the before-state (no progress/redirect/stop verb pre-feature) and document the cooperative + concurrency honest limits (c19)
  - a worked example shows an early correction saving budget vs a blind run; markdownlint-cli2 is clean

### t9 — End-to-end demo + recording (scripts/demo_flight.sh + tests/test_flight_demo.py): a reproducible demo against the mock engine - dispatch a flight, watch the live feed, observe it heading wrong, send one guidance message, observe the next-turn course change, cooperative stop, inspect the preserved partial - using only files under .colleague/ (no socket/daemon).

- depends on: t2, t3, t4, t5, t7
- covers: c1, c9, h10, h11
- acceptance:
  - the demo script runs against the mock engine and reproduces the full sequence (dispatch -> watch -> guide -> course change -> stop -> preserved partial)
  - the demo touches only files under .colleague/ and opens no socket / forks no daemon; it is captured as a reproducible script asserted by a test

### t10 — Version bump + CHANGELOG + zero-deps/boundary guard extension (pyproject.toml, colleague/__init__.py, CHANGELOG.md, tests/test_zero_deps.py, tests/test_boundary.py): minor version bump + Keep-a-Changelog entry; extend test_zero_deps to import colleague.flight and assert no third-party leak; extend test_boundary to assert flight.py opens no socket, forks no daemon, and adds no threading/subprocess at the loop level.

- depends on: t1, t2
- covers: c7, h16
- acceptance:
  - version bumped (minor) in pyproject.toml + colleague/__init__.py with a CHANGELOG entry, satisfying the version-check CI job
  - tests/test_zero_deps.py imports colleague.flight and still passes (zero third-party); tests/test_boundary.py asserts flight.py has no socket/daemon/threading and still passes

### t11 — Agent-facing discoverability: teach piloting in colleague learn + explain (colleague/cli/_commands/learn.py + the explain catalog prose for 'colleague' and 'ask-colleague' + the learn drift test). Update both the _TEXT and the _as_json_payload command-map/verbs so 'colleague learn' teaches the piloting flow: the --watch dispatch, the 'colleague flight' noun (status/guide/stop/list), and the ask-colleague monitor/guide/stop verbs; update 'explain colleague' (architecture) and 'explain ask-colleague' prose to describe piloting. Sequenced AFTER t4 so the shared explain catalog edits never collide.

- depends on: t3, t4, t7
- covers: c2, c13
- acceptance:
  - colleague learn (both text and --json) teaches the piloting flow (--watch dispatch, colleague flight noun, ask-colleague monitor/guide/stop) and its drift test is updated and still passes the agent-first rubric (>=200 chars; purpose, command map, exit codes, --json, explain)
  - explain colleague (architecture) and explain ask-colleague prose describe piloting; teken cli doctor . --strict stays green
  - the flight noun appears in the learn command map (both text and JSON payload)

## Risks

- [unknown_nonblocking] run() is at the SonarCloud S107 13-param ceiling; flight arming MUST ride the existing task param (Task.watch) read inside run(), never a new run() param. Mitigation baked into t2. (task t2)
- [unknown_nonblocking] Guidance-injection accounting: an injected user-role message adds a turn + tokens. v0 leaning: it COUNTS against max_steps + context budget (honest accounting). Confirm during t2 build. (task t2)
- [unknown_nonblocking] The flight handle stream at launch (stdout result vs stderr diagnostic): leaning stderr-diagnostic + flight list for discovery, to keep the stdout TaskResult clean. Final choice in t3. (task t3)
- [unknown_nonblocking] Exact live-feed record schema (reuse artifact step-trace/WorkStats verbatim vs a new lightweight JSONL shape optimized for tailing). Decided in t1. (task t1)
- [unknown_nonblocking] Detached-launch reliability for colleague-as-caller (nohup/& through run_command, gated by approvals): a real honest-limit, not in-process parallelism; the supported pattern is documented + tested, not made bulletproof. t6/t8. (task t6)
- [follow_up] Cooperative stop must report status honestly (compose with #188/#191/#192): a stopped flight must NOT report status 'ok' with no result. Align the preserve-partial status with that work, not duplicate it. (task t2)

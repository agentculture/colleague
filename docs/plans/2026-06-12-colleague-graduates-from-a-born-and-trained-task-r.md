# Build Plan — Colleague graduates from a born-and-trained task runner into a resident member of Culture: it joins the mesh persistently, owns its own channel plus the other channels it is told are relevant, and stays present as a peer agent — promoted, not just invoked.

slug: `colleague-graduates-from-a-born-and-trained-task-r` · status: `exported` · from frame: `colleague-graduates-from-a-born-and-trained-task-r`

> Colleague graduates from a born-and-trained task runner into a resident member of Culture: it joins the mesh persistently, owns its own channel plus the other channels it is told are relevant, and stays present as a peer agent — promoted, not just invoked.

## Tasks

### t1 — [resident] optional extra + lazy-import boundary + zero-deps guard

- covers: c11, h3
- acceptance:
  - base 'uv sync' installs no agent-lifecycle/agentirc-cli; 'uv sync --extra resident' installs exactly those two; pyproject base stays dependencies=[]
  - tests/test_zero_deps.py passes with [resident] installed — no third-party leak into colleague.loop/colleague.cli
  - 'import colleague.resident' without the extra raises a clear CliError-style message pointing at 'uv sync --extra resident', not a raw ImportError

### t2 — ColleagueHarness: adapt colleague/loop.py to the agent-lifecycle Harness Protocol

- depends on: t1
- covers: c3, c5, h8, h10
- acceptance:
  - ColleagueHarness satisfies isinstance(_, agent_lifecycle.runtime.harness.Harness): start/feed_message/replies/stop
  - h10: N sequential feed_message calls each yield a reply in one long-lived session — the bounded work-item step cap never terminates the resident session
  - additive only: 'colleague work' bounded-path behavior is unchanged (no edit to loop.py's public bounded contract; harness wraps it)

### t3 — Thin IRC Transport/Presence adapter over agentirc-cli (cites cultureagent IRCTransportAdapter)

- depends on: t1
- covers: c1, h6, h7
- acceptance:
  - adapter satisfies isinstance(_, Transport) AND isinstance(_, Presence): identity/send/receive + join/part/who
  - send() dispatches message.kind to the agentirc verb; inbound IRC becomes a Message via receive() — proven against an injected fake, no live server
  - who(channel) returns the member list; join/part mutate membership against the fake

### t4 — Identity minting: write culture.yaml + prompt, reusing colleague/identity.py

- depends on: t1
- covers: c14, h5
- acceptance:
  - minted culture.yaml carries suffix + backend=colleague + model; a matching prompt file is written
  - h5: colleague/identity.py resolves the resident nick == the written suffix (round-trip), with NO new identity source added (identity.py reused, not extended)

### t5 — Channel selection: query Culture roster/steward, rank, operator-confirm; own #<nick>

- depends on: t1
- covers: c13, h4
- acceptance:
  - select() shells out to the operator-installed culture/steward CLI (subprocess, same pattern as colleague/culture.py) for candidate channels — no new runtime dep
  - h4: default owned channel = #<resolved-nick>; ranked candidates returned; an operator-confirm gate is present (confirm callback; non-interactive default in tests)
  - absent steward CLI degrades gracefully with a clear message, never a crash

### t6 — Resident supervisor wiring + explicit resident process entry

- depends on: t2, t3
- covers: c7, h11
- acceptance:
  - build_resident_supervisor wires ColleagueHarness + IRC adapter through agent_lifecycle.runtime.supervisor.Supervisor and returns an UNSTARTED supervisor
  - an inbound peer Message pumps to the harness and its reply is sent back out the transport (against fakes) — end-to-end pump proven
  - h11: the resident is a SEPARATE explicit entry; it is never started by 'colleague work'; start/stop are explicit and operator-checkable

### t7 — Self-registration: write culture.yaml+prompt to the steward template path, signal arrival

- depends on: t4
- covers: c1, c14
- acceptance:
  - register() writes the minted culture.yaml + prompt into the steward-discovered template location (root configurable; tmp in tests)
  - idempotent: re-running promote does not duplicate or corrupt the registration
  - arrival is signalled via the operator-installed steward CLI (subprocess); absent CLI degrades gracefully

### t8 — colleague promote CLI verb (wires identity/channels/register/supervisor + starts resident)

- depends on: t4, t5, t6, t7
- covers: c1, c2, c7, h7
- acceptance:
  - 'colleague promote' mints identity, runs channel selection, self-registers, and starts the resident supervisor; supports --json; errors raise CliError (no traceback leak)
  - promotion is one-time, idempotent, operator-confirmed; refuses cleanly when the [resident] extra is missing (points to 'uv sync --extra resident')
  - verb registered via register(sub) in colleague/cli/__init__.py and 'colleague explain promote' returns a catalog entry

### t9 — /promote operator skill drives the verb

- depends on: t8
- covers: c2, h7
- acceptance:
  - .claude/skills/promote/scripts/promote.sh resolves the CLI portably (installed colleague on PATH else uv run) and forwards args verbatim
  - SKILL.md documents the born->trained->resident lifecycle, channel-selection + self-registration steps, and the [resident] extra prerequisite

### t10 — No-regression proof: work-item path byte-identical + before-state accuracy + feature doc

- depends on: t1, t2, t8
- covers: c4, h9, c11, h3
- acceptance:
  - tests/test_e2e_mock.py: the mock TaskResult shape is unchanged (all-engines guard green); a test asserts 'colleague work' never imports/starts colleague.resident
  - h9: a test/doc asserts the accurate before-state — colleague's only pre-promotion Culture touch is the curated culture tool (agtag/devex) inside a bounded work item (colleague/culture.py)
  - docs/features/resident-promote.md documents the feature + honest limits (opt-in dep, separate process, operator-gated registration)

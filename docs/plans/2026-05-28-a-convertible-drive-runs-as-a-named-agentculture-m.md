# Build Plan — A convertible drive runs as a named AgentCulture mesh member: it acts under a specific mesh identity and natively reaches the sibling agent-ops CLIs — agtag (file/fetch/reply to mesh issues), agex/devex (inspect a repo's agent-first surface), culture (mesh presence) — so a worker both contributes to and learns from the agents around it, instead of being a sealed single-repo box.

slug: `a-convertible-drive-runs-as-a-named-agentculture-m` · status: `exported` · from frame: `a-convertible-drive-runs-as-a-named-agentculture-m`

> A convertible drive runs as a named AgentCulture mesh member: it acts under a specific mesh identity and natively reaches the sibling agent-ops CLIs — agtag (file/fetch/reply to mesh issues), agex/devex (inspect a repo's agent-first surface), culture (mesh presence) — so a worker both contributes to and learns from the agents around it, instead of being a sealed single-repo box.

## Tasks

### t1 — Process-level identity resolution module (convertible/identity.py)

- covers: c4
- acceptance:
  - resolve_identity() returns the culture.yaml nick when present, falls back to a .convertible identity field, and returns None when neither is set
  - the resolved identity is exposed to the drive path for downward propagation to subcommands — no per-call flag

### t2 — Neighbour clone manager (convertible/neighbours.py): allow-list, shallow clone, refresh, read-only

- covers: c17, c18, h12, h13
- acceptance:
  - with no .convertible neighbour allow-list configured, the manager clones nothing (neighbour set defaults to empty)
  - an allow-listed repo is shallow-cloned into a gitignored path UNDER the repo root and resolves there for reading
  - refresh re-runs git pull/fetch on demand; no clone is ever committed or pushed by a drive

### t3 — Curated culture loop tools (convertible/culture.py): agtag + agex as identity-injected tools, registered into the loop

- depends on: t1
- covers: c10, c4, h3, h8
- acceptance:
  - the loop exposes curated culture tools (agtag, agex) as declared tool schemas beyond the five base tools, and tests/test_e2e_mock.py is updated so every engine exposes them identically (all-engines rule)
  - a culture tool invocation shells out to the installed CLI via subprocess with the resolved identity injected — no socket, no daemon, no import; an absent CLI yields a clean tool error, not a crash

### t4 — Clone lifecycle wiring: cleanup at finish (loop.py) + never-execute confinement (tools.py)

- depends on: t3, t2
- covers: c17, h12
- acceptance:
  - neighbour clones are removed on the finish lifecycle event (fires on every loop exit), leaving no residue between drives
  - run_command never executes anything inside a clone path (clones are inert) while read_file still permits reading a clone

### t5 — Feature docs + before/after + operator onboarding (docs/, README, CLAUDE.md)

- depends on: t3, t2
- covers: c2, c3, h6, h7
- acceptance:
  - docs state the before-state (sealed box: only run_command + communicate/cicd skills, no identity, no native surface) and after-state, and the before-state is verifiable against HEAD
  - docs show an operator already running convertible enables this by installing only the culture CLIs they want — no bespoke wiring

### t6 — Boundary guards stay green: zero-deps + no-socket/no-daemon checks (tests/)

- depends on: t3, t2, t4
- covers: c6, h10
- acceptance:
  - tests/test_zero_deps.py stays green with the feature present: importing loop/culture/neighbours leaks no third-party module
  - a no-socket/no-daemon check asserts no new code path opens a socket or forks a daemon, and convertible reads no mcp.json

### t7 — End-to-end proof (tests/test_e2e_mesh.py): drive-as-X attributed + reads a neighbour clone

- depends on: t1, t3, t2, t4
- covers: c1, c5, c7, h1, h9, h11
- acceptance:
  - an e2e test drives the mock engine as identity X and asserts the produced mesh artifact is attributed to X, with all guards green
  - the same e2e reads a neighbour clone mid-drive and demonstrates a cross-repo task a sealed drive could not complete

## Risks

- [unknown_nonblocking] exact identity-propagation mechanism to subcommands: env var vs relying on the repo's cwd culture.yaml (agtag already auto-signs from it) vs an explicit flag (task t1)
- [unknown_nonblocking] zehut sub-identity resolution details — zehut CLI surface not yet studied (task t1)
- [follow_up] which culture tools beyond agtag/agex to curate (builder judgment; deferred) (task t3)

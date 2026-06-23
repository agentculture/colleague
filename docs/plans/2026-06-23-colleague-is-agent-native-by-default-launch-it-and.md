# Build Plan — Colleague is agent-native by default: launch it and you are talking to the colleague agent, which drives colleague under the hood, shows every action it takes in a readable feed, and checks a tool's AgentFront surface before reaching for it

slug: `colleague-is-agent-native-by-default-launch-it-and` · status: `exported` · from frame: `colleague-is-agent-native-by-default-launch-it-and`

> Colleague is agent-native by default: launch it and you are talking to the colleague agent, which drives colleague under the hood, shows every action it takes in a readable feed, and checks a tool's AgentFront surface before reaching for it

## Tasks

### t1 — [#234] Default session runs on colleague's OWN served backend and orchestrates colleague's own verbs (work/review/plan...) under the hood; prior backend stays selectable via flag/env.

- covers: c15, h5
- acceptance:
  - A fresh `colleague` session at a TTY runs on colleague's own served backend by default (not an external/configured backend).
  - A free-text goal reaches the underlying verb (e.g. work/review) without the user typing the subcommand.
  - The prior/other backend remains selectable via flag or env, with the override path documented.
  - A headless tui scenario asserts both the default backend and the fired verb.

### t2 — [#233] Make the action feed legible: group repeated mesh events, stop truncating commands, each line reads 'what ran + on what'.

- depends on: t1
- covers: c10, h2
- acceptance:
  - Repeated mesh events are grouped, not spammed -- no Nx duplicated [culture] lines.
  - Tool commands are not silently truncated past the point of understanding.
  - Each feed line reads as 'what ran + on what'.
  - Replaying the #233 paste session reproduces a legible feed (regression-checked).

### t3 — [#235] Add a prompt-level AgentFront-surface reflex: colleague checks an unfamiliar tool's learn/explain/--help/--json before first real use.

- depends on: t1
- covers: c16, h6
- acceptance:
  - colleague's runtime prompt/policy instructs it to check an unfamiliar tool's AgentFront surface (learn/explain/--help/--json) before first real use.
  - Given a tool colleague has not used before, a session trace shows the AgentFront-surface probe before the first substantive invocation.
  - The enforced harness-level probe is explicitly deferred (recorded as follow-up), not implemented here.

### t4 — Integration: the three facets demonstrably ship as ONE default experience in a single end-to-end session, with the success signals observable.

- depends on: t1, t2, t3
- covers: c1, h4, c8, h10, c12, h11
- acceptance:
  - A single end-to-end session demonstrates all three facets together: conversational default on colleague's own backend, legible feed, and a pre-use AgentFront probe.
  - The three success signals are observable from a recorded session with no insider knowledge.
  - The after-state is reachable on real infra (not a mock).

### t5 — Docs + validation: update CLAUDE.md/README/help and headless tui scenarios so the before->after, audience, boundary and non-goals hold.

- depends on: t4
- covers: c2, h7, c5, h8, c6, h9, c13, h12
- acceptance:
  - CLAUDE.md / README / `colleague --help` updated so the before->after, audience, boundary and non-goals in the spec hold.
  - Headless tui scenarios encode the new default-session behavior and pass in CI.
  - Non-goals respected: explicit verbs still work for scripts; backend choice preserved; no new GUI; AgentFront reflex is read-only.

## Risks

- [unknown_nonblocking] The canonical AgentFront-contract definition (7-bundle rubric / exact probe sequence) is not yet pinned; the prompt reflex names the surface generically and the precise probe is left to implementation. (task t3)
- [follow_up] Enforced harness-level AgentFront probe (intercept first-use, run/record the probe before the real call) is deferred to a follow-up; it needs the AgentFront definition pinned first. (task t3)
- [unknown_nonblocking] Recursion cost: colleague driving colleague on its own served backend adds model load; t1 must validate it is affordable and does not self-throttle. (task t1)

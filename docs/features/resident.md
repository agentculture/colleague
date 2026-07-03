# Resident appserver — colleague lives on the mesh

**Spec:** `docs/specs/2026-07-02-colleague-is-now-the-colleague-you-always-wanted-i.md`
(R5, c13/h11, c8/h15; trust decision c19; boundary c6/h6; decision c17) ·
**Plan:** task t13 · **Upstream contract:** agent-lifecycle's
`docs/colleague-embed.md` (the ratified library-embed consumption mode) +
`docs/specs/2026-07-02-agent-lifecycle-is-the-focused-lifecycle-core-that.md`.

Colleague can live on the culture mesh as a **resident that accepts work
requests** and runs them as ordinary work items — the "appserver" mode. The
lifecycle core is **imported, not built**: colleague embeds
`agent_lifecycle.runtime` (PyPI, ≥ 0.9) as a plain library and contributes
only its own engine.

## The pieces

- **`colleague/resident/appserver.py`** (opt-in `[resident]` extra) —
  `AppserverHarness` implements the upstream `Harness` Protocol
  (`start / feed_message / replies / stop`): each inbound `Message` is
  dispatched through `execute_work`, so a mesh-submitted request gets a real
  artifact, the pre-handoff gates, rig-budget governance, and (for authorized
  write requests) the git handoff — all for free. Replies carry the result
  summary + artifact pointer. `build_appserver_supervisor` wires the harness
  to ANY caller-supplied `Transport` through the upstream in-process
  `Supervisor`; a pump failure surfaces via `Supervisor.failure()`, never
  silently.
- **`colleague/resident/trust.py`** — the c19 trust policy, pure and
  dependency-free: **anyone may ask; only the operator has authority.** A
  non-operator plain request is downgraded to the read-only `explorer` role
  (structurally cannot write); a non-operator explicit write request is
  refused before any dispatch; the operator's identity authorizes everything.
  Consulting peers when in doubt is a documented follow-up hook, not built.

## Boundary honesty (c6/h6, decision c17)

Colleague still ships **zero socket/daemon code of its own**: supervision is
agent-lifecycle's, transports are the consumer's, and the base install
imports none of it — pinned by `test_boundary.py`'s package-wide
`agent_lifecycle`-confinement scan and `test_zero_deps.py`'s
subprocess-isolated proof that `colleague.resident.appserver` genuinely
requires the extra. `ProcessSupervisor`/`RestartingSupervisor` are explicitly
NOT used — the upstream consumption doc scopes the embed to the in-process
`Supervisor`, and colleague's batch runs are run-to-completion one-shots
(see `docs/features/background.md`).

## Live status (h15 — recorded honestly)

Proven end-to-end against agent-lifecycle **0.9.0**'s in-process supervisor +
reference `InMemoryTransport` (request in → mock work item → reply out;
failure path verified via a forced pump failure reaching `FAILED` +
`failure()`). **A real mesh transport round-trip stays PENDING** until
upstream ships a transport plug (IRC/agtag/Slack are later increments there);
per h15 the resident row is never claimed live until then.

# Colleague graduates from a born-and-trained task runner into a resident member of Culture: it joins the mesh persistently, owns its own channel plus the other channels it is told are relevant, and stays present as a peer agent — promoted, not just invoked.

> Colleague graduates from a born-and-trained task runner into a resident member of Culture: it joins the mesh persistently, owns its own channel plus the other channels it is told are relevant, and stays present as a peer agent — promoted, not just invoked.

## Audience

- Operators running colleague who want it living in the Culture mesh as a peer, and the Culture agents/operators who will share channels with it.

## Before → After

- Before: Today colleague only touches Culture ephemerally: a bounded work item shells out to allow-listed culture CLIs (agtag/devex) via the curated 'culture' tool, then exits. There is no persistent presence, no owned channel, no addressable mesh identity beyond the resolved nick.
- After: Colleague is a resident Culture agent: persistently connected, with a stable mesh identity, owning its own channel and joined to the channels deemed relevant, able to be addressed peer-to-peer and to respond — not merely shelled out to for a bounded work item.

## Why it matters

- A resident peer can be reached, can collaborate continuously, and can be promoted through a real lifecycle (born -> trained -> resident) instead of being a stateless tool — turning colleague from a callable into a colleague.

## Requirements

- Promotion asks an agent which channels are relevant: the resident owns its own channel by default and joins the agent-selected relevant set. The channel set is chosen interactively (agent-driven), never hardcoded — a human/agent gate in the promote flow.
  - honesty: the channel-selection step names a concrete mechanism (who is asked, how the answer is captured) and a well-defined default owned channel.
- Promotion mints a stable mesh identity: a culture.yaml (suffix + backend=colleague + model) and the matching prompt file, reusing colleague's existing identity resolution (colleague/identity.py) so the resident's nick is the one colleague already resolves.
  - honesty: the minted culture.yaml round-trips through colleague/identity.py: the resident's resolved nick equals the suffix written, with no new identity source added.

## Honesty conditions

- After promotion the agent is reachable in Culture under its identity, holds its owned + chosen channels across a restart, and answers a peer message end-to-end — observable, not just configured.
- Both audiences are real and distinct: a colleague operator can run the promote flow against an existing colleague checkout, and at least one named Culture peer/channel exists to share — promotion needs no third-party IRCd reconfiguration.
- Residence is durable, not a one-shot connect: after a process restart the resident reconnects and rejoins its owned + chosen channels on its own — 'resident' means presence that survives a restart.
- The before-state is accurate: colleague's only current Culture touch is the curated 'culture' tool shelling agtag/devex inside a bounded work item (colleague/culture.py), with no persistent connection or owned channel today.
- Continuous reachability is actually achievable on the reference rig: the served brain holds a long-lived streaming session without the bounded work-item step cap forcing termination — otherwise 'continuous collaboration' is aspirational.
- The success signal is operator-checkable without privileged access: post-promotion the agent shows in 'who', holds its channels across a restart, and answers a peer PRIVMSG — and no colleague-side daemon runs on the 'colleague work' path.
- colleague's bounded tool-loop adapts to the Harness streaming contract (start/feed_message/stream/stop) as an ADDITIVE adapter, without changing bounded work-item behavior — not a loop rewrite.
- the agent-lifecycle/cultureagent deps stay confined to the [resident] optional extra and import lazily, so tests/test_zero_deps.py still passes with the extra installed (no third-party leak into colleague.loop/cli).
- the resident supervisor is opt-in and never starts on the normal 'colleague work' path; a bare work item stays byte-identical (the e2e mock shape test still passes).

## Success signals

- After promotion, the agent appears in Culture under its identity, holds its owned channel and the chosen relevant channels across a restart, and answers a peer message in one of them — with no colleague-side daemon process.

## Scope / boundaries

- Colleague's bounded work-item path stays bounded and byte-identical. The resident is a SEPARATE, explicitly-opted-in long-lived supervisor process (a new resident/promote surface). The 'no daemon' rule is narrowed to 'no daemon on the work-item path'; the resident supervisor is the sanctioned exception this re-spec adds.

## Non-goals

- Not a multi-backend router, not a mesh operator/IRCd, not auto-registration of arbitrary agents. One agent (this colleague) is promoted to resident; the IRCd + operator CLI stay in culture; arrival/registration is operator-gated.

## Decisions

- Home = inside the colleague repo, landed through the re-spec ritual (spec+plan under docs/specs//docs/plans/). This deliberately expands colleague's v1 scope and narrows the standing 'no daemon/server mode' convention — recorded as a graduation (like #156), never a silent breach.
- Runtime = colleague implements agent-lifecycle's Harness interface (its bounded tool-loop adapted into a long-lived streaming brain: start/feed_message/stream/stop); the persistent IRC presence + supervisor come from cultureagent. agent-lifecycle is the brain seam; cultureagent is the wire.
- Coupling = a real pip dependency on agent-lifecycle (+ cultureagent), confined to an optional [resident] extra and imported lazily, so the BASE colleague install stays dependencies=[] and the zero-deps guard still holds (same pattern as the [otel] telemetry extra). The dep is real but opt-in.
- Deliverable = a /promote Claude Code skill (operator flow) backed by a 'colleague promote' agent-first CLI verb plus a Harness adapter module (colleague/resident/). The skill drives the verb; the verb mints identity, runs channel selection, registers, and starts the resident.
- 'Promote' is a lifecycle transition (born -> trained -> resident), not a fresh build: the same colleague that has done bounded work items is elevated in place. Promotion is a one-time, operator-confirmed, idempotent onboarding.
- VERIFIED 2026-06-12 (B landed): agent-lifecycle ships the runtime seam as stdlib-only Protocols — Transport(identity/send/receive) + optional Presence(join/part/who), Harness(start/feed_message/replies/stop), and an in-process Supervisor pump-bridge (inbound transport.receive->harness.feed_message; outbound harness.replies->transport.send) with phased drain shutdown. cultureagent v0.8.2 CONSUMES it: claude (live hybrid cutover) + acp backends wire through that Supervisor via a concrete IRCTransportAdapter + Presence + Harness adapter under cultureagent/clients/claude/runtime/. The seam colleague needs is real and proven in production; v1's transport prerequisite is satisfied. NOTE: the Harness method is replies(), not stream() — supersedes the start/feed_message/stream/stop wording in c9/h1.
- Dependency shape (refines c10): the [resident] extra = agent-lifecycle + agentirc-cli, NOT cultureagent[backend-claude] (which would drag in claude-agent-sdk + anthropic). colleague supplies its OWN Harness wrapping colleague/loop.py, and its OWN thin IRC Transport/Presence adapter over agentirc-cli, citing cultureagent's IRCTransportAdapter (clients/claude/runtime/transport.py) as the reference pattern — cite-don't-import. cultureagent is the proof/reference; agent-lifecycle + agentirc-cli are the real opt-in deps.
- Channel selection = the 'colleague promote' verb QUERIES the Culture roster/steward for candidate channels (shelling out to the operator-installed culture/steward CLI, same subprocess pattern as the curated 'culture' tool — no new runtime dep), ranks them by relevance, and the operator confirms the set; the resident owns its own channel by default (#<resolved-nick>, default #colleague). This is the concrete mechanism behind c13/h4: who is asked = the Culture roster/steward; how captured = ranked candidates + operator confirm; default owned channel = #<nick>.
- Registration = 'colleague promote' SELF-REGISTERS: it writes the culture.yaml identity + prompt into the location steward discovers (the culture-agent-template path, steward-doctor-recognized) and signals arrival. Operator-initiated (the operator runs promote) and idempotent/one-time. This narrows the c16 framing: 'no auto-registration of ARBITRARY agents' still holds — this is self-registration of THIS one agent, reusing the existing template/steward path, not a new IRCd or registrar.
- Resident brain = the SAME vLLM Qwen work-item backend (resolved via EngineConfig), held in a long-lived streaming session for live mesh presence. One mind; diversity vs Claude peers is the point. h10 must hold: the long-lived session must not be terminated by the bounded work-item step cap (the resident path is separate from 'colleague work').
- IRC wire = colleague-owned thin IRC Transport/Presence adapter over agentirc-cli ([resident] extra = agent-lifecycle + agentirc-cli), citing cultureagent's IRCTransportAdapter (clients/claude/runtime/transport.py) as the reference pattern — cite-don't-import. Confirms c18. FOLLOW-UP (operator-tracked, non-blocking): open a cultureagent issue to decouple its IRC transport from claude-agent-sdk so a light cultureagent core could be cited/depended-on later without the heavy backend-claude extra.

## Hard questions

- contradiction with c11? (blocking)
- risk: agent-lifecycle today ships only reference doubles (EchoHarness + in-memory transport); cultureagent's IRC is not yet exposed behind agent-lifecycle's Transport interface, so 'Harness + cultureagent transport' may require that extraction to land first.

## Open / follow-up

- RESOLVED 2026-06-12 (B landed, verified): cultureagent v0.8.2's claude/acp backends expose a concrete IRC presence behind agent-lifecycle's Transport/Presence Protocols (IRCTransportAdapter), wired through agent-lifecycle's Supervisor — so the resident CAN join IRC now via the proven seam. Residual (NON-BLOCKING for colleague): (a) cultureagent's codex/copilot backends are not yet refit and the IRC adapter is claude-namespaced, so colleague writes its OWN thin adapter over agentirc-cli citing that pattern (see c18) rather than depending on cultureagent[backend-claude]; (b) agent-lifecycle's ProcessSupervisor health/restart probes (#15/#16) are on a branch, not yet on main — colleague's in-process Supervisor usage does not need them.
- cultureagent#40 (filed 2026-06-12): expose a light, backend-agnostic IRC-transport core so colleague could later cite/depend on cultureagent's IRCTransportAdapter without the heavy backend-claude (claude-agent-sdk) extra. Non-blocking — colleague ships its own thin adapter over agentirc-cli meanwhile.

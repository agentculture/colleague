# Colleague's middle-manager presence is now its default state on every front: in the session, the talk attach, a background run, and the mesh resident, you keep conversing with senses while cortex works - senses acknowledges your request, keeps you posted on cortex's progress, and relays your words to cortex, everywhere you meet colleague.

> Colleague's middle-manager presence is now its default state on every front: in the session, the talk attach, a background run, and the mesh resident, you keep conversing with senses while cortex works - senses acknowledges your request, keeps you posted on cortex's progress, and relays your words to cortex, everywhere you meet colleague.

## Audience

- The operator delegating work to colleague on any front: a human at the interactive session, an operator attaching to a background run via 'colleague talk', and the operator lane of the mesh resident (c19 trust model).

## Before → After

- Before: The middle-manager lane (ack, cadence-gated proactive updates, clarify-first, rolling history) shipped session-only in v1 (talking-to-one arc, PR #301): 'colleague talk' and the resident appserver carry only the reactive talk lane - no ack, no unprompted updates, no clarify; a background run's presence beats have nowhere to render; issue #300 tracks the parity + tts follow-ups.
- After: The operator talks with senses (gemma4) while cortex (Qwen) works, and can keep talking throughout the run; senses relays operator guidance to cortex and proactively updates the operator about cortex's work - this is the default experience, not an opt-in, and it holds on all fronts.

## Why it matters

- Delegation should never feel like silence, and the experience should not depend on which door you walked in through - one consistent 'talking to one colleague' feel on every front, instead of a premium session-only feature.

## Requirements

- The middle-manager presence (ack, proactive updates, guidance relay, conversational answer) is the DEFAULT state - the operator does not need to opt in or pick a special surface.
  - honesty: An install with no senses resolved stays byte-identical on every front (nothing to talk to = pre-arc behavior), and an explicit off switch (--cortex-only / env / config) remains on every front - 'default' never becomes 'forced'.
- The presence lane is available on ALL fronts: interactive session, colleague talk attach, background runs, and the mesh resident.
  - honesty: Each front's beats are proven per-front (live on the rig where it serves, deterministic + honest SKIP where it doesn't) - the session-only proof is never presented as covering talk/background/resident.
- Resident parity: the mesh resident's operator lane gains the middle-manager beats - senses acks an inbound operator request, pushes cadence-gated proactive updates as mesh messages while the work item runs, and may clarify-first; the c19 trust model holds (non-operators keep the read-only reactive lane, never guidance relay).
  - honesty: A non-operator can structurally never trigger guidance injection (single call site inside the operator branch, pinned by test), and resident update pushes are cap-bounded so senses can never flood a mesh channel.
- Talk-attach parity: 'colleague talk <task-id>' renders senses' ack/context on attach and streams cadence-gated proactive updates live in the REPL between operator turns, not just reactive answers.
  - honesty: Talk-REPL updates render at existing poll boundaries with no new thread; a boundary where no update fired renders nothing - never a fabricated status line.
- Background presence: a background run's presence beats (ack, updates) are written onto the existing file-based flight plane so an attached talk REPL renders them live and the artifact records them - no TTY, thread, or daemon required.
  - honesty: The flight plane stays the only transport (no socket/daemon/thread - boundary test); an unattached background run's added senses cost is cap-bounded and recorded on the artifact whether or not anyone ever reads it.
- Artifact reconstructability extends to every front: ack/updates/clarify/talk/injections land on TaskResult.senses with the same kind-ed chat shape regardless of front, so the same task run on any front yields directly comparable artifacts.
  - honesty: One shared SensesBlock shape serves all fronts (drift-tested); no front grows its own record schema.
- The senses loop is bounded and degrades on a ladder, never losing a request: its own step/turn caps and context budget; senses-loop unavailable -> the fixed-beat lane (intake/ack/updates/talk as shipped today) -> cortex-only. Each rung is recorded on the artifact, never silent.
  - honesty: The degradation ladder is test-pinned rung by rung: kill the senses loop mid-run and the fixed-beat lane takes over; kill senses entirely and cortex still completes the task - the operator's request text reaches cortex verbatim on every rung.
- One-shot foreground 'colleague work' also carries the presence beats by default when senses is armed (ack + updates rendered as labeled lines), so the default state truly holds on every front - while --json and other structured payloads stay machine-parseable (presence never corrupts a JSON contract).
  - honesty: A --json invocation's stdout parses as the same JSON schema as today (presence data lands in dedicated fields, labeled lines go to stderr or the flight plane); an agent caller like ask-colleague still gets a parseable result contract.
- Degrade guarantees, re-scoped for the default: an install with NO senses resolved stays byte-identical on every front; a degraded senses call is bounded and recorded, never failing or stalling the run; --cortex-only (flag/env/config) fully disarms the lane on every front. The armed off-TTY byte-identical pins are the one deliberate break (c19).
  - honesty: Pinned by tests per front: senses-unarmed byte-identical, degraded senses call bounded and recorded, --cortex-only a strict no-op of the whole lane - and the c19 pin-breaks are enumerated in the spec, not discovered in review.

## Honesty conditions

- The announcement is claimable on EVERY named front - a front where the beats don't actually fire (or fire only reactively) is named an honest limit, never implied shipped.
- The operator's words always reach cortex verbatim (relay refines, never rewrites) and every update is grounded strictly in the real feed - a fabricated-status update is a test failure; cortex always does the task.
- The audience is the OPERATOR on every front: non-operator mesh peers never gain guidance relay or operator-lane beats (c19 trust model) - the resident's non-operator lane stays read-only/reactive.
- The before-state is verifiable at the arc's base commit: talk.py and appserver.py carry no ack/update/clarify path, and colleague#300 stays open until this arc lands - the gap is real, not rhetorical.
- Consistency is measured, not asserted: the same beat sequence per front is what c15's livecheck classifiers grade - a front that feels different fails the check.
- livecheck classifiers grade from evidence (feed + artifact), never from the model's self-report; a front the rig cannot exercise records an honest SKIP, never a fabricated pass.
- Senses' executor structurally offers no repo tools (pinned by a boundary test, like the existing no-ToolExecutor/no-subprocess pin); the senses loop is bounded by its own caps; a senses-loop failure degrades to the fixed-beat lane then cortex-only - never a lost or unanswered request.
- Every byte-identical pin this arc breaks is updated DELIBERATELY in the same change (test updated with a stated reason, recorded as the arc's convention change) - never silently; --json/structured output stays parseable by existing consumers (presence rides labeled lines or dedicated fields, never interleaved into a JSON payload).
- Reply-to-origin never widens visibility beyond where the operator already chose to ask: updates land only in the origin channel/DM, cap-bounded, and carry no repo content beyond what the resident's existing trust model already allows in replies.
- The coordination tool list is ENUMERATED in the spec and pinned by a structural test (senses' executor offers exactly that list and no repo tool, even if the model hallucinates a call); widening it requires a new re-spec at the router-exclusion line.

## Success signals

- On each front, the full beat sequence (ack, at least one grounded proactive update, a guidance relay, a conversational answer) is observable live and machine-checkable from feed + artifact alone - livecheck gains per-front middle-manager classifiers, live-proven on the real rig.

## Scope / boundaries

- The senses loop's tool surface is CURATED and coordination-only - dispatch-to-cortex, guide-cortex, read-flight/status, reply-to-operator, clarify - never repo tools (no read_file/write_file/edit_file/run_command/culture/devague): cortex remains the ONLY mind that acts on the repo. Repo work is always dispatched to cortex; senses answers about the conversation and the run, never performs the task itself (#276 senses-direct stays parked). Fixed enumerated surface - still no automatic task-to-model routing policy, no N-agent generalization.

## Decisions

- tts narration of proactive updates (the #300 item 2 follow-up) ships in this arc degrade-clean over the existing [voice] extra - the rig's stt/tts 502 (lobes-cli#89/#92) means the live proof SKIPs honestly until the rig is fixed.
- Senses (gemma4) becomes the front agent with its OWN bounded agentic loop: the operator converses with senses continuously; senses runs the conversation as an agent - dispatching work to cortex, guiding it mid-run, and updating the operator - rather than being called only at fixed beats. This is the FOURTH sanctioned increment at the router-exclusion line, re-specced here.
- Presence may alter stdout for non-interactive callers too (piped, agent callers): the off-TTY byte-identical pins are deliberately, recordedly broken by this arc - one default experience everywhere outranks the old silence guarantee.
- Resident proactive updates reply-to-origin: they go back where the request arrived (channel or DM), cap-bounded - consistent with how the resident already replies.

## Open / follow-up

- Unifying the session lane and talk-verb turn-processing into one shared presence engine (they are parallel implementations of the same lane today) - the plan may fold this in as groundwork or keep it a follow-up.
- Senses-direct-for-cheap-tasks (#276) and the embedder/reranker retrieval lane of #277 stay parked - unchanged by this arc.

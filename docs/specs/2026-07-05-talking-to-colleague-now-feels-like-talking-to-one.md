# Talking to colleague now feels like talking to one person: senses. You speak with senses (Gemma) directly — it acknowledges your request in its own words, hands the work to cortex (Qwen), keeps you posted with proactive progress updates while cortex drives, relays your mid-run guidance, and delivers cortex's answer back conversationally. A middle manager with senses' emotional intelligence fronting cortex's logical intelligence — and the task itself is always done by cortex.

> Talking to colleague now feels like talking to one person: senses. You speak with senses (Gemma) directly — it acknowledges your request in its own words, hands the work to cortex (Qwen), keeps you posted with proactive progress updates while cortex drives, relays your mid-run guidance, and delivers cortex's answer back conversationally. A middle manager with senses' emotional intelligence fronting cortex's logical intelligence — and the task itself is always done by cortex.

## Audience

- colleague operators using 'colleague session' interactively on a TTY (v1 surface), with the mesh-resident and 'colleague talk' surfaces as parity follow-ups

## Before → After

- Before: senses already brackets a work line (intake perceives, speak-back shapes, mid-run talk answers) but only REACTIVELY: no acknowledgment when a request lands, no unprompted progress updates (the operator watches raw cockpit feed lines), each talk exchange is stateless, and intake cannot ask a clarifying question back — it feels like watching a machine, not talking to a colleague
- After: one continuous conversation with senses: it acknowledges the request in its own words, dispatches to cortex, narrates progress proactively at honest boundaries, relays mid-run guidance, and presents cortex's answer conversationally — while cortex remains the only mind that acts on the task

## Why it matters

- the operator gets senses' emotional intelligence and cortex's logical intelligence through ONE smooth interface — informed and in control without parsing raw feed lines, and never blocked waiting in silence
- operator's own words: quick and rich responsiveness in front, with a deep and intelligent worker behind — the front's latency and warmth is the product; the worker's depth is the substance

## Requirements

- acknowledgment turn: on split-mode intake, senses speaks FIRST — a short grounded acknowledgment (what it understood + that it is handing to cortex) rendered before cortex's first step; a degraded intake degrades to a plain dispatch notice, never fabricated understanding
  - honesty: the acknowledgment is derived only from the intake packet (interpretation/task_type/confidence); when intake degrades, the ack degrades to a fixed dispatch notice — a test pins that no ack ever claims an understanding the packet doesn't contain
- proactive interim updates: senses narrates progress unprompted at a bounded cadence (phase changes and/or every N steps), grounded strictly in the live feed tail — a fabricated-status update is a test failure; an update never advances step_count (the #206 invariant)
  - honesty: every proactive update quotes or paraphrases real feed lines from the run it narrates; a grounding test feeds a fabricated-status reply and asserts it is rejected/flagged, mirroring the run_senses_talk grounding contract
  - honesty: updates are bounded per run (a cadence cap, env-tunable) so a chatty senses can never dominate the feed or the senses budget; hitting the cap is recorded, never silent
- conversation continuity: operator-senses exchanges within one session (ack, updates, talk, final answer) thread as rolling chat history into subsequent senses calls, windowed to senses' OWN budget; the operator's original request stays verbatim, and the history folds into TaskResult.senses.chat
  - honesty: chat continuity is windowed to senses' own context budget with the verbatim-original invariant intact; a session with senses absent writes NO chat history and stays byte-identical
- clarify-first (operator decision): on low-confidence intake senses MAY ask clarifying questions before dispatching — MORE THAN ONE allowed, senses judges 'as needed'; an explicit operator go-word always dispatches immediately
  - honesty: clarification can never withhold work: an explicit 'go' (or equivalent) dispatches unconditionally; consecutive questions are bounded by a generous env-tunable ceiling (loop-proofing, not a UX cap); every clarify exchange is recorded on TaskResult.senses.chat and the final dispatched instruction still carries the operator's verbatim words — clarify refines the packet, never rewrites the request

## Honesty conditions

- the SAME work line run cortex-only and split yields the same TaskResult core (summary/status/steps); the middle-manager layer changes what the operator EXPERIENCES, never what cortex does or reports
- the v1 surface is the interactive session on a colour TTY; off-TTY / piped / --no-tui / --cortex-only stays byte-identical (pinned by test), and mesh-resident + 'colleague talk' parity is recorded as a NAMED follow-up in the spec, never implied as shipped
- the before-state is cited to today's code, not asserted: intake/speak-back/talk exist in colleague/senses.py, no ack turn exists, no unprompted-update path exists, and run_senses_talk threads no chat history — each verifiable at spec time
- every promised beat (ack, dispatch, proactive update, relay, conversational answer) is observable in ONE recorded proof run: the session transcript shows the lines and TaskResult.senses records each turn
- smoothness is demonstrated, not asserted: the acceptance proof includes a long-run transcript where phase/progress is legible from senses lines alone — and the raw cockpit feed stays available (senses augments, never hides)
- a structural proof pins that the task instruction always reaches cortex and that no senses output is ever used as TaskResult.summary source — the relay path is the ONLY way senses influences the run
- a boundary test pins the constraint: no new threading/clock imports outside the sanctioned list, updates fire only from existing sink boundaries, and a session with senses unresolved is byte-identical to today (test-pinned)
- the success signal is machine-checkable from the artifact alone: a proof run's TaskResult.senses contains the ack record, at least one proactive-update record, and the folded chat — no human judgment required to verify
- quick is measured: the front responds in low-single-digit seconds (senses p50 under cortex load ~2.3s already proven); rich is grounded: every front line derives from the real packet/feed, never canned filler; deep is structural: the task always reaches cortex un-shortcut

## Success signals

- on a long work line the operator sees: a senses acknowledgment before cortex's first step, at least one unprompted grounded progress update mid-run, and a conversational answer at finish — every senses turn recorded on TaskResult.senses so the whole exchange is reconstructable from the artifact

## Scope / boundaries

- senses NEVER answers the task itself and never decides cortex isn't needed — #276 (senses-direct) stays parked and no automatic task-to-model routing policy is introduced; senses converses about the run and relays, cortex acts. This deepens the EXISTING enumerated senses surface, it does not widen it
- no threads, no clock, no daemon: acknowledgment and proactive updates fire only at existing thread-free boundaries (intake time, progress-sink boundaries); absent senses config stays byte-identical cortex-only, and every senses turn stays tools-off degrade-never-raise

## Non-goals

- not a chat UI rewrite: the cockpit/feed stays; senses lines join the existing conversation surface. Not voice-first: tts narration of updates is a follow-up on the existing [voice] extra, not v1

## Assumptions

- senses latency under cortex load stays conversational — the live-presence arc proved 1.14s alone / 2.33s p50 under load, so an ack + a few updates add seconds, not minutes, to a run

## Decisions

- this is a deepening of the third sanctioned router-exclusion increment (senses live presence), not a fourth surface: same fixed responsibility boundary (cortex acts, senses perceives/presents/converses), same named roles, no new model consumers
- ack shape (operator decision): the acknowledgment rides the ONE existing intake completion — intake returns the ContextPacket AND a senses-authored ack line in the same call, rendered before cortex's first step; zero extra latency, zero extra calls
- update cadence (operator decision): phase changes + every N steps, env-tunable with a per-run cap; the concrete numbers stay parked (v1) pending live tuning

## Open questions

- should low-confidence intake let senses ask ONE clarifying question back before dispatching to cortex (a bounded ask-then-dispatch), or does v1 always dispatch immediately with omissions noted?

## Open / follow-up

- mesh-resident and 'colleague talk' surface parity for ack + proactive updates (session-first in v1)
- tts voice narration of proactive updates over the existing [voice] extra

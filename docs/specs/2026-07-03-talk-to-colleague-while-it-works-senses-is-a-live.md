# Talk to colleague while it works: senses is a live conversational presence — it answers in seconds, keeps you aware of what cortex is doing, relays your words into the running work at the next tool-call boundary, and can hear and speak (lobes stt/tts).

> Talk to colleague while it works: senses is a live conversational presence — it answers in seconds, keeps you aware of what cortex is doing, relays your words into the running work at the next tool-call boundary, and can hear and speak (lobes stt/tts).

## Audience

- Operators in an interactive colleague session (human), and agent callers piloting a background or ask-colleague work item via the flight plane — anyone with a running work item, in every mode

## Before → After

- Before: Senses is synchronous-only — one intake before the run, one speak-back after; mid-run the operator can only watch the flight feed or hand-type 'colleague flight guide'; there is no audio in or speech out
- After: While cortex drives a work item, the operator converses with senses concurrently: senses answers in seconds from live run context (flight feed + context packet), operator words become flight guidance injected at the next tool-call boundary, a spoken request arrives as an stt transcript, and replies can be spoken via tts — every injection visible

## Why it matters

- Delegation stops being silence: the operator stays aware and in control mid-run instead of waiting blind, guidance arrives through natural conversation instead of plumbing, and voice frees colleague from the keyboard

## Requirements

- A concurrent senses chat lane exists while a work item runs: in colleague session for the interactive operator, and as an attach surface over the flight plane for background and agent-caller runs
  - honesty: A second terminal (or the session lane) holds a real conversation with senses during a REAL cortex work item on the live rig — proven end-to-end, not only in mock tests
- Operator input relays into the running cortex loop through the EXISTING flight guidance plane, applied at the next tool-call boundary — reuse of append_guidance / Control reads, no new injection plumbing, never interrupts a tool call mid-flight
  - honesty: A loop-level test observes the injected guidance in cortex's very next turn prompt, and a mid-tool-call injection is deferred to the boundary — never spliced into an in-flight completion
- Senses answers from live run context — the flight feed tail, the context packet, and task state — so its answers reflect what cortex is actually doing right now, windowed to senses' own budget
  - honesty: A senses answer about run state cites facts actually present in the feed tail it was given — a fabricated-status answer is a test failure, and the feed window given to senses respects senses' own context budget
- Audio in: a spoken request is transcribed by the lobes stt role; the verbatim transcript is the raw intent (the v1 verbatim invariant extends to transcripts; the audio file is provenance)
  - honesty: The verbatim stt transcript survives untouched into ContextPacket.original and the artifact; a lossy or paraphrased transcript in the raw-intent position is a test failure
- Speech out: a senses reply can be rendered to audio by the lobes tts role, opt-in; tts failure or absence never blocks the text reply
  - honesty: With tts unreachable or undeclared, the text reply is byte-identical to a no-tts run and one visible notice fires — audio out is strictly additive
- Awareness invariant in ALL modes: every senses-to-cortex injection produces a visible feed line and an artifact record, every senses answer is labeled as senses, nothing is silent — for humans in session AND for agent callers reading feed/artifact (ask-colleague, mesh)
  - honesty: A deliberate injection test finds BOTH the feed line and the artifact record for every injected message, in session mode and in flight-attach mode; an unlabeled senses answer or an unrecorded injection is a test failure
- Degradation: senses, stt, or tts absent or unreachable degrades to today's behavior (watch-only flight, text-only I/O) with one visible notice — never blocks, never fails the run; cortex-only stays byte-identical
  - honesty: Killing senses/stt/tts mid-run leaves the work item completing exactly as a cortex-only run plus one notice; with no live lane armed the TaskResult is byte-identical to today's (pinned by the e2e shape test)
- The artifact records the live lane: injected guidance, senses answer latencies, and voice per-stage latencies extend TaskResult.senses (omit-when-None — a run without the lane is byte-identical)
  - honesty: The same task run with and without the live lane yields directly comparable artifacts — new keys are omit-when-None only, and recorded latencies are measured wall-clock, never estimated

## Honesty conditions

- The whole announcement is demonstrated in one live rig session: cortex working, operator chatting with senses concurrently, one relayed instruction landing at a turn boundary, and the voice lanes proven or honestly SKIPped per the degradation rule
- Both audiences are exercised in the proof: a human conversing in colleague session AND an agent caller attaching over the flight plane to the same running work item
- Every after-state element is individually observable in the h10 live demo: concurrent senses answer, turn-boundary injection, verbatim transcript in, audio file (and play when rigged) out
- The before-state is code-verified: today's run_senses_intake/run_senses_speakback are invoked only before/after the loop — no mid-run senses entry point exists on main
- Awareness is reconstructable from artifacts alone: a reviewer reading feed + artifact can tell exactly what the operator saw and injected mid-run, without the terminal scrollback
- A structural test pins the senses lane tools-off (no ToolExecutor import, no tool schema on the wire) and no code path returns a senses reply as the answer to the TASK without a cortex turn
- Boundary tests pin: zero new socket/daemon code, threads stay confined to the sanctioned list, and the ONLY injection channel is the existing flight control file read at turn boundaries
- test_zero_deps proves the base install carries no audio or device dependency; every capture/playback dep resolves only under the [voice] extra
- CLAUDE.md's scope section records this increment with the same fixed-enumeration language as deepthink and cortex/senses, and no automatic task-to-model routing code path exists
- The live proof lands in docs/live-testing.md with per-stage wall-clock numbers; an unprovable lane (e.g. TTS while the rig 502s) records SKIP or FAIL honestly, never a synthesized pass
- Measured on the rig before build: senses answer latency while cortex is mid-completion meets the responsiveness target; if serving serializes, the 'answers in seconds' claim is re-scoped honestly in this spec, not shipped broken

## Success signals

- Live-proven on the rig: during a real cortex work item, a typed operator message gets a senses answer within the responsiveness target AND the relayed guidance provably reaches cortex's next turn (visible in feed + artifact); a spoken request round-trips audio to transcript to cortex to spoken answer with per-stage latencies recorded

## Scope / boundaries

- Senses converses and relays but never acts: structurally tools-off, the task always goes to cortex, and senses never decides a task doesn't need cortex — #276 (senses-direct) stays parked with its own re-spec
- No colleague-owned daemon, socket, or new thread surface: the live presence is an operator-side foreground process riding the existing file-based flight plane; injection is cooperative at turn boundaries, never preemptive
- No audio-device code in the base install: mic capture and speaker playback stay operator-side (or behind an opt-in extra); colleague consumes stt/tts as lobes roles over HTTP only
- Third sanctioned increment at the router-exclusion line: fixed named-role consumption (stt in, tts out) added to the existing enumerated senses surface — no automatic task-to-model routing, no N-role generalization

## Non-goals

- Not senses-direct: senses never answers the TASK itself without cortex — #276 stays parked behind its own router-boundary re-spec
- No streaming voice, no barge-in, no wake word, no telephony; no embedder/reranker consumption (lane 2 of #277 stays parked)

## Assumptions

- The rig serves a senses completion while a cortex completion is in flight fast enough to feel conversational — cross-model concurrency is real, not head-of-line-blocked serialization (being measured live right now)

## Decisions

- Voice v1 is turn-based — record, transcribe, work, speak — not streaming; no barge-in or interruption semantics (per #277's own lean; streaming needs loop semantics that don't exist)
- The presence is operator-side foreground: a chat lane inside colleague session plus a 'colleague talk <task>' attach verb for background runs — both are flight-plane clients with senses as the mind, neither is a resident daemon
- Audio I/O lives behind an opt-in [voice] extra (mic capture + speaker playback deps, base install untouched); on mesh/culture surfaces (chat, irc-lens) colleague passes a LINK to the audio file so a mic-less peer consumes it as a file — operator decision q1
- Responsiveness target: senses answer during a running work item at p50 under 3s, p95 under 8s (probe measured 1.3-1.6s live 2026-07-03); h9 re-measures against this before build — operator decision q2
- TTS delivery is both: always write the .wav beside the run (durable, headless- and mesh-friendly via file link), and play aloud through the [voice] extra's player when configured; play failure never loses the audio — operator decision q3

## Open / follow-up

- File a lobes-cli issue: /capabilities advertises stt/tts at http://realtime:8080 (not client-resolvable) and the gateway's /v1/audio/speech proxy 502s while transcriptions works — sibling of lobes-cli#87

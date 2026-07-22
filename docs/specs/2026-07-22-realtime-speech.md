# realtime speech

> colleague speaks and listens in realtime: the operator talks to senses by voice while cortex works — a live session over the rig's OpenAI-compatible /v1/realtime lane (server VAD in, spoken senses replies out), with turn-based voice as the degrade floor; and the #304 presence-narration live proof records PASSED, closing the issue
> instruction: verify against the live-demo record in docs/live-testing.md and the updated senses-live-presence feature doc

## Audience

- the colleague operator at a colour TTY in 'colleague session', with a mic + speaker and the [voice] extra installed; the unchanged secondary audience is every other consumer — agent callers, off-TTY/piped/--json sessions, the resident — who must observe zero change
  - instruction: check the spec names the interactive session as the ONLY realtime surface and pins off-TTY/piped byte-identical

## Before → After

- Before: voice v1 is turn-based: '/say FILE' or a fixed N-second record() -> transcribe -> work -> speak; no live speech lane, no VAD, no barge-in — talking to colleague mid-run means typing (the recorded honest limit in docs/features/senses-live-presence.md)
  - instruction: cite the pre-change honest-limits line verbatim in the spec's before-state section
- After: while cortex drives a work item the operator simply talks: continuous mic capture streams to the gateway's /v1/realtime session, server VAD ends the turn, the final transcript lands exactly where typed input lands today (labeled senses answer, 'cortex:' relay as flight guidance), and senses' reply plays back as spoken audio with the text still rendered; typed input keeps working throughout
  - instruction: live demo on the reference rig, recorded in docs/live-testing.md: speak during a running work line, observe the labeled senses: text + spoken reply with no typed command

## Requirements

- close #304 first as its own deliverable: the blocker is gone — probed 2026-07-22, POST /v1/audio/speech returns 200 audio/wav (40KB, 24kHz PCM) and /v1/audio/transcriptions round-trips the transcript; run_presence_narration_check('.') returns status=passed live; remaining work is recording the flip in docs/live-testing.md (rows 22/23 SKIP + the narration row) and commenting/closing the issue
  - honesty: issue #304 is CLOSED with PR #355 merged (6ef5b8e) and docs/live-testing.md carries the dated 2026-07-22 PASS section — verifiable today
- realtime speech rides the EXISTING senses lane, transport-swapped: a final STT transcript lands exactly where typed session input lands today (run_senses_talk → answer displayed, relay → flight guidance injected at the next tool-call boundary), and senses' answer is spoken back over the realtime TTS lane; senses still never produces the task answer and cortex remains the only repo actor
  - honesty: voice transcripts flow through the SAME run_senses_talk + flight-guidance path as typed input (no second repo-touching lane); senses stays structurally tools-off; voice turns land on TaskResult.senses.chat/injections identically to typed turns
- the WebSocket client and continuous audio streams live behind an opt-in extra with LAZY in-function imports, mirroring colleague/voice_devices.py exactly: a base install imports every module fine, carries zero new deps, and only errors (cleanly naming the pip install hint) when a realtime function is actually called without the extra; base install stays byte-identical
  - honesty: a base install (no extras) imports every colleague module and passes the full suite with the WS/audio deps absent; tests/test_zero_deps.py still allow-lists exactly agentfront
- arming is discovery-first with the standard precedence chain: realtime arms only when voice is armed AND the advertised stt role carries the realtime_vad_session responsibility (or an explicit env/config.json realtime knob outranks discovery, matching flag > env > config.json > lobes discovery > absent); absent or unarmed = byte-identical to today's turn-based lanes
  - honesty: tests prove the precedence chain: an explicit env/config knob overrides discovery; with no realtime_vad_session advert and no knob, the session lane is never attempted (zero WS dials observed)
- turn-based voice stays the degrade floor: a realtime session that fails to open, drops mid-session, or hits a warming backend degrades to today's turn-based record→transcribe→speak lane, which itself degrades to text-only — degrade-never-raise at every layer, one stderr notice per degradation, and the text lane output stays byte-identical to an audio-less run
  - honesty: killing the WS mid-session (in test AND live) leaves the run alive: the lane degrades to turn-based/text with ONE stderr notice, no exception escapes, and task output is unaffected
- livecheck grows realtime proofs on the same evidence discipline (never a fabricated pass): a session-open/round-trip check that SKIPs honestly when the extra, mic, or rig lane is absent — and the existing gap gets fixed on the way: run_presence_narration_check has NO production caller today (the livecheck verb only runs the _KNOWN_PROOFS pytest files), so proof-runner checks get wired into the verb or explicitly recorded as manual
  - honesty: after the arc, 'colleague livecheck' executes or explicitly reports the ProofResult runner checks (including the new realtime proof) — a proof that cannot run SKIPs honestly, never fabricates a pass
- v1 is HALF-DUPLEX: mic capture is gated (not forwarded) while senses audio plays — otherwise server VAD hears senses' own speech through the operator's speakers and self-triggers a feedback loop (the bridge defaults AECMode NONE; server_vad segments whatever arrives); barge-in/AEC stay parked
  - honesty: while senses audio plays, ZERO operator audio frames are forwarded (test-pinned on the event stream), and a synthetic senses-speech playback never triggers a VAD turn
- the WS client is SYNCHRONOUS: tests/test_boundary.py flags 'import asyncio' anywhere outside colleague/resident/, so the realtime module must drive a sync WS API from the sanctioned pump thread — no asyncio in colleague's own source
  - honesty: tests/test_boundary.py passes unchanged with the realtime module in tree — no 'import asyncio' outside colleague/resident/, no 'import socket' anywhere
- teardown follows the owned-input-line template: capture/playback/pump threads are daemon threads with a stop event, poll-wake, and BOUNDED join — session exit, work-item end, and Ctrl-C never hang on a parked blocking read; stop-promptness is proven on REAL devices/pipes, not fakes (io.StringIO cannot reproduce a blocking read — the #315 lesson)
  - honesty: a session killed mid-capture exits within the bounded join on a REAL PTY/device stream — measured stop-promptness, never proven only on fakes
- audio devices are operator-selectable (config/env), never hardcoded defaults: the reference operator machine's capture devices are the Reachy Mini USB audio and an Arducam camera mic, and default playback is an HDMI sink — a wrong default device is a realistic first-run failure
  - honesty: input/output devices resolve from config/env with a documented way to list them; a wrong/missing device degrades to turn-based with ONE notice naming the device, never a traceback
- the session shows the voice-lane state honestly — live / muted / degraded-to-turn-based / off — following the cockpit label-state-consequence policy: an operator must be able to distinguish 'silent because muted' from 'silent because the lane died'
  - honesty: every voice-lane state transition renders exactly one honest indicator, and the muted state renders visibly differently from the degraded/dead state (test-pinned)

## Honesty conditions

- a live rig session demonstrates speech -> transcript -> senses answer -> spoken reply WHILE a cortex work item runs, recorded in docs/live-testing.md; with the extra absent or the lane down the same session degrades to today's behavior
- tests/test_boundary.py stays authoritative: no import of socket/socketserver/http.server/server-side asyncio anywhere in colleague/, including the new realtime module (lazy third-party import only)
- the SAME PR that lands the code updates CLAUDE.md's v1 scope list (seventh increment) and rewrites the senses-live-presence.md 'turn-based, no streaming' honest-limit line — no silent breach
- off-TTY / piped / --json sessions show ZERO realtime surface — proven byte-identical by test, the same gate the presence arc used
- capture is continuous with SERVER-side VAD deciding turn end — no fixed N-second window and no push-to-talk keypress required; typed input during an armed voice session still works
- the pre-change doc line reads exactly 'turn-based (record -> transcribe -> work -> speak) — no streaming, no barge-in, no wake word' (docs/features/senses-live-presence.md honest limits)
- the p50/p95 numbers are MEASURED on the reference rig under concurrent cortex load with the method recorded in docs/live-testing.md — never estimated, never extrapolated from a quiet GPU
- a cross-origin realtime dial target gets NO main-key Authorization header (unit-proven); a same-origin target authenticates and upgrades (the live 401-then-101 probe shape)

## Success signals

- on the reference rig a spoken turn round-trips live: VAD speech-end to first audible senses reply < 5s p50 / < 10s p95 while cortex loads the shared GPU; the realtime livecheck proof PASSes (SKIPs honestly off-rig or extra-absent, never fabricated); with realtime unarmed the session is byte-identical to v1.51.1 (0 output diffs in the off-TTY/piped tests)
  - instruction: measure p50/p95 over >= 10 spoken turns under concurrent cortex load, record method + numbers in docs/live-testing.md; run the byte-identical suite with the extra absent

## Scope / boundaries

- no socket code lands in colleague's own source: tests/test_boundary.py structurally forbids 'import socket' (+ socketserver/http.server/server-side asyncio) across colleague/ — the realtime transport must be a third-party WS client imported lazily inside the extra (the [mcp] precedent: the blocking loop is agentfront's, not colleague's), never a hand-rolled stdlib socket client, and never a listening socket or daemon anywhere
- this is a SEVENTH sanctioned increment at the router-exclusion line and gets its own recorded re-spec (this scope→think→spec-to-plan flow IS that re-spec): CLAUDE.md's v1 scope list and docs/features/senses-live-presence.md's honest-limits line ('voice v1 is turn-based — no streaming, no barge-in, no wake word') are updated as recorded convention changes, never silently breached
- the WS handshake carries VoiceConfig's api_key under the #348 same-origin rule only — probed live 2026-07-22: /v1/realtime answers 401 WWW-Authenticate: Bearer without the key and 101 Switching Protocols with it; the main Bearer is never forwarded to a cross-origin realtime target

## Non-goals

- no new lobes roles are consumed and nothing routes: realtime consumes the SAME two named voice roles (stt/tts — realtime_vad_session is a responsibility ON the advertised stt role, verified live), the embedder/reranker retrieval lane stays parked per the v1 scope line, the task always goes to cortex, and no automatic task→model decision appears anywhere
- the resident/mesh surface stays file-link audio: a mesh peer keeps consuming synthesized wav file-links (c19 trust model unchanged, non-operators still never append_guidance); no realtime audio channel over IRC. Realtime is an operator-side, interactive-session surface — off-TTY/piped/--json stays byte-identical

## Assumptions

- the rig-side realtime surface is COMPLETE and colleague builds only the client half: the lobes gateway tunnels /v1/realtime WebSocket upgrades (lobes/gateway/_realtime.py plan_realtime_upgrade + byte pump), the realtime bridge speaks the OpenAI Realtime protocol (PCM16@24kHz base64 events, server_vad turn detection, session config, floor management), and the live /capabilities advertises realtime_vad_session on the stt role (probed 2026-07-22, parakeet runtime, ready+loaded+feasible)

## Scope exploration

- `s1` — `issue #304 + colleague/livecheck.py:483-545 + docs/live-testing.md rows 22/23`: issue DoD = flip run_presence_narration_check SKIP→PASS + record in live-testing.md; probed live 2026-07-22: tts 200 wav, stt round-trip ok, the check itself returns passed — no colleague code change needed, evidence-recording only
  - seeds: `c2`
- `s2` — `lobes-cli checkout (lobes/realtime/{protocol,app}.py, lobes/gateway/_realtime.py, lobes/roles.py:740) + live GET :8001/capabilities`: gateway WS tunnel + OpenAI-Realtime bridge + advertised realtime_vad_session responsibility all exist and are live; _realtime.py's own comment names the Colleague role as the session lane's owner — the rig was built for this consumer
  - seeds: `c3`
- `s3` — `docs/features/senses-live-presence.md + colleague/senses.py run_senses_talk + colleague/cli/_commands/session.py stdin lane`: the text talk lane (tools-off senses, advisory relay, awareness invariant onto TaskResult.senses) is transport-agnostic — voice v1's recorded honest limit is exactly 'turn-based, no streaming, no barge-in, no wake word', so realtime replaces the transport, not the lane
  - seeds: `c4`
- `s4` — `colleague/voice_devices.py + pyproject.toml [voice] extra (lines 61-66)`: the lazy-extra pattern (sounddevice/soundfile behind [voice], import inside each function, degrade-never-raise playback) is the established template a realtime WS+stream client must follow; sounddevice already supports callback InputStream/OutputStream for continuous capture
  - seeds: `c5`
- `s5` — `tests/test_boundary.py (lines 5, 24, 250-359)`: the no-socket rule is enforced by regex over colleague/ source, with named per-module exemptions (flight.py, deepthink.py checked explicitly); a lazy third-party import does not trip it, a stdlib socket client would — the convention line to hold is 'colleague ships no socket code of its own'
  - seeds: `c6`
- `s6` — `colleague/config.py VoiceConfig (line 1689+) + colleague/lobes.py resolve_roles/resolve_role_base_url`: VoiceConfig already resolves stt/tts per-role dial targets through the precedence chain and lobes.py already parses role responsibilities from /capabilities — realtime arming is one more rung on the same resolution ladder, and the same-origin api_key hygiene (#348) applies to the WS dial target too
  - seeds: `c7`
- `s7` — `colleague/voice.py (transcribe/synthesize degrade contract + 503 warming retry)`: the degrade ladder and the warming-retry shape (503+Retry-After, bounded 10s, retry once) are established contracts realtime must slot under, not replace
  - seeds: `c8`
- `s8` — `CLAUDE.md v1 scope section (six sanctioned increments + still-explicitly-OUT list) + live /capabilities role list`: the router-exclusion line names exactly which roles colleague consumes (cortex/senses/stt/tts); the live gateway also advertises embedder+reranker, which must remain unconsumed — realtime is a transport change on already-consumed roles, not a new role
  - seeds: `c9`
- `s9` — `CLAUDE.md 'v1 scope (hold this line)' + docs/features/senses-live-presence.md honest limits`: every past increment (deepthink, cortex/senses, voice, presence-default, front door, muse discovery) landed as an explicit enumerated re-spec; realtime speech supersedes a recorded limit, so it must land the same way
  - seeds: `c10`
- `s10` — `docs/features/senses-live-presence.md 'two audiences, one flight plane' + colleague/resident/appserver.py wav file-link behavior`: the resident's voice surface is deliberately file-based for mic-less mesh peers; realtime targets the human at the TTY, and the existing off-TTY byte-identical gate is the template for gating it
  - seeds: `c11`
- `s11` — `colleague/cli/_commands/livecheck.py cmd_livecheck + colleague/livecheck.py select_proofs/_KNOWN_PROOFS`: select_proofs returns only gated pytest files; the ProofResult runner functions (presence narration, voice lane) are library-level with no CLI caller — #304's DoD was only provable by invoking the function directly, a wiring gap this arc should close or record
  - seeds: `c12`
- `s12` — `colleague thread/subprocess conventions (tests/test_boundary.py structural test 6) + lobes/realtime/{_floor,_segmenter}.py + protocol.py AECMode`: the open decisions above are real: threads need a recorded sanction, the extra split is a packaging choice, and the bridge offers more conversation machinery (floor, AEC, VAD) than a minimal v1 client must consume
- `s13` — `challenge pass / security lens: gateway /v1/realtime auth (live curl probes 2026-07-22)`: route 401s bare and 101-upgrades with the Bearer key — the WS dial is inside the #348 key-hygiene perimeter, seeded the same-origin boundary
  - seeds: `c23`
- `s14` — `challenge pass / failure-modes lens: lobes/realtime protocol.py (AECMode default NONE) + _segmenter.py server_vad`: no echo cancellation by default + VAD segments whatever arrives = senses' own speaker output can self-trigger turns; seeded the half-duplex requirement
  - seeds: `c21`
- `s15` — `challenge pass / hidden-deps lens: tests/test_boundary.py:281-295 asyncio regex`: plain 'import asyncio' is flagged outside colleague/resident/ — the WS client must be sync-API; seeded the sync-client requirement
  - seeds: `c22`
- `s16` — `challenge pass / lifecycle lens: colleague/cli/_commands/_input_line.py teardown template + fake-streams-hide-blocking-reader-bugs lesson (#315)`: daemon thread + stop event + poll-wake + bounded join is the proven in-repo teardown discipline; seeded the teardown requirement
  - seeds: `c24`
- `s17` — `challenge pass / hardware lens: arecord -l / aplay -l device inventory on the reference operator machine`: capture = Reachy Mini USB audio + Arducam camera mic, playback defaults to NVIDIA HDMI sinks — device selection is a real first-run hazard; seeded the device-selection requirement
  - seeds: `c25`
- `s18` — `challenge pass / observability lens: cockpit-ux label-state-consequence policy (docs/features/cockpit-ux.md)`: the session cockpit already claims only enforced states honestly; the voice lane needs the same so muted is distinguishable from dead; seeded the lane-state requirement
  - seeds: `c26`
- `s19` — `challenge pass / overlooked-actors lens: hot-mic privacy (ambient speech -> VAD segments -> transcripts in flight chat + TaskResult.senses.chat)`: confirmed c7's discovery-first arming makes the mic hot by default on an advertising rig; routed as question q4 — a user decision, not a guess
- `s20` — `challenge pass / concurrency + adjacent-systems lenses: session select-polling + owned-input-line reader + new pump/callback threads; shared-GPU sustained load`: examined: thread interplay is covered by the c18 sanction + c24 teardown discipline (typed/spoken floor contention is plan-level sequencing); GPU sustained load stays genuinely unknown — parked as v2, to be re-examined at plan time as a plan risk

## Decisions

- the WS client dependency extends the existing [voice] extra — no new extra (resolved q1, operator decision 2026-07-22)
- continuous-audio + WS-pump threads are sanctioned as a recorded convention entry: PortAudio callbacks + one WS receive pump, confined to ONE realtime client module, extra-gated, degrading to turn-based on any failure (resolved q2, the input-line-reader precedent)
- the first increment is the senses talk lane only — presence beats keep writing .wav files beside the run, no live-streamed narration (resolved q3)
- #304 closed separately via docs PR #355 (merged as 6ef5b8e) — the realtime arc starts from a clean, live-proven turn-based floor
- the mic is never hot by default: lobes discovery makes the realtime lane AVAILABLE, and capture starts only on an explicit per-session opt-in ('/voice' toggle or --voice flag) — refines confirmed c7: arming means availability, never an open mic (resolved q4, operator decision 2026-07-22)

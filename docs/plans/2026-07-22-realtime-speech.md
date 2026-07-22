# Build Plan — realtime speech

slug: `realtime-speech` · status: `exported` · from frame: `realtime-speech`

> colleague speaks and listens in realtime: the operator talks to senses by voice while cortex works — a live session over the rig's OpenAI-compatible /v1/realtime lane (server VAD in, spoken senses replies out), with turn-based voice as the degrade floor; and the #304 presence-narration live proof records PASSED, closing the issue

## Tasks

### t1 — Discovery + config rung: realtime availability and dial target

- instruction: Extend colleague/lobes.py role parsing to surface the stt role's responsibilities list (realtime_vad_session is the availability signal, probed live 2026-07-22) and colleague/config.py with a RealtimeConfig resolved on EngineConfig like VoiceConfig (reuse resolve_role_base_url + the #348 same-origin key helper; ws URL = http(s) origin with ws(s) scheme + /v1/realtime). New tests in tests/test_config_realtime.py. Do NOT touch session.py or voice.py.
- covers: c7, h6, c23, h16
- acceptance:
  - with lobes armed and the stt role advertising realtime_vad_session, RealtimeConfig resolves available=True with the ws URL derived from the role's dial origin; no advert and no knob resolves None and the session lane makes ZERO dial attempts (test-pinned)
  - precedence proven by tests: explicit env/config.json knob > lobes discovery > absent; flag wins over env
  - a cross-origin realtime target gets NO main-key Authorization (unit test); same-origin inherits per the #348 rule; explicit voice/realtime api_key always wins

### t2 — Boundary convention entry + [voice] packaging for the realtime deps

- instruction: Mirror how the input-line reader thread was sanctioned (q1, at-home arc): a named entry in test_boundary.py's thread-confinement test for colleague/realtime.py with the stated reason. Add websocket-client>=1.6 to the voice extra ONLY. Create colleague/realtime.py as an import-clean stub with lazy imports so the smoke test is real; t2 fills it.
- covers: c6, h5, c5, h4
- acceptance:
  - tests/test_boundary.py gains the recorded sanction: threading confined to colleague/realtime.py (stop-event + bounded-join discipline stated), with the socket/asyncio regexes still enforced on it — the full suite passes with the entry present
  - pyproject [voice] gains the sync WS client dep (websocket-client); base install stays zero-third-party-beyond-agentfront (tests/test_zero_deps.py green, allow-list unchanged)
  - a base install (no extras) imports every colleague module including colleague.realtime cleanly (import smoke test)

### t3 — Sync WS session client: dial, event codec, receive pump, degrade

- instruction: Model the pump on colleague/cli/_commands/_input_line.py (daemon thread, _stop_event, poll-wake via recv timeout, bounded join); websocket-client's settimeout gives the poll-wake. THE SESSION IS EARS-ONLY: never send response.create — the bridge's own LLM turn (its model + DEFAULT_SYSTEM_PROMPT, not senses' grounded context) must never arm; colleague consumes VAD boundaries + transcription events only. Reference implementations: ../lobes-cli/scripts/realtime-smoke.py (base64 append/delta event codec, offline-tested in tests/test_realtime_smoke_helpers.py) and lobes/realtime/_session.py (event schema). Test against a threaded stdlib fake WS server INSIDE tests only (tests may open sockets; colleague/ may not).
- depends on: t1, t2
- covers: c22, h15, c8
- acceptance:
  - colleague/realtime.py dials ws(s)://<origin>/v1/realtime with Bearer auth, sends session.update (server_vad, pcm16), encodes/decodes the base64 audio events, and runs ONE receive pump thread with stop event + poll-wake + bounded join
  - no 'import asyncio' / 'import socket' in colleague's own source — test_boundary.py green (sync websocket-client API only, lazily imported)
  - a mid-session WS kill (fake server closes) degrades to the turn-based path with ONE stderr notice and no escaping exception; pump join is bounded on a REAL os.pipe-backed stream, not a fake (the #315 lesson)

### t4 — Continuous audio streams + half-duplex gate + device selection

- instruction: Same file as t3 (colleague/realtime.py) — sequential by design. sounddevice InputStream/OutputStream callbacks (PortAudio threads live inside the sanctioned module); the half-duplex gate is a threading.Event the playback path holds — this is CLIENT-EDGE mute, exactly where lobes' d1 deviation says AEC-substitute belongs (their server forbids automatic mute; the client edge owns it), and t5 makes the muted state visible. Reference client for the event dance + mic/playback handling: ../lobes-cli/site/ (the Astro browser harness) and scripts/realtime-smoke.py. Devices on this machine: Reachy Mini USB audio (capture+speaker), Arducam mic, HDMI default sink — never assume device 0. float32->int16 + 24kHz (CLIENT_SAMPLE_RATE).
- depends on: t3
- covers: c21, h14, c25, h18
- acceptance:
  - while playback is active, ZERO captured frames are forwarded (test pins the event stream over a synthetic playback window) — half-duplex is structural, and a synthetic senses-speech playback never yields a VAD turn
  - input/output devices resolve from RealtimeConfig (env/config.json ids or names); a wrong/missing device degrades to turn-based with ONE notice naming the device — never a traceback
  - sounddevice/soundfile stay lazy in-function imports; PCM converts to 24kHz mono PCM16 for the wire (the bridge's CLIENT_SAMPLE_RATE)

### t5 — Session front: /voice opt-in, lane state, same-lane transcript wiring, teardown

- instruction: colleague/cli/_commands/session.py only (+ SlashSpec catalog for /voice). Wire transcripts into the existing stdin-lane handler so there is ONE senses-talk path — do not duplicate relay logic. The spoken reply uses the EXISTING colleague.voice.synthesize() batch lane + local playback (the realtime socket stays ears-only; senses is the mind, per the t3 instruction). Lane state rides the existing presence/cockpit line surfaces. Teardown hooks where the session already reaps the input line + flight plane. Gate everything on: colour TTY + senses armed + realtime available + operator opt-in (c27).
- depends on: t3, t4
- covers: c4, h3, c14, h11, c26, h19, c24, h17
- acceptance:
  - the mic is NEVER hot by default: realtime available shows an offer line only; capture starts on '/voice' toggle or --voice flag (c27) and '/voice' again mutes — test-pinned on the session loop
  - a final VAD transcript enters EXACTLY the typed-input path (same run_senses_talk + flight-guidance relay call sites; voice turns land on TaskResult.senses.chat/injections identically) and senses' reply plays as audio with the text still rendered
  - the voice lane renders honest state — live / muted / degraded / off — with muted visibly different from degraded (test-pinned), following the cockpit label-state-consequence policy
  - session exit / work-item end / Ctrl-C mid-capture tears down within the bounded join on a REAL PTY-driven test — measured stop-promptness, no hang, no orphan thread
  - capture uses server-side VAD turn ends — no fixed N-second window, no push-to-talk key held; typed input still works while the lane is live

### t6 — Negative-space proofs: byte-identical unarmed / off-TTY / extra-absent

- instruction: New test files only (tests/test_session_realtime_byteident.py etc.) — no production edits; if a diff appears, the fix belongs in t5. Reuse the presence arc's byte-identical fixtures where they exist. Remember conftest scrubs COLLEAGUE_* env — arm explicitly per-test via monkeypatch.
- depends on: t5
- covers: c13, h10
- acceptance:
  - an off-TTY / piped / --json session shows ZERO realtime surface — output byte-identical to the pre-arc fixture (diff-pinned)
  - an armed-but-not-opted-in session makes zero WS dials and zero device opens (spy-pinned)
  - with the [voice] extra absent the full suite passes and the session degrades with the clean install hint

### t7 — Livecheck: realtime proof + wire the ProofResult runners into the verb

- instruction: colleague/livecheck.py + colleague/cli/_commands/livecheck.py only. Follow the classify_/run_ pair pattern (run_presence_narration_check); grade from evidence, SKIP-honestly discipline. Keep exit-1-on-failed semantics; runner SKIPs must not flip exit codes.
- depends on: t3
- covers: c12, h9
- acceptance:
  - run_realtime_check exists: opens an ears-only session end-to-end when armed and PASSes on a real transcript round-trip; SKIPs honestly (named reason) when the extra, config, or rig lane is absent — never a fabricated pass
  - 'colleague livecheck' now executes the ProofResult runner checks (presence narration, voice lanes, realtime) alongside the _KNOWN_PROOFS pytest files and reports them in table + JSON — closing the no-production-caller gap found in /scope

### t8 — Docs + the recorded seventh increment: scope line, feature doc, honest limits

- instruction: Docs only. Quote the before-state line verbatim when superseding it (trim discipline). CHANGELOG + version bump ride the arc's PR workflow, not this task. Keep the CLAUDE.md increment entry in the established compressed style with a Doc: pointer.
- depends on: t5
- covers: c10, h8, c15, h12, c2, h2
- acceptance:
  - CLAUDE.md's v1 scope list gains the seventh sanctioned increment (realtime senses talk lane, ears-only session, half-duplex, opt-in mic) in the SAME PR as the code — an enumerated surface, not a router
  - docs/features/senses-live-presence.md's honest-limit line ('turn-based ... no streaming, no barge-in, no wake word') is rewritten to the new truth quoting the superseded line; a new docs/features/realtime-speech.md links spec + plan and records the client-edge-mute rationale (lobes d1)
  - the #304 closure evidence is cited (issue CLOSED via PR #355 merged 6ef5b8e; docs/live-testing.md dated 2026-07-22 section) — verifying c2/h2 hold at delivery

### t9 — Live proof on the rig: real-mic session, latency numbers, degrade drills

- instruction: Run against the gateway at :8001 (Bearer from COLLEAGUE_API_KEY). Use the Reachy Mini USB audio capture device explicitly. Record everything in a dated docs/live-testing.md section (the #304-section format: probes, numbers, honest limits, reproduce steps). Note in the record that this is also the first rig-side real-mic evidence (lobes-cli evidence file 2026-07-22 lists a real microphone as NOT VALIDATED).
- depends on: t5, t7
- covers: c1, h1, c16, h13, h7
- acceptance:
  - a live session on the reference rig demonstrates speech -> transcript -> senses answer -> spoken reply WHILE a cortex work item runs, recorded in docs/live-testing.md — using the REAL Reachy Mini mic (the first real-microphone validation of the whole realtime stack; every rig-side run so far used synthesized audio)
  - VAD speech-end to first audible senses reply measured over >= 10 spoken turns under concurrent cortex load: p50 < 5s, p95 < 10s, method + numbers recorded — measured, never estimated
  - degrade drills pass live: killing the WS mid-session degrades to turn-based with ONE notice (h7); the VAD-unavailable path and an extra-absent box degrade cleanly; the realtime livecheck grades PASS (or records why not, honestly)

## Risks

- [unknown_nonblocking] shared-GPU sustained load: continuous VAD + per-turn STT + per-reply TTS + cortex + senses generation has never been measured as one loop — row 19 measured a single senses completion; the < 5s p50 may need cadence tuning or fail on this rig (frame park v2) (task t9)
- [unknown_nonblocking] rig-side realtime unknowns carried from lobes-cli's 2026-07-22 evidence: real microphone unvalidated, VAD-unavailable path unvalidated, concurrent sessions unvalidated, barge-in measured broken (pacing fix 0.54.1 unverified) — t9 is downstream of all four (task t9)

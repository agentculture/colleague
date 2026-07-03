# Build Plan — Talk to colleague while it works: senses is a live conversational presence — it answers in seconds, keeps you aware of what cortex is doing, relays your words into the running work at the next tool-call boundary, and can hear and speak (lobes stt/tts).

slug: `talk-to-colleague-while-it-works-senses-is-a-live` · status: `exported` · from frame: `talk-to-colleague-while-it-works-senses-is-a-live`

> Talk to colleague while it works: senses is a live conversational presence — it answers in seconds, keeps you aware of what cortex is doing, relays your words into the running work at the next tool-call boundary, and can hear and speak (lobes stt/tts).

## Tasks

### t1 — Voice role resolution: extend colleague/lobes.py resolve_roles to stt/tts + a VoiceConfig in colleague/config.py (SensesConfig-sibling: model/base_url per role) through the same precedence chain (flag > env > config.json > lobes discovery > absent); gateway-origin routing workaround for the non-resolvable endpoint field; absent config = strict no-op

- covers: c9
- acceptance:
  - resolve_roles returns stt/tts entries from a /capabilities fixture and VoiceConfig resolution follows the chain, degrading to None on any failure without raising
  - with no voice config armed, EngineConfig resolution is byte-identical (pinned by existing resolve tests)

### t2 — Voice wire clients in NEW colleague/voice.py: transcribe(path) POSTs multipart to the role-resolved stt endpoint returning the VERBATIM transcript; synthesize(text) POSTs to tts, writes the .wav beside the run, returns its path (file always; play is the [voice] extra's job); pure urllib, turn-based, degrade-never-raise

- covers: c14, c15, h4, h5
- acceptance:
  - transcribe returns the exact server transcript (fixture asserts byte equality) and returns None with one stderr notice on 4xx/5xx/timeout
  - synthesize writes the wav and returns its path; a 502/'no audio' response degrades to None + one notice and the text reply is byte-identical to a no-tts run
  - voice.py imports no subprocess (boundary allow-list untouched)

### t3 — [voice] extra: mic capture + speaker playback in NEW colleague/voice_devices.py behind lazy imports; pyproject [voice] extra; play failure never loses the written wav; clean CliError naming pip install colleague[voice] when deps absent

- depends on: t2
- covers: c8, h17
- acceptance:
  - test_zero_deps proves zero audio/device deps at base; voice_devices imports lazily and errors cleanly without the extra
  - play(path) failure leaves the wav on disk and the command exiting cleanly with a notice

### t4 — Senses talk lane in colleague/senses.py: run_senses_talk(message, feed_tail, packet, task_state) -> {answer, relay, relay_text} — tools-off via make_complete(senses_config, tools=[]), feed tail windowed to senses' OWN budget, degraded call returns an advisory record never raises; an explicit operator relay prefix (e.g. 'cortex:') forces relay=True regardless of model output

- covers: c13, h3
- acceptance:
  - the completion carries no tool schema and the feed window respects senses' context_budget (unit-pinned)
  - a grounding test fails an answer citing state absent from the provided feed tail; the explicit relay prefix always wins
  - senses unarmed -> run_senses_talk returns None cleanly (caller degrades to watch-only)

### t5 — Injection + chat recording: colleague/flight.py gains chat-record JSONL append/read helpers; colleague/loop.py records every APPLIED guidance injection as a feed line + TaskResult.senses record and folds talk-lane chat records at finish; colleague/contract.py extends TaskResult.senses omit-when-None

- covers: c12, c18, h2, h8
- acceptance:
  - guidance appended mid-tool-call is applied at the NEXT turn boundary and appears verbatim in the next turn's messages (loop test), with a feed line + artifact record
  - runs with and without the live lane yield identical TaskResult shapes except omit-when-None senses additions; latencies are wall-clock floats, never estimates
  - the existing #206 invariant holds: recording an injection never advances step_count or adds a phantom step

### t6 — NEW 'colleague talk <task-id>' attach verb (cli/_commands/talk.py host command): REPL over the flight plane — renders the feed tail, senses-answers each message labeled 'senses:', relays instructions via append_guidance echoing a visible '-> cortex:' line, --audio FILE routes through transcribe, replies synthesized per config

- depends on: t2, t4, t5
- covers: c2, c3, c11, c16
- acceptance:
  - against a flight-dir fixture: a typed message yields a labeled senses answer; a relayed instruction lands in the control file guidance list with the visible -> cortex echo
  - senses unarmed degrades to a watch + raw-guide REPL with one notice; the verb registers via register_into(app) with an explain entry

### t7 — Session concurrent lane: during a running work line, colleague session polls stdin non-blockingly at progress-sink boundaries (select with zero timeout in the existing raw reader — NO threads); typed input routes to run_senses_talk, answers render labeled in the cockpit, relays go through the same flight plane; /say FILE for audio-file input

- depends on: t4, t5
- covers: c11, c16
- acceptance:
  - input typed mid-run is answered by senses and an instruction reaches the loop as guidance at the next boundary (integration test on mock with a scripted sink)
  - off-TTY / --no-tui / piped behavior is byte-identical to today (no polling, plain input()); no new threads (boundary test)

### t8 — Mesh awareness + audio file-link surface: resident appserver replies carry the synthesized wav as a file link line when voice is armed; mid-run peer messages route through the talk lane under the c19 trust model — non-operator identities get answer-only, never relay

- depends on: t2, t4, t5
- covers: c16
- acceptance:
  - a resident reply with synthesized audio includes the artifact-relative wav path (mic-less peers consume the file)
  - a non-operator message can never append guidance (trust test); every relay from an operator peer is visibly labeled in the reply

### t9 — Structural proofs + degradation pins (tests only): senses talk lane tools-off (no ToolExecutor import, no tool schema on wire) and no code path returns a senses reply as the TASK answer; flight-file-only injection channel; threads/subprocess allow-lists unchanged; kill-senses/stt/tts-mid-run completes as cortex-only + one notice; no-lane TaskResult byte-identical (e2e shape); awareness reconstructable from feed + artifact alone

- depends on: t3, t6, t7
- covers: c6, c7, c17, h6, h7, h14, h15, h16
- acceptance:
  - boundary tests pin: zero new socket/daemon code, threads confined to the sanctioned list, voice/talk modules subprocess-free (voice_devices' player path explicitly sanctioned if needed)
  - unarming senses/stt/tts mid-run leaves status unchanged plus exactly one notice; cortex-only TaskResult pinned byte-identical
  - a reconstruction test derives the operator's mid-run view (answers seen + injections made) from feed + artifact alone — an unlabeled answer or unrecorded injection fails

### t10 — Livecheck live proof: during a REAL cortex work item — concurrent senses chat latency measured against the confirmed target (p50<3s / p95<8s; probe baseline 1.3-1.6s), one injection provably reaching the next cortex turn, BOTH audiences exercised (session human + flight-attach caller), stt round-trip with verbatim transcript, tts proven or honest SKIP while the rig 502s; rows land in docs/live-testing.md

- depends on: t6, t7
- covers: c1, c3, c10, h1, h10, h11, h12, h19
- acceptance:
  - livecheck grades each lane from recorded evidence: wall-clock latencies vs target, feed evidence of the injection in-run, tts SKIPs honestly on 'no audio'
  - the full announcement demo passes or each failing lane records FAIL/SKIP with the reason — never a synthesized pass

### t11 — Docs + scope line: CLAUDE.md architecture part + third-sanctioned-increment scope language with non-goals (#276 stays parked, no streaming/wake-word, lane 2 embedder/reranker parked); docs/features/senses-live-presence.md incl. degrade paths + the rig's TTS 502 honest limit; before-state code-verification note; update #277 (lane 1 consumed) + file the lobes-cli issue (endpoint host not client-resolvable + speech proxy 502)

- depends on: t8, t10
- covers: c4, c5, h13, h18
- acceptance:
  - CLAUDE.md scope section records the increment with the fixed-enumeration language and the drift-guard doc tests pass
  - the lobes-cli issue is filed and #277 is updated to lane-1-consumed with lane 2 still parked

## Risks

- [unknown_nonblocking] The rig's TTS returns 'no audio' through the gateway (probed 2026-07-03) — the tts lane live proof depends on a rig-side fix; livecheck SKIPs honestly meanwhile (task t10)
- [unknown_nonblocking] Exact session-side non-blocking stdin mechanism must stay thread-free (select at sink boundaries); fallback if the raw reader can't multiplex cleanly: v1 session lane degrades to flight-attach-only with a notice (task t7)
- [unknown_nonblocking] Senses relay-judgment quality on Gemma (question vs instruction misclassification) — the explicit 'cortex:' prefix is the guaranteed path; a misjudged relay is visible in feed+artifact, never silent (task t4)
- [follow_up] File lobes-cli issue: /capabilities advertises stt/tts at http://realtime:8080 (not client-resolvable) and the gateway speech proxy 502s while transcriptions works

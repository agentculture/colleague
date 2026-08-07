# session streaming + speak-only voice + model-pin hygiene

> colleague session streams senses replies into the conversation, can speak while you type, and a stale model pin fails loud instead of killing the run
> instruction: acceptance is the transcript scenario end-to-end: hi -> long-story in colleague session; senses streams, narration lines appear during the run, stale pin refreshes instead of 404

## Audience

- the colleague session operator — the human typing at the 'colleague ❯' prompt on a colour TTY — plus the rig operator whose model roster rotates underneath pinned ids
  - instruction: the spec's surfaces are session-first: verify each requirement names its session rendering path; bare work --json stays untouched

## Before → After

- After: the operator reads senses' reply as it generates, optionally hears it spoken while only typing, watches cortex/worker activity narrated in-conversation as it happens, and a rotated rig model id never kills a run — the pin refreshes loudly and work proceeds
  - instruction: re-run the 2026-08-06 transcript scenario (hi -> long-story request): senses streams, narration appears mid-run, no `model_not_found` death

## Why it matters

- today the session feels dead while working ('cortex ▸ working…' then silence) and dies outright on a stale model id — the 2026-08-06 live transcript shows both; a conversational teammate must feel alive during the wait and survive model rotation without operator surgery
  - instruction: both failure modes are reproducible today: senses replies paint whole, and `CONVERTIBLE_MODEL` pointing at an unserved id 404s the run

## Requirements

- senses replies stream token-by-token into the conversation stream as a growing 'senses:' line — front-door direct answers, talk-lane replies, and speak-back all included; the SSE seam already exists (engines/`vllm_openai.py` `_make_complete` streams iff config.`on_delta` is armed)
  - honesty: streaming never changes WHAT senses says: the delivered reply equals the concatenation of streamed deltas (modulo JSON-envelope extraction) — provable by running the same turn streamed vs blocking
- the session renders incremental senses text on the conversation surface above the owned input line (the `print_above` cursor already exists); today's DeltaTail folds deltas into the cockpit STATUS line only — that tail stays, conversation streaming is additive
  - honesty: incremental rendering never corrupts the owned input line or the cockpit status tail; off a colour TTY (piped/--json) the session output stays byte-identical to today
- a speak-only voice lane: a session toggle (e.g. /speak or --speak) that TTS-speaks senses conversation lines while the operator only types — voice.py synthesize + session `_speak_reply` already exist (today gated to voice-originated turns) and the rig tts role is ready (ResembleAI/chatterbox), so this is a gating change, not new plumbing
  - honesty: with speak-only on and /voice off, no code path constructs a voice session, opens the mic, or calls stt — TTS synthesis is the only voice.py entry point reached
- a model preflight: doctor (and/or a pre-run check) verifies the configured MAIN model id is in the provider's /v1/models list and names the config source that pinned it (`CONVERTIBLE_MODEL`/`COLLEAGUE_MODEL` env vs config.json vs lobes discovery) — oilcheck/`three_tier.py` already does exactly this membership check for the worker role; the main-model path has none
  - honesty: the preflight degrades gracefully: a provider without /v1/models, or unreachable, yields a warning/skip never a hard failure — retargeting any OpenAI-compatible server stays a config change (the vLLM-adapter carve-out rule)
- stale-pin refresh (q2): a pinned model id the provider no longer serves is STALE CONFIG, not a reason to die — with lobes armed, colleague resolves the SAME role's currently-discovered id and proceeds, loudly (a recorded warning names the stale pin, its source, and the refreshed id); not a fallback and never a routing decision: the intended target (the role) never changed, only its id rotated
  - honesty: the refresh fires ONLY when the provider explicitly reports the pinned id unserved (404 `model_not_found`, or absence from /v1/models), stays within the SAME role, and records a warning naming the stale id + its source + the refreshed id; with lobes unarmed or the role advertising no model, the original error surfaces unchanged
- cortex's live output streams to the user as senses-described '<<higher self thought>>' lines in the conversation stream — keeps a long cortex turn visibly alive instead of 'working…' silence
  - instruction: with cortex mid-run, '<<higher self thought>>' senses-described lines appear in the conversation WHILE the run is in flight; the artifact step trace contains none of them
  - honesty: narration is senses-AUTHORED description of the cortex stream, labeled '<<higher self thought>>' — never raw cortex deltas relabeled; the user can always tell narration from senses' own conversational replies
- in three-tier mode, worker activity surfaces the same way as senses-described '<subconscious thought/actions>' lines in the conversation stream
  - instruction: in a three-tier session, worker steps surface as '<subconscious thought/actions>' lines; unconfigured sessions byte-identical
  - honesty: worker narration exists only in three-tier mode; a session without `three_tier` configured renders byte-identical output
- session cortex turns run STREAMED so each SSE chunk resets the read-timeout window — a long generation no longer dies to `COLLEAGUE_TIMEOUT` mid-turn (urllib's timeout is per-read; `_raise_legible_timeout` is already shared by blocking + streaming paths) — this is the 'stream cortex to avoid timeout' rationale made mechanical
  - honesty: streamed and blocking cortex turns produce identical TaskResult shape and token accounting (usage from the final `include_usage` chunk; zeros when the server sends none — same as blocking)
- TTS decoupling: `_speak_reply` is gated on a live voice session and `play_wav_bytes` takes that session to hold the half-duplex gate — speak-only needs a playback path WITHOUT a voice session (no mic means no half-duplex gate to hold), and typing stays live during playback (the input reader thread keeps the owned line responsive)
  - honesty: with speak-only on, playback runs with NO voice session object in existence; a synth or playback failure leaves the rendered text byte-identical (the existing degrade-never-raise contract)
- narration cadence rides EXISTING tool-call/phase boundaries (the `senses_loop` boundary beats) — a senses narration completion never runs inside cortex's `on_delta` callback (it would stall the stream read) and never spawns a thread outside the sanctioned list; between boundaries, liveness comes from the delta tail
  - honesty: no senses completion is issued between tool-call/phase boundaries during a cortex turn; tests/`test_boundary.py`'s thread confinement stays green
- streaming containment: incremental-extraction failure or mid-stream death degrades THAT turn to a whole/partial reply render with a legible marker — the reply text is never lost (the engine already tracks stream completeness via the accumulator's `finish_reason`)
  - honesty: a test kills the stream mid-reply and asserts the partial text renders with a marker and the session continues — no exception escapes to the operator
- the stale-pin refresh warning lands in the run ARTIFACT (WorkStats/warnings), not only stderr — background one-shots and chained episodes surface it after the fact
  - honesty: a background run with a stale pin produces an artifact whose warnings name the stale id, source, and refreshed id — greppable without a TTY

## Honesty conditions

- every piece (streaming, speak-only, narration, stale-pin refresh) lands inside the existing conventions — no new daemon/socket, threads stay on the sanctioned list, tests/`test_boundary.py` green
- the mic-arming gate is untouched: only --voice or /voice can create a voice/realtime session; the speak-only toggle cannot, by construction
- after the stale-pin refresh lands, model resolution inputs are still exactly {flag, env, config.json, lobes role discovery} — no code path reads task content to pick a model
- machine-checkable: a test on a narrated run asserts zero narration lines in every model-bound messages array
- nothing in this arc changes bare work/--json/piped output — the session colour TTY is the only surface that gains behavior (the recorded off-TTY senses-lines break stays the sole exception)
- the after-state holds with senses armed on a colour TTY; with senses unarmed the session degrades to today's behavior, not to a broken hybrid
- the transcript is representative, not a one-off: both failure modes reproduce on demand today (verified 2026-08-06 — whole-reply senses paints; stale `CONVERTIBLE_MODEL` 404s every cortex run)
- latency numbers are rig-relative (measured: TTFT 0.28s local / 5.31s proxied); the durable signal is incremental paints, exit codes, and call counts — not absolute seconds
- no config default, profile, or mode flips speak-only on without an explicit per-session opt-in (flag or slash toggle)

## Success signals

- in a live session: a senses reply shows >= 2 incremental paints (not one whole-reply paint) with first token < 2s after transport TTFT; with a stale pinned model id + lobes armed, work exits 0 with a recorded stale-pin warning (today: HTTP 404 death); with speak-only on, a senses reply yields exactly 1 TTS playback and 0 stt/mic calls
  - instruction: measure against the live rig (transport TTFT 0.28s local cortex / 5.31s proxied senses); the signal is incremental paints + exit codes + call counts, all scriptable

## Scope / boundaries

- c27 stands untouched: speak-only mode never arms the mic or stt — the mic stays hot only on explicit /voice or --voice; half-duplex mute (lobes d1) is a mic-lane concern irrelevant to speak-only
- no routing policy (v1 scope line): model resolution stays declared/discovered-by-role; the model-pin fix is diagnostics + hygiene, never an automatic task-to-model fallback
- the narration lane is user-display ONLY: '<<higher self thought>>' / '<subconscious thought/actions>' lines never enter any model's context — not senses' own history, not cortex's, not the worker's; presentation, never feedback
  - instruction: after a narrated run, assert zero narration lines in every model-bound messages array (senses history, cortex context, worker context) — a test greps the artifact + step trace
- speak-only is per-session opt-in, default OFF — audio out is a side channel (office speakers); mirrors c27's spirit on the speaker side

## Assumptions

- transport streaming is live end-to-end: 2026-08-06 probes through the lobes gateway :8001 show incremental chunks for both the local cortex model (first chunk 0.28s) and the orin-proxied senses model (first chunk 5.31s) — the gateway no longer buffers SSE (lobes-cli#103 fixed)
- senses direct answers ride a prompted-JSON move envelope (`senses_loop` tools-off completion); verbatim token streaming would leak JSON syntax, so streaming needs incremental text-field extraction or a plain-text completion rung — also `senses_engine_config` dataclasses.replace inherits `on_delta` from the parent config, so an armed cortex sink would receive senses deltas unless rewired
- probed live 2026-08-06: the senses model streams its JSON move envelope as a ``\`json fence with the text field contiguous but chunk boundaries splitting mid-key ('{"move', '": "') — incremental extraction is a small fence-tolerant state machine that withholds the closing quote/brace/fence, never a regex over complete JSON
- cortex-delta input handed to senses for narration is windowed against senses' OWN context budget (the senses.py `_window_text` pattern) — a long cortex turn never blows senses' context

## Scope exploration

- `s1` — `colleague/engines/vllm_openai.py (SSE seam)`: `_make_complete` is the single blocking-vs-streaming decision point, keyed on config.`on_delta`; token deltas (content + reasoning) already emit via `_emit_delta` — streaming senses replies needs only an armed `on_delta` on the senses config path
  - seeds: `c2`
- `s2` — `live rig probe: POST /v1/chat/completions stream:true via gateway :8001`: incremental chunks for both the local cortex model (first 0.28s, ~0.12s cadence) and the orin-proxied senses model (first 5.31s) — the lobes gateway no longer buffers SSE, lobes-cli#103 is fixed in practice
  - seeds: `c3`
- `s3` — `colleague/cli/_commands/session.py + _tui_sink.py (DeltaTail)`: session deltas today fold into the cockpit STATUS line via `delta_status_message` (feels-alive t6), never the conversation; the owned-input-line `print_above` cursor is the existing hook for rendering text above the prompt
  - seeds: `c4`
- `s4` — `colleague/senses.py + senses_loop.py`: senses completions are one-shot `robust_simple_complete` over prompted-JSON moves (tools-off `make_complete`); `senses_engine_config` dataclasses.replace inherits `on_delta` from the parent config — an armed cortex delta sink would receive senses deltas unless rewired
  - seeds: `c5`
- `s5` — `colleague/voice.py + session._speak_reply + config.VoiceConfig`: synthesize + additive speak-back already exist but `_speak_reply` fires only on voice-originated turns; `tts_model` resolves from the lobes tts role, live-checked ready (ResembleAI/chatterbox) — speak-only is a gating change
  - seeds: `c6`
- `s6` — `session /voice toggle (c27) + docs/features/realtime-speech.md`: /voice and --voice arm the MIC lane (the mic is never hot without them, decision c27); a speak-only mode leaves that gate untouched — no echo problem either, since no mic means half-duplex mute is moot
  - seeds: `c7`
- `s7` — `shell env + ~/.bashrc:173-194 + rig /v1/models`: exported `CONVERTIBLE_MODEL`=sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP is the 404 root cause; bashrc's default (line 174) and the rig's served list both already say unsloth/Qwen3.6-27B-NVFP4; ~/.colleague/afb67b0a3116.hi.json is an old run artifact, not config
  - seeds: `c9`
- `s8` — `colleague/oilcheck/ (doctor) + colleague/livecheck.py`: livecheck `probe_endpoint` GETs /models but checks reachability only; oilcheck/`three_tier.py` compares the WORKER model id against gateway /v1/models and FAILs naming the mismatch — the main-model path has no membership check, which is the gap the transcript's 404 fell through
  - seeds: `c8`
- `s9` — `CLAUDE.md v1 scope line (no multi-backend router)`: automatic task-to-model routing is explicitly out of scope; any `model_not_found` auto-fallback both needs the q2 decision and touches the 'env/config.json always win' rule — the safe landing is diagnostics
  - seeds: `c10`
- `s10` — `challenge pass / adjacent-systems lens: vllm_openai.py streaming usage accounting`: CLEAN: `_capture_frame_usage` takes usage verbatim from the final `stream_options`.`include_usage` chunk, degrading to zeros exactly like blocking — the tokens-never-estimated convention survives streaming untouched
- `s11` — `challenge pass / cheap probe: live streamed JSON envelope on the senses model`: fence-wrapped envelope, contiguous text field, chunk boundaries split mid-key — incremental extraction feasible and its shape now pinned
  - seeds: `c20`
- `s12` — `challenge pass / hidden-dependency lens: session._speak_reply + realtime.play_wav_bytes`: the batch TTS lane is coupled to the mic/realtime session (half-duplex gate arg) — speak-only must decouple playback from the voice session; found by reading the code, not assumed
  - seeds: `c21`
- `s13` — `challenge pass / concurrency lens: on_delta read loop + senses_loop boundary beats + sanctioned thread list`: a senses narration completion inside `on_delta` would stall the cortex stream read; the existing boundary beats are the only cadence that needs no new thread — seeded the cadence requirement + windowing assumption
  - seeds: `c23`, `c24`
- `s14` — `challenge pass / failure-mode lens: _raise_legible_timeout + _StreamAccumulator`: read-timeout is per-chunk on a streamed response (the timeout-avoidance rationale is mechanical, not vibes); mid-stream death leaves an accumulator with partial text + `finish_reason` absent — containment is buildable on what exists
  - seeds: `c19`, `c25`
- `s15` — `challenge pass / security lens: audio-out side channel + the c27 mic gate`: mic side already covered (c7/h5, untouched); the NEW side channel is the speaker — speak-only lands default-off per-session opt-in
  - seeds: `c22`
- `s16` — `challenge pass / observability lens: artifact.py WorkStats + background.py`: stderr-only warnings vanish for background one-shots and chained episodes — the refresh warning must ride the artifact
  - seeds: `c26`
- `s17` — `challenge pass / unexamined: three-tier relay internals (lattice, flight seat)`: NOT read this pass — worker narration wiring point unverified; parked v1, verify at plan time
- `s18` — `challenge pass / adjacent-systems lens: off-TTY / --json session surface`: CLEAN: c15/h12 already pin byte-identical off-TTY behavior; nothing in the challenge findings touches piped output

## Open parks

- [unknown_nonblocking] three-tier relay internals (lattice content lane, flight seat) were not read in this pass — the exact wiring point for worker narration is verified at plan time

# Senses live presence + voice

**Talk to colleague while it works.** While cortex drives a work item, the
operator holds a live conversation with **senses** concurrently — senses answers
in seconds from the running context, the operator's words become guidance
injected into cortex at the next tool-call boundary, and audio rides in and out
through two lobes-served voice roles. Delegation stops being silence.

This is the **third sanctioned increment** at colleague's router-exclusion line
(after the dual-model deepthink escalation and the cortex/senses role split).
It extends the *existing* enumerated senses surface — it is **not** a task→model
router: the task always goes to cortex, senses converses and relays but never
acts (structurally tools-off), and #276 (senses-direct) stays parked.

## The lanes

### Senses talk lane — `colleague/senses.py` `run_senses_talk`

The tools-off sibling of `run_senses_intake` / `run_senses_speakback`:

```python
run_senses_talk(message, *, feed_tail, packet, task_state, senses_config,
                make_complete, make_count_tokens=None, relay_prefix="cortex:")
    -> {"answer", "relay", "relay_text", "latency", "degraded", "tokens"} | None
```

- **Tools-off, always**: reaches the wire only via `make_complete(senses_config,
  tools=[])` — an explicit empty tool list, never a schema. `senses.py` imports
  neither `subprocess` nor any `ToolExecutor` (pinned structurally).
- **Grounded**: the prompt is built from the live run context — the flight-feed
  tail, the context packet, and a short task-state snapshot — and windowed to
  senses' OWN `context_budget`. Senses is instructed to answer only from that
  context and to say it doesn't know rather than fabricate run state (a
  fabricated-status answer is a test failure).
- **Advisory only**: the return is NEVER the task answer. `answer` is displayed
  to the operator; `relay`/`relay_text` say whether (and what) to inject into
  cortex.
- **Explicit relay override**: a `cortex:` prefix on the message forces
  `relay=True` regardless of the model's judgment — the guaranteed relay path,
  applied even when the completion itself degrades.
- **Degrade-never-raise**: a dead senses endpoint returns `degraded=True` with a
  safe answer; `senses_config=None` (unarmed) returns `None` so the caller
  degrades to watch-only.

### Voice wire clients — `colleague/voice.py` (pure stdlib, no subprocess)

- `transcribe(audio_path, *, stt_model, base_url, ...) -> str | None`: POSTs
  multipart audio to `{base_url}/audio/transcriptions` and returns the server's
  transcript **verbatim** (the v1 verbatim invariant extends to transcripts — a
  lossy/paraphrased transcript is a test failure). Any 4xx/5xx/timeout degrades
  to `None` + one stderr notice.
- `synthesize(text, *, tts_model, base_url, out_path, ...) -> Path | None`:
  POSTs to `{base_url}/audio/speech`, writes the returned WAV bytes to
  `out_path`, returns the path. A 502 / JSON `no audio` body (the reference
  rig's current state) degrades to `None` + one notice, **writing no file** —
  the text reply stays byte-identical (audio is strictly additive).

### `[voice]` extra — `colleague/voice_devices.py` (opt-in device layer)

Mic capture (`record`) and speaker playback (`play`) behind **lazy** imports of
`sounddevice`/`soundfile` (the `[voice]` extra). A base install carries no audio
dependency — the module imports fine and only errors, cleanly naming
`pip install colleague[voice]`, when a capture function is actually called
without the extra. `play()` is additive: a missing extra or a playback failure
returns `False` + one notice and **never loses the written wav**.

### Role resolution — `colleague/lobes.py` + `colleague/config.py`

`resolve_roles` now parses **optional** `stt`/`tts` roles from the gateway's
`/capabilities` — their absence or a malformed shape leaves them `None` but never
fails resolution (cortex/senses stay the only mandatory roles). A `VoiceConfig`
(`stt_model`/`tts_model`/`stt_base_url`/`tts_base_url`/`api_key`) resolves
through the SAME precedence chain as senses (flag >
`COLLEAGUE_STT_MODEL`/`_TTS_MODEL`/`VOICE_*` env > `.colleague/config.json`
`voice` section > lobes discovery > absent). **Per-role dialing (colleague#292,
closing lobes-cli#87 end-to-end):** `stt_base_url`/`tts_base_url` each resolve
INDEPENDENTLY via `colleague/lobes.py`'s `resolve_role_base_url` — the role's
own advertised `endpoint` when it is a non-empty, allowed-scheme URL, falling
back to the gateway origin (with the OpenAI `/v1` suffix) only for an unwired
role or a disallowed scheme; a rig serving stt/tts from different origins now
dials each correctly (before lobes-cli 0.38.0 both were forced onto one shared
gateway-origin value, since no role's self-reported `endpoint` was
client-reachable yet). The non-lobes env/config.json path sets both fields to
the same declared value. **Absent voice config is byte-identical** —
`EngineConfig.voice` is `None` and omitted from `to_dict`.

**api_key hygiene (conservative, single-field):** `VoiceConfig` carries ONE
`api_key` for both `stt` and `tts`, so the main `api_key` is inherited only
when EVERY armed role's dial target shares the main endpoint's origin — the
reference rig: everything proxied at one gateway. A single cross-origin armed
role withholds the main key from the WHOLE `VoiceConfig` instead — the main
Bearer token is never forwarded to a host a wire payload advertised — falling
back to the no-auth default even for a same-origin sibling role. To arm a
cross-origin voice rung, declare the key explicitly
(`COLLEAGUE_VOICE_API_KEY`, or a `config.json` `voice.api_key` — which works
even without a declared model); a wrong or absent key degrades visibly at the
next transcribe/synthesize call, never fails the run. A per-role
`stt_api_key`/`tts_api_key` split — letting one role inherit while a
cross-origin sibling is withheld — is a named follow-up, not built; a
unified withheld-key stderr notice across all three discovery rungs is
tracked as [#349](https://github.com/agentculture/colleague/issues/349).

## Two audiences, one flight plane

The live presence is an operator-side foreground process riding the existing
file-based flight plane — no daemon, no socket, no new thread.

- **Interactive session** (`colleague/cli/_commands/session.py`): while a work
  line runs, the session polls stdin non-blockingly at each progress-sink
  boundary (`select` with zero timeout — **no threads**). Typed input routes to
  `run_senses_talk` (answer rendered labeled `senses:`), relays land as flight
  guidance (echoing `-> cortex:`), and `/say FILE` transcribes audio first.
  Gated on a colour TTY + senses armed + not `--cortex-only`, so
  off-TTY/`--no-tui`/piped is **byte-identical** to today.
- **Attach verb** (`colleague talk <task-id>`,
  `colleague/cli/_commands/talk.py`): a flight-plane REPL for background and
  agent-caller runs. Senses-unarmed degrades to a watch + raw-guide REPL.
- **Resident appserver** (`colleague/resident/appserver.py`): replies carry a
  synthesized-wav file-link line when voice is armed (so a mic-less mesh peer
  consumes the audio as a file), and peer relays route under the c19 trust
  model — a **non-operator can never `append_guidance`** (one call site,
  structurally inside the operator-only branch).

## Awareness invariant

Nothing mid-run is silent — for a human in session AND for an agent caller
reading feed/artifact:

- Every **applied** guidance injection produces a flight-feed line AND a
  `TaskResult.senses.injections` record (`{text, at, source}`, `at` a wall-clock
  float, never estimated).
- Every talk exchange folds into `TaskResult.senses.chat` at finish (read from
  the flight chat log before the reap).
- The operator's mid-run view (answers seen + injections made) is
  reconstructable from feed + artifact alone — an unlabeled answer or an
  unrecorded injection fails the reconstruction test.
- The #206 invariant holds: recording an injection never advances `step_count`
  or adds a phantom step.

`TaskResult.senses` gains `injections` and `chat`, both **omit-when-empty**, so a
run with no live lane is byte-identical to the pre-arc artifact.

## Runtime-owned (all-engines rule)

The talk lane, injection recording, and voice plumbing fire identically for
`mock` and `vllm-openai`. A run with no live lane is a strict no-op.

## Honest limits

- **The reference rig's gateway speech proxy 502'd for BOTH `stt` and `tts`**
  (probed 2026-07-03: `/audio/speech` → `{"error":"TTS backend returned no
  audio"}`, `/audio/transcriptions` → HTTP 502), even though `/capabilities`
  reported both roles `ready`. The voice round-trip live proofs **SKIPped
  honestly** (never a fabricated pass) until the rig-side proxy was fixed
  (sibling of lobes-cli#87). **2026-07-22: fixed (lobes-cli#89/#92 closed) and
  both lanes PASS live through colleague's own wire clients** — a verbatim stt
  round-trip and a real tts wav; see `docs/live-testing.md`'s dated
  2026-07-22 section (closes #304).
- **The crux latency proof PASSES**: a senses answer WHILE cortex loads the
  shared GPU measured **1.14s alone / 2.33s p50** under a concurrent 27B cortex
  generation (target p50<3s / p95<8s) — the cross-model-concurrency assumption
  holds; the GPU is not head-of-line-blocked to failure.
- A **fully-live cortex-loop injection** waits on the rig serving a
  tool-calling cortex backend — today's 27B emits into `reasoning` with
  `content: null` and does not drive a real tool loop (the standing #66 gap).
  The injection channel itself is proven deterministically at the loop level.
- Superseded 2026-07-22: this doc used to read "Voice v1 is **turn-based**
  (record → transcribe → work → speak) — no streaming, no barge-in, no wake
  word." Streaming speech now ships as the **seventh sanctioned increment** —
  see `docs/features/realtime-speech.md`. Turn-based voice (this section,
  otherwise unchanged) is now the **degrade floor** the realtime lane falls
  back to, not the only lane. Barge-in and wake word remain OUT in v1 — the
  realtime lane is half-duplex (client-edge mute during playback), not
  full-duplex conversation.
- The session lane and `talk` verb are parallel implementations of the same lane
  for two surfaces; unifying their turn-processing is a possible follow-up.

## Live-testing

See `docs/live-testing.md` rows 19–23 for the recorded rig evidence and the
grade-from-evidence classifiers in `colleague/livecheck.py`
(`classify_senses_latency_check` / `classify_injection_reached_check` /
`classify_voice_lane_check`).

## Spec + plan

- `docs/specs/2026-07-03-talk-to-colleague-while-it-works-senses-is-a-live.md`
- `docs/plans/2026-07-03-talk-to-colleague-while-it-works-senses-is-a-live.md`

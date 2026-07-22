# Realtime speech

**Talk to senses by voice, live, while cortex works.** Instead of the
record-then-transcribe turn, the operator's mic streams continuously to the
rig's `/v1/realtime` WebSocket session; the server's own VAD (voice-activity
detection) decides when a turn ends, the final transcript lands exactly where
typed input lands today, and senses' spoken reply plays back over the
speaker. Turn-based voice ([`senses-live-presence.md`](senses-live-presence.md))
becomes the **degrade floor**, not the only lane.

This is the **seventh sanctioned increment** at colleague's router-exclusion
line (after dual-model deepthink, cortex/senses, senses live presence + voice,
presence-default-everywhere, the senses front door, and deepthink discovered
from the lobes `muse` role). It is a transport swap on an *existing* enumerated
surface, not a new one: realtime consumes the same two named voice roles
(`stt`/`tts`) colleague already consumes, no new lobes role is added, and the
task still always goes to cortex.

## The ears-only invariant

`colleague/realtime.py`'s `RealtimeSession` never sends `response.create` and
has no method that ever will. This is not an incidental restriction — it is
the whole design: the rig's realtime bridge has its **own** armed mode with
its **own** LLM and its own `DEFAULT_SYSTEM_PROMPT`, completely independent of
senses' grounded, run-aware context (the flight-feed tail, the context packet,
the task-state snapshot `run_senses_talk` builds from). Arming the bridge's own
turn would mean the operator gets an answer from a *different, ungrounded*
model instead of senses — a second mind quietly replacing the first. So the
realtime socket colleague dials is **ears-only**: it consumes session
lifecycle, VAD turn-boundary, and transcription events only. The final
transcript is handed to the *existing* `run_senses_talk` lane exactly like
typed input (`colleague/cli/_commands/session.py`'s talk-lane poll), and the
spoken reply is produced by the *existing* batch `colleague.voice.synthesize()`
call — the realtime socket is a listening ear, never a second voice. Senses
stays the only mind that answers; cortex remains the only repo actor.

## Config + arming

`colleague.config.RealtimeConfig` (`available`, `ws_url`, `api_key`,
`input_device`, `output_device`) resolves onto `EngineConfig.realtime` through
the same precedence chain every other role uses:

1. **Explicit operator knob** — `COLLEAGUE_REALTIME_URL` /
   `COLLEAGUE_REALTIME_API_KEY` env, or a `realtime` section in
   `.colleague/config.json`.
2. **Lobes discovery** — `colleague/lobes.py`'s `stt_supports_realtime()`
   checks the advertised `stt` role's `responsibilities` for
   `REALTIME_VAD_RESPONSIBILITY` (`"realtime_vad_session"`) **and** voice must
   already be armed; only then does the discovery rung fill a `RealtimeConfig`.
3. **Absent** — `EngineConfig.realtime` is `None`, and the session lane makes
   **zero** WebSocket dial attempts. Nothing resolved means nothing dialed.

`input_device`/`output_device` are pure local knobs (a PortAudio index or a
case-insensitive name substring, e.g. `"Reachy Mini"`) — they resolve
identically regardless of which rung produced the config, because a
discovered dial target says nothing about which mic/speaker *this* machine
should use.

**The #348 same-origin key rule, extended to the WS dial.** The explicit rung
inherits the main `api_key` unconditionally (trusted operator intent) unless
it declares its own. The discovery rung follows the same-origin hygiene rule
`VoiceConfig` already applies to `stt`/`tts`: the main Bearer token is only
carried onto the realtime dial target when that target shares the main
endpoint's origin; a cross-origin discovered realtime target withholds the key
rather than forwarding it somewhere a wire payload advertised. Probed live
2026-07-22 against the reference rig: `/v1/realtime` answers `401
WWW-Authenticate: Bearer` without the key and `101 Switching Protocols` with
it — the same-origin rule is what makes that handshake succeed automatically
for the reference gateway (everything proxied at one origin) while still
refusing to leak the key to an unrelated host.

**Mic-armed is availability, never a hot mic (c27).** A resolved
`RealtimeConfig` only ever means the lane is *available* — `colleague session`
renders exactly one offer line (`voice · available · type /voice (or restart
with --voice) to talk by voice`) and dials nothing on its own. Capture starts
only on an explicit per-session opt-in: the `--voice` CLI flag, or the
`/voice` slash command toggling it on mid-session (and back off — `/voice`
again mutes). This is a deliberate, recorded decision (arc decision q4): a
rig that advertises realtime support does not get to make the operator's mic
live by discovery alone. Lane state renders honestly following the cockpit
label-state-consequence policy — `off` / `live` / `muted` / `degraded` are
four visibly different labels (a muted lane must never look the same as a
dead one).

## The degrade ladder

Every layer degrades instead of raising, with exactly one `colleague: ...`
stderr notice per degradation:

- **realtime → turn-based**: a dial/handshake failure, a mid-session drop, or
  the receive pump erroring out flips `RealtimeSession.degraded` and falls
  back to the existing record → transcribe → work → speak lane
  (`senses-live-presence.md`). The `[voice]` extra missing (checked first,
  before config is even read) raises a clean, named `CliError` instead — an
  environment problem the operator fixes once, not a live-session hiccup.
- **turn-based → text**: as documented in `senses-live-presence.md`, a dead
  `stt`/`tts` endpoint degrades further to text-only; the text reply stays
  byte-identical to an audio-less run either way.

A bad/missing audio device (an unmatched name, a `PortAudioError`) degrades
the same way, naming the configured device value in the one notice it prints
— never a traceback, and the session stays usable in the turn-based/text lane
regardless (additive, never a replacement).

## Half-duplex: client-edge mute, not AEC

v1 is deliberately **half-duplex**: while senses' spoken reply plays back,
captured mic frames are dropped before they ever reach the encode step, the
send lock, or the wire (`RealtimeSession.mute()`/`unmute()`, held for the
whole `play_wav_bytes()` call, checked structurally on the capture side in
`_forward_captured_frame` *and* again inside `send_audio` — belt and
suspenders). Without this gate, the rig's server-side VAD would hear senses'
own synthesized speech coming back through the operator's speakers and
self-trigger a feedback-loop turn (the bridge's `AECMode` defaults to `NONE`
and `server_vad` segments whatever arrives, regardless of source).

This is the recorded **lobes d1 deviation**: `../lobes-cli`'s own Astro
browser client deliberately does *not* auto-mute during playback there,
because the browser's own `echoCancellation` constraint already owns AEC, and
an automatic mute would defeat barge-in in that context. This machine's actual
hardware (Reachy Mini USB audio, an Arducam mic, an HDMI sink) has no such
echo-cancelling front end reachable from Python/PortAudio — so the *same*
deviation d1 places the AEC-substitute responsibility at exactly **this**
client edge instead. Colleague *is* the client edge here, and its mute is
that substitute — not a violation of the browser-side ban, just a different
client meeting a different hardware reality with the same documented
rationale. Barge-in (talking over a playing reply) and true AEC stay
explicitly OUT of v1.

## Thread sanction

Continuous audio needs a receive-pump thread. `colleague/realtime.py` is the
sanctioned third module (after `colleague/subagents.py` and
`colleague/cli/_commands/_input_line.py`) allowed to import `threading`
directly (`tests/test_boundary.py`). The pump mirrors
`_input_line.py`'s `OwnedInputLine` exactly: one daemon thread, a
`threading.Event` stop signal, a poll-wake read (`websocket-client`'s
`settimeout` gives the same wake-and-recheck shape `select` gives the input
line), and a bounded join so teardown never hangs on a parked blocking read
(the `#315` lesson — a fake stream cannot prove stop-promptness; this module
is proven against a real threaded stdlib socket server, never a mocked
WebSocket object). Mic capture's own audio thread is PortAudio's, not a
`threading.Thread` colleague spawns — `CaptureHandle` only owns start/stop of
that stream. The WS client is synchronous throughout (`tests/test_boundary.py`
also flags `import asyncio` anywhere outside `colleague/resident/`), so the
pump drives a sync recv loop from the one sanctioned thread rather than an
event loop.

## Device selection

`input_device`/`output_device` resolve against `sounddevice.query_devices()`:
a purely-numeric string is a PortAudio index, anything else is matched as a
case-insensitive name substring restricted to the right kind of device (an
input match requires `max_input_channels > 0`, an output match requires
`max_output_channels > 0`, so a name that exists only as the wrong kind never
silently matches). `None`/blank resolves to the audio library's own default
device — never a hardcoded index (this reference machine alone exposes
multiple HDMI outputs, a Reachy Mini USB capture device, an Arducam capture
device, and PipeWire's aggregate/default nodes; "device 0" is a genuinely
different piece of hardware on every box). A device that fails to open
degrades with one notice naming the configured value.

## Two audiences, one flight plane

Realtime is an **operator-side, interactive-session surface only** — the same
gating `senses-live-presence.md`'s talk lane already uses (colour TTY + senses
armed + not `--cortex-only`) plus realtime availability, so off-TTY / piped /
`--json` sessions stay byte-identical: zero realtime dial attempts, zero
output difference. The resident/mesh surface is unchanged by this arc — a
mesh peer still consumes synthesized-wav file links (the c19 trust model
still applies; a non-operator still never gets a live audio channel). No
realtime audio rides IRC or any mesh transport.

## Livecheck

`colleague/livecheck.py`'s `run_realtime_check` opens the ears-only session
end-to-end, sends one short silence burst, and waits for at least one server
event — graded by `classify_realtime_check`. It SKIPs honestly (never a
fabricated pass) on any of three absences: the `[voice]` extra not installed,
`config.realtime` not resolved, or the dial/handshake itself failing (a
configured endpoint not actually serving `/v1/realtime`). This task (t8) also
records that all `ProofResult` runner checks — including this one — are now
wired into the `colleague livecheck` verb itself, closing the gap `#304`'s
evidence trail found: `run_presence_narration_check` previously had no
production caller and had to be invoked directly.

## Honest limits

- **The PASS bar for `run_realtime_check` is a session-open + event handshake,
  not a transcription proof.** `classify_realtime_check`'s own docstring says
  so explicitly: a PASS proves the WebSocket session opened and the server
  emitted at least one event back — it does **not** prove a speech-to-text
  transcript round-tripped correctly. A real transcript proof needs a live
  spoken (or rig-synthesized) utterance, not a silence burst.
- **No live real-microphone proof exists yet at the time this doc is
  written.** Every rig-side probe so far (including the `#304` stt/tts
  round-trip below) used rig-synthesized audio (chatterbox → parakeet), never
  a human speaking into a real Reachy Mini/Arducam mic while cortex runs. That
  proof — end-to-end speech → transcript → senses answer → spoken reply, live
  mic, under concurrent cortex load, with measured p50/p95 latency — is
  **plan task t9**, not yet run as of this doc.
- **Barge-in, true AEC, and wake-word detection stay OUT of v1** — see
  "Half-duplex" above. The realtime lane is half-duplex by design, not a
  full-duplex conversation.
- **The WS client and continuous-audio deps stay behind the opt-in `[voice]`
  extra**, imported lazily inside each function (never at module load) —
  mirroring `colleague/voice_devices.py` exactly, so a base install (no
  extras) stays import-clean and byte-identical.
- The session lane and the `talk` verb (`senses-live-presence.md`) remain
  parallel implementations of the same underlying talk lane for two surfaces;
  realtime only wires the interactive-session one. Unifying their
  turn-processing remains a possible follow-up, unchanged by this arc.

## `#304` closure — the floor this arc builds on

Before this arc could add a realtime lane on top of the voice roles, the
turn-based `stt`/`tts` round-trip itself had to be genuinely live (not just
discovery-reachable). Issue **`#304` is CLOSED**, landed via **PR `#355`**
(merged as `6ef5b8e`, "docs: voice lanes live — stt/tts/presence-narration
proofs flip SKIP → PASS (closes #304)"). `docs/live-testing.md`'s dated
**2026-07-22** section ("Voice lanes live: stt/tts/presence-narration flip
SKIP → PASS (closes #304)") records the evidence this realtime arc starts
from: a real 119,084-byte tts wav synthesized in 1.45s, a verbatim stt
transcript round-tripped in 0.11s, and `run_presence_narration_check`
returning a real `passed` grade — all through colleague's own wire clients
against the reference rig, no colleague code change needed to flip those
three rows from SKIP to PASS. This realtime arc treats that dated section as
the last word on the pre-realtime turn-based floor; see it directly rather
than re-deriving the numbers here.

## Spec + plan

- `docs/specs/2026-07-22-realtime-speech.md`
- `docs/plans/2026-07-22-realtime-speech.md`

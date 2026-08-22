# Session streaming, narration, speak-only voice, and model-pin hygiene

> **Opt-in since v1.63 (qwen-direct).** Senses is no longer resolved from the
> lobes gateway by default — a bare run dials exactly one model (cortex). Arm
> this lane explicitly with `COLLEAGUE_SENSES_MODEL=lobes` (discovery) or an
> explicit model id (config.json `senses.model` works too); unarmed, every
> behaviour below is dormant and the artifact is byte-identical to the unarmed
> floor. Spec: `docs/specs/2026-08-22-qwen-direct-no-gemma.md` · doc:
> [`qwen-direct.md`](qwen-direct.md).

**Spec:** [`docs/specs/2026-08-06-session-streaming-speak-only-voice-model-pin-hygie.md`](../specs/2026-08-06-session-streaming-speak-only-voice-model-pin-hygie.md)
· **Plan:** [`docs/plans/2026-08-06-session-streaming-speak-only-voice-model-pin-hygie.md`](../plans/2026-08-06-session-streaming-speak-only-voice-model-pin-hygie.md)
· Landed as the session-streaming arc (v1.55.0); live-proven against the rig
2026-08-06 (`tools/live_proofs/session_streaming_proof.py`).

The arc closes the transcript that motivated it: a session that painted senses
replies whole, went silent for a whole cortex turn ("`cortex ▸ working…`"),
had no way to speak while the operator typed, and died outright on a stale
pinned model id.

## Streaming — senses replies render as they generate

- **Extractor** (`colleague/senses_stream.py`): senses replies ride a
  prompted-JSON move envelope, usually ```` ```json ````-fenced, with chunk
  boundaries splitting mid-key. `EnvelopeStream` is a stdlib character state
  machine extracting the reply field incrementally — fence markers, braces,
  keys, and the closing quote/brace/fence withheld; JSON escapes decoded;
  non-target keys skipped with full JSON awareness. A hopeless stream flips
  `.failed` (callers bail to raw rendering); `finish()` raises `EnvelopeError`
  carrying `.accumulated` so no text is ever lost. A complete envelope whose
  closing fence never arrives is fine (models stop at `}` on EOS routinely).
- **Per-surface envelope keys** (d4, #374): coordination moves carry `text`;
  the front door and talk lane carry `answer` (`FRONTDOOR_STREAM_FIELD` /
  `TALK_STREAM_FIELD` bind streaming to the same key each parser requires);
  speak-back is bare prose — raw pass-through, no extractor.
- **Arming** (`colleague/senses.py`): `senses_engine_config(config, *,
  on_delta=None)` — the senses twin **clears** the parent's `on_delta` (and
  `refresh_seat`); streaming arms explicitly per surface, only on the live
  colour-TTY session tier. `make_senses_display_delta(sink, field=…)` adapts
  raw deltas → extractor → display deltas, never raising into the engine's
  read loop.
- **Rendering** (`colleague/cli/_commands/session.py` + `_input_line.py`):
  one growing transient `senses: …` row above the owned input line (CR+erase
  repaint, cockpit `should_repaint_delta` cadence); the final line always
  comes from the unchanged blocking-path render. The cockpit DeltaTail
  (cortex → status line) is untouched. Off-TTY / `--json` / Markdown output
  is byte-identical to before (h12).
- **Cortex turns stream too** (t4): every session view tier arms `on_delta`,
  so the engine takes its SSE path — each chunk resets the per-read timeout,
  and a long generation no longer dies to `COLLEAGUE_TIMEOUT` mid-turn.
- **Containment** (t5): a mid-stream death finalizes the partial painted text
  as a real line plus `error: senses stream cut mid-reply — showing partial
  text`; an extraction failure degrades that turn to the whole-reply render.
  The reply is never lost, and no traceback escapes.

## Narration — senses describes the working mind, display-only

At tool-call/phase boundary beats (never inside `on_delta`, never on a new
thread), senses may author a `narrate` move describing the acting mind's
windowed delta excerpt (`BoundaryContext.delta_tail`, capped at 800 chars,
re-windowed against senses' own budget). Render-time labels:

- `<<higher self thought>>` — cortex's stream (normal mode);
- `<subconscious thought/actions>` — the worker's, in three-tier mode (the
  label selector rides `PresenceEngine._render_turn`'s existing three-tier
  dial; verified wiring: the on_delta/delta_tail lane, **not** the lattice
  content lane and **not** the flight feed).

The narration lane is user-display ONLY (spec boundary c14): the labels never
appear in any model-bound prompt (the move schema deliberately never spells
them), narration is never absorbed into senses' history, and a narrated run's
artifact and messages arrays are machine-checked narration-free (h11).

## Speak-only voice — colleague talks while you only type

`--speak` at launch or `/speak` in-session (default OFF, c22; no config
default, profile, or mode can arm it — it is a session attribute, not a
config field). Senses' conversational replies — front-door direct answers
included — are synthesized through the existing batch TTS lane and played
via `play_wav_bytes_local`, a voice-session-free playback path (no mic ⇒ no
half-duplex gate to hold). The mic-arming gate is untouched: only `--voice` /
`/voice` ever construct a voice session (c27/h5). Synth or playback failure
leaves the rendered text byte-identical. Replies-only for now (open q4):
narration lines are not spoken — widening is a one-line change documented at
`_reply_text_from_turns`.

## Model-pin hygiene — a stale pin fails loud, never dead

- **Same-role refresh** (c11): a pinned model id the provider no longer
  serves is stale config. With lobes armed, resolution substitutes the SAME
  role's currently-discovered id and records a structured warning naming the
  stale id, its source layer (`flag` / `COLLEAGUE_MODEL` /
  `CONVERTIBLE_MODEL` / `config.json`), and the refreshed id. A call-time
  404 `model_not_found` performs the same refresh once (source labeled
  `call-time-404`, follow-up #370) — **for the main seat only**
  (`EngineConfig.refresh_seat`; the deepthink/senses twins disarm it, so
  their 404s surface into their own degrade paths — d5, #375). Never a
  fallback, never routing: the role never changes, only its id.
- **Artifact warnings** (t11): refresh warnings ride
  `TaskResult.warnings` (omit-when-empty — pre-feature artifacts stay
  byte-identical) so background/chained runs are greppable with no TTY.
- **Doctor preflight** (t10): `model_membership_source` (always) reports the
  configured model + pinning source; `model_membership` (under `--probe`)
  checks membership against the provider's `/v1/models`, degrading to
  skip/info when the endpoint is missing, unreachable, or unauthenticated.
- Both the resolution-rung fetch and the doctor probe send the resolved
  Bearer key — an authed gateway 401s anonymous fetches, which silently
  degraded the rung until the live proof caught it.

## Honest limits

- Narration is a **senses-chosen** move (h9): beats may pass without a
  narration line; the live proof observed a full story run with zero. The
  mechanism is pinned by the mocked suites; cadence is the model's judgment.
- The live rig's known zero-step markup collapse (#346) is orthogonal but
  real: small fresh dispatches can honest-incomplete regardless of this
  arc's lanes (t12's control run: valid pin, same collapse).
- Call-time refresh warnings carry `call-time-404` as their source, not the
  original pinning layer (#370).
- Off a colour TTY nothing here changes any output byte (h12); with senses
  unarmed the session degrades to pre-arc behavior wholesale (h13).
- `--speak` with no resolvable tts degrades silently; only the `/speak`
  toggle renders the honest unavailable line.

# Build Plan — session streaming + speak-only voice + model-pin hygiene

slug: `session-streaming-speak-only-voice-model-pin-hygie` · status: `exported` · from frame: `session-streaming-speak-only-voice-model-pin-hygie`

> colleague session streams senses replies into the conversation, can speak while you type, and a stale model pin fails loud instead of killing the run

## Tasks

### t1 — Fence-tolerant incremental JSON-envelope extractor

- instruction: new stdlib-only module colleague/`senses_stream.py`: a small state machine over streamed chunks; build test-first in tests/`test_senses_stream.py` with a fixture copied verbatim from the 2026-08-06 probe chunks; no third-party imports
- acceptance:
  - given the live-probed chunk sequence (fence-wrapped envelope, chunk boundaries splitting mid-key) the extractor emits exactly the text-field characters and withholds the closing quote/brace/fence
  - malformed / unfenced / non-JSON input raises a typed extraction error without losing accumulated text; a plain unfenced JSON envelope also extracts

### t2 — Streamed senses completions deliver identical text

- instruction: wire senses `on_delta` through the engine's existing streamed path (engines/`vllm_openai.py` `_make_complete` streams iff config.`on_delta` armed); feed deltas through the t1 extractor; clear inherited `on_delta` in senses.py `senses_engine_config` (replace(..., `on_delta`=None)) unless explicitly armed
- depends on: t1
- covers: c2, h2
- acceptance:
  - a senses direct-answer/talk/speak-back turn run streamed delivers final text identical to the blocking path on the same transcript (test both against a mock SSE server)
  - `senses_engine_config` no longer silently inherits the parent `on_delta` — senses streaming is armed explicitly, only when the session surface wants it; token accounting unchanged (usage verbatim)

### t3 — Conversation-surface incremental rendering above the owned line

- instruction: render via the existing `print_above` delta cursor seam in session.py/`_input_line.py`; reuse `should_repaint_delta` throttling; all terminal writes stay on the main thread through the owned-line seam; per the fake-streams lesson test on a real os.pipe/PTY, never StringIO
- depends on: t2
- covers: c4, h3, h12
- acceptance:
  - on a real PTY a senses reply produces >= 2 paints of a growing senses: line above the owned input line; the cockpit DeltaTail status behavior is unchanged
  - a piped / --json session stays byte-identical to baseline (golden test)

### t4 — Session cortex turns run streamed (per-read timeout reset)

- instruction: extend `_arm_delta_stream` / `wants_delta_stream` in cli/`_commands`/work.py + the session sink so session cortex turns arm `on_delta`; no new flags; usage stays verbatim from the final `include_usage` chunk
- covers: c19, h16
- acceptance:
  - a mocked slow stream whose total generation exceeds the request timeout completes when streamed (per-read timeout resets); blocking baseline still times out
  - TaskResult shape and usage identical streamed vs blocking (extend the existing equivalence test); bare non-TTY work output unchanged

### t5 — Streaming containment: partial render + marker, reply never lost

- instruction: catch at the turn seam in session.py; reuse the stream accumulator's `finish_reason` completeness signal; marker line style matches existing error: lines
- depends on: t3
- covers: c25, h20
- acceptance:
  - a test kills the mock stream mid-reply: the partial text renders with a legible marker line, the session continues to the next prompt, no traceback escapes
  - a typed extraction error degrades that turn to the whole-reply blocking render — the reply text is never lost

### t6 — Cortex narration: senses-authored higher-self lines at boundaries

- instruction: add a narration move to `senses_moves.py` fed by a windowed cortex-delta buffer captured in the `on_delta` callback (buffering there is fine — never a completion); render through the same feed-line surface as presence lines; label verbatim '<<higher self thought>>'
- depends on: t3, t4, t5
- covers: c12, c14, c23, h9, h11, h19
- acceptance:
  - during a mocked cortex run, '<<higher self thought>>' senses-authored lines appear at tool-call/phase boundaries ONLY — a test asserts no senses completion is issued between boundaries
  - a narrated run's artifact and every model-bound messages array contain zero narration lines (the h11 test); narration input is windowed against senses' own budget; senses unarmed renders byte-identical

### t7 — Worker narration: subconscious lines in three-tier mode

- instruction: FIRST read the three-tier relay internals and record the wiring point (risk r2); then reuse t6's narration move with the worker label; keep the authority boundary — narration never becomes a routing or authority change
- depends on: t6
- covers: c13, h10
- acceptance:
  - in a mocked three-tier session, worker steps yield '<subconscious thought/actions>' senses-described lines; with `three_tier` unconfigured the session renders byte-identical (golden test)
  - the actual relay wiring point (lattice content lane / flight seat) is verified and named in the PR description before code lands — the challenge pass did not read it

### t8 — Speak-only lane: /speak toggle + voice-session-free playback

- instruction: split the half-duplex-gate concern out of `play_wav_bytes`: a session-free playback function for speak-only; gate `_speak_reply` on (voice session present) OR (speak-only on); speak the RENDERED reply text after the turn completes — replies-only per risk r1 unless the user resolves q4 to narration-aloud
- depends on: t6
- covers: c6, c7, c21, c22, h4, h5, h17, h18
- acceptance:
  - a /speak toggle and --speak flag exist, default OFF; a test asserts no config default, profile, or mode flips speak-only on (h18)
  - with speak-only on and /voice off: zero voice-session objects constructed, zero stt calls, exactly one synthesize+playback per senses reply (call-count test); only --voice or /voice can construct a voice session (h5)
  - playback takes no voice session; a synth or playback failure leaves the rendered text byte-identical; typing stays live during playback on a real PTY

### t9 — Same-role stale-pin refresh at resolution + call time

- instruction: implement at resolution time in the config/lobes layer plus a once-only call-time 404 catch in engines/`vllm_openai.py` performing the same refresh; source attribution reuses the flag > env > config.json > discovery precedence to name which layer pinned the stale id
- covers: c10, c11, h7, h8
- acceptance:
  - pinned id absent from /v1/models (or a call-time 404 `model_not_found`) with lobes armed: the run proceeds on the SAME role's discovered id and the warning names the stale id, its source layer, and the refreshed id
  - with lobes unarmed, or the role advertising no model, the original error surfaces unchanged; a valid pin resolves byte-identically
  - the refresh never crosses roles and never reads task content — a test enumerates the resolution inputs as exactly flag/env/config.json/role-discovery (h7)

### t10 — Doctor model-membership preflight

- instruction: add the check to the oilcheck provider/usage group mirroring `three_tier.py`'s model-id match; unit tests with fake /v1/models payloads (present, absent, endpoint missing, 401)
- covers: c8, h6
- acceptance:
  - doctor warns when the configured main model is not in the provider /v1/models list, naming the pinning source; a provider without /v1/models or unreachable yields skip/info, never a hard failure (h6)
  - the check follows the oilcheck/`three_tier.py` membership-check pattern and respects the doctor --probe network gating

### t11 — Refresh warning rides the run artifact

- instruction: surface via WorkStats/warnings on TaskResult into artifact.py; test with a tmp-repo background run against a mocked provider (tmp-repo git tests need cwd-scoped identity)
- depends on: t9
- covers: c26, h21
- acceptance:
  - a background/one-shot run with a stale pin writes an artifact whose warnings name the stale id, source, and refreshed id — greppable with no TTY (h21)
  - the artifact schema change is additive: pre-existing artifacts still load without error

### t12 — Live rig proof: the transcript scenario end-to-end

- instruction: extend the livecheck proof-runners (or a scripts/ proof) reusing the transcript's exact prompts; record paint counts, exit codes, and call counts — not absolute seconds; a degraded lane is recorded as SKIP/degrade, never faked PASS
- depends on: t7, t8, t11
- covers: c1, c16, c17, c18, h1, h13, h14, h15
- acceptance:
  - a scripted PTY session against the live rig replays the 2026-08-06 transcript scenario: the senses reply shows >= 2 incremental paints; a stale-pin run (bogus pinned id, lobes armed) exits 0 with the recorded refresh warning; a speak-only run yields exactly 1 TTS playback and 0 stt calls
  - tests/`test_boundary.py` stays green (h1: no new daemon/socket/thread outside the sanctioned list); recorded numbers are rig-relative (h15); with senses unarmed the session degrades to today's behavior and the proof records the degrade honestly (h13)

### t13 — Feature doc, CLAUDE.md bullet, version bump

- instruction: follow the bullet + pointer-doc pattern; update the senses-live-presence / realtime-speech bullets where the speak lane touches them; name the q4 resolution (replies-only default) explicitly
- depends on: t12
- covers: c15
- acceptance:
  - docs/features/ gains the arc's doc (streaming, narration labels, speak-only default-off, stale-pin refresh, honest limits incl. the off-TTY h12 invariant) linked from a new CLAUDE.md architecture bullet per the trim discipline
  - the version is bumped with a CHANGELOG entry so the version-check CI job passes

## Risks

- [unknown_nonblocking] q4 is open: speak-only is built replies-only by default; the user may resolve it to also speak narration lines — t8's gating is written so the change is a one-line scope widen (task t8)
- [unknown_nonblocking] three-tier relay internals (lattice content lane, flight seat) were not read during the challenge pass — t7 verifies the wiring point first; a mismatch becomes a /deviate, not silent drift (task t7)
- [unknown_nonblocking] proxied senses TTFT measured 5.31s via the orin hop — streaming shows life immediately but first-paint latency is rig-bound, not colleague-fixable
- [unknown_nonblocking] real-PTY paint assertions can flake in CI (gates-flake precedent #239) — t3/t8 tests may need bounded retries or CI-skip discipline with the live proof as the backstop (task t3)

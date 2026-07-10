# Build Plan — Colleague now feels alive while it works: model output streams in token-by-token instead of arriving in silent blocks, the interactive session shows live state and reactivity so you feel the agent working, a first-class coherence command measures the coherence of colleague's own work via coherence-cli, and CLAUDE.md shrank from a wall of history to a readable brief.

slug: `colleague-now-feels-alive-while-it-works-model-out` · status: `exported` · from frame: `colleague-now-feels-alive-while-it-works-model-out`

> Colleague now feels alive while it works: model output streams in token-by-token instead of arriving in silent blocks, the interactive session shows live state and reactivity so you feel the agent working, a first-class coherence command measures the coherence of colleague's own work via coherence-cli, and CLAUDE.md shrank from a wall of history to a readable brief.

## Tasks

### t1 — Reproduce the before-state live: a timed run on the rig showing full-turn silence between phase notices, wc -c CLAUDE.md (158454), and the absent 'colleague coherence' noun — recorded as the plan's baseline evidence

- instruction: read-only: run one timed 'colleague work' against the rig noting seconds between phase notices; wc -c CLAUDE.md; run 'colleague coherence' expecting unknown-command; write the numbers into a dated baseline section of the plan notes or docs/live-testing.md
- covers: c3, h8
- acceptance:
  - a dated baseline note (docs or plan notes) records the three reproduced frictions with real numbers: seconds of silence on one completion, CLAUDE.md bytes, 'colleague coherence' exiting with unknown-command

### t3 — Runtime token-delta seam + mock stream: extend the runtime completion path (ContextControls / progress-sink family) with an optional on_delta callback engines feed incremental text into; the mock engine emits a synthetic delta stream; no callback armed = exactly today's code path; deltas never reach the flight feed (heartbeat-only, operator decision c18)

- instruction: touch colleague/loop.py (+ContextControls), colleague/engines/mock.py, maybe colleague/contract.py: add an optional on_delta callback threaded config->ContextControls->completion call; mock emits its final content as N synthetic deltas when armed; TDD-pin unarmed byte-identity, delta ordering/concat equality, step_count/events/flight invariance; keep tests/test_boundary.py + test_zero_deps.py green
- covers: c12, h1, h11, c6
- acceptance:
  - with no delta sink armed, TaskResult.to_dict on mock is byte-identical to pre-change for the same task (test-pinned)
  - with a delta sink armed on mock, the sink receives ordered deltas whose concatenation equals the final message content, and TaskResult.to_dict is STILL identical to the unstreamed run
  - a delta never advances step_count and never lands in the events sink or the flight feed (test-pinned); boundary + zero-deps tests stay green

### t4 — vLLM SSE streaming: when (and only when) a delta sink is armed, the vLLM engine requests stream:true + stream_options include_usage and parses the SSE chunk stream incrementally over stdlib urllib, feeding deltas to the t3 seam; usage stays verbatim-from-server or honestly absent

- instruction: touch colleague/engines/vllm_openai.py + colleague/config.py only: when controls carry an armed delta sink, POST with stream:true + stream_options{include_usage:true}, iterate response lines (SSE 'data:' frames) over stdlib urllib, accumulate content/reasoning/tool_calls deltas into the same ModelResponse shape; build a fake SSE HTTP server fixture in tests; never send stream when unarmed
- depends on: t3
- covers: c12, h12, c7
- acceptance:
  - a fake-SSE-server test proves incremental parsing: deltas arrive before the stream closes and the assembled ModelResponse (content, reasoning, tool calls, usage) equals the blocking-path equivalent
  - with no delta sink armed the wire request carries NO stream field (byte-identical request, test-pinned)
  - tool-call chunks accumulate correctly across SSE deltas (the OpenAI incremental tool_calls shape); usage tokens come verbatim from the final usage chunk or are honestly absent — never estimated

### t5 — Streaming degradation: a mid-stream disconnect, malformed SSE, or a server refusing stream:true routes through classify_degradable and falls back to the blocking completion within the same turn's bounded retries; backpressure latency measurement and /tokenize counting keep working under streaming

- instruction: touch colleague/context.py (classify_degradable) + the vLLM stream reader: wrap stream consumption so IncompleteRead/socket error/malformed SSE raises a degradable classification; the same turn retries blocking (no stream field); a 400 mentioning stream retries blocking immediately; keep _timed_complete latency = full-turn wall clock
- depends on: t4
- covers: c16, h5
- acceptance:
  - a test that kills the fake SSE stream mid-turn sees the turn complete via the blocking fallback and the run end with an honest TaskResult
  - a server that 400s on stream:true is retried without streaming in the same turn and the failure is never surfaced as a run error
  - per-turn latency recorded by backpressure under streaming measures full-turn wall clock (same semantics as today, test-pinned)

### t6 — Cockpit live tail: both live sinks (session _WorkSink + work --tui CockpitProgressSink) render armed deltas as a throttled live-updating tail on the cockpit STATUS surface (the fold_phase pattern), replacing the static 'thinking…' notice with visible generation while a completion runs; off-colour-TTY / piped / --json / --no-tui sessions never arm the sink

- instruction: touch colleague/cli/_commands/_tui_sink.py + session.py (+cockpit_run.py if needed): arm the delta sink only on the colour-TTY live-cockpit paths; fold the accumulated tail (last ~80 chars) onto state.status.message like fold_phase; throttle repaints to ~4/s by delta count or chunk size (no clock thread); clear on turn end; pin off-TTY byte-identity
- depends on: t3
- covers: c13, h2, c2, h7
- acceptance:
  - on a colour TTY the STATUS line visibly updates with the generation tail while a (mock synthetic) completion streams, and clears to the normal status on turn end
  - off-TTY / piped / --json surfaces are byte-identical with streaming enabled (test-pinned): the sink is never armed there
  - redraws are throttled (a bounded repaint rate, no per-token full-screen repaint) and no colleague-side fork of an agentfront renderer appears — a genuine renderer gap becomes a filed agentfront issue linked from the PR

### t7 — The 'colleague coherence' CLI noun: new colleague/cli/_commands/coherence.py with register_into(app) (verbs: score PATH.../show TASK-ID/overview, --json everywhere), reusing colleague/coherence.py's scoring seam + embed_env injection to measure a work item's summary artifact and changed docs on demand; advisory always, never a gate; explain catalog entry added

- instruction: new file colleague/cli/_commands/coherence.py (register_into(app) + register(sub)): verbs score PATH... / show TASK-ID|last / overview; reuse colleague/coherence.py's single-file scoring helper + colleague/lobes.py embed_env; resolve artifacts via colleague/artifact.py find_artifact/read_request; add explain catalog entry; degrade to clean skip when shutil.which('coherence') is None
- covers: c14, h3
- acceptance:
  - 'colleague coherence score <file.md>' returns the scored JSON payload with embedding-frame provenance on a machine with the coherence CLI installed
  - 'colleague coherence show <task-id|last>' scores a finished work item's summary + changed docs from its artifact and renders per-file scores
  - with no coherence CLI installed every verb reports a clean actionable skip (exit 0 on overview, structured error with remediation on score/show) — never a traceback
  - cross-surface parity holds (registry == MCP catalog == learn catalog, existing test) and the noun appears in explain

### t8 — CLAUDE.md cut to a <=25KB brief: each architecture part shrinks to a few-line summary + a pointer to its docs/features/ or docs/specs/ file (creating the missing feature docs); conventions + scope + commands stay authoritative inline; no fact deleted without a surviving pointer; before/after byte+token counts recorded in the PR

- instruction: edit CLAUDE.md only + create missing docs/features/*.md: for each architecture bullet keep 3-6 lines (what it is, the one rule, the pointer); keep conventions/scope/commands sections intact; move deep detail verbatim into the feature doc it points at; run markdownlint + the doc-test-alignment skill; record byte/token counts
- covers: c15, h4, h10, c5
- acceptance:
  - wc -c CLAUDE.md <= 25600 after the cut
  - a doc-test-alignment pass over the reduced CLAUDE.md + new feature docs finds no orphaned fact: every trimmed part's content survives at its named pointer target
  - markdownlint, pytest, and the teken rubric gate stay green; before/after byte and token counts appear in the PR description

### t9 — Live proofs + livecheck: measure time-to-first-visible-delta on the live rig vs the full-turn baseline (docs/live-testing.md rows), prove the dead-server path renders a distinct no-stream state, live-prove 'colleague coherence' against a real finished work item, and verify every announcement thread landed (streamed run, reactive cockpit, coherence verb, brief CLAUDE.md)

- instruction: extend colleague/livecheck.py with a streaming check (classify from evidence, SKIP honestly when rig unreachable); run the live rig proof: first-delta latency vs t1 baseline, dead-server distinct state, 'colleague coherence show last' on a real artifact; append dated rows to docs/live-testing.md
- depends on: t1, t5, t6, t7, t8
- covers: c1, h6, c4, h9, c10, h13, c11, h14
- acceptance:
  - docs/live-testing.md gains dated rows: first-delta latency (target ~1-2s vs full-turn baseline from t1), the coherence verb's live payload, and the CLAUDE.md before/after numbers
  - an unreachable/stalled server yields a visually distinct no-stream state, not silence (proven live or via the fake server)
  - each after-state clause traces to its landed requirement in the PR description; a livecheck classifier SKIPs honestly when the rig is unreachable

## Risks

- [unknown_nonblocking] the live tail may hit a genuine agentfront renderer gap (partial-line repaint); fallback is colleague-side composition on the STATUS surface, upstream issue filed only if needed (the #249 rule) (task t6)
- [unknown_nonblocking] the served rig's vLLM version must support stream_options include_usage and streamed tool_calls; fake-SSE-server tests carry v1 correctness, t9 verifies live and SKIPs honestly if the rig lags (task t9)
- [follow_up] v2 candidates deliberately out of this plan: throttled delta chunks on the flight feed, streaming for senses/deepthink tools-off turns, coherence signal/trend over run history

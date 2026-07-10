# Colleague now feels alive while it works: model output streams in token-by-token instead of arriving in silent blocks, the interactive session shows live state and reactivity so you feel the agent working, a first-class coherence command measures the coherence of colleague's own work via coherence-cli, and CLAUDE.md shrank from a wall of history to a readable brief.

> Colleague now feels alive while it works: model output streams in token-by-token instead of arriving in silent blocks, the interactive session shows live state and reactivity so you feel the agent working, a first-class coherence command measures the coherence of colleague's own work via coherence-cli, and CLAUDE.md shrank from a wall of history to a readable brief.
> instruction: verify by running each thread's live proof after build: a streamed live run, the cockpit reacting, 'colleague coherence' on a real artifact, wc -c CLAUDE.md

## Audience

- the operator driving colleague interactively (session, work, talk) — and secondarily agent callers who read artifacts and docs
  - instruction: pin agent-caller neutrality with byte-identity tests on --json/piped surfaces before touching render paths

## Before → After

- Before: a model turn arrives as one silent block: only phase notices (#206) break minutes of quiet, so a slow completion is indistinguishable from a stall until it ends; CLAUDE.md is a 158KB wall of accreted history that taxes every session's context; coherence exists only as a hidden advisory gate on changed .md files; the cockpit shows steps, never the model actually generating
  - instruction: reproduce each friction live first (timed silent turn, wc -c CLAUDE.md, missing coherence noun) and record it in the plan's task notes
- After: model output streams in token-by-token on the live surfaces, the session cockpit visibly reacts while the model generates, a first-class 'colleague coherence' command measures colleague's own work on demand, and CLAUDE.md is a readable brief that points at docs/features/ for depth
  - instruction: trace each after-state clause to a requirement (c12-c16) in the exported spec; a clause with no requirement is scope creep or a gap

## Why it matters

- delegation trust is felt, not just reported: an operator who sees tokens arriving knows the agent is alive, catches derailment early instead of after a wasted turn, and a lean CLAUDE.md stops taxing ~40K tokens of context from every future session in this repo
  - instruction: count CLAUDE.md tokens (e.g. via the rig /tokenize or a char/4 estimate) before and after; put the numbers in the PR description

## Requirements

- token-streaming: the vLLM engine requests stream:true and consumes the SSE chunk stream via stdlib urllib; a runtime-owned token sink (an extension of the existing #38 progress-sink contract) receives incremental text deltas; the all-engines rule holds — mock emits a synthetic delta stream so the contract is testable without a live server
  - instruction: add stream:true + stream_options include_usage to the vLLM completion path behind a config knob; parse SSE lines incrementally over stdlib urllib; thread a delta callback through ContextControls (runtime-owned, all-engines); give mock a synthetic delta emitter; pin streamed-vs-not TaskResult equality on mock
  - honesty: on mock, the same task run streamed and non-streamed yields an identical TaskResult; under live streaming, usage tokens still come verbatim from the server (stream_options include_usage) or are honestly omitted — never estimated
- live visibility: the session cockpit and work --tui render streamed deltas as they arrive (a live-updating tail line or panel, throttled redraw), replacing the static 'thinking…' phase notice with visible generation; the #206 invariant holds — deltas never advance step_count and never land in the events sink or tui replay
  - instruction: render deltas as a throttled live tail on the cockpit STATUS surface (the fold_phase pattern) in both live sinks (session _WorkSink + CockpitProgressSink); pin off-TTY/--json byte-identity and step_count/events-sink invariance with tests
  - honesty: off-TTY / piped / --json surfaces are byte-identical with streaming enabled (test-pinned), and a delta never advances step_count nor appears in the events sink / tui replay (the #206 invariant, test-pinned)
- coherence command: a new 'colleague coherence' CLI noun (e.g. score/show/overview) shells out to the operator-installed coherence CLI (same allow-list pattern as the #294 gate, embed_env injected) to measure a work item's outputs — its summary/artifact and changed docs — on demand, reusing colleague/coherence.py's scoring seam rather than duplicating it
  - instruction: new colleague/cli/_commands/coherence.py with register_into(app) (verbs: score/show/overview, --json); reuse colleague/coherence.py's scoring seam + embed_env injection; clean actionable skip when the CLI is absent; add an explain catalog entry
  - honesty: with no coherence CLI installed the command reports a clean actionable skip (never a traceback), and every emitted score carries its embedding-frame provenance exactly as the #294 gate records it
- CLAUDE.md reduction: each architecture part shrinks to a few-line summary + a pointer to its existing docs/features/ or docs/specs/ file (creating the feature doc where one is missing); the conventions/scope sections stay authoritative; no fact is deleted without a surviving pointer
  - instruction: cut CLAUDE.md part-by-part to a few-line summary + docs/features//docs/specs/ pointer, creating missing feature docs; run the doc-test-alignment pass; record before/after byte+token counts in the PR description
  - honesty: a doc-alignment pass verifies every fact trimmed from CLAUDE.md survives at the named pointer target; the tests, lint, and teken rubric gates stay green after the cut
- streaming degrades, never breaks: a server without SSE support, a mid-stream disconnect, or a non-TTY consumer falls back to today's blocking completion path with the same TaskResult; backpressure latency measurement and /tokenize counting keep working under streaming
  - instruction: route mid-stream failures through classify_degradable and fall back to the blocking completion within the same turn's bounded retries; add a test that kills the stream mid-turn and asserts an honest completed TaskResult
  - honesty: a mid-stream disconnect or SSE-refusing server degrades to the existing blocking path within the bounded retry budget and the run still completes with an honest TaskResult — proven by a test that kills the stream mid-turn

## Honesty conditions

- each announcement thread lands as a verifiable artifact: streamed tokens on a live run, a visibly reactive cockpit, a working 'colleague coherence' verb, and a brief CLAUDE.md — no thread is quietly dropped
- no interactive gain costs the agent caller anything: --json, piped, and off-TTY output is pinned byte-identical by tests
- the before-state is reproduced live before building (a timed run showing full-turn silence, wc -c CLAUDE.md, the absent coherence noun) — fixes target reproduced frictions, not assumed ones
- every after-state clause maps to at least one requirement claim carrying its own confirmed honesty condition
- the context-tax claim is measured, not asserted: CLAUDE.md token cost is counted before and after the cut and recorded in the PR
- a run that streams and a run that doesn't produce equal TaskResult dicts on mock (test-pinned); no new artifact key appears for display-only behavior
- test_zero_deps.py stays an allow-list of exactly agentfront; if a renderer gap appears it becomes a filed agentfront issue linked from the PR, never a forked renderer module
- time-to-first-visible-output is measured on the live rig and recorded in docs/live-testing.md; an unreachable server yields a distinct 'no stream' state, not an indistinguishable silence
- wc -c CLAUDE.md is at or under the target after the cut; the doc-alignment verification is run and its result recorded; the coherence verb is live-proven against a real finished work item

## Success signals

- watching a live run, the first visible model output lands within ~1-2s of a completion starting instead of after the full turn; a stalled server is visually distinct from a thinking model
  - instruction: log first-delta latency in the livecheck run; assert the no-stream/dead-server path renders a distinct state
- CLAUDE.md drops from 158KB to a brief (target <=25KB) with zero information lost — every trimmed part survives as a docs/features/ or docs/specs/ pointer; 'colleague coherence' returns a scored JSON payload on a real finished work item
  - instruction: run the doc-test-alignment pass over the reduced CLAUDE.md; live-prove the coherence verb; record both in docs/live-testing.md

## Scope / boundaries

- streaming is display-only: TaskResult, the artifact, and every off-TTY/piped/--json surface stay byte-identical — an agent caller sees no change
  - instruction: add a mock-backend test asserting TaskResult.to_dict equality between a streamed and non-streamed identical task
- no new base dependency and no TUI framework: SSE consumption is stdlib urllib line-iteration in the engine; renderer gaps are filed upstream in agentfront (the #249/#285 rule), never forked locally
  - instruction: SSE parsing lives in the engine on stdlib urllib; check test_zero_deps.py green; file an agentfront issue for any renderer gap and link it

## Non-goals

- not a quality score for the run — coherence measurement stays advisory and descriptive; ROI/grading stays with the existing feedback loop; the coherence command never becomes a blocking gate
- not a rewrite of the cockpit and not a multi-model router: the five threads improve the EXISTING surfaces (session, work --tui, talk, docs) within the standing scope lines

## Decisions

- CLAUDE.md target is <=25KB: each architecture part becomes a few lines + a pointer to its feature doc (operator-decided)
- v1 streaming is display-only on live TTY surfaces; the flight feed keeps the #308 heartbeat only — no streamed deltas to the file plane (operator-decided; throttled-chunks-to-flight is a possible v2)

## Open / follow-up

- streaming for senses/deepthink tools-off completions — senses turns are already ~1s; v1 scopes streaming to the cortex main-loop completions where the silence actually hurts

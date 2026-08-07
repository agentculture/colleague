# Delivery Summary — session streaming + speak-only voice + model-pin hygiene

plan: `session-streaming-speak-only-voice-model-pin-hygie` · run: `complete` · date: `2026-08-06`
baseline: `devague summary skeleton`

## Intent

Close the 2026-08-06 live transcript's three failures — senses replies painting
whole, no speak-while-typing lane, and a stale pinned model id killing every
cortex run — by executing the converged 14-task plan: 13 build-wave tasks in
the colleague repo plus t14, the NEBULA RUN co-design arc that field-trials the
new lanes with Colleague as the designer/builder and the operator gating.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Fence-tolerant incremental JSON-envelope extractor
- `t2` — Streamed senses completions deliver identical text
- `t3` — Conversation-surface incremental rendering above the owned line
- `t4` — Session cortex turns run streamed (per-read timeout reset)
- `t5` — Streaming containment: partial render + marker, reply never lost
- `t6` — Cortex narration: senses-authored higher-self lines at boundaries
- `t7` — Worker narration: subconscious lines in three-tier mode
- `t8` — Speak-only lane: /speak toggle + voice-session-free playback
- `t9` — Same-role stale-pin refresh at resolution + call time
- `t10` — Doctor model-membership preflight
- `t11` — Refresh warning rides the run artifact
- `t12` — Live rig proof: the transcript scenario end-to-end
- `t13` — Feature doc, CLAUDE.md bullet, version bump
- `t14` — t14 — NEBULA RUN: upgraded Colleague co-designs and builds an agent-first game under guidance

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `colleague/senses_stream.py` + 34 tests; colleague's salvaged TDD tests (d3) + integrator implementation + the per-surface field parameter (d4) |
| `t2` | delivered | explicit `on_delta` arming in `senses_engine_config`, `make_senses_display_delta`, streamed≡blocking equivalence tests (sonnet) |
| `t3` | delivered | owned-line transient `senses:` paints, real-PTY proof, off-TTY goldens (fable) |
| `t4` | delivered | every session view tier arms the SSE path; real-socket timeout-reset proof (sonnet) |
| `t5` | delivered | mid-stream cut finalizes partial text + `error:` marker; canned-fallback silent-replacement bug fixed (sonnet) |
| `t6` | delivered | `narrate` move at boundary beats, `<<higher self thought>>` render-only label, h11 machine checks (fable) |
| `t7` | delivered | `<subconscious thought/actions>` label selection at the verified relay seam (park v1 resolved: the on_delta/delta_tail lane, not lattice/flight) (fable) |
| `t8` | delivered | `/speak` + `--speak` (session attribute, default off), `play_wav_bytes_local`, replies-only; front-door speak gap found by t12 proof C and fixed |
| `t9` | delivered | resolution + call-time refresh, `refresh_seat` main-seat gating (d5 fix), Bearer-authed roster fetch (t12-forced fix) (sonnet + integrator) |
| `t10` | delivered | `model_membership` doctor group + probe; colleague-built, integrator fixed the doubled `/v1` path + auth (d2 found the stale builtin default) |
| `t11` | delivered | additive `TaskResult.warnings`, omit-when-empty (integrator corrected 17 byte-identity pins); colleague-built |
| `t12` | delivered | `tools/live_proofs/session_streaming_proof.py`: A PASS (2 paints, exit 0), B refresh-lane PASS / exit-0 DEGRADE (environment: #346, control-proven), C PASS (1 wav, 0 stt) |
| `t13` | delivered | `docs/features/session-streaming-voice.md`, CLAUDE.md bullet, CHANGELOG, v1.55.0 |
| `t14` | delivered | NEBULA RUN playable at `/home/spark/git/nebula-run`: Colleague-authored design (943 lines), build plan (20 tasks), 21 build dispatches (b21 integration added per d7), 163 tests, seed-42 bot run to a real outcome; analysis bundle (`analysis/`: internals study, run ledger, transcripts, artifacts, operator log) |

## Mid-work Decisions

- `d1` — call-time refresh warning labels its source `call-time-404` instead of
  re-deriving the pinning layer — the engine's `complete()` scope has no
  repo/env snapshot; resolution-time attribution is exact (issue #370)
- `d2` — the builtin `_DEFAULT_MODEL` was itself the stale id; refreshed
  in-arc across config, tests, skill help, living docs (issue #371)
- `d3` — t1 reassigned colleague→main agent after a client-side hang past the
  raised timeout; WIP tests salvaged per #222 (issues #372/#373)
- `d4` — senses envelope keys differ per surface (text / answer / bare prose);
  extractor gained a field parameter, surfaces arm their own key (issue #374)
- `d5` — the call-time refresh fired on a muse-discovered deepthink call live
  and crossed roles; `refresh_seat` gates it to the main seat (issue #375)
- `d6` — t14's planning vehicle pivoted from `colleague plan` (claim-parse
  wall on the 35B, no checkpoint on the 27B) to a Colleague-authored
  BUILD-PLAN.md under operator gates (issue #376)
- `d7` — the 20-task build plan had no integration task; the assembled game
  was hollow until b21 wired the trunk (issue #380)
- Not covered by a record: the 27B-vs-35B zero-step collapse A/B (commented on
  #346) rerouted all NEBULA dispatches to the worker model; build-driver
  hardening (SIGTERM ceiling, landed-content check, one retry) evolved
  across three driver generations after live failure modes.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t9` (`d1`) | call-time source labeled `call-time-404`, not the original pinning layer | needs-follow-up |
| `t10` (`d2`) | scope grew: the stale builtin default was the repo-side half of the incident | acceptable |
| `t1` (`d3`) | executor changed colleague→main agent mid-wave after the hang | acceptable |
| `t2` (`d4`) | c2's three streaming surfaces need per-surface envelope keys | acceptable |
| `t9` (`d5`) | refresh crossed roles on a deepthink call live; gated in-arc | risky |
| `t14` (`d6`) | planning vehicle changed; authorship + gates preserved | acceptable |
| `t14` (`d7`) | build plan lacked integration; b21 added | needs-follow-up |

## Evidence

- tests: `uv run pytest -n auto` — **7543 passed, 20 skipped** (colleague repo, HEAD `805e7f1`)
- tests: NEBULA `uv run pytest tests/` — **163 passed** (nebula-run repo)
- live proof: `tools/live_proofs/session_streaming_proof.py` + `scratchpad` reports (A/B/C verdicts above); seed-42 bot run: 751 ticks, 300 points, `outcome: death` (`nebula-run/analysis/agent-run.jsonl`)
- commits: `7c8c4903..805e7f1` (39 commits, 66 files, +9407/−181)
- issues filed this arc: #370 #371 #372 #373 #374 #375 #376 #377 #378 #379 #380
- deviations: `devague deviate --list` — d1–d7 (all `proposed`, awaiting operator confirm)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| senses replies stream into the conversation on a live TTY | high | proof A (2 growing paints) · `tests/test_session_senses_streaming.py` |
| the original stale-pin incident now survives, loudly, source named | high | proof B artifact warning (stale/source/refreshed) · `tests/test_config_model_refresh.py` |
| speak-only speaks replies incl. the front door, mic never armed | high | proof C (1 wav, 0 stt) · `tests/test_session_speak.py` |
| narration renders display-only and never enters model context | high | h11 tests (`tests/test_cortex_narration.py`, `tests/test_worker_narration.py`) — mock-proven; live cadence is senses-chosen (0 lines in the observed story run) |
| off-TTY / `--json` output is byte-identical to v1.54.0 | high | golden tests in `tests/test_session_senses_streaming.py` + contract byte-identity pins |
| NEBULA RUN is a playable agent-first game, Colleague-authored | high | seed-42 pipe run to `outcome: death` · `nebula-run/tests/test_agent_pipes.py` · provenance in `nebula-run/analysis/` |
| the smart bot outperforms the dumb bot | unverified | identical seed-42 outcomes — not claimed; designated #377 benchmark |
| stale-pin refresh exit-0 under live rig on a work item | unverified | environment-blocked by #346 (valid-pin control collapsed identically) |

## Remaining Work / Follow-up

- Operator confirms for deviations d1–d7 (all `proposed`) and open question q4
  (speak narration lines aloud? built replies-only)
- #379 lesson-grade remember-after — specified, first post-merge PR
- #370 call-time source attribution · #376 plan-mode parse on the 35B ·
  #372/#373 stall diagnosis + grading of interrupted runs
- Smart-bot differentiation (the #377 necessity-loop crucible benchmark)
- PR triage after CI: Qodo comments + SonarCloud new/reliability issues

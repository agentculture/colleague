# Delivery Summary — colleague now feels alive while it works

plan: `colleague-now-feels-alive-while-it-works-model-out` · run: `complete` · date: `2026-07-10`
baseline: `devague plan (colleague-now-feels-alive-while-it-works-model-out)`

## Intent

Make delegation trust *felt*, not just reported: model output streams in
token-by-token instead of arriving in silent blocks, the interactive session
shows live state while the model generates, a first-class
`colleague coherence` command measures colleague's own work via coherence-cli,
and CLAUDE.md shrinks from a 158KB wall of history to a readable brief. The run
executed all four dependency waves of the confirmed plan via
`/assign-to-workforce` (mixed workforce: four Claude sonnet subagents, one haiku,
one opus, one colleague work item, integrator merges TDD-gated), landing as
PR [#318](https://github.com/agentculture/colleague/pull/318) (v1.45.0).

## Planned Work

Quoted verbatim (summaries truncated at the clause boundary) from
`devague plan waves --json`; waves were
`[[t1, t3, t7, t8], [t4, t6], [t5], [t9]]` (t2 is a rejected authoring
mis-fire — no such task in the plan):

- `t1` — Reproduce the before-state live: a timed run on the rig showing
  full-turn silence between phase notices, wc -c CLAUDE.md (158454), and the
  absent 'colleague coherence' noun — recorded as the plan's baseline evidence
- `t3` — Runtime token-delta seam + mock stream: extend the runtime completion
  path (ContextControls / progress-sink family) with an optional on_delta
  callback engines feed incremental text into; the mock engine emits a
  synthetic delta stream; no callback armed = exactly today's code path;
  deltas never reach the flight feed (heartbeat-only, operator decision c18)
- `t4` — vLLM SSE streaming: when (and only when) a delta sink is armed, the
  vLLM engine requests stream:true + stream_options include_usage and parses
  the SSE chunk stream incrementally over stdlib urllib, feeding deltas to the
  t3 seam; usage stays verbatim-from-server or honestly absent
- `t5` — Streaming degradation: a mid-stream disconnect, malformed SSE, or a
  server refusing stream:true routes through classify_degradable and falls
  back to the blocking completion within the same turn's bounded retries;
  backpressure latency measurement and /tokenize counting keep working under
  streaming
- `t6` — Cockpit live tail: both live sinks (session _WorkSink + work --tui
  CockpitProgressSink) render armed deltas as a throttled live-updating tail
  on the cockpit STATUS surface (the fold_phase pattern), replacing the static
  'thinking…' notice with visible generation while a completion runs;
  off-colour-TTY / piped / --json / --no-tui sessions never arm the sink
- `t7` — The 'colleague coherence' CLI noun: new
  colleague/cli/_commands/coherence.py with register_into(app) (verbs: score
  PATH.../show TASK-ID/overview, --json everywhere), reusing
  colleague/coherence.py's scoring seam + embed_env injection to measure a
  work item's summary artifact and changed docs on demand; advisory always,
  never a gate; explain catalog entry added
- `t8` — CLAUDE.md cut to a <=25KB brief: each architecture part shrinks to a
  few-line summary + a pointer to its docs/features/ or docs/specs/ file
  (creating the missing feature docs); conventions + scope + commands stay
  authoritative inline; no fact deleted without a surviving pointer;
  before/after byte+token counts recorded in the PR
- `t9` — Live proofs + livecheck: measure time-to-first-visible-delta on the
  live rig vs the full-turn baseline (docs/live-testing.md rows), prove the
  dead-server path renders a distinct no-stream state, live-prove 'colleague
  coherence' against a real finished work item, and verify every announcement
  thread landed

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | Baseline measured live and committed (`3868c38`): 13.62s full turn, 4.43s longest silent gap, CLAUDE.md 158,454 bytes, `coherence` noun absent (exit 1). |
| `t3` | delivered | `EngineConfig.on_delta` seam (mirrors the `progress` field; loop untouched — engines wrap their complete callable) + mock synthetic delta stream; 8 invariant tests (`02017b2`). |
| `t4` | delivered | vLLM SSE consumption over stdlib urllib (`_post_json_stream`/`_iter_sse_frames`), content+reasoning deltas, incremental tool-call/usage assembly, unarmed wire byte-identical; 17 tests (`385129b`). |
| `t5` | delivered | `_stream_or_blocking` fallback: mid-stream drop / malformed frame / missing terminal / stream-refusing 400/422 → ONE blocking retry in the same turn; loop sees one completion per turn; 10 tests (`e07afa1`). |
| `t6` | delivered | Throttled generation tail folded onto STATUS in both live sinks (pure helpers in `cockpit_run.py`); off-TTY byte-identity + #206 invariants pinned; 43 tests (`d83c711` + integration fix `879cda7`). |
| `t7` | delivered | `colleague coherence score/show/overview` (colleague-built work item `44a9865c4be5`, `993c52c`) + integrator fixes for three live-caught bugs (`baaf0b8`) and the rendered `show` signature (`3006337`); live-proven against the rig. |
| `t8` | delivered | CLAUDE.md 158,454 → 25,564 bytes (≤25,600 target; ~39.6K → ~6.4K est. tokens); facts relocated to `docs/features/` (10/10 spot-checks); drift-guard phrase restored at merge (`068c10f` + `02ee57b`). |
| `t9` | delivered | `classify_streaming_check` + gated live proof registered in the livecheck ledger; dead-server distinct state PASSED live; streaming graded honest SKIP (rig-side buffering, below); coherence verb live PASS; ledger rows appended (`3006337`). |

## Mid-work Decisions

- **t3 seam placement**: `on_delta` lives on `EngineConfig` (mirroring
  `progress`) rather than threading through `ContextControls`/the loop — the
  loop only ever sees a completed response, so engines wrap their own complete
  callable. Minimal diff, loop untouched.
- **t4 emits reasoning deltas too** (`delta.reasoning`/`reasoning_content`
  both spellings): the served Qwen spends its silent time in reasoning — the
  exact silence the feature removes.
- **t5 excludes read-timeouts from the stream fallback** (they keep the loop's
  existing `_MAX_TIMEOUT_RETRIES` path) so one turn's worst case stays 2× the
  timeout, not 3×.
- **t6 arms on the pre-existing `cockpit_active` gate**, meaning a bare
  `colleague work` on a real colour TTY (which already auto-activates the
  visual cockpit) also streams — judged more consistent than a second
  divergent gate.
- **Wave-barrier relaxation**: wave 2 (t4/t6) launched once t3 merged rather
  than after ALL of wave 1 — the dependency graph (waves' ground truth) was
  satisfied and the running tasks were file-disjoint; all merges stayed
  TDD-gated.
- **t7 sequenced after t1's rig timing** so the GPU baseline was not skewed by
  a concurrent colleague loop.
- **Terminal-burst SKIP semantics** (t9): the ≥90%-of-turn many-deltas
  signature grades `skipped` (rig-side), not `failed`, mirroring the
  stt/tts-502 voice-lane precedent — colleague-side incrementality stays
  pinned by the fake-SSE-server unit suite.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t9` | "measure time-to-first-visible-delta on the live rig vs the full-turn baseline" could not produce a PASS latency number: the lobes gateway proxy buffers SSE (client-agnostic `curl -N` proof — 21 frames, first=last=3.06s), so the live proof grades an honest SKIP instead of the intended first-delta measurement. Colleague-side incrementality is unit-proven; the same proof turns PASS with zero colleague changes once the gateway streams. | needs-follow-up |
| `t3` | Seam landed on `EngineConfig`, not "ContextControls / progress-sink family" as the task text sketched — same contract (runtime-owned, all-engines, unarmed byte-identical), different carrier, all acceptance criteria met. | acceptable |
| `t9` | `coherence show last` was live-proven against work item `44a9865c4be5` (honest "no changed .md files") rather than a work item carrying scored docs — the artifact-resolution path is what the criterion exercises; per-file scoring was separately live-proven via `coherence score`. | acceptable |

No other task drifted: t1, t4, t5, t6, t7, t8 delivered to their confirmed
acceptance criteria (see Actual Delivery).

## Evidence

- tests: full suite `uv run pytest -n auto` — **6174 passed, 20 skipped, 0 failed** (local, post-final-commit); CI `test` jobs ×2 — pass
- lint: `flake8` / `black --check` / `isort --check-only` / `bandit -c pyproject.toml -r colleague` — all clean; CI `lint` job — pass
- rubric: `uv run teken cli doctor . --strict` — pass (29 checks healthy)
- CI: SonarCloud Code Analysis — pass; GitGuardian — pass; version-check — pass (v1.45.0)
- commits: `159eba5..cbd8bd4` on `spec/feels-alive` (spec `159eba5`, plan `c0ec440`, merges `a9eb441`/`e4fb08b`/`3e3ebf6`/`b1ea1ad`/`47ca1d4`/`467dd9f`/`a328523`, integration fixes `baaf0b8`/`879cda7`/`02ee57b`/`cbd8bd4`, live proofs `3006337`, bump `8478d44`)
- PR: [#318](https://github.com/agentculture/colleague/pull/318) — Qodo review 0 bugs / 0 rule violations / 0 requirement gaps
- live ledger: `docs/live-testing.md` §"2026-07-10 — Feels-alive baseline measurements (t1)" and §"2026-07-10 — Feels-alive arc live proofs (t9)"
- ROI loop: `colleague feedback record 44a9865c4be5 --rating 3` recorded (t7's work item)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| Unarmed runs are byte-identical: no `stream` key on the wire, identical `TaskResult` on mock | high | tests `tests/test_delta_seam.py` + `tests/test_vllm_stream.py` (unarmed pins) — pass in CI |
| An armed sink receives ordered incremental deltas (content + reasoning) whose assembly equals the blocking result | high | `tests/test_vllm_stream.py` (17 tests, fake SSE transport) — pass |
| A broken stream never breaks a run (blocking fallback within the turn) | high | `tests/test_vllm_stream_degradation.py` (10 tests incl. mid-stream kill e2e) — pass |
| Both live cockpits render a throttled generation tail; off-TTY/piped/`--json` never arm | high | `tests/test_cockpit_delta_tail.py` (43 tests incl. arming-site invariants) — pass |
| `colleague coherence` works live against the real rig (score with frame provenance; `show last` resolves a real artifact) | high | live ledger rows (docs/live-testing.md, 2026-07-10) · meaning 0.3705 payload · work item `44a9865c4be5` |
| CLAUDE.md ≤25,600 bytes with no orphaned fact | high | `wc -c` = 25,564 · 10/10 relocation spot-checks (commit `068c10f` body) · drift-guard suite green |
| Dead server yields a distinct no-stream state (legible error, zero deltas) | high | `tests/test_vllm_live_streaming.py::test_live_dead_server_yields_a_distinct_no_stream_state` — PASSED live 2026-07-10 |
| First visible output lands within ~1–2s on the live rig (spec c10) | unverified | gateway buffers SSE (curl-proven rig-side) — honest SKIP; NOT claimed done. Unit-level incrementality is proven; the live number waits on the gateway fix |
| Streaming works under `colleague session`'s real colour TTY end-to-end | medium | unit/integration pins cover both sinks + the mock e2e path; no interactive PTY capture was run (same posture as prior arcs' hands-on lanes) |

## Remaining Work / Follow-up

- **lobes-cli#103 filed** (gateway chat proxy buffers SSE → streaming
  clients get one terminal burst):
  <https://github.com/agentculture/lobes-cli/issues/103>, operator-approved.
  Until fixed, the live streaming UX is a terminal burst and the livecheck
  row SKIPs; the gated proof flips to PASS with no colleague change once the
  gateway forwards frames incrementally.
- **agentfront upstream ask (optional)**: variadic positionals for rendered
  tools — `coherence score` takes one path per call on the rendered surface
  (multi-path works via the legacy parser); noted in-code in
  `colleague/cli/_commands/coherence.py`.
- **Parked v2 items from the spec** (recorded, not regressions): throttled
  delta chunks on the flight feed (operator decision c18 kept v1
  heartbeat-only), streaming for senses/deepthink tools-off turns, coherence
  domains beyond `meaning` + signal/trend over run history.
- **Embedder window**: `coherence meaning score` 400s on files exceeding the
  embedder's 8192-token window (recorded per-file, honest) — chunking is a
  coherence-cli-side follow-up.
- **Human gate 3**: review + merge PR #318 (all CI green; Qodo 0/0/0).

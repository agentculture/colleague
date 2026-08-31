# Delivery Summary — effort-v4-rung-observability-rerank

plan: `effort-v4-rung-observability-rerank` · run: `partial` · date: `2026-08-31`
baseline: `devague summary skeleton`

## Intent

Execute the 11-task / 5-wave plan converged from the challenged
`effort-v4-rung-observability-rerank` frame: drop the acting/associate/purpose
thinking-effort defaults to the v4 low set (#475), make every run record the
rung it actually ran at (#476) plus the reasoning text itself (a gitignored
sidecar), make `--continue` rung-aware, opt recall into eidetic `--rerank`
behind a version probe (#467), and validate with a live rerun of the preserved
`6daa8d083e7b` brief at `low`. Fan-out per `/assign-to-workforce`: colleague
took t2/t3/t7/t9 + a survey explore + two scoped reviews; Claude subagents took
t1/t4/t5/t6/t8; every merge was TDD-gated.

## Planned Work

Quoted verbatim from the `devague summary` skeleton / `devague plan waves --json`:

- `t1` — v4 effort tables: SEAT_TABLE cortex/worker/evaluator/associate + ROLE_TABLE writer/planner -> low; ASSOCIATE_SEAT_TABLE + PURPOSE_TABLE all low; FALLBACK_EFFORT -> off
- `t2` — FinishRecord gains reasoning_effort (contract only)
- `t3` — reasoning sidecar module: writer with size cap, off-knob, tagged child naming, request timestamp + index
- `t4` — eidetic --rerank opt-in behind a version probe
- `t5` — wire the resolved rung into the loop: populate FinishRecord.reasoning_effort + top-level artifact effort block {seat: rung}
- `t6` — wire the sidecar into the loop with request timestamp/index; children tagged to the operator repo
- `t7` — docs to v4 + narrative fidelity sweep
- `t8` — work --continue re-applies the recorded rung, loudly on mismatch
- `t9` — sidecar stays out of every sharing surface
- `t10` — byte-identical audit: overrides unchanged, adapter diff minimal, full suite
- `t11` — live validation: rerun 6daa8d083e7b at low; close #475/#476/#467

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | merge `10396e7b` — all four tables + FALLBACK_EFFORT to the v4 set across 20 files; precedence tests unchanged; byte-identical fixture suites handled via explicit carve-out assertions |
| `t2` | delivered | merge (colleague `fdf6f524267a`) — `FinishRecord.reasoning_effort` (sentinel `""`), round-trip + old-artifact tests, `docs/contract.md` key mirrored; ratchet baseline fixed post-merge (`c9a5fefe`) |
| `t3` | delivered | merge `5fa4dabe` (colleague `b7623b9588a0`) — new `colleague/reasoninglog.py` + `tests/test_reasoninglog.py`, two new files only |
| `t4` | delivered | merge `48866b96` — version probe (cached, any-failure-withholds), `--rerank` appended only on >= 0.14.0; fake-CLI stubs incl. the flag-rejecting 0.13 case |
| `t5` | delivered | merge `a81c4b05` — rung threaded once via `ContextControls.from_config`; new `colleague/effortrecord.py`; FinishRecord populated; artifact `effort` block; SubResult rung; c29 pair test |
| `t6` | delivered | merge `189f0e3f` — per-turn sidecar records with `request_ts`/`request_index` (one index per parallel batch), children tagged to the operator repo; the h7 reasoning-free-run fix |
| `t7` | delivered | merge `87e0ec8c` (colleague `17c41401f9fe`) + fixup `482b7ec5` — v4 doc table, prose sweep, P0/P1/P2 overlays; P2-0/P3 head-pin fixup was integrator work |
| `t8` | delivered | merge `bd0d7db5` — `recorded_acting_effort` + `reapply_recorded_effort`, explicit `--effort`//`effort` wins on both CLI and session legs, mismatch warning, 19 pins |
| `t9` | delivered | merge `3a1e46d0` (colleague `91055587522e`) — 10 assertion tests over feedback export, git/handoff, and a pinned source-tree grep audit; no source change needed |
| `t10` | delivered | full suite 11,319 green; black/isort/flake8/bandit/teken all pass; adapter diff EMPTY; h10 sweep clean; both colleague reviews triaged — 3 real findings fixed (`c9dae2c9`, `c9e43a18`) |
| `t11` | partial | dispatched twice against the preserved brief at commit `5a721b8f`; both segments externally SIGTERM'd (~2 min each; rig healthy). Completion A/B UNANSWERED; partial evidence recorded as `docs/live-testing.md` row 66 |

## Mid-work Decisions

No `/deviate` records exist (`devague deviate --list`: none); decisions below
are captured directly.

- Branch namespacing: bare `agent/tN` branches survive from earlier workforce
  runs, so this run used `agent/ev4-*` — no old branch touched.
- t6 decided plan risk r1 in-flight (as the plan allowed): chain episodes
  APPEND to one per-task-id sidecar under the same cap.
- t6's h7 hazard fix: a reasoning-free run writes nothing at all (tool-call
  records included) — materializing `.colleague/` mid-run changed
  model-visible `list_dir` output against pinned wire fixtures.
- t5: the batch merge child records no rung (it runs no model) — the honest
  reading, documented in tests; the seat name stays `"main"` per decision c22.
- Integrator fixups beyond task briefs: ratchet baselines via the sanctioned
  `FILE_LENGTH_BASELINE_UPDATE=1` path (t2/t5/t6/t8/t10); P2-0/P3 staged
  overlays + two hardcoded test literals (`482b7ec5`); sidecar clean-parity in
  the 0-byte reap (`c9dae2c9`, review-1 finding); deepthink rung recorded when
  the escalation fired + stale continuation-warning cleared on engine raise
  (`c9e43a18`, review-2 findings).
- t11 was resumed once via `work --continue` after the first SIGTERM (the
  sanctioned resumable-runs practice); after the second SIGTERM no third
  attempt was made — two consecutive external stops were read as intervention,
  not noise.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t11` | both live-rerun segments externally SIGTERM'd; the completion A/B (inside 1800 s, six pins, suite green) is unanswered — partial evidence only (row 66) | needs-follow-up |
| `t5` | the artifact `effort` block covers main/senses/children/scout/distill/deepthink(-when-fired) but NOT the design-site seats (fillline.split / autosplit / subagents.decompose) — no thread-through exists at those call sites; additive, no shape change needed | needs-follow-up |
| `t7` | scope grew beyond the briefed file list to satisfy test-forced pins (P1/P2 overlays; then P2-0/P3 + `test_overlays_p3.py` literals as integrator fixup) | acceptable |

## Evidence

- tests: `uv run pytest -n auto` — **11,319 passed, 51 skipped, 0 failed** (final tree)
- lint: `black --check` / `isort --check-only` / `flake8` / `bandit -c pyproject.toml -r colleague` — all clean; `teken cli doctor . --strict` — PASS
- adapter audit (h11): `git diff main...HEAD -- colleague/engines/` — **empty**
- h10 sweep: no live `medium` default in effort modules/tests/doc (ladder vocabulary + history only)
- commits: `c71e67f4..dca2effc` on `spec/effort-v4-rung-observability-rerank` (28 commits: spec, plan, 11 tasks, fixups, v1.73.0, row 66)
- colleague work items graded via `feedback record`: t2 = 4, t3 = 5, t7 = 4, t9 = 5, survey = 5, review-1 `a5e0789bf3bf` = 5, review-2 `287a01ec6dc9` = 5
- t11 artifacts: `2975aed37fb9` + `14a4df780b45` (continued), in the `rerun-low-arm` worktree's `.colleague/`; ledger: `docs/live-testing.md` row 66
- issues: #475, #476, #467, #474 (index semantics), #399 (h24 context)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| v4 low defaults ship on every acting/associate/purpose table; deepthink/design stay xhigh | high | commit `10396e7b` · `tests/test_effort.py` pins |
| every run's artifact names the rung per seat (FinishRecord + effort block), override included | high | `tests/test_effort_recording.py` · `tests/test_e2e_mock.py` |
| reasoning text is readable post-run from a gitignored, capped, excluded-from-sharing sidecar | high | `colleague/reasoninglog.py` · `tests/test_reasoninglog_wiring.py` · `tests/test_reasoninglog_sharing.py` · live: row 66's segments journaled turns |
| a parallel tool batch shares ONE request timestamp/index; sequential calls get distinct indices | high | `tests/test_reasoninglog_wiring.py` batch pins |
| `--continue` re-applies the recorded rung, loudly on mismatch, explicit flag wins | high | commit `bd0d7db5` · `tests/test_continue_effort_reapply.py` (20 pins) · live: `14a4df780b45.continued_from` |
| recall passes `--rerank` only on eidetic >= 0.14.0; dark on this rig (0.13.0); min_score stays on hybrid `score` | high | commit `48866b96` · fake-CLI stub tests; probed `eidetic --version` = 0.13.0 |
| dropping the acting seat to `low` makes the 6daa8d083e7b task complete inside the stream-lifetime bound | unverified | t11 interrupted — NOT claimed; directional-only: 705 reasoning chars over 6 turns vs 133,637 over 7 at medium (row 66) |

## Remaining Work / Follow-up

- `t11` — finish the low-arm rerun when the rig is free: `work --continue 14a4df780b45` in the `rerun-low-arm` worktree (base `5a721b8f`), then fill row 66's completion cells and post the closure evidence on #475. Blocking for c21/h8's headline claim; everything else in the arc stands without it.
- Effort block coverage for the design-site seats (fillline.split / autosplit / subagents.decompose) — additive follow-up, no shape change (t5 drift).
- Senses/distill sidecar attribution test (review-1 speculative note); batch `request_ts` stamps after the pool join (semantic nuance, documented here).
- Parked from the spec: v1 (sampling compensation — measure in the completed rerun, never blind), v2 (a `reasoning_exhausted_reason`-style warning for the acting seat).
- The rerank live proof waits for a rig eidetic upgrade to >= 0.14.0 (r2; stub-tested only).

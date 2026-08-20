# Delivery Summary — qwen38 pin rollover

plan: `qwen38-pin-rollover` · run: `complete` · date: `2026-08-19`
baseline: `devague summary skeleton`

## Intent

Follow the Spark's cortex rollover (`unsloth/Qwen3.6-27B-NVFP4` →
`unsloth/Qwen3.8-27B-NVFP4`, 1,048,576-token YaRN context, issue #404)
end-to-end in colleague: flip the builtin default pin, retune the rig-sized
knobs, harden bounded completions against reasoning-consumes-`max_tokens`,
sweep the current-state docs/skills, and prove every change against the live
rig — executed as the confirmed 5-task / 4-wave plan
`docs/plans/2026-08-19-qwen38-pin-rollover.md` via `/assign-to-workforce`.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Live pre-flight: re-probe the rig and reproduce the before-state
- `t2` — Flip the default pin + retune the rig-sized knobs in config.py
- `t3` — Harden bounded completions against reasoning-consumes-`max_tokens`
- `t4` — Sweep current-state docs and skills to the new id; document the
  timeout stance and the overlay hazard
- `t5` — Verify the sweep, prove it live, and close the PR loop

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | Evidence-only (no repo edits, by design): authed `/capabilities` probe confirmed cortex `unsloth/Qwen3.8-27B-NVFP4` @ 1048576, ready/tools; before-state reproduced live — the resolution-time refresh warning on the stale `CONVERTIBLE_MODEL` pin, captured verbatim into the PR body. Bonus second reproduction during t5: the installed 1.59.0 CLI's old builtin default hard-404'd with lobes disarmed. |
| `t2` | delivered | Commit `5c78cb0` (merge `33c547f`): `_DEFAULT_MODEL` → `unsloth/Qwen3.8-27B-NVFP4`, `_DEFAULT_CONTEXT_BUDGET` 48000 → 131072, `_DEFAULT_MAX_OUTPUT_CHARS` 25000 → 68000, comments cite the 2026-08-20 probe; default-value assertions updated in 5 test files, zero precedence tests touched. |
| `t3` | delivered | Commit `56cc9b6` (merge `1f1ac93`): `_DISTILL_MAX_TOKENS` 1600 → 4096 + 180s timeout, `DistillCompletion` truncation plumbing + explicit failure reasons on the distill outcome marker; oilcheck `_PROBE_MAX_TOKENS` 128 → 512 in both probes; 12 new tests written failing-first. All caps sized from a live 8-completion measurement matrix (scratchpad `t3-sizing.md`, tables mirrored into code comments). |
| `t4` | delivered | Commit `a02fcf4` (merge `131f630`): id sweep across README, model-selection.md, live-testing.md reference-rig table, stats-and-feedback.md, ask-colleague SKILL.md + wrapper; new `COLLEAGUE_TIMEOUT` (c11) section in graceful-degradation.md; per-model overlay advisory in per-model-configuration.md; two d2 assertion literals updated. |
| `t5` | delivered | Commit `914a015` + PR #406: exclusion grep clean on current-state surfaces, zero hunks under historical paths, full suite 8335 passed / 20 skipped, bare live smoke exit 0 on the new default (27s), 3h07m WebGPU long-context proof at the 131072 default (live-testing.md row 35), v1.60.0 bump + CHANGELOG. |

## Mid-work Decisions

All three deviation records were **approved by the operator on 2026-08-20**
(`devague deviate --confirm d1 d2 d3`); quoted from the store, not
re-litigated:

- `d1` (t3) — probe caps raised 128 → 512 although the 3.8 itself passes at
  128: the live measurement showed the probe's actual three-tier target, the
  35B worker seat, truncating mid-reasoning at 128 with no `tool_calls` — a
  false ACCEPTED-BUT-IGNORED; `tool_calling.py` sends a byte-identical payload
  against `config.model`, which points at the worker in worker-dispatch mode.
- `d2` (t4) — the "zero Python changes" instruction gained a two-file
  carve-out: assertion literals only, in `tests/test_doc_config_drift.py:34`
  and `tests/test_ask_colleague_skill.py:145`, both of which exist to pin
  exactly the doc/skill lines t4 was briefed to change.
- `d3` (t4) — `docs/live-testing.md:146` left untouched although criterion 1
  named it: the line sits inside a dated proof block, so the h3
  never-rewrite-history rule was honored over the plan's line pointer.
- Not covered by any record: the t5 long-context proof needed **one flight
  guidance** (#309) mid-run — "write the files one per step" — to break a
  single-turn mega-composition; recorded in live-testing.md row 35 and graded
  into the run's feedback (rating 4).
- Not covered by any record: worktree branch namespace switched from the
  skill's literal `agent/<task-id>` to `agent/q38-<task-id>` — bare
  `agent/t2`/`agent/t3` branches already existed from an older arc.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t3` (`d1`) | cap raised on the worker seat's measured misreport, not the 3.8's — the criterion's letter scoped re-validation to the 3.8 | acceptable (approved) |
| `t4` (`d2`) | two test-assertion literals edited alongside the briefed doc/skill lines, against the task's "zero Python changes" instruction | acceptable (approved) |
| `t4` (`d3`) | criterion 1's `live-testing.md:~146` pointer misclassified a dated proof row; h3/c4 took precedence | acceptable (approved) |

No other task diverged: t1, t2, t5 delivered to their acceptance criteria as
confirmed (task-by-task accounting above).

## Evidence

- tests: `uv run pytest -n auto -q` on the final tree — **8335 passed,
  20 skipped, 0 failed** (suite also run green before/after every wave merge;
  baseline before wave 2 was 8323 passed)
- lint: `black --check` / `isort --check-only` / `flake8` / `bandit -c
  pyproject.toml -r colleague` / `markdownlint-cli2` — all clean
- commits: `1771cfa..914a015` on `spec/qwen38-pin-rollover` (task commits
  `5c78cb0`, `56cc9b6`, `a02fcf4`; merges `33c547f`, `1f1ac93`, `131f630`)
- PR: #406 · closes issue #404
- live runs: smoke artifact `t5-smoke/.colleague/980efecb6a6b.*.json`
  (`stats.model = unsloth/Qwen3.8-27B-NVFP4`, status ok, 27s); game artifact
  `t5-game/.colleague/512e13920268.*.json` (status ok, 9 turns / 7 steps /
  37,419 bytes / 686,893 reasoning chars, 11,253s) — scratchpad artifacts,
  durable extracts quoted in live-testing.md row 35 and the PR body
- measurements: `t3-sizing.md` tables mirrored into `colleague/distill.py` /
  `colleague/oilcheck/*.py` code comments (committed)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A bare work item resolves the new default and completes against the live rig | high | smoke run exit 0, `stats.model = unsloth/Qwen3.8-27B-NVFP4` · live-testing.md row 35 |
| Resolution precedence is byte-identical | high | zero precedence-test edits in `33c547f`; suite green |
| The reasoning-consumes-`max_tokens` degradation is real and now surfaces loudly instead of silently | high | live repro (cap 400 → `finish_reason=length`, 0 content) · `tests/test_distill.py::TestTruncatedDistillation` |
| The 131072 budget survives a long-context run with streaming and zero overflow churn | high | game run artifact: status ok, no warnings, no incompletion · row 35 |
| Historical artifacts untouched | high | `git diff main...HEAD` — zero hunks under CHANGELOG history, `.devague/` (beyond this arc), `docs/specs/` + `docs/plans/` (beyond this arc), recordings, `.eidetic/` |
| The WGSL/WebGPU game runs at 60fps in a browser | unverified | `node --check` PASS is syntax-only; no browser executed the WebGPU runtime (stated honestly by the run itself) |
| Probe caps at 512 fix the worker-seat false negative | medium | live probe: 35B at 512 → `tool_calls` detected (t3 report); not yet re-proven via a full `doctor --probe` pass on the merged tree |

## Remaining Work / Follow-up

- PR #406 awaits human review/merge (gate 3); Sonar analysis + full CI pending
  at write time — Qodo posted 2 summaries, 0 inline comments so far.
- `d1`–`d3` await `devague deviate --confirm` by the operator.
- Browser-execute the Nebula Drift game to upgrade the 60fps/WebGPU claim from
  `unverified` (nothing in this repo depends on it; it was the load generator).
- Frame follow-up v1 (adaptive prefill — agent-chosen context size) and plan
  risk r1's residue: realistic strive prompts vs the new 4096 cap remain
  unmeasured beyond the t3 matrix.
- The operator shell still exports stale `CONVERTIBLE_MODEL=unsloth/Qwen3.6-27B-NVFP4`
  — harmless (the refresh rung cushions it, and it reproduced the before-state
  for free) but worth cleaning from the environment.

## Post-delivery addendum (2026-08-20, pre-merge)

Claims and remaining work that RESOLVED between delivery and merge — recorded
so the artifact stays honest rather than frozen wrong:

- **"WGSL/WebGPU game runs at 60fps in a browser" (was `unverified`) →
  resolved AGAINST the claim, then repaired.** Browser execution showed the
  run's game logic alive but every draw dead: 6 WebGPU/WGSL bug classes
  across 17 sites, all silent to `node --check` (WebGPU errors are async and
  non-throwing). Fixed operator-side and verified rendering. Full record:
  live-testing.md row 36; follow-ups #407 (incremental authoring lane) and
  #408 (tool-surface audit). The row-35 long-context proof claims (streamed
  completion, zero overflow churn at the 131072 default) stand unaffected.
- **Qodo review closed**: 3 inline findings triaged — 2 PUSHBACK on
  adjudicated spec decisions (c10 budget ratio, c11 timeout stance), 1 FIX
  (real bug: a truncated-but-parseable distill completion could be recorded
  `done`; fixed in `6209806` with a schema-valid regression test). All
  threads replied and resolved; Sonar Quality Gate OK.
- **New defects found by exercising this tree** (filed, out of this PR's
  scope): #409 (a remote-proxied worker read can starve past the timeout
  ladder) and #410 (SIGTERM salvage writes WIP but no artifact from that
  wedged state, blocking `--continue`).
- Deviations `d1`–`d3`: **approved** by the operator pre-merge (2026-08-20).

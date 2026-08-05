# Experiment B — worker promotion gate (pre-registered)

Promotion gate B of the three-tier arc (spec claim c10, operator decision c23,
plan task t14; deviation d1 explains the committed-runner vehicle). Compares
the proposed **worker** seat (`unsloth/Qwen3.6-35B-A3B-NVFP4`) against the
current **acting cortex** (`unsloth/Qwen3.6-27B-NVFP4`) on colleague's real
surface — the full `colleague work` pipeline: structured tool calls through
the served parser, multi-step read/edit/test/finish, gates, artifact.

**Pre-registration.** Protocol + runner + fixture committed BEFORE the first
measured run. Results appended after, unedited. Per decision c23 this gate's
verdict lands BEFORE the delivery summary and the PR.

## Design

- **Arms:** `baseline` (legacy resolution, cortex acts) vs `worker`
  (`COLLEAGUE_THREE_TIER=1`, t8 wiring — the acting dial is the worker's).
  Identical everything else: same tasks, same env knobs
  (`COLLEAGUE_TIMEOUT=300`), same fresh fixture repo per run, serial
  execution on an otherwise idle rig.
- **Fixture:** `tools/experiments/fixture_repo_b/` — a tiny package with one
  deliberate bug (zero-denominator crash vs documented 0.0 sentinel) and a
  failing test. Materialized into a fresh temp git repo per run.
- **Tasks (4, fixed):** fix-divide (make the suite green), add-mean
  (function + tests), rename-acc (cross-file rename), write-usage (doc from
  code). Exact texts in `tools/experiments/experiment_b.py`.
- **Runs:** 4 tasks × 2 arms = 8 live `colleague work` runs.

## Measures (per run, from the artifact + drive branch)

- completion: artifact `status` (`ok` vs incomplete/failed) + exit code;
- tool-protocol failures: run recorded as tool-protocol-broken / zero-step;
- truncation: count of `finish_states` entries with state `truncated` (t1);
- wall seconds, total tokens (prompt+completion, exact from usage);
- drive-branch diffstat (did real edits land);
- **operator-graded quality 0–3 per run** (pre-registered rubric):
  3 = correct AND tested/verifiable (suite green where applicable);
  2 = correct outcome, minor gaps; 1 = partial/wrong-but-related;
  0 = nothing relevant landed. Graded from the drive-branch diffs.

## Pass bars (decision c23 — "performs better")

The worker arm PROMOTES only if, against the baseline arm:

- completion rate (status ok) is **greater or equal**, AND
- summed quality grade is **strictly greater**, AND
- tool-protocol failures are **not more frequent**.

Latency and tokens are observational (a 35B-A3B MoE may cost more per turn;
cost alone does not fail the gate). Truncation feeds risk r1 (max_tokens
tuning) — if the worker arm shows truncated turns, tuning is applied and the
affected runs re-measured ONCE (recorded, not silently).

## Results

*(appended after the run — empty at pre-registration)*

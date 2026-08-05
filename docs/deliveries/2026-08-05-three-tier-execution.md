# Delivery Summary — three-tier execution

plan: `three-tier-execution` · run: `complete` · date: `2026-08-05`
baseline: `devague summary skeleton`

## Intent

Ship the eighth sanctioned increment (#364, design brief #363): an opt-in
three-tier execution mode — the worker drives the bounded tool loop, senses
relays the worker's answer faithfully, cortex configures what the other seats
run under — resolved by role name from the lobes gateway, byte-identical when
unconfigured, executed as a 17-task / 5-wave workforce run on branch
`spec/three-tier-execution` with TDD-gated merges, three pre-registered
promotion gates, and a recorded live three-seat proof. Per operator decision
c23, the live performs-better verdict (experiment B) landed before this
summary and before the PR.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Propagate `finish_reason` end-to-end (unconditional observability)
- `t2` — Structural senses relay fidelity in the existing lane
- `t3` — Worker role resolution, loud refusal, same-origin key hygiene
- `t4` — Typed change lattice + authority ceiling (refuse-whole)
- `t5` — Bounded task-local strategist prompt section via layers
- `t6` — Episode-boundary config lifecycle (synchronous review window)
- `t7` — Append-only config event stream on the artifact
- `t8` — Opt-in worker-as-actor resolution (strategist absent, deepthink absent)
- `t9` — Seat-aware attribution: no cortex label on the worker's work
- `t10` — Doctor three-tier readiness group
- `t11` — Opt-in cortex configurator through the lattice
- `t12` — Re-pin the structural gates: byte-identical, loud refusal, finish-state CI
- `t13` — Experiment A: senses fidelity gate (pre-registered, committed)
- `t14` — Experiment B: worker promotion, live performs-better (c23 gate)
- `t15` — Experiment C: strategist value + off-by-default pin
- `t16` — Docs: eighth increment record + legacy/three-tier distinction
- `t17` — Live three-seat proof + arc wrap

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `ModelResponse.finish_reason`, `colleague/finishstate.py` five-state classifier, always-on `TaskResult.finish_states` (sonnet agent, `122f39e`) |
| `t2` | delivered | Fidelity clauses + verbatim containment + raw-answer fallback + 4 `SensesRecord` counters + the embodiment 6/6 regression (sonnet, `d39472d`); fronts do not wire `worker_answer` yet (in-plan scope note) |
| `t3` | delivered | `worker` optional role in lobes.py, `three_tier` arming, `CliError` refusal on both fronts, same-origin key hygiene (sonnet, `d04b9d4`) |
| `t4` | delivered | `colleague/lattice.py` + 34 tests (colleague backend + integrator tightening `200c032`: distinct forbidden-key refusal, field/target shape strictness) |
| `t5` | delivered | `compose_strategist_section` + threaded kwargs through both composition entry points, 27 tests (sonnet, `34b8a5f`) |
| `t6` | delivered | `colleague/configlifecycle.py`, sanctioned windows in chain.py, loop seam with `end_episode` on every exit path (T1), 41 tests (sonnet, `e0289a0`) |
| `t7` | delivered | `colleague/configevents.py` (baseline-as-event, digest from replay alone, liveness-by-counters), additive `TaskResult.config_events`/`config_digest`, 41 tests (sonnet, `657969e`+`a8a56d2`) |
| `t8` | delivered | Acting dial becomes the worker's when armed; deepthink never constructed in three-tier mode; legacy byte-identical (sonnet, `e5a1d2f`) |
| `t9` | delivered | Seat-aware `attribution.py`/livecheck/presence surfaces; legacy strings pinned byte-identical (colleague backend, honest-incomplete; integrator finished 4 construction-site threadings + 1 defensive getattr, `9af8ff0`) |
| `t10` | delivered | oilcheck three-tier readiness group incl. the id-mismatch loud FAIL, 43 tests (colleague backend, honest-incomplete at 90%; integrator applied the one-line tuple fix colleague itself diagnosed, `5fffa45`) |
| `t11` | delivered | `colleague/configurator.py` (opt-in, off by default) + `run_configurator_window` chain hook; structural pins: no worker-history write path, acting seam never wrapped (sonnet high-effort, `38b8e1c`) |
| `t12` | delivered | `tests/test_three_tier_gates.py` — 12 gate tests, no production code, no regression found against the merged tree (sonnet, `75c9d2d`) |
| `t13` | delivered | Experiment A pre-registered (`6569156`) then run live: **SUPPORTING** — visible 6/6, replacement 0/6, attribution 6/6, fallback floor live-proven (`aa25c58`) |
| `t14` | delivered | Experiment B pre-registered (`306c1e1`) then run live: **PROMOTES** — worker 4/4 ok / quality 12 / 0 protocol failures vs baseline 0/4 (all #346 zero-step collapses); the c23 gate (`9ee7970`) |
| `t15` | delivered | Experiment C pre-registered (`0a67ef9`) then run live: **SUPPORTING** — detection 4/4, false intervention 0/4; proposals refused on entry-origin stamping (content correct); strategist stays off (`7c1d107`) |
| `t16` | delivered | CLAUDE.md eighth-increment record + architecture bullet, `docs/features/three-tier.md` with honest d2/#366 limits, legacy/three-tier paragraphs in cortex-senses/deepthink/senses-live-presence docs (colleague backend, full completion, merge `c7574d8`) |
| `t17` | delivered | Live three-seat proof recorded in `docs/live-testing.md` (`a7dff5a`): worker acted (CLI, artifact-proven), senses fallback floor live, cortex `worker.tools` narrowing proposed→verified→applied at the between-episodes window (module level per d3), byte-identical gates re-run 12/12 |

## Mid-work Decisions

- `d1` — experiments A/B/C cannot literally run "through the experiment noun"
  (`colleague/experiment.py` is the sloth training-run launcher, not a generic
  experiment surface) — the gates shipped as pre-registered protocol docs +
  committed runners under `docs/experiments/` + `tools/experiments/`,
  protocols committed before any measurement, preserving the pre-registration
  property h10/h19 protect.
- `d2` — the change-content consumption lane is not wired in v1: `ChangeUnit`
  carries no free-text content field, so strategist-section proposals are
  opaque markers; applied changes are real at the lifecycle/digest/artifact
  level but content does not reach the next episode's composed prompt or tool
  schema (issue #366).
- `d3` — the work front does not arm the config plane (no lifecycle
  construction, no `run_configurator_window` call in work.py), so the t17
  live proof demonstrates at two stated levels: CLI-level for worker-acts +
  attribution + finish_states + byte-identical; module-level for the
  configurator window through the same sanctioned functions (#366).
- Not covered by a record: the first colleague t4 dispatch 404'd on the stale
  `CONVERTIBLE_MODEL` bashrc default (the exact #363 §7 trap, live) — fixed
  the bashrc default to the served id and removed the stale muse-pinning
  deepthink block from `~/.colleague/config.json`, both matching the
  operator's "trust the actual models served" ruling.
- Not covered by a record: wave-3 tasks t11/t12 launched ahead of the wave
  barrier once their dependencies had all merged (pipeline over barrier —
  the dependency graph, not the wave index, is the constraint).
- Not covered by a record: experiment C's runner needed a serialization fix
  (`ConfiguratorReviewResult` list fields → counts) before its first
  completed measurement; no protocol change, recorded in the results doc.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t13`/`t14`/`t15` (`d1`) | the plan bound the gates to a vehicle that is training-shaped; the pre-registration property, not the vehicle, is the promotion-gate substance | acceptable |
| `t11` (`d2`) | the plan under-specified snapshot-to-surface consumption; wiring it would be unplanned surgery outside any confirmed task's ownership | needs-follow-up |
| `t17` (`d3`) | t11 kept the wiring surface deliberately tiny (chain hooks only); no confirmed task owned work-front arming — same root as d2, recorded separately so h1's live-proof claim is scoped honestly | needs-follow-up |

No other task drifted: t1–t10, t12, t16 delivered to their acceptance criteria
as confirmed (see the task-by-task accounting above; t9/t10's incomplete
colleague runs were finished by the integrator within their briefs, not
re-scoped).

## Evidence

- tests: full suite on the spec branch after the final merge —
  `uv run pytest -n auto -q` → **7161 passed, 20 skipped** (baseline at fan-out:
  6782 passed; +379 net new green tests)
- tests: `tests/test_three_tier_gates.py` re-run at wrap — 12 passed
- lint: black / isort / flake8 / bandit clean per task branch (each agent's
  gate) and enforced across merges by the suite
- commits: `main..spec/three-tier-execution` — 46 commits (task SHAs in the
  Actual Delivery table; version bump `2b74853` = v1.53.0)
- live records: `docs/live-testing.md` (t17 entry), `docs/experiments/`
  (three protocols with committed verdicts)
- PRs / issues: #364 (design), #363 (brief), #365 (run tracker), #366
  (consumption-lane + front-arming follow-up)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| With no three-tier config, behavior and existing artifact fields are byte-identical and the sanctioned new fields are present (c30 scope) | high | test `tests/test_three_tier_gates.py` (12/12) · suite 7161 green |
| The worker seat drives the real tool loop live through the CLI | high | `docs/live-testing.md` t17 entry · artifact acting model `unsloth/Qwen3.6-35B-A3B-NVFP4` |
| Explicit three-tier without a resolvable worker refuses loudly on both fronts | high | `tests/test_config_worker.py` + gate suite refusal tests |
| Senses cannot silently suppress a worker answer: verbatim containment or raw-answer fallback + recorded degradation | high | experiment A (6/6 visible live) · `tests/test_senses_fidelity.py` |
| The worker performs better than the acting cortex on the pre-registered task set (decision c23) | high | `docs/experiments/2026-08-05-experiment-b-worker-promotion.md` (4/4 vs 0/4, quality 12 vs 0) — tiny-fixture caveat recorded |
| Cortex can detect a misconfigured actor and stay silent on a correct one | high | `docs/experiments/2026-08-06-experiment-c-strategist-value.md` (4/4 / 0/4) |
| A cortex-authored change can reach verified+applied at the sanctioned window | medium | t17 live record (module level, one run: `worker.tools` narrowing applied, digest changed) — CLI-front arming pending #366 |
| Cortex-authored knowledge changes verify end-to-end | unverified | experiment C refusals (entry-origin stamping) — not claimed done; #366 |
| Applied configuration alters the next episode's actual prompt/tool surface | unverified | d2 — content lane not wired; not claimed done; #366 |
| The strategist earns a default-on | unverified | pre-declared: stays opt-in + OFF until an end-to-end verified/applied repeat post-#366 |

## Remaining Work / Follow-up

- #366 — wire the change-content consumption lane (bounded `content` field on
  `ChangeUnit`, snapshot→surface handoff at the window) AND the work-front
  arming (lifecycle construction, `run_configurator_window` in the execute
  path, folding lifecycle events onto `TaskResult.config_events`); include
  entry-origin auto-stamping in the configurator (experiment C's refusal
  cause). Owner: next arc re-spec.
- Wire `worker_answer` from the session/resident/talk fronts into the senses
  lane (t2's in-scope note) so the structural containment guards real
  conversations end-to-end.
- Drop the lingering muse advert from the gateway (rig-side; ready:false but
  legacy discovery ignores `ready`) — or add a ready-check to legacy muse
  discovery as a small colleague fix.
- Worker drive-branch hygiene: 3 of 4 experiment-B worker runs committed
  `__pycache__` junk — consider a default ignore in the drive worktree.
- Experiment B's runner token capture read non-existent stats keys — fix if
  tokens become a bar in a future comparison.

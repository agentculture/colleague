# Delivery Summary — measure-effort-spikes-484

plan: `measure-effort-spikes-484` · run: `partial` · date: `2026-09-02`
baseline: `devague summary skeleton`

## Intent

Measure the #484 effort-spike surface merged dark in v1.75.0: a barrier smoke,
then arms A (`low` + feedback, spikes off) / B (barrier pinned `low`) / C
(barrier `medium` from the table) on the row-69 brief preserved verbatim by
issue #481, each a `docs/live-testing.md` row with a miss written as a miss, the
pre-registered C-beats-B rule deciding whether any spike arms by default, and
the disposition posted to #484. Plan
[`docs/plans/2026-09-01-measure-effort-spikes-484.md`](../plans/2026-09-01-measure-effort-spikes-484.md)
from spec
[`docs/specs/2026-09-01-measure-effort-spikes-484.md`](../specs/2026-09-01-measure-effort-spikes-484.md)
(devague `/scope` → `/think` → `/spec-to-plan`; executed sequentially by the
main agent on the rig, not fanned out).

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — t1 barrier smoke on a throwaway repo (DONE: artifact 2db5bb0ae410, row 70)
- `t2` — t2 arm A — low, spikes OFF, `MAX_STEPS` 90, TIMEOUT 600, fresh dispatch from row-69 `task_text`; verify the result branch
- `t3` — t3 arm B — spikes ON, barrier pinned low, gate/fillline pinned low; verify
- `t4` — t4 arm C — spikes ON, barrier medium from the table, gate/fillline pinned low; verify
- `t5` — t5 rows 71-73 in docs/live-testing.md + effort-spikes.md Honest-limits pointer + memory update
- `t6` — t6 patch version bump + PR via cicd (docs-only diff)
- `t7` — t7 #484 disposition comment applying the pre-registered rule

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | row 70: artifact `2db5bb0ae410`, `effort_spikes` `[{barrier.pre_mutation, medium, cortex}]`, barrier Step, no warning — the barrier's first live firing (commit `04a63041`) |
| `t2` | delivered | row 71: artifact `26d71865aeee`, `status: ok`, 77 turns / 3,140 s / 150,284 reasoning chars; branch verified in a fresh worktree — import OK, six pins, 11,226 passed (commit `f0a5a1be`) |
| `t3` | partial | row 72: the barrier NEVER fired — attempt 1 `4f362863a7b5` and the one rerun `d6088d427346` both opened with `run_command`, and `should_fire` latches on the first mutating step. VOID as a barrier arm; the rerun stands as a wire-identical replicate of arm A (39 / 2,877 / 146,083, correct, verified) (commit `b3e02dea`) |
| `t4` | delivered | row 73: attempt 1 `1452182d4e80` shell-first → VOID; relaunch `c46cea837568` killed with its launcher before step 0 (not a model outcome); measured run `7af9b55d66a6` — barrier fired at step 21 after a 20-step survey, 5,661-char plan, `status: ok`, 29 / 4,581 / 341,791, branch verified (commit `6288cab9`) |
| `t5` | delivered | rows 71-73 + `docs/features/effort-spikes.md` Honest-limits pointer (commits `f0a5a1be`..`6288cab9`); memory file updated (outside the repo) |
| `t6` | delivered | v1.75.1 bumped, CHANGELOG entry, `git diff 4405d07b -- colleague/` empty (commit `6b14c244`); PR #488 opened via `devex pr open` |
| `t7` | delivered | #484 comment `5502727884` applying #482's pre-registered wording ("same correctness at materially lower reasoning spend → close #484"); trigger follow-up filed as #487 |

## Mid-work Decisions

No `/deviate` records exist for this plan; every decision below was put to the
operator through the frame's `question` loop and is recorded there.

- `q6`/`c20` — `run_command` is a mutating tool BY NAME, so the barrier fires on the first shell-out; the operator chose "measure as shipped, record the fire position, file a follow-up if it fires at step ≤ 2" over pausing to re-spec the trigger (frame s9, c20).
- arm B attempt 1 stopped cooperatively at step 8 (`flight stop`) the moment its shell-first opening made the barrier unreachable, to spend the h4 rerun immediately instead of an hour on a void run (frame s10).
- arm B's rerun, also shell-first, was allowed to complete rather than stopped: with no spike able to fire and the other two points pinned `low`, its payloads are wire-identical to arm A's, so it was kept as an n=2 replicate (frame s11, delta `b2`).
- arm C attempt 1 stopped the same way at step 9 (frame s12); its relaunch died with the background launcher shell (SIGTERM before step 0, artifact `c46cea837568`) and was relaunched detached via `setsid nohup` — counted as an operational failure, not as a model attempt, so the measured run is still C's single h4 rerun.
- the pre-registered C-vs-B rule could not be applied (B void); the q4 tie-break (equal correctness → lower spend wins) was applied to C vs A instead, and the disposition says so.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t3` | the barrier `low` arm could not be produced: both dispatches opened shell-first and the v0 trigger precondition latched shut; its acceptance criterion ("carries the barrier Step … else VOID + one rerun") ended VOID after the rerun (evidence `e5`, delta `b1`, #487) | needs-follow-up |
| `t4` | one extra dispatch beyond the plan's "VOID + one rerun" — the killed launcher — before the measured run; no model attempt was added | acceptable |
| `c14` (success signal) | "zero arms VOID by barrier degradation after at most 1 rerun" is unmet: arm B is VOID after its rerun (evidence `e6`) — not degradation by timeout (c4's guarded case) but the trigger precondition; recorded as a fail, not reworded | needs-follow-up |

## Evidence

- tests: `tests/test_effortspikes_boundary.py`, `tests/test_offknob_byte_identity.py`, `tests/test_barrier_pre_mutation.py` — 66 passed at `6b14c244`
- tests: `uv run pytest -n auto -q` on result branches `colleague/26d71865aeee-…`, `colleague/d6088d427346-…`, `colleague/7af9b55d66a6-…` (fresh worktrees) — 11,226 passed / 51 skipped each
- checks: `python -c 'import colleague.loop'` + the six pin greps on each result branch — IMPORT OK, pins 1/1/0/0/0/0 (rows 71-73 quote them)
- check: sha256 of each arm artifact's `task_text` == `815f5c3f…1ac9` (row-69 brief) — equal on all three
- check: `git diff 4405d07b -- colleague/` — empty
- lint: `markdownlint-cli2 docs/features/effort-spikes.md docs/live-testing.md` — 0 errors
- commits: `092a77a1..977c71e2` on `measure/effort-spikes-484`
- PRs / issues: PR #488 · #484 (comment `5502727884`) · #487 (filed) · #482 · #480
- devague delivery ledger: obligations `o1`-`o7`, evidence `e1`-`e8` (`e5`, `e6` fail), deltas `b1`-`b2` — all adjudicated by the operator

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| the armed barrier fires live and lands on the artifact as `(point, rung, seat)` with a Step | high | row 70 · artifact `2db5bb0ae410` · `e1` |
| all three measured arms landed a correct branch (import, six pins, green suite) | high | rows 71-73 · `e3` · verify outputs quoted in the rows |
| arm C's barrier fired at the post-survey point (step 21) and produced the seam-naming plan #484 described | high | row 73 · artifact `7af9b55d66a6` trace · `e4` |
| C did not beat A: same correctness at 2.3× the reasoning and 1.5× the wall (n=1 vs n=2) | medium | rows 71-73 figures · `e3`/`e4` — n small, one brief |
| the C-vs-B rule could not be applied; arm B (barrier `low`) is untested, not refuted | high | row 72 · `e5` · `b1` · #487 |
| no code or default changed in this arc | high | `git diff 4405d07b -- colleague/` empty · `e7` · `e8` |
| the #484 disposition names exactly one pre-registered reading (close #484 for #480+#482) | high | issue comment `5502727884` · `e6` (the reading half passes; the zero-VOID half fails) |
| `fillline.decision` and `gate.repeat_failure` behave as specified live | unverified | never fired in any arm (fill-line never crossed; no gate failed) — not claimed |

## Remaining Work / Follow-up

- `t3` — a measurable barrier-`low` arm needs #487 (name-only trigger fix) first; then rerun B (and ideally C) on the same brief and apply the C-vs-B rule as pre-registered.
- PR #488 — await CI + Sonar + review triage, then human merge.
- #484 — the operator decides whether to close it on the disposition; the surface stays merged, opt-in, default OFF either way.
- observability — the reasoning sidecar labels the barrier turn `seat: cortex` with no rung field, and nothing captures the per-turn wire payload; a small follow-up would let a live row prove `medium` reached the server directly.
- rig hygiene — the `sf-arms` worktree keeps five `colleague/*` result branches and the killed run's worktree; reap after review (`colleague clean` would also reap the three result branches, so grade first).

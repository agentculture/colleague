# Delivery Summary — hard 1000-line file limit

plan: `hard-1000-line-file-limit` · run: `complete` · date: `2026-08-31`
baseline: `devague summary skeleton`

## Intent

Port culture-nodes' `tests/lint/filelength_test.go` to pytest as a hard 1000-physical-line
ceiling over tracked source (covering `.py`), and then do the work to make the repo pass
it — emptying the gate's own grandfather list rather than shipping a permanent exception
list. The stated motivation (#399) was that oversized modules blocked delegation to
colleague: a local model exhausts its budget reading them, so every task touching them
routed away.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Land the gate, record the baseline, add the blame-ignore file
- `t2` — Build a read-only pin-audit helper for a module path
- `t3` — Split colleague/explain/catalog.py — the pilot that proves the workflow
- `t4` — Split the five oversized test files other than `test_boundary.py`
- `t5` — Split colleague/tools.py, keeping subprocess in place
- `t6` — Split colleague/senses.py by lane
- `t7` — Split colleague/subagents.py, keeping threading in place
- `t8` — Split livecheck.py, memory.py and handoff.py, keeping subprocess in place
- `t9` — Split colleague/engines/`vllm_openai.py`
- `t10` — Split colleague/resident/appserver.py under a real safety net
- `t11` — Split colleague/`tae_loop.py`
- `t12` — Split tests/`test_boundary.py` last, after the allow-lists have settled
- `t13` — Decompose colleague/contract.py — the star-shaped split
- `t14` — Decompose colleague/config.py — helpers out, then resolve() itself
- `t15` — Decompose colleague/loop.py — leaf types first, then the lanes
- `t16` — Decompose colleague/cli/`_commands`/work.py
- `t17` — Decompose colleague/cli/`_commands`/session.py via mixins
- `t18` — Sweep the live docs so no cited module path is stale
- `t19` — Measure whether the ceiling actually buys delegation
- `t20` — Sequence the arc as thematic PRs and keep the Sonar gate honest
- `t21` — Close the arc: empty the grandfather list and prove behaviour is unchanged

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | gate verified; `.git-blame-ignore-revs` + `docs/arc-hard-1000-line-baseline.md` (10715/51 recorded) |
| `t2` | delivered | `scripts/pin_audit.py`, 224 lines. Authored by colleague; **rejected at the TDD gate on the first attempt** (blind to module-object source reads), re-dispatched, verified |
| `t3` | delivered | `catalog.py` 1507 → 160, five topic siblings, `ENTRIES` intact at 100 keys |
| `t4` | delivered | five test files split; collected count 10756 → 10756, AST-verified byte-identical test bodies |
| `t5` | delivered | `tools.py` 1552 → 943; `tool_schemas.py` 649 |
| `t6` | delivered | `senses.py` 1483 → 943; talk lane **kept in place** by a source-text pin |
| `t7` | delivered | `subagents.py` 1703 → 925; `concurrent.futures` retained in place |
| `t8` | delivered | `livecheck` 1481→775, `memory` 1147→667, `handoff` 1037→923 |
| `t9` | delivered | `vllm_openai.py` 1445 → 620; entry point verified via `colleague backends list` |
| `t10` | delivered | `appserver.py` 1206 → 948, under `colleague/resident/`; `[resident]` extra installed, 30 tests run (not skipped) |
| `t11` | delivered | `tae_loop.py` 1043 → 864; `tae_front.py` 217 |
| `t12` | delivered | `test_boundary.py` 1144 → 920; both frozensets still literal `AnnAssign`s (19 / 5 elements) |
| `t13` | delivered | `contract.py` 2479 → 702, six siblings; import stays cheap (verified) |
| `t14` | delivered | `config.py` 4442 → 880, ten siblings; `resolve()` 680 → 212; 22-case differential proof byte-identical |
| `t15` | delivered | `loop.py` 5392 → 962, 21 siblings; `loop_types.py` a true leaf, no sibling imports `colleague.loop` |
| `t16` | delivered | `work.py` 2854 → 979, seven siblings; `execute_work` decomposed into named steps |
| `t17` | delivered | `session.py` 3979 → 821, ten mixin siblings |
| `t18` | delivered | `scripts/check_doc_paths.py`; 87 doc files scanned, all citations resolve; **12 pre-existing** stale paths fixed |
| `t19` | delivered | measurement run; **result is negative** — see Drift and Delivery Claims |
| `t20` | partial | version bumped to v1.72.0 and Sonar reasoning recorded, but the PR-granularity contract was not met — see `d1` |
| `t21` | delivered | `GRANDFATHERED` empty; 0 files over 1000; ratchet baseline regenerated (4 entries still pinned pre-split sizes) |

## Mid-work Decisions

- `d1` — the arc lands as ONE PR from a single stacked branch instead of the six-to-eight
  thematic PRs `c36` confirmed. Reason, from the record: every split task deletes its own
  entry from the shared `GRANDFATHERED` dict, so each merge depends on the file state of
  the ones before it — measured, reverting the `t5` merge alone conflicts. Operator approved.
- **A design constraint added at gate 2, not in the plan:** every split keeps its
  `subprocess`/`threading` import *and a use of it* in the original module. This turned a
  six-place mirrored allow-list edit into a **zero-place** edit — both lists end the arc
  byte-identical to `main`. No deviation record covers this; it was a tightening, not a
  departure.
- **The plan's success criterion was wrong and was corrected mid-run.** `c27`/`h23` require
  "the full suite still 10715 passed". `tests/test_boundary.py` parametrizes its structural
  scans over every `colleague/**/*.py`, so each new module adds ~7 cases — the count
  necessarily grows (10715 → 11226). Forcing it back would require deleting tests, the exact
  act `h1` forbids. The corrected standard used throughout: **zero failures, skip count
  stays 51, no test deleted or weakened.** The frame amendment recording this (`c38`/`h30`)
  was captured and then **lost** to an operator stash cycle; the exported spec therefore
  still carries the superseded criterion. Recorded here rather than by rewriting the spec,
  which `c14` keeps as append-only history.
- **`scripts/pin_audit.py` was extended twice mid-arc**, both times after it missed a real
  coupling class: module-object source reads (`Path(mod.__file__)`, `inspect.getsource`),
  then alias-form object patches (`monkeypatch.setattr(mod, "name")`) — **444 sites** it had
  been blind to.
- **A structural guard was silently narrowed by the refactor and repaired.** Decomposing
  `session.py` moved two of three `flight.append_guidance` call sites out of it, so a pin
  greping only `session.py` covered less while still passing. The path list now globs the
  `_session_*.py` siblings.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t20` (`d1`) | Every split task deletes its own entry from the shared `GRANDFATHERED` dict, so each merge depends on the file state of the ones before it. Reverting the `t5` merge alone conflicts. Splitting the branch into stacked PRs would not restore revertibility because the coupling is in the content, not the branch shape. Operator approved landing as one PR. | needs-follow-up |
| `t19` | The task delivered its measurement; the **result falsifies the arc's stated rationale**. `c23`/`c26` claim the ceiling buys delegation. It does not: on the identical brief, colleague returned `incomplete` with zero files changed. `h24`'s alternative branch applies — 1000 stands as a reviewability limit, not a delegation one. | needs-follow-up |
| `c27`/`h23` | The plan's success criterion ("still 10715 passed") is unsatisfiable by construction; superseded mid-run by the corrected standard. The amending claims were lost before commit, so the exported spec still states the old criterion. | needs-follow-up |

## Evidence

- tests: full suite `uv run pytest -n auto` — **11226 passed, 51 skipped, 0 failed**
- tests: `tests/test_file_length_limit.py` — 4 passed (all four gate tests)
- tests: `tests/test_boundary.py` + `tests/test_agents_boundary.py` + `tests/test_chain_e2e.py` — allow-lists byte-identical to `main` (19 subprocess / 5 thread entries, diffed)
- lint: `flake8` + `black --check` + `isort --check-only` + `bandit` over `colleague tests` — clean
- lint: `teken cli doctor . --strict` — PASS
- docs: `python3 scripts/check_doc_paths.py` — 87 files, every citation resolves
- measurement: artifact `.colleague/6daa8d083e7b.reduce-colleague-loop-py-from-962-lines.json` — `status: incomplete`, 2851 s, 7 turns, 133,637 reasoning chars, 414 answer chars, 0 files changed
- commits: `1be4cc8..421f3de` (45 commits, 17 TDD-gated merges)
- issues: #474, #475, #476 filed from this run; closes the file-length half of #399, #412, #413, #280

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| No tracked source file exceeds 1000 lines | high | `git ls-files` scan returns 0 over-limit files · test `tests/test_file_length_limit.py::test_tracked_source_files_stay_within_the_hard_line_limit` |
| `GRANDFATHERED` is empty — 21 entries reduced to 0 | high | `tests/test_file_length_limit.py` · test `::test_the_grandfather_list_is_reaped` |
| The gate is CI-enforced with no workflow change | high | `.github/workflows/tests.yml:45` already runs `pytest`; no new job in `1be4cc8..421f3de` |
| Behaviour is unchanged across all 21 splits | high | 11226 passed / **51 skipped** (identical to the recorded pre-split skip count) / 0 failed; no test deleted or weakened |
| The two boundary allow-lists are byte-identical to `main` | high | AST-extracted and diffed against `main`; 19 / 5 entries |
| Re-export alone does not preserve monkeypatching (the `__globals__` hazard) | high | six independent negative controls: `run_hook`, `_build_user_message`, `_reap_flight`, `load_telemetry`, `_work.execute_work`, `_session_mod().run_frontdoor` — each fails the test when defeated |
| Splitting to <1000 lines makes these files delegable to colleague | **unverified — measured FALSE** | arm A returned `incomplete`, 0 files changed. The claim is **not** made. |
| Sonar's quality gate passes on this diff | unverified | not probed — answerable only once a PR opens (risk `r1`) |
| Each PR is independently revertible (`h27`) | **unverified — measured FALSE** | reverting the `t5` merge alone conflicts on `tests/test_file_length_limit.py`. Recorded as `d1`. |

## Remaining Work / Follow-up

- **`t20` / `d1`** — the PR-granularity contract is unmet and unmeetable as built. The design
  that would satisfy it: no task touches `GRANDFATHERED`; all entries drop in one final
  commit. Applies to the next arc of this shape.
- **`t19` / #475** — the effort ladder is the real constraint, not file size. v4 tables
  (cortex/worker/evaluator/associate → `low`, all associate and purpose rows → `low`,
  `FALLBACK_EFFORT` → `off`) are implemented on `effort/less-reasoning-475` and need their
  own version bump and PR. **Validation still owed:** rerun the identical t19 brief at `low`
  against the recorded control (506 s, complete).
- **#476** — a run does not record the rung it ran at. The `medium` figure behind #475 is
  *derived*, not read from the artifact. Land this before the rerun above, or the second
  data point inherits the same weak provenance.
- **#474** — the flight feed cannot express a parallel tool batch; consumers render
  concurrency as sequence.
- **`r1` (Sonar)** — `sonar.qualitygate.wait=true` blocks CI and a move-only diff of
  +31,958/−22,280 reads as new code. If its new-code conditions fire, record the explanation
  rather than merging past it (`h26`).
- **`c27`/`h23`** — the exported spec still states the superseded success criterion. Left as
  written history per `c14`; the correction lives in this artifact.
- **A pre-existing weak test surfaced, not caused, by this arc** — `_DEFAULT_SYSTEM`'s patch
  in `tests/test_knobs_byte_identical.py` is not load-bearing (its defeat probe did not fail).
  Reported as inconclusive by `t15` rather than claimed as a pass.

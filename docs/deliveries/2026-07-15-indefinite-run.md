# Delivery Summary — indefinite-run

plan: `indefinite-run` · run: `complete` · date: `2026-07-15`
baseline: `devague summary skeleton`

## Intent

> colleague work items no longer die at their budgets: when the step budget
> exhausts mid-task, colleague automatically continues from the persisted
> artifact — carrying the prior episode's actual tree state — and when the
> context fills, it compacts with a validated summary that provably preserves
> the goal and the work done so far; a big task keeps going until it is done
> or honestly cannot progress, and the operator can stop it at any moment

Executed as 12 tasks in 6 dependency waves via /assign-to-workforce (Claude
subagents in isolated worktrees; colleague built t8 and ran t12 per the
approved split), TDD-gated merges, PR [#333](https://github.com/agentculture/colleague/pull/333)
(v1.47.0).

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Fill-line re-arm + compaction cap
- `t2` — Deterministic compaction validation + unrepairable-note policy
- `t3` — Chain driver core: continuable exits, no-progress guard, episode cap, knobs
- `t4` — Tree carry: base episode N+1 on episode N's branch tip
- `t5` — Work dispatch chain loop: arming flags, config inheritance, handoff-once
- `t6` — Flight continuity + episode-transition observability
- `t7` — Chain view accounting on the artifact
- `t8` — Chain-aware feedback grading
- `t9` — Session parity + background forwarding
- `t10` — E2E chain proofs + dormancy/boundary guards (tests only)
- `t11` — Docs: the new line, stated honestly
- `t12` — Live dogfood proof: chained review of this arc's own PR

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | fill-line re-arms per crossing; `DEFAULT_COMPACTION_CAP = 4` counted cell; cap recorded on `capacity_warning` (merge `279d2e7`) |
| `t2` | delivered | `validate_compaction` deterministic repair/reject; `(no summary produced)` amnesia path removed; armed rejection → finish-with-handoff (merge into `60add0b` lineage) |
| `t3` | delivered | NEW `colleague/chain.py` (allow-list, verdicts, `ChainState`), `until_done`/`max_episodes` knobs; 51 unit tests |
| `t4` | delivered | `isolation_worktree_add[_outcome]` `base_ref` + degrade-to-HEAD-with-warning; 9 tests incl. raw-SHA pin added post-dogfood |
| `t5` | delivered | `execute_work_chain` loop: handoff-once (ok-finish only), verbatim inheritance, per-episode `ChainView` stamping, intermediate reap |
| `t6` | delivered | between-episode pilot stop (`read_stop`), `episode-transition` markers, `chain:` sink announcements |
| `t7` | delivered | `ChainView` on `TaskResult` (exact per-episode sums, omit-when-None) + `read_chain_view` |
| `t8` | delivered | `grade_chain` lineage traversal (colleague-built; integrator added omit-when-False marker + chain-aware CLI `record`) |
| `t9` | delivered | session arms via the SAME `execute_work_chain` (identity-pinned); background forwarding needed only pinning tests (t5 had built it) |
| `t10` | delivered | `tests/test_chain_e2e.py`: the 3 named proofs + dormancy byte-identity + boundary + all-engines guards; fails-on-main baseline recorded in its docstring |
| `t11` | delivered | `docs/features/indefinite-run.md` + 5 feature docs + CLAUDE.md bullet + CHANGELOG; honest-limits stated |
| `t12` | delivered | attempt 3 PASSED: budget-cut review completed across 2 chained episodes with a delivered verdict (attempts 1–2 were honest negatives that each fixed a real gap; see Drift) |

## Mid-work Decisions

- `d1` — a non-ok episode whose artifact carries
  `capacity_decision.kind == 'finish-with-handoff'` is continuable (reason
  `capacity-handoff`) — the #156-declared handoff restarts the chain from its
  seed; ok-guard and every deliberate halt in c24 stay — live dogfood attempt
  2: a review chain's fill-line FINISH-WITH-HANDOFF classified
  write-no-changes and halted at episode 1 (recorded via /deviate, approved,
  `acceptable`).
- t3 agent: `exit_reason` maps the persisted `not_finished` flag to
  `budget-exhausted` — the #313 soft rule suppresses the incompletion record
  exactly in the headline chaining case (partial-delivery budget exit); a
  literal reading would have made chaining fire only on zero-deliverable runs.
  No deviation record (within-task interpretation, flagged in-run, test-pinned).
- t5 agent: HALTED chains never push/PR and keep every episode branch (a
  capped/no-progress chain PRing partial work would launder #313); read-only
  chains feed `progressed=None` (commits are structurally impossible; the cap
  bounds them). Flagged in-run; the read-only half was later generalized to
  read-only MODES by the t12 live catch below.
- t2 agent: mid-run changed-files evidence reads the live `executor.changed`
  set (the brief's `result.changed_files` is only snapshotted post-loop — the
  letter would have made the check a permanent no-op).
- Integrator (t10's catch): `chain_armed` threaded from `config.until_done` in
  `ContextControls.from_config` — the field existed but nothing set it, so
  decision c23's armed branch was unreachable in any real dispatch.
- Integrator (t12 attempt-1 catch): read-only MODES (`explore`/`review`) get
  read-only chain semantics — `--mode review --until-done` otherwise halted
  `no-progress` after episode 1.
- Ambient-vs-armed split: fill-line re-arm (t1) and compaction validation (t2)
  ship default-ON (loop improvements); only episode chaining is flag-gated.
  Documented in `docs/features/indefinite-run.md`; the h1 dormancy test pins
  the chaining half.
- Review triage: 2 Qodo findings fixed (no-op chain finalize; flight
  `ValueError` leak), 3 SonarCloud findings fixed (S107 via
  `DisplayOptions.sink`; 2× S3776 via extractions); colleague's dogfood
  verdict adopted 1 of 3 findings (raw-SHA base_ref test), 2 were by-design
  (empty-reason fallthrough is conservatively non-continuable; unsafe-id
  swallow is the pinned best-effort contract).

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t3` (`d1`) | live dogfood attempt 2: a review chain's fill-line FINISH-WITH-HANDOFF classified write-no-changes and halted at episode 1 — c24's allow-list letter contradicts c23's restart-from-seed intent for exactly the declared-handoff shape | acceptable |
| `t12` | passed on attempt 3, not attempt 1: attempt 1 exposed the read-only-mode gap (halted `no-progress`), attempt 2 exposed the d1 conflict (halted `non-continuable`) — each honest negative became a fix + regression pin before the pass | acceptable |

No other task drifted: t1–t11 delivered against their confirmed acceptance
criteria (the task-by-task accounting above), with in-task interpretations
flagged in Mid-work Decisions rather than silently normalized.

## Evidence

- tests: full suite `uv run pytest -n auto` — **6466 passed, 20 skipped, 0 failed** (skips are pre-existing live-rig/extras gates)
- tests: the three named proofs `tests/test_chain_e2e.py::test_chain_completes` / `::test_chain_halts_honestly` / `::test_compaction_validated` — pass; each fails on main `f94063f` (commands + failure modes recorded in the module docstring)
- lint: `black --check` / `isort --check-only` / `flake8` / `bandit` — clean; markdownlint — 0 errors on all touched docs
- SonarCloud: Quality Gate **OK, 0 open issues, 0 hotspots** (after 3 findings fixed); Qodo: 0 bugs open, 2 inline threads fixed + resolved
- commits: `b25b538..2b7fe9e` (35 commits on `spec/indefinite-run`)
- PR: [#333](https://github.com/agentculture/colleague/pull/333) · issues filed: [#334](https://github.com/agentculture/colleague/issues/334), [#335](https://github.com/agentculture/colleague/issues/335), [#336](https://github.com/agentculture/colleague/issues/336)
- live proof artifacts: dogfood chain `fe829ff8984e` → `06b892d655ad` (2 episodes, `status: ok`, `chain.total_tokens: 1085494` exact-summed, lineage on `continued_from`); chain-graded via one `feedback record last` (both episodes stamped)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| an armed run chains bounded episodes automatically and lands the deliverable | high | live chain `fe829ff8984e`→`06b892d655ad` (ok after 2 episodes) · test `test_chain_e2e.py::test_chain_completes` |
| a chain that cannot progress halts honestly with a non-ok reason | high | test `test_chain_e2e.py::test_chain_halts_honestly` · dogfood attempt 1 (halted `no-progress`, exit 2) |
| an empty compaction summary never silently replaces history | high | test `test_chain_e2e.py::test_compaction_validated` · live attempt 2 (fill-line handoff taken instead) |
| episode N+1 sees episode N's committed tree | high | `tests/test_worktrees.py::TestIsolationBaseRef` (incl. raw-SHA pin) |
| unarmed runs are byte-identical | high | `test_chain_e2e.py::test_dormant_bare_work_artifact_is_byte_identical` + full suite green |
| a chain is stoppable between episodes via the flight plane | high | `tests/test_work_chain.py::TestChainFlightContinuity` (boundary stop test) |
| one `feedback record` grades every episode of a chain | high | live grade of both dogfood episodes · `tests/test_feedback_cli.py::test_record_chain_tail_grades_every_episode` |
| chaining reduces operator babysitting on the live rig at scale | medium | one live chain (review, 2 episodes) — broader task shapes unproven; per c18/h17 this is the honest current extent |
| a multi-compaction long WRITE run on the live rig | unverified | not exercised live in this run — mock-only coverage (`test_fillline.py`); not claimed done |

## Remaining Work / Follow-up

- [#334](https://github.com/agentculture/colleague/issues/334) — promote `DEFAULT_COMPACTION_CAP` to an operator config knob (module constant today).
- [#335](https://github.com/agentculture/colleague/issues/335) — defer per-episode gates (lint/affected-tests/test-integrity) to the final episode.
- [#336](https://github.com/agentculture/colleague/issues/336) — session `run_session` doesn't mark `--max-steps` in `explicit_knobs` (t9 discovery).
- Live coverage gap: a long armed WRITE chain (multi-compaction, tree carry
  under real edits) on the rig — the dogfood exercised the read-only shape;
  run one after merge.
- Crawl risk under explicit `--max-episodes 0` and per-episode memory
  work-lesson churn: accepted residuals, documented in
  `docs/features/indefinite-run.md` (frame parks v3, s21).
- PR #333 awaits the human merge (gate 3).

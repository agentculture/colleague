# Delivery Summary — indefinite-run follow-ups wrap-up

plan: `indefinite-run-follow-ups-wrap-up` · run: `complete` · date: `2026-07-16`
baseline: `devague summary skeleton`

## Intent

Close the three follow-up issues filed from the indefinite-run arc (PR #333):
\#336 (a session-passed `--max-steps` silently refilled by the mode profile),
\#335 (chain-armed runs re-running the pre-finish gates every episode), and
\#334 (the compaction cap locked as a module constant). One PR, one minor
version bump, executed as a 7-task devague plan fanned out by
/assign-to-workforce (waves `[t1,t2] → t3 → t5 → t6 → t4 → t7`), with the
docs task built by the colleague backend. The whole run operated under the
operator's standing full-flow instruction — claim confirmations and the
split-plan (gate 2) approval were made by the agent under that authorization
and are disclosed here.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — t336: run_session marks --max-steps in explicit_knobs
- `t2` — t334a: COLLEAGUE_COMPACTION_CAP config resolution
- `t3` — t334b: loop consumes the resolved compaction cap
- `t4` — t-docs: flip the honest gaps in docs
- `t5` — t335a: chain-episode plumbing (chain_episode + prior_changed)
- `t6` — t335b: gate-skip guard + final-episode union gate set
- `t7` — t-wrap: version bump, chained-count proof, PR

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `run_session` marks `explicit_knobs` after `EngineConfig.resolve` (session.py ~3024, the cmd_work mirror); e2e flipped from the `COLLEAGUE_MAX_STEPS` env workaround to the flag; new red-on-main unit test (merge `f098d28`) |
| `t2` | delivered | `compaction_cap` field + resolve leg (env > config.json > `fillline.DEFAULT_COMPACTION_CAP`), in `to_dict`/`config show`; 10 precedence tests; fillline.py untouched (merge `e333881`) |
| `t3` | delivered | both loop read sites consume the resolved cap via `ContextControls` threading; cap=2 suppression + cap=0 unlimited tests; byte-identical unset (merge `a833219`) |
| `t4` | delivered | both docs flipped by the colleague backend (branch `colleague/54a6c63f7dc3-…`), stale-phrase grep count 0, markdownlint clean, honest limits recorded incl. the halted-chain and ok-handoff corners (merge `98a279a`) |
| `t5` | delivered | `ChainEpisodeOptions.prior_changed` + dispatch-keyed `chain_episode` marker on runtime-only `EngineConfig` fields, stamped unconditionally per dispatch and reset in `run_subagent` (the c22 guard); 10 new tests (merge `2ef72ab`) |
| `t6` | delivered | `_gates_deferred_to_chain` (imports `chain.declared_capacity_handoff`; `aborted` arm guards the pre-try `outcome=_EXIT_BUDGET` trap) + `_gate_changed_set` union helper applied at all seven gate read sites; 36 tests incl. 20-param predicate matrix, chain-equivalence pin, artifact-level 2-episode e2e (merge `850a9cc`) |
| `t7` | delivered | version 1.48.0 + CHANGELOG; PR #338 with `Closes #334/#335/#336`, the operator-verifiable paragraph, and test names cited (commit `261e711`) |

## Mid-work Decisions

- `t5` threading path: the chain-episode marker rides two runtime-only
  `EngineConfig` fields (`compare=False, repr=False`, the `role`/`memory_root`
  precedent) because `EngineConfig` is the only channel from `execute_work`
  into `ContextControls.from_config`; stamped unconditionally on every
  dispatch so a session's reused config object never leaks a stale marker, and
  explicitly reset in `run_subagent` so children never inherit it. The brief
  left the path open and demanded honesty about the inheritance hazard.
- `t6` implemented the brief's predicate verbatim and flagged (not "fixed")
  the narrow corner it leaves: an episode that declares finish-with-handoff
  and then finishes clean halts the chain ok with that episode's gates
  skipped. Recorded as an honest limit in `docs/features/indefinite-run.md`.
- Split-plan model-column edits at gate 2: `t6 → fable` (highest-correctness
  loop.py surgery), `t4 → colleague` (verifiable doc edits; the operator asked
  for colleague involvement), `t7 → main agent`; `t1/t2/t3/t5 → sonnet`.
- The pre-PR colleague review was attempted twice (30 then 60 steps, second
  try single-focus) and both runs budget-exhausted honestly (#313
  `INCOMPLETE`) — the 27B thrashes re-reading the 4,300-line `loop.py`
  without synthesizing. Not retried further; verification carried by the
  owner's eyes-on pass of the predicate + t6's test matrix + the full suite.
  Both work items graded 2/5 in the feedback store.
- The in-repo eidetic store is dirtied by every `/recall` (passive
  reinforcement bookkeeping) — committed twice in-branch so colleague's
  dirty-tree guard (#149) could dispatch.

## Drift From Plan

No drift: all seven tasks delivered against their verbatim acceptance
criteria (see the task-by-task accounting above); no `/deviate` records exist
for this plan (`devague deviate --list` — "no deviations recorded yet"). The
two plan risks recorded at planning time (`r1` renamed-file union gap, `r2`
loop.py same-file serialization) were managed as designed — `r2` by the
sequential wave order, `r1` recorded as an honest limit.

## Evidence

- tests: full suite `uv run pytest -n auto` — **6,524 passed, 20 skipped**
  (skips = gated live-vLLM proofs)
- tests: `tests/test_gate_deferral.py` (36 new, incl.
  `test_chained_e2e_mid_episode_defers_gates_final_episode_reports`,
  `test_loop_skip_equivalent_to_chain_continue`,
  `test_subagent_shaped_until_done_run_gates_on_budget`) — pass
- tests: `tests/test_session_chain.py::test_max_steps_flag_survives_the_work_mode_profile`
  (red on main: profile refilled 40 over an explicit 5) — pass post-fix
- tests: 10 × `compaction_cap` precedence tests in `tests/test_chain.py`;
  `tests/test_fillline.py::test_resolved_compaction_cap_suppresses_at_configured_value`,
  `::test_compaction_cap_zero_is_unlimited` — pass
- lint/gates: `black`/`isort`/`flake8`/`bandit` clean; `teken cli doctor .
  --strict` PASS; `markdownlint-cli2` clean on touched docs
- CI on PR #338: test / test-publish / lint / version-check / GitGuardian /
  SonarCloud Code Analysis all success; Sonar quality gate **Passed**; Qodo
  review (initial + `/agentic_review`-triggered) — 0 bugs, 0 rule violations,
  0 requirement gaps
- commits: `f18dbcc..fe920c2` (spec, plan, 7 task merges, docs, bump,
  bookkeeping)
- PRs / issues: PR [#338](https://github.com/agentculture/colleague/pull/338);
  closes #334 #335 #336; follow-up filed
  [#337](https://github.com/agentculture/colleague/issues/337)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A session-passed `--max-steps` survives mode-profile application on both fronts | high | test `test_max_steps_flag_survives_the_work_mode_profile` · merge `f098d28` |
| `COLLEAGUE_COMPACTION_CAP` resolves env > config.json > default 4, 0 = unlimited, visible in `config show` | high | 10 precedence tests in `tests/test_chain.py` · merges `e333881`/`a833219` |
| A chain-armed run defers all four pre-finish gates to the final episode, which gates the union changed set | high | `tests/test_gate_deferral.py` e2e + matrix · merges `2ef72ab`/`850a9cc` |
| Subagent children of an armed run still run their gates (c22) | high | `test_subagent_shaped_until_done_run_gates_on_budget` · `test_chain_episode_marker_never_inherited_by_subagent_child` |
| Unarmed runs are byte-identical | high | existing gate/fillline/session test files pass unmodified; full suite 6,524 |
| The loop-side skip cannot drift from the chain verdict | high | `declared_capacity_handoff` imported from `colleague.chain` + `test_loop_skip_equivalent_to_chain_continue` |
| Docs state the shipped behavior + honest limits | high | stale-phrase grep count 0 · merge `98a279a` |
| PR #338 is merge-ready | medium | CI green + Sonar passed + Qodo 0/0/0 — human gate 3 (review + merge) remains |

## Remaining Work / Follow-up

- **Human gate 3**: review + merge PR #338 (the one remaining gate; merging
  is the operator's call).
- **#337** (filed this run): the pre-existing fill-line `chain_armed`
  consumers still key on `config.until_done` and leak into subagent children —
  same fix shape as c22 (key on the dispatch marker, or clear `until_done` in
  `run_subagent`).
- **Recorded corners, no action unless the operator wants them tightened**:
  the declared-handoff-then-clean-finish episode halts ok with gates skipped
  (deferral note on its artifact); a renamed file's old path drops out of the
  union gate set (plan risk `r1`, advisory-only).
- **Colleague large-file review limit** (operational note, not a code item):
  diff reviews touching `loop.py` exhaust the 27B's budget even single-focus
  at 60 steps — scope future colleague reviews to small files or the diff text
  itself.

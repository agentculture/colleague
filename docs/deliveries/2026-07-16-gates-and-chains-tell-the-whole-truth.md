# Delivery Summary — gates and chains tell the whole truth

plan: `gates-and-chains-tell-the-whole-truth` · run: `complete` · date: `2026-07-16`
baseline: `devague summary skeleton`

## Intent

Close five gate/chain/config honesty gaps — issues #337, #339, #340, #341, #342
— in one arc: the pre-finish gates record every union path they could
not grade and
the run_command blind spot gets an explicit scope decision; a halted chain
names its ungated episodes and kept WIP branches at outcome + artifact level;
a completed chain that hands off with its final episode's gates skipped says
so on the outcome line, the artifact, and the PR body; every config.json
override loader honors the at-home per-key merge; and an armed until_done run
stops arming fill-line chain consumers inside its subagent children. Executed
from the challenged frame's plan by a mixed Claude + colleague (Qwen3.6-27B)
workforce over six file-disjoint waves, delivered as PR
[#345](https://github.com/agentculture/colleague/pull/345) (v1.49.0), plus one
post-plan Qodo triage round (2 FIX by parallel worktree subagents, 1 PUSHBACK).

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — contract.py: TaskResult.gates_deferred + ChainView.deferred_gate_episodes
- `t2` — loop.py: stamp the structured deferral marker + dropped-path note (once per run)
- `t3` — handoff.py: PR body seam for the deferral warning
- `t4` — config.py: migrate the seven whole-file loaders to the per-key merge
- `t5` — icons.py: migrate the eighth config.json reader
- `t6` — subagents.py: stop until_done leaking into children
- `t7` — work.py: chain-side deferral accounting, halted outcome line, completed-chain detection
- `t8` — continue-regate proof: halted chain then --continue ends gated
- `t9` — docs: deferral surfacing, gate scope decision (2a), before/after honesty
- `t10` — full verification: suites, byte-identity, counts
- `t11` — file follow-ups: 2b git-status sweep spec + UI rendering of the deferral flag

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `TaskResult.gates_deferred` (omit-when-False) + `ChainView.deferred_gate_episodes` (omit-when-empty, degrade-to-empty `from_dict`, `accumulate` appends deferring ids); commit `65b74d5`-era t1 commit; 8 contract tests in `tests/test_chain_view.py` |
| `t2` | delivered | `_record_gate_dropped_paths` (once-per-run cell) + marker stamping in `_record_gate_deferral`; 6 tests in `tests/test_gate_deferral.py`; byte-identity tests pass with unmodified bodies |
| `t3` | delivered | `_gh_pr_create` optional `body` (replaces `--fill`; never `gh pr edit`) threaded through `chain_handoff_finalize`; 3 tests in `tests/test_handoff.py` |
| `t4` | delivered | seven loaders (lint/testintegrity/watch/coherence/memory/affected-tests/presence) on `_merged_config_json`; 7 fall-through tests + repo-wins pin in `tests/test_config_merge.py` |
| `t5` | delivered | `icons.py:_load_icons_config` on the per-key merge — built by colleague (work item `aa18ff1515b2`), folded with two fixes (unused import, needless blanket except); 2 tests in `tests/test_icons.py` |
| `t6` | delivered | `until_done: False` joins the c22 resets in `run_subagent` — reassigned colleague→Claude after an honest budget-exhausted INCOMPLETE (work item `bd67c5de4860`, 0 changes); test in `tests/test_subagent_budget.py` |
| `t7` | delivered | `_chain_deferral_surfacing` + `_emit_chain_outcome` deferral naming + `pr_body` threading; 3 e2e tests in `tests/test_work_chain.py` (halted naming, completed warning + PR body + exit 0, gated-completion byte-identity) |
| `t8` | delivered | `test_halted_then_continued_chain_ends_gated`: the only lint-gate call in the scenario is the continuing episode's, over the inherited union; resumed accounting keeps every deferring id |
| `t9` | delivered | five feature docs updated — built by colleague (work item `7e0f706c466d`), folded verbatim, markdownlint 0 errors |
| `t10` | delivered | full suite 6558→6562 passed / 20 live-gated skips; `colleague/chain.py` byte-identical; `tests/test_chain.py` unmodified; black/isort/flake8/bandit clean; `teken cli doctor --strict` 29/29 |
| `t11` | delivered | follow-ups filed: [#343](https://github.com/agentculture/colleague/issues/343) (2b git-status sweep spec), [#344](https://github.com/agentculture/colleague/issues/344) (cockpit/tui rendering) |

## Mid-work Decisions

No `devague deviate` records exist for this plan; each departure is captured
directly:

- t6 reassignment (colleague → Claude inline): colleague returned an honest
  `budget-exhausted` INCOMPLETE with 0 changed files on the 2-line brief — the
  read-heavy approach ate its 30-step budget; re-dispatch cost more than doing
  it.
- t9 double dispatch: the first colleague dispatch was refused by the #149
  dirty-tree guard — colleague's own memory-armed runs had dirtied the tracked
  `.eidetic/memory/colleague__public.jsonl` (the recorded churn gotcha,
  colleague#329). The churn was committed and the identical brief re-dispatched
  successfully.
- Post-plan SonarCloud fix: the t7 wiring pushed `execute_work_chain` to
  cognitive complexity 16 (ceiling 15, S3776) — extracted
  `_chain_deferral_surfacing`, the codebase's standing pattern.
- Post-plan Qodo triage round (2 FIX / 1 PUSHBACK, fixes by two parallel
  worktree subagents): (a) the halted-continued outcome line resolved inherited
  deferred ids' branches from episode artifacts with an explicit
  "(branch not resolved)" fallback — and the red run disproved the finding's
  own premise: cap-halted chained episodes' artifacts carried `branch: null`,
  so `_preserve_non_ok_wip` now records the iso branch on a CHAINED episode's
  result (unchained non-OK artifacts byte-identical); (b)
  `gates_deferred` parses strictly (`raw is True` only) so truthy junk like
  the string `"false"` degrades to False; (c) PUSHBACK on the "missing git
  sweep" requirement gap — it is the recorded user decision q1 (2a now, 2b
  filed as #343); Qodo's own relevance note rated it Low citing the same
  rejection on PR #338.
- The four named byte-identity tests kept unmodified bodies, but their shared
  `_union_ctx` fixture gained additive fields for the new recorder surface —
  recorded here so the "unmodified" claim is precise.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t5` | delivered by colleague per the approved pairing but folded with two code-quality fixes the task contract did not anticipate (unused import, needless blanket except) | acceptable |
| `t6` | executor reassigned colleague → Claude after an honest INCOMPLETE; the landed change matches the task contract exactly | acceptable |
| `t7` | delivered beyond contract post-plan: the Qodo round added artifact-based branch resolution to the outcome line and the chained-episode branch record in `_preserve_non_ok_wip` (commit `09b8d41`) | acceptable |
| `t1` | delivered beyond contract post-plan: `gates_deferred` parsing tightened from truthy to strict boolean (commit `2b7b09e`) | acceptable |

No other task drifted; the task-by-task accounting above covers all eleven.

## Evidence

- tests: `uv run pytest -n auto` — **6562 passed, 20 skipped** (live-gated
  vLLM proofs) at `d94d694`
- tests: `tests/test_work_chain.py::TestChainGateDeferralSurfacing` (5 node
  ids incl. `test_halted_then_continued_chain_ends_gated`,
  `test_continued_halt_outcome_resolves_inherited_deferred_branches`) — pass
- tests: `tests/test_chain_view.py::test_gates_deferred_truthy_junk_degrades_false` — pass
- byte-identity: `git diff main -- colleague/chain.py` — empty;
  `tests/test_chain.py` untouched in the diff
- lint: `black --check` / `isort --check-only` / `flake8` / `bandit -c
  pyproject.toml` — all clean; `teken cli doctor . --strict` — 29/29 PASS
- new tests in diff: 32 (plan waves) + 4 (Qodo round)
- commits: `100373e..d94d694` (23 commits on
  `spec/gates-and-chains-tell-the-whole-truth`)
- PRs / issues: PR #345 (v1.49.0); closes #337 #339 #340 #341 #342; filed
  #343, #344; Qodo threads 3593177561 + 3593177565 both FIXed and resolved,
  requirement gap PUSHBACKed with references
- SonarCloud: Quality Gate OK, 0 open issues, 0 hotspots (pre-Qodo-round
  head `1abfab6`); post-round gate re-check running at write time

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| the gate union's dropped paths are recorded once per run and named on the artifact | high | `tests/test_gate_deferral.py::test_gate_changed_set_records_dropped_paths_once` · `::test_final_episode_drop_note_on_artifact` |
| deferral state is machine-readable end to end (marker + chain list), no prose matching | high | `tests/test_chain_view.py` deferred/gates_deferred tests · `colleague/contract.py` |
| a halted chain's outcome names deferring episodes + kept WIP branches, including inherited ones after `--continue` | high | `tests/test_work_chain.py::TestChainGateDeferralSurfacing::test_halted_chain_outcome_names_deferred_episodes` · `::test_continued_halt_outcome_resolves_inherited_deferred_branches` |
| the completed-ungated corner (#340) warns on outcome + artifact + PR body, exit stays 0 | high | `::test_completed_chain_with_deferred_final_warns_everywhere` · commit range `100373e..d94d694` |
| `work --continue` re-gates halted WIP over the inherited union | high | `::test_halted_then_continued_chain_ends_gated` |
| all eight config.json loaders honor the per-key merge | high | `tests/test_config_merge.py` (8 fall-through tests) · `tests/test_icons.py::test_user_icons_survives_repo_config_that_omits_key` |
| armed runs' subagent children stay unarmed | high | `tests/test_subagent_budget.py::test_until_done_never_inherited_by_subagent_child` |
| unchained/unarmed/no-deferral runs are byte-identical | high | the four named byte-identity tests (unmodified bodies) + `test_completed_gated_chain_renders_no_warning` |
| the arc's PR passes every automated gate after the Qodo round | medium | pre-round gates all green (Sonar 0/0, Qodo 0 inline); post-round re-check in flight at artifact-write time — not claimed until it lands |
| audio/live chained behavior on a real vLLM rig is unaffected | unverified | live-gated tests skipped in this run (COLLEAGUE_VLLM_E2E unset) — not claimed |

## Remaining Work / Follow-up

- #343 — spec + build the gate-time git-status sweep (the 2b half of #342);
  owner: next arc, needs its own spec per decision q1.
- #344 — render `deferred_gate_episodes` in the cockpit Last-run panel + tui
  snapshot; owner: follow-up arc (boundary c22).
- #340 option A (prevention) stays parked in the spec — the six-shape
  equivalence-test extension is its named acceptance gate; blocked on
  reordering the #313 classification ahead of the gate block.
- Post-Qodo-round gate re-check (CI + Sonar + Qodo re-review on `d94d694`) —
  in flight at write time; human merge of PR #345 is gate 3.
- Eidetic-churn ergonomics (colleague#329 / eidetic-cli#32) — bit this run
  twice; unchanged by this arc.

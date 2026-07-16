# gates and chains tell the whole truth

> Five gate/chain/config honesty gaps close together: the pre-finish gates record every union path they could not grade and the run_command mutation blind spot gets an explicit scope decision (#342); a halted chain names its ungated episodes and kept WIP branches at outcome + artifact level (#341); a completed chain that hands off with its final episode's gates skipped says so on the outcome line, the artifact, and the PR body (#340); every config.json override loader honors the at-home per-key merge (#339); and an armed until_done run stops arming fill-line chain consumers inside its subagent children (#337).

## Audience

- colleague operators arming chained/armed runs and the human reviewer at handoff gate 3 (the PR), plus artifact consumers (cockpit Last-run panel, feedback export, tui snapshot) that must flag ungated WIP without string-matching capacity_warning
  - instruction: the spec names both the operator-facing surfaces (outcome line, PR body) and the machine-facing ones (artifact flag)

## Before → After

- Before: today the ONLY gate-deferral record is a capacity_warning substring per episode artifact (loop.py:3450); union paths the existence filter removes vanish with no record (loop.py:3476); a repo config.json that omits lint/testintegrity/watch/coherence/memory/affected-tests/presence keys hides the user-level default entirely (7 whole-file loaders); and every subagent child of an --until-done run arms fill-line chain consumers nobody chains (subagents.py:338 copies until_done)
  - instruction: each fact cites the line it was read at — verify against the scope entries s1-s11
- After: every path the gates could not grade is named on the artifact; a halted chain outcome line names its ungated episodes + kept WIP branches and ChainView carries deferred_gate_episodes; a completed chain that handed off with final-episode gates skipped says so on the outcome line, the artifact, and the PR body; user-level config defaults survive repo files that omit their keys across all seven loaders; a subagent child of an armed run behaves byte-identically to a child of an unarmed run
  - instruction: the chained mock e2e suite asserts each surface listed here

## Why it matters

- the handoff PR is the trust boundary: a PR that skipped its gates without saying so, or a silently ungraded rename, is a silent breach of the honest-limits discipline (h4) — detection keeps the operator able to see exactly what went ungated instead of inferring it from per-episode artifacts

## Requirements

- #342(1): _gate_changed_set (colleague/loop.py:3459) filters union(episode changed, chain prior_changed) to worktree-existing paths and drops the rest SILENTLY; when the filter removes paths, append ONE note naming them to result.capacity_warning plus a phase notice (the _record_gate_deferral precedent at loop.py:3438); a run with nothing dropped stays byte-identical
  - instruction: extend tests/test_gate_deferral.py chained e2e: episode 2 deletes an episode-1 file, assert the final artifact note lists it; assert no note otherwise
  - honesty: the dropped-paths note fires ONLY when the existence filter actually removed paths; a chained e2e where episode 2 deletes an episode-1 file asserts the note names exactly that path; nothing-dropped runs stay byte-identical
  - honesty: the dropped-paths note records ONCE per run even though _gate_changed_set is called by each of the four gates (up to twice each — loop.py:3540/3550/3600/3773/3786/3879/3899); the _gate_deferral_noted single-fire cell is the precedent
- #341(1)+(2): halted chains surface deferred-gate episodes: _record_gate_deferral stamps a STRUCTURED marker on the episode result (not only the capacity_warning string), the chain loop accumulates deferring episode ids onto ChainView.deferred_gate_episodes, and _emit_chain_outcome (work.py:1308) names the deferring episodes + kept WIP branches when any exist
  - instruction: unit-test from_dict with missing, null, and junk deferred_gate_episodes payloads
  - honesty: no consumer string-matches capacity_warning: the chain loop reads the structured deferral marker; ChainView.from_dict degrades a missing/malformed deferred_gate_episodes to empty without raising
- #341(3): prove the continue path re-gates: a test pins that a halted-then-continued chained run ends with a gated final episode over the inherited union — continue-the-chain becomes the documented remedy for ungated halted WIP
  - honesty: the continue-regate proof drives a real halted chain (episode cap) then work --continue whose next episode finishes ok, asserting gate reports on the continuing episode artifact over the inherited union
- #340(B): a COMPLETED chain whose final episode carried the gate-deferral marker (ok-finish + declared finish-with-handoff, the ONE completing shape that skips gates: chain.py ok-guard at 172 vs loop.py predicate at 3435) is detected loudly: outcome-line warning, artifact flag (final episode id present in ChainView.deferred_gate_episodes), and the warning included in the handoff PR body via _chain_finalize (work.py:1198)
  - instruction: chained mock e2e: final episode declares finish-with-handoff and finishes ok; assert outcome warning + artifact flag + PR-body text; assert absent on a gated completion
  - honesty: detection keys on the structured deferral marker of the FINAL episode of a COMPLETED chain only; halted chains and gated completions render byte-identical outcome lines; the PR-body warning appears only when a PR is actually opened
- #339: migrate the config.json override loaders still on whole-file configdir.resolve_file to the _merged_config_json per-key merge — the live count is SEVEN, not four as filed: _load_lint_overrides(732), _load_testintegrity_overrides(758), _load_watch_override(807), _load_coherence_override(887), _load_memory_override(924), _load_affected_tests_overrides(967), _load_presence_override(1350); regression tests mirror tests/test_config_merge.py::test_repo_config_without_compaction_cap_falls_through_to_user_default
  - instruction: mirror tests/test_config_merge.py::test_repo_config_without_compaction_cap_falls_through_to_user_default for all seven loaders
  - honesty: each migrated loader falls through to the user-level default when the repo file omits its key(s) — one regression test per loader mirroring the #338 test shape; per-key precedence (repo wins where the key is present) unchanged
- #337: run_subagent child config (subagents.py:338-351) resets chain_episode/chain_prior_changed unconditionally but copies until_done through dataclasses.replace; ContextControls.from_config keys chain_armed on config.until_done (loop.py:2751), arming _reject_compaction finish-with-handoff (loop.py:1263) + the budget-exhausted handoff instruction in children. Fix: reset until_done False in replace_kwargs alongside the existing c22 resets
  - instruction: unit test run_subagent child config until_done is False when parent True; existing armed-parent chain tests unmodified
  - honesty: a chain-armed parent spawns children with chain_armed False (unit test on the child config plus a loop-level proof that a child _reject_compaction takes the lossy-windowing floor); the armed parent own episodes still arm
- challenge catch (#339 extension): colleague/icons.py:_load_icons_config (line 57) is an EIGHTH config.json reader on whole-file resolve_file — outside config.py, missed by the issue and the scope survey; it migrates to the per-key merge with the other seven (icons.py imports only configdir today — no cycle either direction; the merge may live in configdir or be imported from config)
  - instruction: add a regression test: user config.json sets icons, repo config.json omits it, icon mode resolves to the user value
  - honesty: the icons regression test proves the merge: a user-level icons value survives a repo config.json that omits the key; existing icon-mode precedence (explicit > env > config) is unchanged
- challenge catch (#340 b3 mechanism): _gh_pr_create (handoff.py:627) builds the PR with gh pr create --fill and accepts NO body parameter — the PR-body warning needs either a composed --body at create time (replacing --fill when a warning is present) or a post-create gh api PATCH; NEVER gh pr edit, which no-ops on agentculture repos (Projects-classic GraphQL deprecation, recorded gotcha)
  - instruction: unit-test the argv composition: warning present adds a body carrying the deferral text; warning absent keeps --fill byte-identical
  - honesty: with no deferral warning the create path stays byte-identical (--fill); with a warning the body carries the deferral text and the offline/CI degrade paths (no remote, no gh, push failure) still return local-only notes without raising

## Honesty conditions

- the five issues genuinely share one arc: every change is detection/observability/hygiene on existing chain+gate seams — no routing policy, no daemon, no gate-semantics change
- the PR diff touches no profiles.json read path (_read_profiles_file / _load_profile_overlays unchanged)
- colleague/chain.py is byte-identical in the PR diff; tests/test_chain.py passes unmodified
- the four named byte-identity tests pass unmodified: test_gate_changed_set_empty_prior_is_byte_identical, test_chain_episode_clean_finish_runs_gates_no_note, test_non_chain_budget_exit_still_runs_gates, test_subagent_shaped_until_done_run_gates_on_budget
- every named consumer can read the deferral state without parsing prose — deferred_gate_episodes is a typed list on the artifact JSON
- each before-state fact is verifiable at its cited line in the pre-change tree (scope entries s1-s11 are the provenance)
- each after-state surface has at least one asserting test in the PR diff
- no surface claims prevention: docs say detection-only; halted chains stay ungated by design (the rejected post-hoc-gate shape is recorded, not resurrected)
- the counts are checked against the PR diff before merge: new tests counted, full suite run, equivalence matrix + test_chain.py verified unmodified
- the chained e2e asserts exit code 0 on the detected ok-handoff completion; no gate gains blocking behavior anywhere in the diff
- the diff touches no cockpit/tui rendering module — the session Last-run panel and taui renderers are unchanged; the only new operator-visible lines ride the existing work.py diagnostics channel

## Success signals

- all 5 issues (#337 #339 #340 #341 #342-part-1) close in ONE PR with 0 new dependencies; >= 4 new chained-e2e assertions land (dropped-path note, halted-chain outcome+flag, continue-regate proof, completed-chain ok-handoff detection); >= 7 config-merge regression tests (one per migrated loader); the existing 5-shape equivalence matrix and tests/test_chain.py pass unmodified; full uv run pytest -n auto green
  - instruction: count the new tests in the PR diff; run the full suite

## Scope / boundaries

- profiles overlays are OUT of the #339 migration: config.py:2392/2400 read profiles.json (not config.json) via resolve_file exact-path — per-model isolation is deliberate (per-model-configuration exact-path rule); they stay whole-file
- the chain driver verdict semantics stay untouched: should_continue ok-guard-first ordering, deviation d1 declared-handoff continuation, CONTINUABLE_REASONS == {budget-exhausted}, and the halted-chain no-backfill rule (a post-hoc gate pass loses the live fix-turn/re-examine — the rejected #335 shape). #341/#340 land detection only
- byte-identical invariants hold everywhere: non-chained runs and chain first episodes keep exactly the current gate set (empty prior_changed short-circuit, loop.py:3472); unarmed runs and subagent children of unarmed parents see zero behavior change; empty-drop and no-deferral chains render no new notes
- detection never changes exit codes or blocking behavior: a completed chain that handed off with final-episode gates skipped still exits 0; all four gates stay advisory/non-blocking; the warning surfaces are diagnostics + artifact + PR body only
- consumer UIs are NOT re-rendered this arc: the typed ChainView.deferred_gate_episodes flag is the deliverable that ENABLES the cockpit Last-run panel / feedback export / tui snapshot to flag ungated chains; adding those renderings is follow-up territory, not this PR

## Scope exploration

- `s1` — `colleague/loop.py:_gate_changed_set (3459-3476)`: the union filter (root / path).exists() silently drops deleted/renamed prior-episode paths; _record_gate_deferral (3438) directly above is the capacity_warning-append + phase-notice precedent to reuse for the dropped-paths note
  - seeds: `c2`
- `s2` — `colleague/loop.py exit path (4300-4429)`: gates run at 4325 BEFORE _apply_outcome_flags (4403) and _maybe_flag_incompletion (4416) — the #313 classification is unavailable at gate time, confirming the #340 Option-A ordering caveat first-hand
  - seeds: `c6`, `c5`
- `s3` — `colleague/chain.py:should_continue (142-223)`: the ok-guard wins before declared_capacity_handoff, so ok-finish + declared handoff COMPLETES the chain while loop-side _gates_deferred_to_chain (loop.py:3435) fires on the handoff alone — the exact #340 divergence; verdict ordering must stay per deviation d1
  - seeds: `c5`, `c10`
- `s4` — `colleague/cli/_commands/work.py chain loop (1198-1512)`: execute_work_chain already accumulates changed_so_far + episode_branches per episode; _emit_chain_outcome prints kept-WIP branches on halt; _chain_finalize rewrites the final artifact after the real handoff — the natural hook points for the #341 outcome line, ChainView accumulation, and the #340 PR-body warning
  - seeds: `c3`, `c5`
- `s5` — `colleague/contract.py:ChainView (844-928)`: frozen dataclass, to_dict/from_dict with best-effort _coerce_count (never raises on malformed artifacts) — deferred_gate_episodes must join both serializers with the same degrade-to-empty stance
  - seeds: `c3`
- `s6` — `colleague/config.py override loaders (700-1360)`: SEVEN config.json readers still call resolve_file whole-file (lint 732, testintegrity 758, watch 807, coherence 887, memory 924, affected-tests 967, presence 1350) — the filed count of four undercounts; _load_chain_overrides (853) is the already-migrated template from PR #338
  - seeds: `c7`
- `s7` — `colleague/config.py profiles overlay (2392-2400)`: reads profiles.json, not config.json, exact-path per-model — deliberately whole-file per the per-model-configuration isolation rule; out of the #339 migration
  - seeds: `c8`
- `s8` — `colleague/subagents.py:run_subagent (315-351)`: replace_kwargs already resets chain_episode/chain_prior_changed with the c22 comment explaining why a child must never see chain markers; until_done is NOT in the reset set — the #337 leak lands its one-line fix in the same block
  - seeds: `c9`
- `s9` — `colleague/tools.py changed-set writers (871/937/1281/1353)`: executor.changed is populated ONLY by write_file/edit_file + subagent merges; no run_command path touches it — the #342(2) blind spot is structural, not incidental, so the decision is 2a-vs-2b, never a small patch
  - seeds: `c11`
- `s10` — `tests/test_gate_deferral.py:_EXIT_SHAPES (207-252)`: the five-shape loop-skip == chain-continue equivalence matrix lacks the sixth {ok-finish + declared handoff} shape where the two sides genuinely diverge — the acceptance gate for #340 Option A if prevention is ever built
  - seeds: `c6`
- `s11` — `docs/features/indefinite-run.md (178-188)`: the pre-finish-gate-deferral bullet records the per-episode capacity_warning note as the ONLY deferral record today — the doc must gain the structured marker + outcome-line surfacing #341/#340 add
  - seeds: `c3`
- `s12` — `challenge pass / adjacent-systems lens: capacity_warning consumers`: contract.py serializes omit-when-None; session.py:926 renders the warning VERBATIM as the cockpit signal line; work.py:1859 emits it as a diagnostic — no consumer string-MATCHES it today, so appending note text is safe and the structured marker forestalls anyone starting
  - seeds: `c3`
- `s13` — `challenge pass / adjacent-systems lens: colleague/handoff.py:_gh_pr_create (627-647)`: gh pr create --fill, no body parameter; chain_handoff_finalize passes head explicitly and degrades push/PR failures to local-only notes — the b3 warning must ride a new body path without breaking the offline/CI degrade
  - seeds: `c20`
- `s14` — `challenge pass / adjacent-systems lens: colleague/icons.py:_load_icons_config (51-69)`: an eighth whole-file config.json reader outside config.py, reading the icons key with its own json.loads — found only by grepping resolve_file across the package; imports only configdir, so no cycle blocks the migration
  - seeds: `c19`
- `s15` — `challenge pass / failure-modes lens: ChainView.from_dict malformed path (contract.py:920)`: the malformed-payload fallback constructs positionally — cls(0, 0, 0, 0, 0, 0) — so the new deferred_gate_episodes field needs a default AND that call left valid; both serializers must carry it with the degrade-to-empty stance
  - seeds: `c3`
- `s16` — `challenge pass / lifecycle lens: artifact forward/backward compat`: old artifact read by new code: from_dict missing key degrades to empty; new artifact read by an old installed colleague: from_dict reads only known keys, unknown keys ignored — both directions degrade safely, no migration needed; clean pass
- `s17` — `challenge pass / concurrency lens: chain + subagent state`: chain state (ChainState, changed_so_far, episode_branches) is in-process locals of execute_work_chain; worktree admin mutations stay fcntl-serialized (#239); the #337 fix only narrows child config — nothing new is shared; clean pass
- `s18` — `challenge pass / probe: baseline suites`: uv run pytest tests/test_gate_deferral.py tests/test_chain.py tests/test_config_merge.py — 118 passed in 0.36s pre-change; the byte-identity claims measure against a green baseline
  - seeds: `c12`

## Decisions

- #342(2) resolved as 2a-plus-follow-up (user decision, q1): the pre-finish gates grade model-authored edits BY DESIGN — run_command mutations (git mv, sed -i, codegen) are the approval-gate domain; this arc states that in docs/features/lint-gate.md + docs/features/work-and-loop.md, and FILES (not builds) the 2b follow-up: a git-status sweep (git diff --name-status --find-renames vs base, isolated worktree) merged into the gate set, weighing that changed_files also feeds chain progress evidence + WorkStats

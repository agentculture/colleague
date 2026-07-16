# Build Plan — gates and chains tell the whole truth

slug: `gates-and-chains-tell-the-whole-truth` · status: `exported` · from frame: `gates-and-chains-tell-the-whole-truth`

> Five gate/chain/config honesty gaps close together: the pre-finish gates record every union path they could not grade and the run_command mutation blind spot gets an explicit scope decision (#342); a halted chain names its ungated episodes and kept WIP branches at outcome + artifact level (#341); a completed chain that hands off with its final episode's gates skipped says so on the outcome line, the artifact, and the PR body (#340); every config.json override loader honors the at-home per-key merge (#339); and an armed until_done run stops arming fill-line chain consumers inside its subagent children (#337).

## Tasks

### t1 — contract.py: TaskResult.gates_deferred + ChainView.deferred_gate_episodes

- instruction: colleague/contract.py only (+ its test file). Keep the frozen-dataclass + _coerce_count degrade stance; mirror omit-when-None precedent (capacity_warning) for gates_deferred as omit-when-False. accumulate signature stays (prior, result).
- covers: c3, h3, c13, h11
- acceptance:
  - TaskResult gains gates_deferred (bool, default False, omit-when-False in to_dict, read back in from_dict) and ChainView gains deferred_gate_episodes (tuple/list of task ids, default empty, in to_dict + from_dict)
  - ChainView.from_dict degrades missing, null, and junk deferred_gate_episodes to empty without raising; the malformed-payload positional fallback still constructs
  - ChainView.accumulate appends the episode task id when the result carries gates_deferred; round-trip tests cover both fields

### t2 — loop.py: stamp the structured deferral marker + dropped-path note (once per run)

- instruction: colleague/loop.py: _gate_changed_set + _record_gate_deferral region (3411-3513) + a new single-fire cell on _Work; tests extend tests/test_gate_deferral.py. Do NOT touch chain.py or the gate predicates.
- depends on: t1
- covers: c2, h2, h16
- acceptance:
  - a chained e2e where episode 2 deletes an episode-1 file asserts the final artifact capacity_warning names exactly that dropped path; a run where nothing is dropped emits no note (byte-identical)
  - the note records ONCE per run although _gate_changed_set is called by all four gates (single-fire cell like _gate_deferral_noted)
  - _record_gate_deferral additionally sets result.gates_deferred=True; existing test_gate_deferral.py byte-identity tests pass unmodified

### t3 — handoff.py: PR body seam for the deferral warning

- instruction: colleague/handoff.py: _gh_pr_create (627) gains an optional body param; chain_handoff_finalize (515) threads it. gh pr create --fill and --body are mutually exclusive — when a body is passed, compose --title + --body and drop --fill. Never gh pr edit (broken on agentculture: Projects-classic).
- covers: c20, h18
- acceptance:
  - chain_handoff_finalize accepts an optional warning text; absent, gh pr create argv is byte-identical (--fill, no --body); present, the argv carries a body containing the deferral warning (no gh pr edit anywhere)
  - offline/CI degrade paths (no remote, no gh, push failure) return local-only notes without raising, warning present or not — proven with mocked subprocess, no live remote

### t4 — config.py: migrate the seven whole-file loaders to the per-key merge

- instruction: colleague/config.py only. _load_chain_overrides (853) is the migrated template from PR #338; mirror tests/test_config_merge.py::test_repo_config_without_compaction_cap_falls_through_to_user_default per loader.
- covers: c7, h6, c8, h7
- acceptance:
  - all seven loaders (_load_lint_overrides, _load_testintegrity_overrides, _load_watch_override, _load_coherence_override, _load_memory_override, _load_affected_tests_overrides, _load_presence_override) read via _merged_config_json; a repo config.json omitting their keys falls through to the user-level default — one regression test per loader in tests/test_config_merge.py
  - per-key precedence unchanged where the repo file HAS the key (repo wins); profiles.json read paths (_read_profiles_file/_load_profile_overlays) untouched in the diff

### t5 — icons.py: migrate the eighth config.json reader

- instruction: colleague/icons.py:_load_icons_config (51-69). icons.py imports only configdir today; either import the merge from colleague.config (no cycle — config does not import icons) or extend configdir with the shared per-key helper if the import feels heavy. Add tests (new test file or the icons test home).
- covers: c19, h17
- acceptance:
  - a user-level config.json icons value survives a repo config.json that omits the key; explicit > env > config precedence unchanged

### t6 — subagents.py: stop until_done leaking into children

- instruction: colleague/subagents.py: add "until_done": False to replace_kwargs (338-343) next to the existing chain_episode/chain_prior_changed resets; extend the c22 comment to name #337. Loop-level proof: a child-config _Work has chain_armed False so _reject_compaction takes the lossy-windowing floor.
- covers: c9, h8
- acceptance:
  - run_subagent child config carries until_done=False when the parent is armed (unit test on the built child config)
  - ContextControls.from_config over the child config yields chain_armed=False; existing armed-parent chain tests pass unmodified

### t7 — work.py: chain-side deferral accounting, halted outcome line, completed-chain detection

- instruction: colleague/cli/_commands/work.py: thread deferral ids through the episode loop (execute_work_chain 1444-1512) into ChainView accumulation, extend _emit_chain_outcome (1308) + _maybe_finalize_chain/_chain_finalize (1198-1350) to pass the warning into chain_handoff_finalize. VERIFY ordering first: result.gates_deferred must be set before the ChainView accumulate + artifact write (find the accumulate call site in execute_work).
- depends on: t1, t2, t3
- covers: c3, c5, h5, c21, h19, c22, h20, c13
- acceptance:
  - a chained mock e2e halting on the episode cap asserts: the outcome line names the deferring episodes and kept WIP branches, and the final artifact chain view carries deferred_gate_episodes
  - a chained mock e2e whose final episode declares finish-with-handoff and finishes ok asserts: outcome warning, final episode id present in deferred_gate_episodes, PR body carries the warning, and exit code 0
  - halted chains and gated completions render byte-identical outcome lines to today; detection reads result.gates_deferred, never string-matches capacity_warning; no cockpit/tui rendering module touched

### t8 — continue-regate proof: halted chain then --continue ends gated

- instruction: test-only task in tests/test_gate_deferral.py (or the chained e2e home); reuse the #335 chained-e2e fixtures + continuation.py read_chain_view resume; no production code change expected.
- depends on: t7
- covers: c4, h4
- acceptance:
  - a test drives a chained run halted on the cap, then work --continue whose next episode finishes ok, and asserts gate reports on the continuing episode artifact over the inherited union(changed, prior_changed)

### t9 — docs: deferral surfacing, gate scope decision (2a), before/after honesty

- instruction: Also touch docs/features/config-resolution.md (eight loaders now merged) and docs/features/subagents.md (until_done reset). Keep each edit scoped to the affected bullets; no restructuring.
- depends on: t7
- covers: c1, h1, c14, h12, c16, h14
- acceptance:
  - docs/features/indefinite-run.md documents the structured marker, ChainView.deferred_gate_episodes, the halted outcome naming, and the completed-chain warning (detection-only stance explicit; halted chains stay ungated by design)
  - docs/features/lint-gate.md + docs/features/work-and-loop.md state the 2a decision: gates grade model-authored edits (write_file/edit_file + subagent merges); run_command mutations are the approval-gate domain — with the 2b follow-up issue linked

### t10 — full verification: suites, byte-identity, counts

- instruction: Run: git diff main --stat (chain.py absent), uv run pytest -n auto, plus black/isort/flake8/bandit and teken cli doctor . --strict per CLAUDE.md. Count tests via git diff main -- tests/ | grep "^+.*def test_".
- depends on: t2, t4, t5, t6, t7, t8
- covers: c10, h9, c12, h10, c15, h13, c17, h15
- acceptance:
  - colleague/chain.py is byte-identical in the diff; tests/test_chain.py passes unmodified; the four named byte-identity tests pass unmodified
  - full uv run pytest -n auto green; >= 4 new chained-e2e assertions and >= 8 config-merge regression tests counted in the diff; every after_state surface has at least one asserting test

### t11 — file follow-ups: 2b git-status sweep spec + UI rendering of the deferral flag

- instruction: File with gh issue create, signed - colleague (Claude) per posting convention; reference decision q1/c18 and boundary c22 in the spec doc.
- depends on: t10
- acceptance:
  - two issues filed on agentculture/colleague: (1) the 2b gate-time git-status sweep with its small spec sketch (git diff --name-status --find-renames vs base; weighs chain progress evidence + WorkStats; risks from #342 recorded), (2) rendering deferred_gate_episodes in cockpit Last-run / tui snapshot; both link the spec + this arc PR

## Risks

- [unknown_nonblocking] ChainView accumulate call-site ordering: result.gates_deferred must be set before the accumulate + artifact write — verify in execute_work when wiring t7 (task t7)
- [unknown_nonblocking] gh pr create --fill and --body are mutually exclusive; the warned path swaps composition — argv unit tests must pin both shapes, mocked subprocess only (task t3)
- [unknown_nonblocking] workforce routing: loop.py + work.py surgery stays with Claude (large-file timeout gotcha, budget-exhaust on big-file reviews); colleague takes the file-scoped tasks with tight briefs
- [follow_up] the 2b git-status sweep is deliberately NOT built here — follow-up issue only (user decision q1)
- [follow_up] UI rendering of deferred_gate_episodes (cockpit Last-run panel, tui snapshot) is follow-up territory (boundary c22)

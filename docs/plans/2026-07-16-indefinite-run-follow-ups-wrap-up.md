# Build Plan — indefinite-run follow-ups wrap-up

slug: `indefinite-run-follow-ups-wrap-up` · status: `exported` · from frame: `indefinite-run-follow-ups-wrap-up`

> colleague wraps up the three indefinite-run follow-ups: a session-passed --max-steps survives mode profiles (#336), a chain-armed run defers its pre-finish gates to the final episode instead of re-running them every episode (#335), and the per-run compaction cap is an operator config knob COLLEAGUE_COMPACTION_CAP with 0=unlimited (#334)

## Tasks

### t1 — t336: run_session marks --max-steps in explicit_knobs

- instruction: in run_session (colleague/cli/_commands/session.py ~3017, right after EngineConfig.resolve): mirror cmd_work (work.py:1701-1703) — if getattr(args, 'max_steps', None) is not None: config.explicit_knobs = frozenset({'max_steps'}). Then flip tests/test_session_chain.py:304 from monkeypatch.setenv COLLEAGUE_MAX_STEPS to passing the flag. TDD: write the red unit test first.
- covers: c2, c3, h2, h3
- acceptance:
  - a unit test dispatching a session work item with --max-steps N through a mode-profiled path asserts effective config.max_steps == N (red on main)
  - tests/test_session_chain.py e2e passes with the --max-steps flag replacing the COLLEAGUE_MAX_STEPS=1 env workaround
  - full suite green; no other session behavior changes

### t2 — t334a: COLLEAGUE_COMPACTION_CAP config resolution

- instruction: follow the max_episodes precedent exactly (config.py: extend _load_chain_overrides to also return 'compaction_cap' as a raw string (836-859); add the resolve leg via _try_int(_pick(None, 'COLLEAGUE_COMPACTION_CAP', 'CONVERTIBLE_COMPACTION_CAP', default=_file_or_default(...))) near 2116; add the field near max_episodes; add to to_dict ~2150). Import DEFAULT_COMPACTION_CAP from colleague.fillline for the default (fillline imports nothing from config — no cycle); do NOT touch fillline.py.
- covers: c4, c7, h4, h7
- acceptance:
  - EngineConfig gains compaction_cap resolving env COLLEAGUE_COMPACTION_CAP > config.json top-level 'compaction_cap' > default fillline.DEFAULT_COMPACTION_CAP (4); malformed falls back to 4; 0 (and any non-positive) resolves and passes through
  - 'colleague config show' / to_dict includes compaction_cap
  - precedence unit tests cover env-beats-file, file-beats-default, malformed-falls-back

### t3 — t334b: loop consumes the resolved compaction cap

- instruction: thread the resolved cap into the loop like sibling knobs: _fillline_cap_reached (loop.py ~1250) and _record_fillline_cap (~1270) read the resolved value (via ContextControls or ctx config — follow how the fill-line threshold/budget already travel) instead of _fillline.DEFAULT_COMPACTION_CAP. cap_reached already treats cap<=0 as unlimited — do not reimplement.
- depends on: t2
- covers: c5, c6, h5, h6
- acceptance:
  - with cap resolved to 2, the third fill-line crossing in one run is suppressed and the recorded note names 2 (not the constant)
  - with cap 0, a 5th compaction turn is permitted (unlimited)
  - with the knob unset, behavior is byte-identical to today (existing fillline/loop tests pass unmodified)
  - the PR diff of colleague/fillline.py is empty or comment-only

### t5 — t335a: chain-episode plumbing (chain_episode + prior_changed)

- instruction: work.py: extend ChainEpisodeOptions (frozen dataclass ~576) with prior_changed: tuple[str, ...] = (); in execute_work_chain's loop accumulate a set from each result.changed_files and pass it; thread into the loop's ContextControls (loop.py ~630, the chain_armed precedent at 2699 — but keyed on the chain option's PRESENCE, never config.until_done, per c22: subagent children inherit until_done via dataclasses.replace). Keep S107 bundles intact.
- depends on: t3
- covers: c22, h17
- acceptance:
  - ChainEpisodeOptions gains prior_changed (cumulative changed files from prior episodes); execute_work_chain accumulates per-episode result.changed_files and passes the union to the next episode
  - execute_work threads a chain-episode marker + prior_changed into ContextControls; the marker is set ONLY when ChainEpisodeOptions is present — a run with config.until_done=True but no chain dispatch does NOT set it
  - unarmed/non-chained dispatches are byte-identical (chain=None path untouched; existing tests pass unmodified)

### t6 — t335b: gate-skip guard + final-episode union gate set

- instruction: loop.py exit path (~4152-4175): guard the four _maybe_run_*_gate calls behind the skip predicate; derive continuation-shape from chain.py's signals (declared_capacity_handoff + the budget outcome) — import or mirror-with-equivalence-test. Widen the gate changed-set at the call sites via a helper unioning ctx.executor.changed with the threaded prior_changed, filtered to existing paths. The lint fix-turn / test-integrity re-examine stay untouched on the final episode (they need the live loop — the post-hoc shape was rejected: fix-turn loss + final-episode-only changed set). Record the skip via the _record_fillline_cap precedent (capacity_warning + phase notice), ONCE per episode.
- depends on: t5
- covers: c8, h8, c10, h10, c23, h18
- acceptance:
  - a unit test on the gate guard asserts skip fires exactly on (chain-episode AND (outcome == budget-exhausted OR capacity_decision.kind == finish-with-handoff)) and never otherwise — incl. a subagent-shaped run (until_done=True, no chain dispatch) which still runs gates on a budget exit
  - an equivalence test (or reuse of chain.py helpers) pins loop-skip <=> chain-would-continue across exits {ok-finish, budget, capacity-handoff, timeout, error}
  - mid-chain skip records ONE deferral note on the episode artifact; a chained mock e2e (>=2 episodes) asserts mid-episode artifacts carry NO lint/coherence/test-integrity/affected-tests reports but DO carry the note, and the final episode's artifact carries the reports
  - on the final (finish-shaped) episode the four gates operate over union(this episode's changed, prior_changed) filtered to files existing in the worktree
  - existing gate test files pass unmodified

### t4 — t-docs: flip the honest gaps in docs

- instruction: docs/features/indefinite-run.md lines ~149/178/188 + capacity-standard.md ~38/64; also session.md only if it names max-steps/profile interplay. Keep trim discipline: state what shipped + honest limits, no history prose.
- depends on: t3, t5, t6
- covers: c12, h11, c14, h13
- acceptance:
  - post-change grep of docs/features/ finds no 'not yet an operator knob' (capacity-standard.md/indefinite-run.md) and no 'a recorded follow-up, not built' for #335
  - new statements name COLLEAGUE_COMPACTION_CAP (env > config.json > default 4, 0=unlimited) and the gate deferral incl. the halted-chain gap (skipped gates on halted chains stay skipped, recorded) and the subagent non-leak (until_done alone never skips)
  - markdownlint-cli2 clean on the touched docs

### t7 — t-wrap: version bump, chained-count proof, PR

- instruction: use the version-bump skill then the cicd skill; the PR paragraph is h15's contract; cite the colleague second-opinion divergence honestly (post-hoc shape rejected; artifact 167b06e844d1 graded 4/5); note the parked v1 pre-existing fill-line until_done leak as a filed follow-up issue
- depends on: t1, t4, t6
- covers: c1, h1, c13, h12, c15, h14, c16, h15, c17, h16
- acceptance:
  - version bumped once (minor) with CHANGELOG entry naming all three issues; version-check CI passes
  - the success-signal counts hold in tests: gate runs 1x vs 3x on a 3-episode chain, session max_steps stays 1, cap=0 allows a 5th compaction, cap=2 suppresses the 3rd — test names cited in the PR body
  - PR body carries 'Closes #334', 'Closes #335', 'Closes #336' + one operator-verifiable paragraph on gate cost saved and knobs gained (both fronts named)

## Risks

- [unknown_nonblocking] the union changed-set on the final episode can name files a later episode deleted; the filter-to-existing rule covers it, but a RENAMED file's old path silently drops out of gating — advisory-only exposure, accepted
- [unknown_nonblocking] loop.py is one large file: t3 (fillline reads ~1250-1270), t5 (ContextControls ~630), t6 (gate block ~4150) touch disjoint regions but the same file — waves must serialize loop.py tasks to avoid merge friction (t3 -> t5 -> t6 ordering via deps)

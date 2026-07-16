# indefinite-run follow-ups wrap-up

> colleague wraps up the three indefinite-run follow-ups: a session-passed --max-steps survives mode profiles (#336), a chain-armed run defers its pre-finish gates to the final episode instead of re-running them every episode (#335), and the per-run compaction cap is an operator config knob COLLEAGUE_COMPACTION_CAP with 0=unlimited (#334)

## Audience

- colleague operators running --until-done chains and interactive sessions, plus this repo's CI (the gates + version-check jobs)
  - instruction: the spec names both fronts (work + session) and CI as consumers; verify each requirement states which front it touches

## Before → After

- Before: today: a session-passed --max-steps is silently refilled by the mode profile (#336, worked around in tests via COLLEAGUE_MAX_STEPS env); a chain-armed run re-runs all four pre-finish gates on every episode though only the final hands off (#335); tuning the compaction cap requires a code change (#334)
  - instruction: reproduce each on main before building: run the new #336 test red; read a chained artifact's per-episode gate reports; grep DEFAULT_COMPACTION_CAP
- After: after: run_session marks explicit_knobs like cmd_work so --max-steps survives profiles; a chain-armed run skips gates on continuation-shaped exits and runs them once on the final episode over the chain-cumulative changed set; COLLEAGUE_COMPACTION_CAP (env > config.json 'compaction_cap' > default 4, 0=unlimited) tunes the fill-line compaction cap; all three issues close in one PR
  - instruction: trace each after-state item to its requirement's honesty condition in the test run

## Why it matters

- mid-chain gates burn model turns + wall-clock per episode for advisory reports nobody hands off; a refilled --max-steps makes session budgeting lie to the operator; an untunable cap contradicts the operator-knob convention the same arc established for max_episodes
  - instruction: write the PR body paragraph; verify it names episodes-saved gate runs + the two knobs

## Requirements

- run_session (colleague/cli/_commands/session.py ~3017) resolves max_steps from args but never marks config.explicit_knobs; mirror cmd_work's marking (work.py:1701-1703: explicit_knobs = frozenset({'max_steps'}) when args.max_steps is not None) so apply_mode_profile via _moded_config (work.py:484-494, shared by both fronts inside execute_work) never refills a session-passed --max-steps
  - honesty: a unit test dispatches a session work item with --max-steps N through a mode-profiled path and asserts the effective config.max_steps == N (fails on main today)
- tests/test_session_chain.py:304 works around the bug with monkeypatch.setenv COLLEAGUE_MAX_STEPS=1; once fixed, the e2e should pass --max-steps as the flag it originally wanted, proving the fix end-to-end
  - honesty: tests/test_session_chain.py's e2e passes with the --max-steps flag in place of the COLLEAGUE_MAX_STEPS=1 env workaround
- add COLLEAGUE_COMPACTION_CAP riding the max_episodes precedent (config.py: _load_chain_overrides reads top-level config.json keys as raw strings at 836-859; resolve leg _try_int(_pick(None, ENV, default=_file_or_default(file_val, str(default)))) at 2116-2124): env > config.json top-level 'compaction_cap' > default 4; 0 = unlimited per the existing convention (fillline.cap_reached already treats cap <= 0 as unlimited)
  - honesty: precedence unit tests: COLLEAGUE_COMPACTION_CAP env beats config.json 'compaction_cap' beats the default 4; a malformed value falls back to 4; 0 resolves and is passed through as unlimited
- loop.py consumes the knob at its two read sites: _fillline_cap_reached (1250-1255) and _record_fillline_cap (1270) both read fillline.DEFAULT_COMPACTION_CAP at call time today; the docstring already promises 'the knob can wire in without touching this seam' since cap_reached(count, cap) takes the cap as a parameter
  - honesty: with cap resolved to 2, the third fill-line crossing in one run is suppressed and the recorded note names the resolved cap (not the constant); with the knob unset behavior is byte-identical to DEFAULT_COMPACTION_CAP=4
- the new knob appears in 'colleague config show' output (EngineConfig.to_dict ~line 2150 lists sibling numeric knobs like max_steps/context_budget_tokens)
  - instruction: add 'compaction_cap' to EngineConfig.to_dict; assert via a config-show test
  - honesty: 'colleague config show' output includes compaction_cap with its resolved value
- the four pre-finish gates run on EVERY non-aborted loop exit (loop.py:4152-4175: lint #200, coherence #294, test-integrity #203, affected-tests #213), so a chain-armed run pays them per episode though only the final episode hands off; defer them so they run effectively once per chain
  - instruction: chained mock e2e in tests/: assert mid-episode artifact has no lint/coherence/test-integrity/affected-tests reports + carries the deferral note; final artifact has them
  - honesty: a chained mock e2e (>=2 episodes) asserts mid-chain episode artifacts carry NO gate reports but DO carry a recorded deferral note, and the final episode's artifact carries the gate reports
- docs stay honest: docs/features/capacity-standard.md + indefinite-run.md currently record 'not yet an operator knob' (#334) and 'a recorded follow-up, not built' (#335) — both statements must flip when the code lands, same-PR (trim discipline / honesty h4)
  - instruction: edit docs/features/indefinite-run.md (lines ~149/178/188) + capacity-standard.md (~38/64): name COLLEAGUE_COMPACTION_CAP + the gate deferral incl. the halted-chain gap; grep for the stale phrases after
  - honesty: post-change grep of docs/features/ finds no 'not yet an operator knob' (capacity-standard/indefinite-run) and no 'a recorded follow-up, not built' for #335; new statements name the shipped knob + deferral honestly including the halted-chain gap
- the gate-skip predicate keys on being a chain-DISPATCHED episode — threaded from ChainEpisodeOptions (passed ONLY by execute_work_chain) through execute_work into ContextControls (e.g. chain_episode: bool) — NEVER on config.until_done: subagent children inherit the parent config verbatim (subagents.py dataclasses.replace(parent_config, ...)) and run the same loop, so an until_done-keyed skip would wrongly disable gates inside every subagent of an armed run
  - instruction: unit test: a loop run with config.until_done=True but NO chain episode option still runs gates on a budget exit; a chain-dispatched episode skips
  - honesty: the new unit test proves a subagent-shaped run (until_done=True, no chain dispatch) still runs gates; grep shows the skip guard reads the ContextControls chain-episode field, not config.until_done
- the loop-side continuation-shaped predicate REUSES colleague.chain's classification helpers (or an equivalence unit test pins loop-skip <=> chain-continues) so the skip decision and the chain verdict can never drift apart
  - instruction: prefer importing/deriving from chain.py's should_continue signals (budget-exhausted allow-list + declared_capacity_handoff); at minimum an equivalence test enumerates every exit shape
  - honesty: either the guard imports chain.py's signal helpers or a test enumerates exits {ok-finish, budget, capacity-handoff, timeout, error, empty-turn} asserting skip <=> chain-would-continue

## Honesty conditions

- the PR body carries 'Closes #334 / #335 / #336' and the full suite is green on the branch
- the PR's diff of colleague/fillline.py is empty or comment-only (the knob lives in config resolution + loop consumption)
- a unit test on the loop's gate guard asserts skip fires exactly on (chain_armed AND (outcome == budget-exhausted OR capacity_decision.kind == finish-with-handoff)) and never otherwise
- the existing gate test files pass unmodified (unarmed gate behavior byte-identical)
- the exported spec names both fronts (work + session) per requirement so no front silently forks (the all-fronts session/work symmetry)
- each before-state fact is reproducible on main: the session refill (test red on main), per-episode gate runs (visible in chained artifacts), the constant cap (grep fillline.py)
- each after-state fact maps to a merged requirement claim (c2/c4/c5/c7/c8) whose honesty condition passed
- the PR description states the per-episode gate cost saved and the operator knobs gained, in one paragraph an operator can verify
- the named counts hold in tests: gate runs 1 vs 3 on a 3-episode chain; max_steps stays 1; cap=0 allows a 5th compaction; cap=2 suppresses the 3rd; full suite green

## Success signals

- a 3-episode mock chain runs each pre-finish gate exactly 1 time (final episode only), vs 3 today; 'colleague session --max-steps 1' keeps max_steps == 1 after mode-profile application; COLLEAGUE_COMPACTION_CAP=0 permits > 4 compaction turns in one run and =2 suppresses the 3rd; unarmed single-episode runs byte-identical (full suite green)
  - instruction: encode each count as a test assertion (gate-run count, max_steps==1, cap 0/2 behavior); cite test names in the PR

## Scope / boundaries

- fillline.py keeps DEFAULT_COMPACTION_CAP = 4 as the module-constant default and cap_reached's signature is untouched; the knob lives in config resolution, not in fillline
- unarmed runs (until_done false) are byte-identical: gates run exactly as today; the deferral activates only when chain-armed
  - instruction: run the existing gate test files untouched; any edit to them for this change is a spec violation

## Non-goals

- no new CLI flag for the compaction cap: #334 asks for env + config.json only (COLLEAGUE_COMPACTION_CAP + 'compaction_cap' key); a --compaction-cap flag is not requested and stays out

## Assumptions

- the loop can already recognize a continuation-shaped exit AT gate time: ContextControls.chain_armed exists (loop.py:635-638, set from config.until_done at 2699), and the continuation signals (budget-exhausted outcome; TaskResult.capacity_decision.kind == finish-with-handoff per deviation d1) are all set before the gate block runs

## Scope exploration

- `s1` — `colleague/cli/_commands/session.py run_session + work.py _moded_config`: session resolves max_steps at line ~3020 but never sets explicit_knobs; the mode profile applies inside execute_work for BOTH fronts, reading config.explicit_knobs — cmd_work marks it (work.py:1701-1703), run_session does not
  - seeds: `c2`
- `s2` — `tests/test_session_chain.py`: line 304 sets COLLEAGUE_MAX_STEPS=1 env explicitly as the workaround the issue names; flipping it to the flag is the natural regression proof
  - seeds: `c3`
- `s3` — `colleague/config.py resolve() + _load_chain_overrides`: max_episodes (same arc, same 0=unlimited convention) is the exact precedent: top-level config.json key read as raw string, env > file > default via _pick/_file_or_default; note top-level context_budget in config.json is SILENTLY IGNORED (known gotcha) so the file leg must be wired deliberately
  - seeds: `c4`
- `s4` — `colleague/loop.py _fillline_cap_reached/_record_fillline_cap`: both sites read the module constant at call time and their docstrings name the follow-up knob explicitly; cap_reached signature already parameterized, so consumption switches to the resolved config value
  - seeds: `c5`
- `s5` — `colleague/fillline.py`: DEFAULT_COMPACTION_CAP = 4 at line 70 with the deliberate 'module constant for now' comment (t1 file boundary); cap_reached(count, cap) already takes cap as a parameter with cap<=0 = unlimited
  - seeds: `c6`
- `s6` — `colleague config show / EngineConfig.to_dict`: sibling knobs (max_steps, context_budget_tokens, max_output_chars) all render in to_dict; a knob missing there contradicts config-show provenance (#322 lineage)
  - seeds: `c7`
- `s7` — `colleague/loop.py run() exit sequence 4120-4180`: gates are called unconditionally on loop exit (aborted guard inside each helper); ordering lint -> coherence -> test-integrity -> affected-tests, later gates see the lint-fixed changed set; NOTE the issue names three gates but there are FOUR pre-finish gates (coherence #294 too)
  - seeds: `c8`
- `s8` — `colleague/loop.py chain_armed + colleague/chain.py exit classification`: chain.py should_continue's allow-list is {budget-exhausted} + declared_capacity_handoff(result); both signals exist on ctx/result before loop.py:4152 — so in-loop skip of non-final episodes is feasible without new plumbing
  - seeds: `c9`
- `s9` — `colleague/cli/_commands/work.py execute_work_chain/_chain_finalize (1119-1230, 1321+)`: _chain_finalize calls handoff.chain_handoff_finalize post-hoc on the final branch — a candidate site for a forced final gate pass, BUT the lint gate's model fix-turn needs the live loop, so a purely post-hoc pass would be degraded
  - seeds: `c10`
- `s10` — `docs/features/capacity-standard.md + indefinite-run.md`: both docs honestly record the current gaps by issue number; landing the code without flipping the docs would leave them lying in the other direction
  - seeds: `c12`
- `s11` — `challenge pass / adjacent-systems lens: colleague/subagents.py run_subagent config inheritance`: child_config = dataclasses.replace(parent_config, ...) copies until_done; children run the same loop.run() with gates — an until_done-keyed skip predicate leaks into subagents; seeded the ContextControls-threading requirement
  - seeds: `c22`
- `s12` — `challenge pass / assumptions lens: colleague/chain.py should_continue vs loop.py outcome strings`: chain classifies from persisted terminal facts (not_finished, capacity_decision) while the loop has the live outcome string; timeout exits are NOT continuation-shaped (allow-list is exactly budget-exhausted + declared handoff) so a drifted predicate would silently over- or under-skip
  - seeds: `c23`
- `s13` — `challenge pass / lifecycle lens: artifact consumers of gate reports (cockpit Last-run, feedback export, tui snapshot)`: gate reports are omit-when-None on the artifact already (advisory contract), so mid-chain artifacts without them break no consumer; clean pass
- `s14` — `challenge pass / security+concurrency+migration lenses: config.py knob resolution + sequential chain loop`: additive knob with no secret value, redacted-view unaffected; chain loop is sequential in one process, no new concurrency; no migration (default preserves DEFAULT_COMPACTION_CAP=4); clean pass
- `s15` — `challenge pass / observability lens: deferral + cap notes`: mid-chain skip records a deferral note per c8; the cap note names the RESOLVED cap per h5; halted-chain skipped gates stay visible on episode artifacts; clean pass with the h5/c8 conditions as the containment

## Decisions

- gate-deferral shape (a): in-loop skip on continuation-shaped exits; final episode gates run in-loop over union(this episode's changed, prior episodes' changed files that still exist in the worktree); a halted chain's skipped gates are recorded, not backfilled
- all FOUR pre-finish gates defer uniformly — lint #200, coherence #294, test-integrity #203, affected-tests #213 — though issue #335 names three; deferring three and re-running coherence per-episode would be inconsistent for the same redundancy
- one PR closes all three issues with one minor version bump (the #328 consumer-trust-batch precedent); each issue's change stays a separately testable commit-scoped unit
- colleague's independent explore (artifact 167b06e844d1) recommended the post-hoc shape (skip always + degraded detect-and-record re-run in _chain_finalize); rejected in favor of shape (a) because post-hoc loses the lint fix-turn / test-integrity re-examine (colleague's own flagged risk), needs a duplicated gate runner outside the loop's ctx, and gates only the final episode's changed_files (missing prior episodes' files); colleague's seam map (ContextControls plumbing, finality-unknowable, fix-turn dependency) independently confirms the constraints

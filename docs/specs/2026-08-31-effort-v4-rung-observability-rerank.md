# effort-v4-rung-observability-rerank

> colleague drops its acting/associate/purpose effort defaults to the v4 low set, records the resolved effort rung per seat on the run artifact so effort experiments are verifiable from the run's own record, and its eidetic recall lane is rerank-aware
> instruction: run the full suite; the effort override tests (`test_effort.py` precedence cases) must pass unchanged

## Audience

- colleague operators running local-model rigs (Qwen3.8 via lobes) and anyone reading a run artifact to diagnose or A/B effort behavior

## Before → After

- Before: a bounded refactor fails by thinking (133,637 reasoning chars, 0 files changed, 2851s) at the v3 medium defaults; the rung a run used is not recorded anywhere and the reasoning text itself is dropped after len(); an effort A/B must re-derive its independent variable from source that may have changed
- After: acting/associate/purpose seats default to low (v4); every artifact records the resolved rung per seat; the model's reasoning text is readable post-run from a gitignored sidecar; recall is safe against a future --rerank opt-in

## Why it matters

- the hard-1000-line arc's own honesty condition (h24) showed file size was never the binding constraint — uncapped acting-seat reasoning is; fixing the tables without fixing observability would make every future effort claim as weakly evidenced as #475's was

## Requirements

- effort.`SEAT_TABLE` moves cortex/worker/evaluator medium->low and associate off->low (v4, per the #475 measurement: 133,637 reasoning chars vs 414 answer chars, 0 files changed, stream guard at 1800s); deepthink/design stay xhigh, senses stays off
  - instruction: grep tests/`test_effort.py` for the (`SEAT_TABLE`, seat, rung) tuples; run `test_thinking_effort_docs.py`
  - honesty: the v4 `SEAT_TABLE` is pinned row-for-row in tests and rendered once in docs/features/thinking-effort.md, both updated in the same commit
- efforttables.`ASSOCIATE_SEAT_TABLE` moves every row to low (scout/compact/synthesis/digest off->low; distill already low) and `PURPOSE_TABLE` moves every row to low (plan/`handover_to_colleague` medium->low are the exposed pair)
  - instruction: the test asserting the two scout rows agree changes to assert the NEW deliberate relationship (or its removal is commented with the v4 rationale)
  - honesty: breaking the pinned `ASSOCIATE_SEAT_TABLE`-scout == `ROLE_TABLE`-scout agreement is recorded in the changed test with a comment naming this arc, never silently
- `associate_seats`.`FALLBACK_EFFORT` moves low->off — the fallback is cortex occupying the associate seat, and cortex above off over-thinks a shallow scout lane; the seeming contradiction with `SEAT_TABLE`\[associate\]=low is two different models in one seat (Nemotron needs low as its floor, cortex needs off)
  - honesty: `FALLBACK_EFFORT`=off and `SEAT_TABLE`\[associate\]=low are both asserted with the two-models-one-seat rationale in the test, so a future reader cannot 'fix' the seeming contradiction
- the table pins move with the values: tests/`test_effort.py`'s row-for-row pin list (lines 26-44 + 223-226), the sibling effort test modules (`test_effort_groups`, `test_associate_seats`, `test_associate_config`, `test_purpose_tools_boundary`, `test_subagent_thinking_effort`, `test_vllm_thinking_effort`, `test_thinking_effort_docs`), and docs/features/thinking-effort.md's 'v3 default table' section (which the docs test pins) all update to v4 in the same change
  - honesty: no v3 value survives anywhere: grep for 'medium' across the effort modules, tests, and thinking-effort.md returns only deliberate mentions (ladder vocabulary, history), never a live default
- \#476 lands as option 1: FinishRecord gains a `reasoning_effort` field (`contract_records.py`), populated where the seat is built from the same resolved value the wire sends (effort.`effort_of` / `vllm_openai`.`_effort_for` at line 462's `sent_effort`), so the rung is joinable to the seat that used it on every artifact — the all-engines rule applies (mock records it identically)
  - instruction: extend tests/`test_e2e_mock.py` to assert the field exists on `finish_states`; `from_dict` tolerates old artifacts without the field
  - honesty: mock and vllm-openai record `reasoning_effort` identically in shape (all-engines rule); a backend that never resolves a rung records a stable sentinel, not a missing key
- the recorded rung (c6) is the RESOLVED value at the work seam, override included: work --effort <rung> lands via `_listing`.`apply_effort`(config, rung, `acting_seat`(config)) after resolve(), so FinishRecord.`reasoning_effort` must read the seat's effective rung (what the wire sends), never the `SEAT_TABLE` default — otherwise an overridden run records the wrong independent variable
  - honesty: a run with work --effort xhigh records xhigh on its FinishRecord — the recorded value is the effective rung, proven by a test that overrides and reads the artifact back
- reasoning text becomes readable post-run: the per-turn ModelResponse.reasoning (`loop_wire.py`:52) is today reduced to a char count (WorkStats.`add_generated`, `contract_records.py`:260-267) and the text dropped — the run persists it to a gitignored per-run sidecar under .colleague/ (beside the artifact, e.g. <`task_id`>.reasoning.jsonl: one record per turn with seat + turn index), size-capped, so a #475-style diagnosis can read WHAT the model thought, not just how much
  - instruction: test: run with reasoning present, assert sidecar content per turn, assert git status clean, assert context messages unchanged
  - honesty: the reasoning sidecar never lands in git (covered by the .colleague/ gitignore path) and never changes model context — display/disk only, like flight; a size cap prevents an unbounded file on a 133k-char run
- the rerank opt-in is version-safe: memory.py passes --rerank only when the installed eidetic CLI supports it (eidetic-cli >= 0.14.0) — on an older CLI the flag is withheld and recall behaves exactly as today, never an argv error that silently empties recall
  - honesty: a rig with pre-0.14 eidetic keeps working recall (test with a fake eidetic on PATH that rejects --rerank); recalled=0-because-flag-error can never recur (the #387-class failure)
- the version gate needs a real detection mechanism and an honest dark-launch note: the operator rig runs eidetic-cli 0.13.0 TODAY (probed: 'eidetic --version' -> 0.13.0; 'recall --help' has no --rerank), so the opt-in ships dormant here until the rig upgrades — memory.py detects support via one 'eidetic --version' probe (parse >= 0.14.0), never try-and-retry on argv error
  - honesty: on this rig, post-change recall output is byte-identical to today (0.13.0 withholds the flag); the version probe adds at most one subprocess call per run and its failure degrades to withholding, never to broken recall
- the sidecar has the conventional off-knob: default-on, but `COLLEAGUE_REASONING_LOG`=0 disables it byte-identically (no file, no code-path residue) — matching the one-off-knob-per-mechanic convention every adopted default carries
  - honesty: `COLLEAGUE_REASONING_LOG`=0 leaves no sidecar file and the artifact/stats unchanged vs a pre-arc run
- the c25 re-apply is loud, never silent: after v4 lands, continuing a pre-v4 run re-applies its recorded rung (e.g. medium) over the new low default — the continuation prints and records a warning naming the re-applied rung and its source artifact whenever it differs from what env/config would resolve, so an operator can see an old rung resurrected
  - honesty: a continuation test pins: recorded rung != current resolution -> warning on TaskResult.warnings naming both values; equal -> no warning

## Honesty conditions

- every default-change is byte-identical off the changed rungs: a run with explicit effort overrides set resolves exactly as before v4
- the adapter diff for this arc touches no request-building code path beyond reading the already-computed `sent_effort`
- the spec names the rig (Qwen3.8 via lobes) and the artifact reader as the two audiences and serves both in every requirement
- the before-state figures are quoted from the preserved 6daa8d083e7b artifact, not paraphrased
- each after-state clause maps to at least one requirement claim (v4->c2/c3/c4, rung->c6/c14/c22, sidecar->c16/c26, rerank->c23/c27)
- the h24 finding is cited as recorded on #475 (the 1000-line ceiling did not buy delegation), not restated stronger
- the rerun is executed AFTER the rung-recording lands, and its artifact is quoted in #475 as closure evidence
- grep of feedback export + handoff paths shows no read of the sidecar; a test asserts export output for a run WITH a sidecar contains no reasoning text

## Success signals

- the 6daa8d083e7b brief rerun at low completes inside the 1800s stream-lifetime bound with the 6 pins intact and the suite green (vs 2851s incomplete at medium, 506s Claude control), and its artifact alone — no source archaeology — names the rung each seat ran at

## Scope / boundaries

- the vLLM adapter keeps touching only the OpenAI surface: recording the rung reuses the already-computed `_effort_for` value — no new probe, no new wire field beyond the existing `chat_template_kwargs` carve-out (#476 option 3, per-turn wire recording, is not taken)
- the sidecar stays out of every sharing surface: feedback export, handoff/PR content, and mesh surfaces never read or transmit <`task_id`>.reasoning.jsonl — chain-of-thought can quote repo content (including secrets read during the run) and is local-diagnostic only

## Assumptions

- if recall opts in to --rerank, `min_score` keeps reading the hybrid score field (not `rerank_score`): #467 measures the reranker as near-binary (0.9998/0.9963 vs 0.0048/0.0035 for topically-relevant material), so a hybrid-calibrated `COLLEAGUE_RECALL_MIN_SCORE` applied to `rerank_score` would cut supporting records the reranker ranked first; ordering-sensitive consumers (`score_recall_precision`'s rank computation) must instead become order-driven rather than score-driven
- landing order: the #476 rung-recording lands FIRST, then the #475 validation rerun (the identical 6daa8d083e7b brief at low on the same rig vs the recorded arms: 2851s incomplete at medium, 506s complete Claude control) — so the rerun's independent variable is read from the run's own artifact instead of re-derived from source
- the work seam's forwarding lanes stay coherent: --background already forwards --effort verbatim (`_work_background.py` line 34's ('effort','--effort','value') tuple), and chain episodes share the one in-process config so an override rides every episode; neither needs new plumbing for v4 or #476
- the ladder-400 retry path stays interpretable: when a retry drops the `reasoning_effort` key, the artifact already records a ladder-retry warning (`vllm_payload`.`ladder_retry_warnings_as_dicts`) — FinishRecord.`reasoning_effort` records the RESOLVED rung and the warning marks that the key was dropped on the wire; the pair, together, is the honest record (no new field needed)

## Scope exploration

- `s1` — `colleague/effort.py (SEAT_TABLE, lines 60-70)`: v3 table on main: cortex/worker/evaluator=medium, associate=off — the #475 comment's 'v4 set now implemented' does NOT match main; the change is still to make
  - seeds: `c2`
- `s2` — `colleague/efforttables.py (ASSOCIATE_SEAT_TABLE + PURPOSE_TABLE)`: current values pin scout/compact/synthesis/digest=off, plan/handover=medium; module docstring notes `ASSOCIATE_SEAT_TABLE` deliberately agrees with `ROLE_TABLE`'s scout row (both off) and `test_effort.py` pins that agreement — moving associate seats to low while `ROLE_TABLE` scout stays off breaks that pinned agreement and the test must change knowingly
  - seeds: `c3`
- `s3` — `colleague/associate_seats.py (FALLBACK_EFFORT, line 82)`: main still has `FALLBACK_EFFORT`='low' with the fallback warning text embedding the rung string at line 139 — both the constant and the message surface change
  - seeds: `c4`
- `s4` — `tests/test_*effort*.py + docs/features/thinking-effort.md`: `test_effort.py` pins each table row as (table, key, value) tuples; thinking-effort.md renders the v3 table once and `test_thinking_effort_docs.py` pins doc<->source agreement — a value change that skips any of these fails CI
  - seeds: `c5`
- `s5` — `colleague/contract_records.py (FinishRecord) + colleague/loop_outcomes.py + colleague/engines/vllm_openai.py`: FinishRecord is seat/`finish_reason`/state/truncated with `to_dict`/`from_dict`; `loop_outcomes.py` line 200 hardcodes seat='main'; `vllm_openai` already computes `sent_effort` = `_effort_for`(config) on the request path — the value exists at record time, it is just never persisted
  - seeds: `c6`
- `s6` — `colleague/memory.py (recall argv, lines 133-145)`: colleague never passes --rerank today, so the #467 interaction is currently dormant; the argv is the single place an opt-in would land
  - seeds: `c7` (rejected)
- `s7` — `colleague/memory_lessons.py (filter_recall_records lines 355-383, _threshold_exclusion line 276, score_recall_precision)`: thresholding keys on the literal 'score' field and precision ranks over recalled order; under rerank the order follows `rerank_score` while score keeps the hybrid value — the two consumers split: filtering stays on score, ranking follows order
  - seeds: `c8`
- `s8` — `colleague/outputclamp.py (seat_ceiling, OUTPUT_TOKEN_CEILING=64000, DESIGN_SEATS)`: the seat-keyed ceiling still lands on the same values after v4 because the xhigh seats remain exactly {deepthink, design}; the divergence risk (an operator raising cortex to xhigh on a 64k ceiling) predates this arc and stays a follow-up
  - seeds: `c9`
- `s9` — `CLAUDE.md (vLLM adapter carve-outs) + docs/features/thinking-effort.md`: the adapter's enumerated carve-outs (stale-pin refresh, `chat_template_kwargs`, one /tokenize) are pinned convention; option 1 of #476 adds nothing to the wire so the convention holds untouched
  - seeds: `c12`
- `s10` — `issue #475 comments + .colleague/6daa8d083e7b.*.json (preserved artifact)`: \#475's own comment states the rerun will have the same weak provenance unless #476 lands first; the brief and both arms' results are preserved, making the A/B cheap
  - seeds: `c13`
- `s11` — `colleague/cli/_commands/_listing.py (apply_effort, lines 236-257)`: an explicit --effort applies to the acting seat (`acting_seat`(config), not always cortex) as a post-resolve config mutation; a bare --effort lists rungs and exits — the flag is the one CLI door into per-run effort
  - seeds: `c14`
- `s12` — `colleague/cli/_commands/_work_background.py (line 34) + colleague/chain.py`: background re-spawn forwards --effort; chain.py contains zero effort references because episodes reuse the resolved config in-process — the override survives a chain without persistence
  - seeds: `c15`
- `s13` — `colleague/loop_wire.py (ModelResponse.reasoning) + colleague/loop_accounting.py (lines 21-36) + colleague/contract_records.py (WorkStats.add_generated)`: reasoning arrives as a separate wire field per turn and only len() is kept; no surface (artifact steps, flight feed, spill-to-disk) carries the text — the flight feed is also reaped at run end, so even transient traces vanish
  - seeds: `c16`
- `s14` — `challenge pass / adjacent-systems lens: installed eidetic CLI (probe)`: eidetic-cli 0.13.0 on this rig, no --rerank in recall --help — c23's opt-in is dark on the validation rig itself; version-probe detection seeded as c28
  - seeds: `c28`
- `s15` — `challenge pass / failure-mode lens: colleague/engines/vllm_payload.py ladder retry`: `ladder_retry_warnings_as_dicts` already lands retry evidence on the artifact after every work item; the recorded-rung + retry-warning pair covers the dropped-key case
  - seeds: `c29`
- `s16` — `challenge pass / security lens: .gitignore + feedback export surface`: .gitignore lines 247-249 already ignore /.colleague/\* except commands/skills, so the sidecar path is covered as-is; the remaining exposure is export/sharing lanes, seeded as boundary c31
  - seeds: `c31`
- `s17` — `challenge pass / lifecycle lens: colleague/continuation.py + the v4 cutover`: re-applying a recorded rung across the v4 boundary silently resurrects pre-v4 defaults on continued runs; loud-warning requirement seeded as c32
  - seeds: `c32`
- `s18` — `challenge pass / concurrency lens: loop turns + toolbatch pool`: reasoning arrives only on main-thread sequential completions (the toolbatch pool runs executor.execute only, convention change (6)); sidecar writes are single-writer per run — clean pass, residual risk only if a future concurrent completion lane appears
- `s19` — `challenge pass / counter-evidence lens: docs/live-testing.md rows 49-65`: no recorded measurement contradicts the low-is-better hypothesis for this rig, but none confirms it either — the only supporting datum is the single #475 A/B; the rerun (success signal) is the counter-evidence hunt, deliberately kept as the arc's own validation

## Decisions

- artifact shape (#476): FinishRecord gains `reasoning_effort` (seat stays 'main' — the rung on the record makes a name join unnecessary) plus a top-level effort block {seat: rung} for every seat built during the run, including seats with no finish record
- recall opts in to --rerank now (supersedes the rejected c7): `COLLEAGUE_RECALL_MIN_SCORE` keeps reading the hybrid score field, ordering-sensitive consumers follow recalled order
- `ROLE_TABLE` writer/planner drop medium->low alongside the v4 tables (unmeasured for children specifically; the rerun validates)
- work --continue re-applies the recorded rung from the resumed artifact to the acting seat; an explicit --effort on the continue invocation wins over the recorded value
- the reasoning sidecar is default-on, size-capped, gitignored under .colleague/, survives the run, and is reaped by colleague clean
- child reasoning sidecars land tagged in the operator repo's .colleague/ beside the parent's, surviving worktree reap and SIGTERM — the lost-work case is exactly when they are needed

## Open parks

- [unknown_nonblocking] whether dropping effort to low alone lands the 6daa8d083e7b task inside the stream-lifetime bound, or a sampling change (small non-zero temperature / `top_p`) is also needed — measurable only by the rerun
- [unknown_nonblocking] whether the acting seat should gain `reasoning_exhausted_reason`'s treatment (a warning when `finish_reason`=length with high `reasoning_chars` and near-zero `answer_chars` — today wired only for the distill child in distilleffort.py); #475's run reported only step-stall
- [unknown_nonblocking] sidecar semantics across an --until-done chain (one task id, several episodes): append across episodes vs per-episode files, and whether the size cap is per-run or per-chain — decidable at plan time, not a spec blocker

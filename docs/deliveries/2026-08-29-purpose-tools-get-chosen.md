# Delivery Summary — purpose-tools-get-chosen

plan: `purpose-tools-get-chosen` · run: `complete` · date: `2026-08-29`
baseline: `devague summary skeleton`

## Intent

Make colleague's cortex actually choose the six typed purpose tools it has held
since #443, by fixing the defects that made delegation unmeasurable and then
measuring three separable levers as pre-registered arms. The arc executed the
16-task plan `docs/plans/2026-08-29-purpose-tools-get-chosen.md` across seven
waves: wave 1 landed the #438 stall-recovery fixes and the surface lever's
instrument (merged as PR #450, v1.67.0); waves 2-7 landed the prompt/surface
unification, the two measurement instruments, the arm-4 restoration, the prose
overlays, and then ran and recorded the 21-run arm matrix.

**The arc refuted its own founding hypothesis.** It set out to make cortex
choose its purpose tools more often; it found that cortex was already choosing
correctly, and that the premise — that #443's removal of raw
`subagent`/`subagents` is what suppressed delegation — is false.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — \#438a: bound the blocking-fallback path with the same StreamGuards
- `t2` — \#438b: stop backpressure's timeout self-raise when stream guards are armed
- `t3` — \#438c: the idle guard treats SSE keepalive lines as non-activity
- `t4` — \#438d: tally stream-guard trips onto the artifact
- `t5` — Prompt/surface unification: the depth-0 writer substitution feeds the prompt as well as the tool surface
- `t6` — Count markup-shaped tool calls for any function name on the artifact
- `t7` — Record a system-prompt digest on the artifact so a prose arm is attributable
- `t8` — Acting-seat-scoped tool drop knob (the surface lever's instrument)
- `t9` — Repair the stale SUBAGENTS prompt section in both literals
- `t10` — Author the arm briefs: re-authored decomposable brief + a large-surface brief
- `t11` — Arm 4: restore subagent/subagents to the acting seat without leaking to children
- `t12` — Author the three prose overlays P0/P1/P2
- `t13` — Row 49 validity re-run: is the 0/3 real or dropped markup?
- `t14` — Pre-register the arm rows and their pass bars
- `t15` — Close the arc: docs, honest conclusion, and the before-state record
- `t16` — Run the arm matrix and record results honestly

## Actual Delivery

All 16 tasks delivered. Wave 1 (`t1`-`t4`, `t8`, `t10`) merged to `main` as
PR #450 / `ede7d7f` (v1.67.0); waves 2-7 sit on `spec/purpose-tools-get-chosen-w2`.

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `_stream_or_blocking` builds ONE `StreamGuards` shared by the streaming reader and the blocking fallback; real-socket drip-feed test. PR #450 |
| `t2` | delivered | proactive timeout raise suppressed while guards are armed. PR #450. **Later corrected** — see `t2`/`t3` drift and `c77a269` |
| `t3` | delivered | `_is_comment_line`: SSE keepalives no longer refresh the idle clock. PR #450. **Later corrected** — see drift and `a745521` |
| `t4` | delivered | `stream_guard_trips`, the 6th key in `colleague/runcounts.py`, folded from `step-stall` warnings naming a stream guard. PR #450 |
| `t5` | delivered | `actingsurface.substitute_bare_role` + `acting_role_name`: one resolution feeds prompt AND surface. Bare run and `--role writer` now compose an identical prompt (4076 chars each; was 0 vs 4076). Commit `956e49c` |
| `t6` | delivered | new `colleague/toolmarkup.py` (detection only) + `markup_tool_calls`, the 7th run counter, bumped per turn in `_account_turn`. Commit `1f36616` |
| `t7` | delivered | `TaskResult.prompt_digest` (sha256 of the composed prompt), beside `config_digest`, omitted-when-None, set by both engines. Commit `929bb20` |
| `t8` | delivered | `COLLEAGUE_ACTING_DROP_TOOLS` drop-set threaded through `narrow_role_by_tool_set`, depth-0 only. PR #450. **Later corrected** — see drift and `7562fbf` |
| `t9` | delivered | both duplicated literals repaired: `_SUBAGENTS` → `_PURPOSE_TOOLS`, 174 → 165 words; snapshot regenerated under `d1`. Commit `95c921b` |
| `t10` | delivered | `arm-decomposable-neutral.md` + `arm-large-surface.md`; the large-surface pilot returned a NEGATIVE result recorded as such. PR #450. Fixture generator later corrected — see drift |
| `t11` | delivered | `_writer_allowlist` drops only `web`; `strip_purpose_tools` → `strip_child_forbidden_tools` also strips the raw pair at depth ≥1. Four exact-set pins updated, never relaxed. Commit `ab76f74` |
| `t12` | delivered | P0/P1/P2 overlays staged under `docs/live-testing/overlays/`, identical `effort: medium` line; `diff P1 P2` is exactly one paragraph. Commit `847ef9d` |
| `t13` | delivered | row 51: row-49 brief re-run n=3, **delegation 0/3, markup 0/3** — the 0/3 is real behaviour, not dropped markup. Commit `25a8c63` |
| `t14` | delivered | rows 52-58 pre-registered with `result: pending` and their bars, committed 01:31:56 before the matrix started 01:33:36. Commit `3b59d24` |
| `t15` | delivered | closing record; before-state recomputed from source, correcting two stale doc figures. Commit `26c9a3a` |
| `t16` | delivered | 21/21 runs, all `ok`, all digests matched, zero voids; rows 52-58 filled. Commit `412992d` |

## Mid-work Decisions

- `d1` (approved) — t9 regenerates `tests/snapshots/prompttext_v1.txt`; c39's
  no-change guarantee is scoped to the prose arms' instruments (the P0/P1/P2
  overlays), not the base v1 snapshot. Plan risk r3 named a conflict between
  two confirmed claims: c39/h28 promise the v1 snapshot is unchanged across the
  whole arc, while c2/h10 require the default prompt to stop naming
  subagent/subagents, which the acting seat no longer holds. Operator ruled r3
  in favour of c2/h10 with c39 narrowed. Consequence carried into t16: every arm
  run must execute on the post-t9 tip so no arm compares across a prompt change.
- `d2` (approved) — t5 lets the three-tier worker seat's composed prompt gain
  the writer fragment. The worker IS the depth-0 acting seat with no
  `config.role`, so `curate_for_depth` has offered it the writer's tool surface
  since d14; excluding it would require a second condition the surface half does
  not have. No pre-existing test pinned that seat's prompt. Operator accepted the
  consequent shift of the `three_tier` benchmark baseline.
- `d3` (**proposed — awaiting operator confirm**) — t12 was built by a Claude
  subagent, not by colleague, after two consecutive colleague dispatches produced
  no files (attempt 1 exited 0 with zero output; attempt 2 stalled past 10
  minutes). Neither run left a salvageable partial.
- **Build split by task shape** (operator ruling, no `dN` record) — Claude
  subagents for large-file cross-module work (t5, t6, t7, t11, t14, t15, t16),
  colleague for authoring. Taken after wave 1's evidence: all 6 colleague runs
  finished INCOMPLETE, every one salvaged only by the #222 WIP-on-stop sweep.
- **t9-vs-t11 conflict resolved without escalation** — t9's acceptance
  ("`subagent`/`subagents` appear nowhere in the composed prompt") and t11's
  restoration of those tools appear to contradict. They do not: the defect
  c2/h10 targets is advertising tools the seat does NOT hold. A present but
  undescribed tool is safe in both arm states, because the baseline arm removes
  the pair again via t8's drop knob. Recorded in `95c921b`'s message so a later
  reader does not "fix" it back.
- **The matrix was restarted** — the first launch began 33 seconds BEFORE t14's
  pre-registration commit, breaking the one guarantee pre-registration exists to
  give. Two of 21 runs were affected; the run directory was wiped and the matrix
  restarted from the pre-registration commit.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t9` (`d1`) | c39/h28's whole-arc snapshot guarantee conflicts with c2/h10's requirement that the default prompt stop naming absent tools; operator narrowed c39 to the prose-arm instruments | acceptable |
| `t5` (`d2`) | the three-tier worker seat's composed prompt gains the writer fragment, so acceptance 3's "compose exactly as before" is NOT met for that one seat; the `three_tier` benchmark baseline shifts with it | acceptable |
| `t12` (`d3`) | built by a Claude subagent rather than colleague after two colleague dispatches produced no files; the fallback preserved the wave rather than blocking the arc | acceptable |
| `t2`, `t3`, `t8`, `t10` | all four shipped defects that PR #450's review caught and that were fixed on the same PR: `t2`/`t3` gated escalation on the ENV rather than the active transport and refreshed the idle clock only per newline-terminated line; `t8` ignored `drop` when `tool_set` was also given; `t10`'s fixture generated one 8-way duplicate rather than four distinct pairs, over-many public functions, and only one of two call edges. All fixed pre-merge | acceptable |
| `t16` | the arm matrix answers the arc's question in the NEGATIVE: neither declared lever moved the delegation rate. The task was executed exactly as specified; the plan's implicit expectation that a lever would move it was not met | acceptable |
| `t10` | the large-surface brief's acceptance required a "non-delegating baseline [that] provably hits a budget or context limit". The pilot showed the acting seat greps a symbol index and does ranged reads rather than `read_file`, so no such limit is hit; recorded as a negative result rather than forced. The brief still worked — arms A5/A6 delegated — but for a different reason than the acceptance assumed | needs-follow-up |

## Evidence

- tests: full suite `uv run pytest -n auto -q` — **10402 passed, 51 skipped, 0 failed**
- tests: `tests/test_toolmarkup_count.py` — 13 passed (validates t13's measured zero)
- tests: `tests/test_prompt_surface_unification.py` — 18 nodes (t5)
- tests: `tests/test_prose_overlays.py` — 22 nodes (t12)
- tests: `tests/test_contract_prompt_digest.py` — 14 nodes (t7)
- lint: `black --check` / `isort --check-only` / `flake8` over `colleague tests scripts` — clean
- security: `bandit -c pyproject.toml -r colleague` — 0 High / 0 Medium / 0 Low
- markdown: `markdownlint-cli2` on every changed file — 0 errors
- alignment: `doc-test-alignment` — `aligned: true` (1413 advisory warnings, all pre-existing)
- commits (waves 2-7): `956e49c..26c9a3a` (10 commits)
- commits (wave 1): merged as `ede7d7f`
- PRs: #450 (merged, v1.67.0)
- issues raised by this arc: #451, #452, #453, #454
- live matrix: 21 artifacts, ids listed in `docs/live-testing.md` rows 52-58

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A bare run and an explicit `--role writer` run compose an identical system prompt and tool surface | high | commit `956e49c` · test `tests/test_prompt_surface_unification.py::test_bare_run_and_explicit_writer_compose_identical_prompt` |
| An operator overlay at `.colleague/agents/writer.md` reaches a bare run (was unreachable) | high | commit `956e49c` · measured 0 → 8003 chars · test `…::test_operator_writer_overlay_reaches_a_bare_run` |
| The default prompt no longer names `subagent`/`subagents`, and names all six purpose tools | high | commit `95c921b` · test `tests/test_prompttext.py::test_default_prompt_never_names_the_raw_delegation_tools` |
| Markup-shaped tool calls are counted for any function name, and never executed | high | commit `1f36616` · test `tests/test_toolmarkup_count.py::test_markup_naming_a_real_tool_never_runs_it` |
| A prose arm is attributable: the artifact carries a sha256 digest of the prompt that actually ran | high | commit `929bb20` · verified live — the composer's no-overlay digest `b7491476a61238a4` matched all 9 no-overlay run artifacts |
| Row 49's 0/3 delegation is real behaviour, not dropped markup | high | `docs/live-testing.md` row 51 · commit `25a8c63` · markup 0 on 3/3 runs with the counter proven live |
| Neither the prose lever nor the surface lever moved the delegation rate | high | rows 53-56 · A1/A2/A3/A4 all 0/3 · ratios 0.560/0.826, 0.908/0.913, 0.866/0.783, 0.522/0.783 |
| No `subagent`/`subagents` call occurred anywhere in the 21-run matrix, including the arm where both were on the seat | high | row 56 · commit `412992d` · tool breakdown across all 21 artifacts |
| Task shape moved delegation: 0 of 15 small-brief runs vs 5 of 6 large-surface runs | high | rows 57-58 · every delegation was `code_survey` (A5: 6, A6: 12) |
| Delegating runs succeeded equally often as non-delegating ones (5/5 vs 16/16 `ok`) | high | rows 52-58 · all 21 runs `status: ok`, each changed exactly one module |
| Cortex substitutes the parallel read-only tool batch for delegation | medium | rows 51, 57 · A5-r1 delegated 3 with `batches_run` 0; A5-r2 delegated 0 with `batches_run` 3 / `calls_parallelised` 10. Consistent across arms but not an isolated experiment |
| The P2 (capability-equal) framing raises delegation on a large surface | low | row 58 · 6 → 12 `code_survey` calls, turns 0.762×. **Confounded** — no P0 control on the large brief, so it conflates the paragraph with the fragment replacement. Explicitly does NOT promote |
| A prose effect is undetectable on the small brief | high | rows 53-55 · all five small-brief arms sat at exactly 0/3 — a floor, which is NOT evidence that prose has no effect |
| #438's stall class is closed | unverified | the four guidance points landed (PR #450) but no run in this arc reproduced the original stall class to confirm it — not claimed |
| The large-surface baseline provably hits a budget or context limit | unverified | t10's pilot REFUTED this: the seat greps a symbol index and does ranged reads, so no limit is hit — recorded as a negative result |

## Remaining Work / Follow-up

- **`d3` awaits operator confirm** — it is `proposed` (LLM-origin); until confirmed it is not a recorded decision.
- **`t10`'s unmet acceptance clause** — no brief was found whose non-delegating baseline provably hits a budget or context limit, because the acting seat surveys by grep + ranged reads rather than `read_file`. The arms still worked, so this is a follow-up, not a blocker: either re-spec the clause around the real survey strategy, or drop it.
- **The 2026-08-29 large-surface pilot ran against the superseded fixture generator** — the generator was corrected during PR #450 review (four distinct pair algorithms, 8-12 public functions per module, both call edges). The pilot's *finding* concerns the tool surface, not fixture internals, so it is unaffected — but a re-pilot on the corrected fixture is the honest re-confirmation, and none was run.
- **A clean prose test remains undone** — the isolated prose contrast (A3-vs-A1) sat at a floor, and the only contrast that moved (A6-vs-A5) is confounded. A clean test needs a P0-control arm on a brief that is not already at zero. Until then P2 does not promote into `BUILTIN_ROLES['writer'].prompt_fragment`.
- **Issues filed, unresolved:** #451 (a stalled authoring run leaves no partial, no artifact, and can exit 0 silently), #452 (the step budget has no headroom for the finishing commit — 5 of 5 runs), #453 (`work --continue` re-bases on HEAD, discarding what #222 saved), #454 (`COLLEAGUE_UPDATE_SNAPSHOTS=1` was a silent no-op; fixed in `95c921b`, but the general hazard of test-time `COLLEAGUE_*` reads remains).
- **`three_tier` benchmark rows before `956e49c` are not comparable** (`d2`) — the worker seat's prompt changed. Re-running the #346 benchmark on the new tip was offered and not taken.

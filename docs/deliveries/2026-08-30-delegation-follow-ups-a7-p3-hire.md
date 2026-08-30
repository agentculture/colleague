# Delivery Summary — delegation-follow-ups-a7-p3-hire

plan: `delegation-follow-ups-a7-p3-hire` · run: `partial` · date: `2026-08-30`
baseline: `devague summary skeleton`

## Intent

Phase A of the plan: run the two follow-up arms #456 asked for — the
raw-vs-purpose fair fight (A7) and a size-trigger prose arm with a clean
control (P3) — as one pre-registered matrix on the large-surface brief, take
the q3 promotion decision on measured numbers, and ship the arms PR
(v1.69.0). Phase B — `hire_colleague` as a twelfth sanctioned increment
(t9–t18, t20) — was planned behind the arms PR and did not run in this
delivery. Mid-run the operator added the nemotron scout arm (d2), the
associate default-ON task (d3, parked by d5), the explicitly-requested
delegation arm R (d4), and the associate window/sampling fixes (t21–t23).
PR #464 merged as `8a5b1f5`.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Add-knob: `COLLEAGUE_ACTING_ADD_TOOLS` at the depth-0 seam
- `t2` — Persist `offered_tools` on TaskResult for both engines
- `t3` — Stage the P2-0 control and P3 trigger overlays
- `t4` — Surface both new knobs in config show and the config digest
- `t5` — Pre-register rows 59-61 (A7, P2-0, P3) before any run
- `t6` — Run the 9-arm matrix and fill the cells from artifacts
- `t7` — Record the arc conclusion and apply the q3 promotion decision
- `t8` — Arms PR: version 1.69.0, CHANGELOG, PR, review triage
- `t9` — colleague/hire.py: the Hire record, roster and prompt-never-grants role builder
- `t10` — `hire_schemas`: the two tool schemas, the `COLLEAGUE_HIRE` hidden rule and the surface splice
- `t11` — Confinement: children, agents-mode tool sets and the batch pool never hold the hire pair
- `t12` — `hire_colleague` handler: the bounded two-round negotiation, on mock and vllm
- `t13` — `assign_to_colleague` handler + TaskResult.hires block
- `t14` — Ledger refs-not-payloads event and hires dead at the cut
- `t15` — `compare_arms.py`: hires / assignments columns (versioned, before the hire row)
- `t16` — Hire arm: the repeated-sub-tasks brief, fixture generator and pre-registered row 62
- `t17` — Run the hire arm and record row 62
- `t18` — Hire docs, CLAUDE.md twelfth increment, version 1.70.0, PR
- `t19` — Associate default-ON for the non-writer purpose seats (t19, decision c45 / deviation d3)
- `t20` — Evidence-trail digests for the survey purposes (t20, decision c47)
- `t21` — Associate validation guide (t21): how to test the associate/Nemotron seat with colleague on real cases
- `t22` — \#460 fixes (t22): clamp the associate window to the served `max_model_len` and never let the alias retry hide a context-length 400
- `t23` — Per-seat sampling for the associate (t23): let the deployment's tuning apply

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `actingsurface.ACTING_ADD_ENV` / `acting_add_set()`: a depth-0 add after the drop, names restricted to `tools.SCHEMAS`, children untouched; `tests/test_acting_add_knob.py` |
| `t2` | delivered | `TaskResult.offered_tools` (omit-when-None; an EMPTY surface stays absent — a review fix), stamped identically by mock and vllm; `tests/test_contract_offered_tools.py` |
| `t3` | delivered | overlays `docs/live-testing/overlays/P2-0/writer.md` + `P3/writer.md`; `tests/test_overlays_p3.py` |
| `t4` | partial | `COLLEAGUE_HIRE` / config.json `hire` (env > file > OFF; the nested `{"enabled": …}` form reads `enabled` — a review fix) + `acting_add_tools` on `EngineConfig`, `config show` text + JSON; the "config digest" half is the d1 deviation — attestation moved to `offered_tools` |
| `t5` | delivered | rows 59–61 pre-registered before any run (`docs/live-testing.md`) |
| `t6` | delivered | 9 runs + the added arms: rows 59 (A7 0/3), 60 (P2-0 1/3), 61 (P3 0/3), 62 (nemotron, refused — #460), 63 (R-cortex 3/3 compliant, full redo, 3.2× wall), 64 (R-nemotron re-run n=3: 14/14 children on Nemotron, ranged verification 3/3, wall miss 1.626, 2.0× faster than row 63) |
| `t7` | delivered | `docs/features/purpose-tools.md` "delegation-follow-ups arc" + CLAUDE.md sentence; q3 decision: nothing promotes (P3 misses), the shipped prompt carries no delegation prose |
| `t8` | delivered | v1.69.0, CHANGELOG, PR #464 merged `8a5b1f5`; Qodo 7 threads (3 pushback, 4 fixed), 13+2 Sonar smells fixed, two colleague reviews (one delivered, one recorded miss) |
| `t9` | dropped | Phase B not started in this delivery (behind the arms PR by plan; hire arm moved to row 65 by d4) |
| `t10` | dropped | as t9 |
| `t11` | dropped | as t9 — the child confinement that exists (`CHILD_FORBIDDEN_TOOLS`) predates this plan |
| `t12` | dropped | as t9 |
| `t13` | dropped | as t9 |
| `t14` | dropped | as t9 |
| `t15` | dropped | as t9 (`compare_arms.py` unchanged, sha `f7e25fdc…`) |
| `t16` | dropped | as t9 |
| `t17` | dropped | as t9 |
| `t18` | dropped | as t9 |
| `t19` | blocked | built on `agent/t19` (`d57ce7e`, suite green there) and PARKED by d5 — not in the PR; gated on the validation ladder |
| `t20` | dropped | not started (Phase B) |
| `t21` | delivered | `docs/features/associate-validation.md` (preconditions off the rig, the #461 contract with its correction, five-case ladder, pass bars, failure shapes) |
| `t22` | delivered | `associate.served_window_budget` (one root `/tokenize` probe per (url, wire model), failures memoised, locked), context-length-400 guard, folded two-body error; `tests/test_associate_window.py`, `tests/test_associate_probe_cache.py`; proven live by row 64 (0 refusals) |
| `t23` | delivered | `AssociateProfile` depth/triage, per-value overrides (explicit thinking spellings only), the payload branch `_apply_associate_profile`; `tests/test_associate_sampling.py`, `tests/test_associate_thinking_parse.py` |

## Mid-work Decisions

- `d1` — h26's `config_digest` clause cannot hold on a bare run; t4 attests the knobs via `config show` + the EngineConfig snapshot and the artifact-side attestation is `offered_tools` — discovered while implementing t4: the digest named in h26 does not exist on the artifacts the arm rows read
- `d2` — finish the 9-run matrix as-is AND add a nemotron arm (row 62) — operator: 'scout (`code_survey`) is nemotron 3.5 lightning' — the intended topology differs from what the rig served
- `d3` — nemotron as the non-writer seat ON BY DEFAULT (new task t19) — operator: 'nemotron as the non-writer (code-survey, web-survey, etc.) should be on by default'
- `d4` — add arm R, explicitly requested delegation, rows 63/64, hire arm → row 65 — operator: 'can we merge A5+A6? (+ explicitly request delegation)'
- `d5` — the associate seat is NOT validated; Rn-2/Rn-3 skipped; row 64 re-runs on the #460 tip; t19 stays parked — operator: skip Rn-2/Rn-3; open a lobes-cli issue; add instructions for testing associate/Nemotron on real cases; until then use qwen with none/low thinking
- No deviation record covers these, captured directly: (a) the #461 correction (the second lobes comment reverses the first's thinking-off numbers) was folded into the guide as frame decision c51; (b) top-level `--role reviewer` and `--mode explore|review` now reason at `low` on the acting seat (operator rule after a cortex-`medium` review overflowed a 274k-char synthesis turn); (c) the associate-seat diff review by colleague failed twice (truncated synthesis + step-stall) and was reviewed by Claude instead; (d) a false "full suite green on 09b999b" was carried across a compaction (a piped exit code) — corrected by fixing the nine pre-existing failures in `22dccb9`; (e) the file-length ratchet baseline was moved with its sanctioned command, the per-arc convention since v1.65.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|------------------------|-----------------|
| `t4` (`d1`) | discovered while implementing t4: the digest named in h26 does not exist on the artifacts the arm rows read | acceptable |
| `t6` (`d2`) | operator: 'scout (`code_survey`) is nemotron 3.5 lightning' — the intended topology differs from what the rig served | acceptable |
| `t6` (`d3`) | operator: 'nemotron as the non-writer (code-survey, web-survey, etc.) should be on by default' | risky |
| `t6` (`d4`) | operator: 'can we merge A5+A6? (+ explicitly request delegation)' — the speed question needs delegation to actually happen | acceptable |
| `t19` (`d5`) | operator: skip Rn-2/Rn-3; open a lobes-cli issue; add instructions for testing associate/Nemotron on real cases; until then use qwen with none/low thinking | risky |
| `t9`–`t18`, `t20` | Phase B (the hire increment) was sequenced behind the arms PR and not started; the plan's row for the hire arm moved 62 → 63 → 65 (d2, d4) | needs-follow-up |
| `t8` | the PR also carries the low-effort top-level review default, the #461 correction, and the review-round fixes — none in the task's contract | acceptable |

## Evidence

- tests: `uv run pytest -n auto -q` on `main` @ `8a5b1f5` — `10518 passed, 51 skipped` — exit 0 (read directly, not through a pipe)
- lint: `uv run flake8 colleague tests` — clean; `uv run black --check colleague tests` — clean; markdownlint clean on every touched `.md`
- commits: `daedbc6..8a5b1f5` (squash-merged PR #464; branch history 79a42c1…08bfe56)
- PRs / issues: PR #464 (merged 2026-08-30T18:48Z); closes #460; refs #456, #457, #458, #459, #461, #462, #463, lobes-cli#234, lobes-cli#235
- live-testing: rows 59–64 in `docs/live-testing.md`; artifacts row 64: `d5c57e32a644`, `a3e4b1726bf9`, `a56de2c569e6` (tip `d0ff8c0`); comparator sha `f7e25fdc…`
- colleague reviews: knobs diff task `8e658025caa2` (delivered); associate diff tasks `6267ef2f4fec`, `657afd0187f6` (incomplete — recorded miss)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A7: offering the raw pair beside the purpose tools does not move delegation (0/3 by either form) | high | row 59 · artifacts' `offered_tools` · `tests/test_acting_add_knob.py` |
| P3 does not promote (0/3; turns 1.286×, reasoning 123k vs 9.8k) against the P2-0 control | high | rows 60–61 · `scripts/compare_arms.py` (sha `f7e25fdc…`) |
| Requested delegation on cortex children is compliant but 3.2× slower with a full redo | high | row 63 · artifacts `e3b34f4bd27c`, `77a8f51496d3`, `8da050ce241c` |
| On the fixed tip, Nemotron children run without refusal and the parent verifies digests by ranged reads (3/3) | high | row 64 · artifacts `d5c57e32a644`, `a3e4b1726bf9`, `a56de2c569e6` |
| Delegation to Nemotron is faster than cortex children (2.0×) but slower than in-seat (wall ratio 1.626 vs P2-0; 3.8–5.3× the 392 s bar) | high | row 64 · `compare_arms.py` output quoted in the row |
| #460 is fixed (served-window clamp; the alias retry never hides a context-length 400) | high | `colleague/associate.py` · `tests/test_associate_window.py` · row 64 (0 refusals) · issue #460 closed |
| The associate sends the operator's measured `depth` profile | high | `colleague/associate_config.py` · `tests/test_associate_sampling.py` · `Rn2-*.config.json` captures |
| `TaskResult.offered_tools` identifies a surface arm off the artifact on both engines | high | `tests/test_contract_offered_tools.py` · `tests/test_e2e_mock.py` key sets |
| `COLLEAGUE_HIRE` resolves env > config.json > OFF and is attestable from `config show` | high | `tests/test_config_hire_knobs.py` |
| Top-level reviews reason at `low` and this prevents the synthesis overflow | medium | `tests/test_effort_top_level_mode.py` (the rule) · one observation: 37 steps/23 min at `low` vs a 30-min stall at `medium` (n=1 each — not a measured arm) |
| Nemotron (thinking on) beats cortex-`low` on the survey task | unverified | no arm ran cortex children at `low` (row 63's ran at `off`); #459's decision rule |
| `hire_colleague` exists | unverified | Phase B not started — not claimed |

## Remaining Work / Follow-up

- `t9`–`t18`, `t20` — Phase B, the hire increment: scope it as its own PR (v1.70.0) with the hire arm as row 65; owner: the next workforce run.
- `t19` — associate default-ON stays parked on `agent/t19`: rebase after the validation ladder (`docs/features/associate-validation.md`) has a green row and #459's per-lane decision is taken.
- #458 — the purpose child's 12-step cap is unapplied (children read to 460k–846k tokens); fix it, then re-run row 64 as row-64b (pre-registered condition) — the whole wall gap is child over-reading.
- #459 — fixture-scored digest quality for `code_survey`/`web_survey`/memory, with the #461 correction folded in; decides qwen-`low` vs nemotron per lane.
- #462 / #463 — future purpose tools; `run_command` reason + slower-warning — issues only.
- Row 64 — the Orin's serving parameters are still to be pasted beside the row by the operator (the origin refuses without its key).
- lobes-cli#234 / #235 — advert carries the served window; `thinking_budget` on vLLM.
- The colleague second opinion on the associate-seat diff never completed on cortex (two attempts) — a recorded miss; re-attempt on the associate seat once validated, or accept Claude's review as the second opinion.

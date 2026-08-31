# Delivery Summary — delegation-follow-ups-a7-p3-hire

plan: `delegation-follow-ups-a7-p3-hire` · run: `complete` · date: `2026-08-30`
baseline: `devague summary skeleton`

> Supersedes the Phase-A-only version of this artifact committed in PR #465
> (run: `partial`); that text stays in git history. The plan is now fully
> executed except `t19`, which remains blocked by an operator decision.

## Intent

Answer #456's two follow-up questions (the raw-vs-purpose fair fight A7, and a
size-conditional prose arm P3 with a clean control) on measured numbers, then
build #457's `hire_colleague` as a twelfth sanctioned surface — a run-scoped
employee with an agreed purpose — and decide its default on evidence rather
than intent. Delivered in two waves: Phase A (arms + the associate fixes the
arms exposed) as PR #464, Phase B (the hire increment + evidence-trail
digests) as PR #469, with the #458 follow-through as PR #468 between them.

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
| `t1` | delivered | `actingsurface.ACTING_ADD_ENV`/`acting_add_set`: depth-0 add after the drop, `tools.SCHEMAS`-restricted, children untouched (PR #464) |
| `t2` | delivered | `TaskResult.offered_tools`, stamped identically by both engines; an EMPTY surface stays absent (review fix) (PR #464) |
| `t3` | delivered | overlays `P2-0/writer.md`, `P3/writer.md` + `tests/test_overlays_p3.py` (PR #464) |
| `t4` | partial | both knobs on `EngineConfig` + `config show` (text and JSON); the "config digest" half is `d1` — attestation moved to `offered_tools` |
| `t5` | delivered | rows 59–61 pre-registered before any run |
| `t6` | delivered | 9-run matrix + the added arms: rows 59 (A7 0/3), 60 (P2-0 1/3), 61 (P3 0/3), 62, 63, 64 |
| `t7` | delivered | `docs/features/purpose-tools.md` arc section + CLAUDE.md; q3 decision taken: nothing promotes |
| `t8` | delivered | v1.69.0, PR #464 merged `8a5b1f5`; Qodo 7 threads (3 pushback, 4 fixed), 15 Sonar findings fixed |
| `t9` | delivered | `colleague/hire.py`: ten-field `Hire`, `Roster` cap 4, `hired_role` proven prompt-never-grants over every base (PR #469) |
| `t10` | delivered | `colleague/hire_schemas.py` + the `curate_schemas` splice, `_writer_allowlist`, one armed-only prompt sentence (PR #469) |
| `t11` | delivered | `strip_child_forbidden_tools` strips the pair at depth ≥ 1; agents sets knob-guarded; batch pool excludes it (PR #469) |
| `t12` | delivered | `colleague/hire_dispatch.py`: ≤ 2 tools-off completions on the real `make_complete(tools=[])` seam; mock candidate rule (PR #469) |
| `t13` | delivered | `colleague/hire_assign.py` + `TaskResult.hires` (omit-when-empty), reusing the purpose fold/render (PR #469) |
| `t14` | delivered | additive `"hire"` ledger kind, refs-not-payloads event, hires expired at the cut (PR #469) |
| `t15` | delivered | `compare_arms.py` hires/assignments columns, 0 on pre-field artifacts, `delegations` unchanged (PR #469) |
| `t16` | delivered | `arm-repeated-subtasks.md` + `make_repeated_subtasks_fixture.py` (8 packages, one seeded contradiction each); row **65** pre-registered (renumbered, `d4`) |
| `t17` | delivered | row 65 run and recorded: H vs control, n=3 each, interleaved — **hires 0/3** |
| `t18` | delivered | `docs/features/hire-colleague.md`, CLAUDE.md twelfth increment, **v1.71.0** (not the planned 1.70.0 — see drift), PR #469 merged `69339a5` |
| `t19` | blocked | built on `agent/t19` (`d57ce7e`, suite green there), PARKED by `d5`; not in any PR — gated on the validation ladder and #459 |
| `t20` | delivered | fixed digest shape on both survey briefs + scout fragment, parent-side `[uncited digest: …]` marker, scripted mock digests; measured as row 64c (PR #469) |
| `t21` | delivered | `docs/features/associate-validation.md` incl. the corrected #461 evidence (PR #464) |
| `t22` | delivered | `served_window_budget` (one `/tokenize` probe per (url, model), failures memoised + locked), context-length-400 guard, folded two-body error; proven live by row 64 (0 refusals) (PR #464 + review round) |
| `t23` | delivered | `AssociateProfile` depth/triage + per-value overrides; explicit thinking spellings only (review fix) (PR #464) |

## Mid-work Decisions

- `d1` — h26's `config_digest` clause cannot hold on a bare run; t4 attests via `config show` + the EngineConfig snapshot, and the artifact-side attestation is `offered_tools` — discovered while implementing t4.
- `d2` — finish the 9-run matrix as-is AND add a nemotron arm (row 62) — operator: the scout seat is intended to be Nemotron, but the rig served cortex.
- `d3` — nemotron as the non-writer seat ON BY DEFAULT (new task t19) — operator decision.
- `d4` — add arm R (explicitly requested delegation, rows 63/64); the hire arm moves to row 65 — operator: the speed question needs delegation to actually happen.
- `d5` — the associate seat is NOT validated; Rn-2/Rn-3 skipped; row 64 re-runs on the #460 tip; t19 stays parked — operator decision.
- No deviation record covers these; captured directly: **(a)** #461's second comment reversed its first (thinking-off vs thinking-on numbers) and was folded into the guide as frame decision `c51`; **(b)** a top-level `--role reviewer` and `--mode explore|review` now reason at `low` (operator rule, after a cortex-`medium` review overflowed a 274k-char synthesis turn); **(c)** #458 was re-scoped after a **steps-vs-turns correction** — the 12-turn cap was applying all along — and its lever shipped as PR #468 with row 64b recording a MISS; **(d)** Phase B was built by Claude worktree agents rather than colleague-as-developer, because the GPU was reserved for pre-registered rows; **(e)** an early "full suite green" claim was false (a piped exit code) and was corrected by fixing the nine real failures it hid; **(f)** one row-65 H attempt was VOIDED for a runner env bug (`hire=unset`) and re-run.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t4` (`d1`) | the digest named in h26 does not exist on the artifacts the arm rows read | acceptable |
| `t6` (`d2`) | the intended scout topology differs from what the rig served | acceptable |
| `t6` (`d3`) | operator: nemotron as the non-writer seat should be on by default | risky |
| `t6` (`d4`) | the speed question needs delegation to actually happen | acceptable |
| `t19` (`d5`) | the associate seat is not validated on real cases; default-ON does not ship until it is | risky |
| `t16`, `t17` | the hire arm is row **65**, not the plan's row 62 (`d2`/`d4` consumed 62–64) | acceptable |
| `t18` | shipped as **v1.71.0**, not the planned 1.70.0 — PR #468 (the #458 lever, unplanned work discovered mid-arc) consumed 1.70.0 | acceptable |
| `t12`, `t13` | `role=hired_role(hire)` cannot ride the spawn seam (a Role OBJECT silently widens through `load_role` → `None` → the full surface); the hired child runs the base role NAME with the authored fragment opening its brief | acceptable |
| `t13`, `t17` | `hires_block` was never called by the run path, so `TaskResult.hires` was structurally empty **while row 65 ran** (found in review, Qodo #469/2, fixed in the same PR); the row's verdict was re-derived from the step trace | needs-follow-up |
| `t20` | its measurement arm is row **64c**, added after the plan was written; the plan named no row | acceptable |
| — (unplanned) | the #458 lever + row 64b shipped as their own PR #468 (v1.70.0); no plan task covers them | acceptable |

## Evidence

- tests: `uv run pytest -n auto -q` on `main` @ `69339a5` — **10711 passed, 51 skipped** — exit 0 (read directly, never through a pipe)
- lint: `uv run flake8 colleague tests` clean; `black`/`isort` clean; markdownlint clean on every touched `.md`
- commits: `daedbc6..69339a5` — PRs #464 (`8a5b1f5`), #465 (`e283a20`), #468 (`4fcf7b2`), #469 (`69339a5`)
- rows: `docs/live-testing.md` rows 59–65 (each figure carries its artifact id)
- row 64b artifacts: `c8f7e1244907`, `702358ee78ab`, `134533394a11`
- row 64c artifacts: `d19a89765eab`, `474e744bf301`, `69cde59b032c`
- row 65 artifacts: control `afc8687bdd85`, `414c5c86a8cb`, `7bfb680cd928`; H `fa54fae93a7a`, `ca84bab55170`, `196bd9c40607`
- issues: closes #457, #460; refs #456, #458, #459, #461, #462, #463; filed #470 (Dependabot, unrelated); lobes-cli#234, #235

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| A7: offering the raw pair beside the purpose tools does not move delegation (0/3 either form) | high | row 59 · `tests/test_acting_add_knob.py` |
| P3 does not promote against its P2-0 control (0/3) | high | rows 60–61 · `scripts/compare_arms.py` |
| Nemotron children run without refusal and the parent verifies by ranged reads | high | row 64 (3/3, 0 refusals) · `tests/test_associate_window.py` |
| #460 is fixed (served-window clamp; the alias retry never hides a context-length 400) | high | commit `8a5b1f5` · issue #460 closed · row 64 |
| The child context-budget lever does NOT earn a default (row 64b MISS on wall and tokens) | high | row 64b · PR #468 (`4fcf7b2`) |
| The evidence-trail digest shape turns post-digest verification ranged (26/28 reads, 3/3 runs) | high | row 64c · `colleague/purpose_schemas.py` |
| The hire lane is built, confined, and byte-identical when unarmed | high | `tests/test_hire*.py` (5 files) · `tests/test_purpose_tools_byte_identical.py` · commit `69339a5` |
| Cortex does not choose the hire lane on a brief it can hold (hires 0/3) | high | row 65 · the step trace of all three H runs (0 `hire_colleague` steps) |
| `COLLEAGUE_HIRE` is correct to ship default-OFF | high | row 65 (the pre-registered decision rule) · `docs/features/hire-colleague.md` |
| A hire, when one occurs, reaches `TaskResult.hires` on every exit path | high | `tests/test_hire_assign.py::test_hires_snapshot_lands_on_every_exit_path` (added in review) |
| The hire lane amortises on a brief too large to hold in-seat | unverified | no such brief exists yet — parked, never claimed |
| Nemotron beats cortex-`low` on survey work | unverified | no arm ran cortex children at `low` (row 63's ran at `off`) — #459 |
| A live model's negotiation accepts/amends/declines sensibly | unverified | no negotiation ever ran outside the mock tests (row 65: 0 hires) |

## Remaining Work / Follow-up

- `t19` — associate default-ON stays parked on `agent/t19`; unblock via the validation ladder (`docs/features/associate-validation.md`) plus #459's per-lane decision, then rebase and ship.
- The **amortisation test above the in-seat ceiling** — the one shape that could still make the hire lane earn its keep: a repeated-sub-task brief too large for one seat. Does not exist; the parked follow-up.
- #459 — score digest CONTENT against fixture ground truth (the #461 correction folded in) before any seat default changes.
- #462 / #463 — future purpose tools from the #461 evidence; `run_command` reason + slower-warning. Issues only.
- #470 — two high Dependabot alerts in the `[mcp]` extra's chain (base install unaffected); filed while closing this arc.
- lobes-cli#234 / #235 — the advert should carry the served window; `thinking_budget` is ignored on vLLM.
- The colleague second opinion on the associate-seat diff never completed on cortex (two attempts, both truncated/stalled) — a recorded miss; retry on the associate seat once validated.

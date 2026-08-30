# Arm brief — repeated sub-tasks, where one hire amortises

Pre-registered 2026-08-30 for the `delegation-follow-ups-a7-p3-hire` arc
(plan t16, spec `docs/specs/2026-08-30-delegation-follow-ups-a7-p3-hire.md`,
covers c21/h11; row 65 of `docs/live-testing.md`). Two arms run the SAME
brief below: **arm H** with the hire knob armed (`COLLEAGUE_HIRE=1`) and a
**control** with the knob unset (one-shot purpose tools only). The knob is
the ONLY difference between the arms — the brief never names a hire tool, it
presents eight similar independent sub-tasks and lets the model choose.

## Why this brief exists — the input from row 61

Row 61's P3 verdict is the direct input to this arm's hypothesis: **P3 (the
size-conditional delegation prose — one trigger sentence on top of a truthful
control paragraph) went 0/3 against a clean P2-0 control and DID NOT
promote** — it produced zero delegation in three runs and cost turns and
reasoning chars. Per-call prose is not the lever, and per spec c46 the
recurring reading is that cortex's in-seat mechanism is often the rational
choice on a brief it can hold.

The hire hypothesis therefore states what it tests INSTEAD: not prose pushing
a per-call delegation decision, but whether a **persistent, purpose-agreed
employee** — hired once, with an agreed purpose and when clause, then
assigned similar work repeatedly — gets chosen when the TASK SHAPE repeats.
One negotiation amortises across >= 6 similar assignments; a one-shot
purpose call amortises nothing. The lever under test is the standing
arrangement, not a sentence urging delegation.

## The repo fixture (build before the run, same fixture on every arm)

A throwaway repo with an `.eidetic` store (as rows 57–64), generated
deterministically by `scripts/make_repeated_subtasks_fixture.py`: **eight
packages** `pkgs/pkg_a` … `pkgs/pkg_h`, each a single `core.py` of the SAME
shape — 8 public normaliser functions, each reading its own module-level data
table — and each seeding exactly ONE docstring/behaviour contradiction (one
function whose docstring claims a rounding precision its body does not use)
at a per-package index derived from the package name, so no single known
offset surfaces every answer.

Recorded per-file counts (printed by the generator; byte-identical shape
across packages by construction): each `core.py` is **641 lines / 24,799
chars** — under the 25,000-char `read_file` page
(`colleague/truncation.py` `DEFAULT_TOOL_MAX_CHARS`), so each sub-task is a
genuinely small one-page read — total **5,128 lines / 198,392 chars** across
the eight. The generator also prints the per-package answer key
(which function contradicts, claimed vs actual precision); that key is
**operator-only** — it scores the audits and is never committed into the
fixture repo. Determinism is pinned by
`tests/test_repeated_subtasks_fixture.py` (two runs → identical trees).

## Why the argument is amortisation, not surface size (the arithmetic)

`arm-large-surface.md` argued its baseline could not fit; this brief argues
no such thing, and says so up front:

- **The in-seat baseline CAN fit.** 198,392 chars is roughly 49,600 tokens
  at ~4 chars/token — well inside the 131,072 default context budget — and
  eight one-page reads plus eight audit write-ups sit comfortably inside the
  default 40-step budget. An in-seat sweep is a rational choice here, and if
  the control (or arm H) does exactly that, the row records it as such (the
  c46 reading, again).
- **What repeats is the WORK SHAPE, not the surface.** The eight audits are
  identical in form and independent in content. On the one-shot path, every
  `code_survey` call must restate the full audit specification (functions,
  tables, the contradiction hunt, the report shape) in its own brief — eight
  restatements, nothing carried between calls. On the hire path the fixed
  cost is paid ONCE: at most 2 tools-off candidate completions
  (`colleague/hire_dispatch.py` `MAX_ROUNDS`) plus one authored standing
  prompt of at most 2,000 chars (`colleague/hire_schemas.py`
  `PROMPT_MAX_CHARS`); after that, each `assign_to_colleague` carries only
  the per-package delta, and the standing prompt opens the child's brief
  verbatim (`colleague/hire_assign.py`). Hiring breaks even when
  n × (restated specification) exceeds the negotiation cost plus the
  standing prompt — and n = 8 here, the shape where it should if it ever
  does.
- **Honest limit of the arithmetic.** Each assignment still spawns a fresh
  child (run-scoped, no shared child memory across assignments), so the
  amortisation is in the parent's authored context and the agreed purpose,
  never in child warm-up. Whether that saving is worth two extra
  completions — or worth anything against the in-seat sweep — is exactly
  what the row measures, not what this file assumes.

### The tools available when armed (what the model actually sees)

Both arms hold the six purpose tools. Arm H additionally holds two typed
tools, appended after the purpose splice (`colleague/hire_schemas.py`):
`hire_colleague(purpose, when, base_role, prompt)` — a bounded two-round
negotiation with a candidate voice minting a run-scoped employee over one
builtin base role (roster capped at 4; a refusal is the readable tool result
`not hired: <reason>`) — and `assign_to_colleague(agent_id, task,
acceptance?)`, which hands a live hire one scoped task and returns its digest
as the tool result. The armed system prompt gains exactly ONE sentence (the
`HIRE` section, `colleague/prompttext.py`). Neither tool is named in the
brief; choosing them — or not — is the measurement.

## Pass bar (committed BEFORE the run)

- **the hire lane is USED** iff hires >= 1 AND assignments >= 6 on >= 2 of 3
  arm-H runs — hires read as `len(artifact['hires'])` and assignments as the
  count of `assign_to_colleague` steps (t15's `hires` / `assignments`
  columns in `scripts/compare_arms.py`), never from prose
- **accept/amend/decline counts per hire are a cell**, read off each
  `hire_colleague` step's result text (`hired: … (1 negotiation
  completion(s))` = round-1 accept; `… (2 …)` = round-2 accept, amended
  terms beside it; `not hired: <reason>` = decline/refusal), pasted verbatim
- **a 0/N result is publishable**: three armed runs with zero hires is the
  finding, written as a miss — not a voided row and not a reason to add
  prose
- control runs must show hires = 0 and assignments = 0 (the schemas are
  hidden unarmed); a nonzero control voids that run
- task success recorded beside the hire cells: status, all eight packages
  audited, contradictions named against the generator's answer key (n/8
  correct), exactly one docstring fixed
- turns <= 1.0x and wall <= 1.2x vs the control at the same tip, n=3
  (`scripts/compare_arms.py --bar-wall 1.2 --bar-turns 1.0`, from artifact
  stats; comparator unmodified, its empty `git diff` recorded)
- markup count per run beside every zero (`stats.counts.markup_tool_calls`;
  a zero-hire run with markup > 0 is INCONCLUSIVE)
- reasoning chars per run; a miss is written as a miss

## The brief (paste into `colleague work`, both arms verbatim)

```text
Audit eight packages, then fix one defect.

1. For each of the eight packages under `pkgs/` in this repo — `pkg_a`
   through `pkg_h`, each a single `core.py` of about 640 lines — write an
   audit note: its public functions, what each does, which reference table
   each reads, and the ONE function whose docstring contradicts its body
   about rounding precision (each package has exactly one).

2. The eight audits are independent and all have the same shape. You may
   set up help once and reuse it across them, hand each audit out
   separately, or do all of it yourself; the choice is yours.

3. Then fix exactly ONE of the eight contradictions you found: change that
   one docstring to match its body, in one package only. Say which package
   and function you fixed and what the mismatch was.
```

Note: this brief names no tool, for the reasons recorded in
`docs/live-testing/briefs/arm-decomposable-neutral.md` — the same brief runs
on an arm whose surface lacks the hire tools, so any tool name would be a
steer the control cannot act on. Item 2's "set up help once and reuse it" is
deliberately arrangement-shaped, not tool-shaped: it is equally satisfiable
by a hire, by repeated one-shot calls, or by an in-seat sweep.

## After the run — record (never fill before)

Per-run hires and assignments (t15's columns), the accept/amend/decline
outcome per hire with the negotiation completions count, the delegation
histogram over `Step.tool` (each purpose tool and `assign_to_colleague`
separately), markup count, task success (status / audits complete / n-of-8
contradictions correct / one docstring fixed), each assignment child's served
model and per-child `usage` from `sub_results[]`, `stats.step_count`,
`stats.counts` in full, turns, wall-clock and reasoning chars; the ratio
cells from `scripts/compare_arms.py`; the `prompt_digest` and
`offered_tools` read off every artifact (the row's validity clause); the
memory distill counters and the distill child's served model.

## Row 65 pre-registration (integrator: move verbatim into `docs/live-testing.md`)

The fenced block below is the row-65 table line for the validation matrix,
authored here because the ledger file is integrator-owned. Move it verbatim
(one table row, one line).

```markdown
| 65 | delegation-follow-ups-a7-p3-hire (spec 2026-08-30, plan t16): **arm H — the HIRE knob on the repeated-sub-tasks brief, H vs control** | `docs/live-testing/briefs/arm-repeated-subtasks.md`, `scripts/make_repeated_subtasks_fixture.py`, `colleague/hire_schemas.py`, `colleague/hire_dispatch.py`, `colleague/hire_assign.py`, `scripts/compare_arms.py` | ✅ | PRE-REGISTERED 2026-08-30, BEFORE any run, queued behind rows 62-64. Arc: `delegation-follow-ups-a7-p3-hire` (spec `docs/specs/2026-08-30-delegation-follow-ups-a7-p3-hire.md`, plan t16, covers c21/h11). **Hypothesis (the input is row 61's verdict):** P3 — size-conditional delegation prose — went 0/3 against a clean P2-0 control and did not promote, so per-call prose is not the lever; this arm tests INSTEAD whether a persistent, purpose-agreed employee (one `hire_colleague` negotiation amortising across >= 6 similar assignments) gets chosen when the task shape repeats, vs one-shot purpose calls that amortise nothing. **Conditions:** arm H = `COLLEAGUE_HIRE=1`; control = knob unset (one-shot purpose tools only). Same brief verbatim (`docs/live-testing/briefs/arm-repeated-subtasks.md` — it never names a hire tool), same fixture rebuilt fresh per run, n=3 each, interleaved, sequential on the rig. **Tip pin:** every run executes on a tip carrying t10-t13's hire lane (`colleague/hire_schemas.py`, `hire_dispatch.py`, `hire_assign.py`) and t15's `hires`/`assignments` comparator columns; the exact SHA of each run is recorded beside its artifact id; an earlier tip VOIDS the run. **Fixture:** `scripts/make_repeated_subtasks_fixture.py` (deterministic; `tests/test_repeated_subtasks_fixture.py` pins two runs → identical trees): eight packages `pkgs/pkg_a`…`pkg_h`, each `core.py` 641 lines / 24,799 chars (one `read_file` page), total 5,128 lines / 198,392 chars, one seeded docstring/behaviour contradiction per package at a name-derived index; an `.eidetic` store as rows 57-64; the generator's printed answer key is operator-only and never committed into the fixture repo. **Rig:** recorded at run time in this row exactly as rows 59-64 did (gateway, cortex model, consumed roles, effort, `COLLEAGUE_TIMEOUT`, `max_steps`); a gateway stall / `step-stall` run is a rig failure: VOIDED and re-run (q4 precedent). **Comparator (h3):** `scripts/compare_arms.py` is not modified for this row beyond its merged t15 columns — `git diff` against the run tip recorded EMPTY at every run's SHA; ratio cells use `--bar-wall 1.2 --bar-turns 1.0` with the control as the baseline arm. **Validity (h18) — digest + surface, pasted per run:** each artifact carries `prompt_digest` and `offered_tools`. Control: all three control artifacts must share one digest (recorded from control run 1). **Arm H's digest is DERIVED, not free:** `tests/test_hire_schemas.py` pins `prompttext.default_system(hire=True) == V1_DEFAULT_SYSTEM + "\n\n" + SECTION_TABLE["HIRE"]` — the armed and unarmed composed prompts differ by exactly the ONE `HIRE` sentence (single period, no newline) — and `colleague/loop.py` computes `prompt_digest = prompt_digest_for(system_prompt)`; so the expected H digest is recomputed from the control's composed prompt text plus `"\n\n"` plus `prompttext.SECTION_TABLE["HIRE"]`, and every H artifact must match it; any other preimage difference VOIDS the pair. `offered_tools`: H runs end with `hire_colleague`, `assign_to_colleague` appended after the purpose splice (t11); control runs carry neither name; a mismatch VOIDS the run. **Pass bar (committed before the run, numeric):** the hire lane is USED iff hires >= 1 AND assignments >= 6 on >= 2 of 3 H runs — hires = `len(artifact['hires'])`, assignments = `assign_to_colleague` step count (t15's columns), never from prose. **A 0/3 result (no H run hires) is DECLARED PUBLISHABLE:** it is the finding, written as a miss — not a voided row. Control runs must show hires = 0 and assignments = 0 (schemas hidden unarmed); a nonzero control voids that run. **Cells to fill after the run (in this order, never before):** (1) hires per run; (2) assignments per run; (3) **accept/amend/decline counts per hire** — read off each `hire_colleague` step's result text (`hired: … (1 negotiation completion(s))` = round-1 accept; `… (2 …)` = round-2 accept with amended terms quoted beside it; `not hired: <reason>` = decline/refusal), pasted verbatim; (4) delegation histogram over `Step.tool` (each purpose tool and `assign_to_colleague` separately); (5) task success — status, all eight packages audited, contradictions named vs the generator's answer key (n/8 correct), exactly one docstring fixed; (6) turns ratio and wall ratio vs the control (`compare_arms.py --bar-wall 1.2 --bar-turns 1.0`); beside them markup count per run (`stats.counts.markup_tool_calls`; a zero-hire run with markup > 0 is INCONCLUSIVE), reasoning chars, `stats.counts` in full, stalls per run, each assignment child's served model + per-child `usage` from `sub_results[]`, the memory distill counters, and the artifact ids with their SHAs. **Every number comes from an artifact; a figure without an artifact id beside it is a defect in the row (h16).** **Audience (h12):** the operator reads this row and takes the one decision; cortex is OFFERED the hire surface and calls or ignores it explicitly — no cell records the runtime choosing on its behalf. **Honest caveats, carried from the brief:** the in-seat baseline CAN fit this fixture (~49,600 tokens, eight one-page reads), so an in-seat sweep is a rational choice and is recorded as such (c46); amortisation lives in the parent's authored context and agreed purpose, never in child warm-up (each assignment spawns a fresh run-scoped child); n=3. | #457 |
```

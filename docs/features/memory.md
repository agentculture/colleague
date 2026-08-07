# Memory — colleague remembers and learns from every run

**Spec:** `docs/specs/2026-07-02-colleague-is-now-the-colleague-you-always-wanted-i.md`
(R1, claims c9/c7, honesty h7/h3/h14) · **Plan:** tasks t1–t4.

Colleague's runs used to start cold: every explore re-derived the repo map,
every work item re-learned the settled decisions, and nothing a run learned
survived it. Colleague's own self-reflection over its run history (work item
`7c6bcb80eb42`, graded 4/5) quantified the waste at **15–25 steps per run**
(30–50 % of a default 40-step budget): anchor-file re-reads, fishing-expedition
exploration, re-derived conventions, and meta-description finishes.

Now every work item is wrapped in a memory exchange against the repo's
**eidetic** store — the same store, scope, and visibility the operator's
`/remember` and `/recall` skills use, so colleague's lessons and the
operator's (or Claude's) notes are mutually visible.

## The pieces

| Piece | Where | What |
|-------|-------|------|
| CLI adapter | `colleague/memory.py` | `recall(repo, query, top_k)` / `remember(repo, record)` shell-outs to the operator-installed `eidetic` CLI. Allow-list exactly those two verbs; identity injected (`COLLEAGUE_IDENTITY`); `cwd` pinned at the store repo; absent CLI ⇒ strict no-op (`[]`/`False`, no subprocess). |
| Recall-before | `colleague/loop.py` `_maybe_recall_memory` | ONE advisory user-role message at task start: a prior-lessons block derived from `eidetic recall` on the task's goal/instruction head, char-capped at `RECALL_BLOCK_CAP` (4000 — h7's token-cap without bundling a tokenizer). |
| Remember-after | `colleague/loop.py` `_maybe_remember_lesson` | ONE deterministic lesson record per work item at exit — status, steps, tool counts, honesty signals, **and the failure substance verbatim** (#379 rung 1: the #313 incompletion reason/evidence/recommendation, error strings, stale-pin warnings, lint-gate fixes, test-integrity findings, affected-tests failures — all bounded per field) — upserted by id (`work-lesson-<task_id>`), so re-runs never duplicate. INCOMPLETE runs are recorded too: failures are the most valuable lessons. |
| Rung-2 distillation | `colleague/lessons.py` + `colleague/distill.py` + the loop's remember seam | A gated cause→lesson→next-delta pass at remember time (#379 rung 2): the seam (`ContextControls.distill_fn`, or an author resolved BY ROLE via `distill.resolve_distill_author_from_config` — deepthink/muse > armed-lobes main > none) produces raw text that must pass the strict `{cause, lesson, next_delta}` schema (refuse-whole on any deviation) before the lesson folds into the record marked `origin=model`; an invalid distillation leaves the rung-1 record with an honest `no-lesson-extracted` marker. Production runs detach a bounded background child (`distill.make_distill_fn`, the sanctioned one-shot pattern) recorded as `distill: detached` — the child validates-then-upserts and writes an outcome marker; the run's return is never blocked. Kill switch: `COLLEAGUE_MEMORY_DISTILL=0` / config `memory_distill` — independent of the memory gate, rung-1 stands. |
| Alive counters | `TaskResult.memory` `distill_attempts`/`distill_validated` | Armed is not evidence the tier is alive — a counter that increments is (the #363 T1/T2 lesson): a seam that never validates shows `attempts>0, validated=0` on every artifact, and `doctor` surfaces attempts-vs-validated across recent runs. |
| Code-lessons | `colleague/memory.py` `build_code_lesson_record` | Repo-convention records (`type=code-lesson`, own id namespace, `{area, convention, evidence, confidence}` with verbatim evidence) grown from teachers: the integrator-correction diff (`colleague/correction.py` — tip SHA vs the PR's squash commit, scoped to `changed_files`, honest no-diff when any fact is missing), lint-gate fixes, in-run test failures, and ROI grades. Captured seamlessly by the auto-trigger lane (grade-time + work-start, observable sidecar, never blocking the grade). |
| Artifact record | `TaskResult.memory` | Omit-when-None `{query, recalled, injected_chars, lesson_recorded}` — h7: a misleading recall is diagnosable from the artifact, never silent. |
| Loop tool | `colleague/tools.py` `memory` | Model-callable mid-run (`verb=recall\|remember`). Offered to every backend (all-engines). Read-only roles get **recall only** — `remember` is a write-capable shell-out, refused by the role-aware executor. |

## Arming — triple-gated, default-ON

Memory fires only when **all three** hold:

1. `config.memory` (default ON; opt out per run with `COLLEAGUE_MEMORY=0` or
   `.colleague/config.json` `{"memory": false}`);
2. the repo carries a **`.eidetic/` store** — a repo opts into memory by
   having one. A store-less repo (every tmp test repo) is a strict no-op with
   zero subprocess, which is what makes default-ON safe;
3. the `eidetic` CLI is installed (absent ⇒ the t1 adapter no-ops).

## Two lessons the feature itself taught us (caught live, day one)

- **Isolated runs must target the operator repo.** `colleague work` runs in a
  throwaway isolation worktree; a lesson written there is reaped with it. The
  first live smoke run reported `lesson_recorded: true` while the durable
  store stayed empty. `execute_work` now threads `config.memory_root` (the
  operator repo) and the loop resolves every recall/remember against it —
  pinned by a test that asserts the CLI's **cwd**, not just its argv.
- **Store churn must not read as dirt.** `eidetic recall` reinforces recalled
  records (bumps `last_recall`), mutating the tracked store — so a
  memory-armed run used to block the *next* run on the #149 dirty-tree guard.
  Changes confined to `.eidetic/` now read as clean; they still sweep onto the
  work branch (lessons travel with the work). Real tracked WIP still refuses.

## Warm-vs-cold (h3/h14) — the honest measurement

The success signal is measurable, not asserted: the same task run live twice —
once against a cold store, once warmed — compared via the always-on
`WorkStats`. Per h3/h14, the first honest comparison counts and a no-saving
result would have retracted the claim.

**Status: MEASURED (2026-07-02, live rig, 27B, `--mode explore --role
explorer`).** Task: locate a computation hidden behind three layers of
delegation in a 10-file fixture repo ("find where the retry backoff multiplier
is computed"). Cold store = no task-specific lesson; warm = one seeded
prior-run lesson naming the real location.

| Leg | Work item | Steps | Model turns | Tokens | Duration |
|-----|-----------|-------|-------------|--------|----------|
| Cold | `503b0a36c33a` | 10 | 9 | 23,358 | 46.4 s |
| Warm | `c5774404bc3d` | **2** | **2** | **4,266** | **14.1 s** |

**5× fewer steps, 5.5× fewer tokens, 3.3× faster — the same correct answer.**
Notably the warm run did not parrot the lesson: it spent its one read step
*verifying* the recalled location against the real file before finishing —
recall as a map, evidence still from the territory. Honest footnote: "cold"
means no task-specific lesson, not zero recall — eidetic merges the operator's
`$HOME` store, so one generic record (1,056 chars) was injected in the cold
leg too; it contained nothing about the task and the cold run's 10 steps show
it. Both artifacts carry the full `memory` block for audit.

**The self-taught counterpoint (2026-08-07, #387 exp-1 — FALSIFYING).** The
same design rerun with a lesson the pipeline authored *itself* (cold fail →
rung-2 distill → warm rerun, nothing hand-seeded; live-testing row 34): the
distilled lesson was genuinely diagnostic but *process-level* ("all steps
went to tracing; transition to execution early"), and with it verifiably in
context the warm run's step trace was **identical** to the cold run's —
equal turns, no deliverable either way. Together the two measurements bound
the claim honestly: an **answer-level** lesson transforms a rerun (5×); a
**process-level** lesson, at least at a tight step cap and one repetition,
does not. Lesson *specificity* — whether distillation captures what was
*learned about the task* rather than what was *learned about budgeting* —
is the operative variable, and the arc's recorded next-delta (#388 is the
validator-side start).

## Honest limits

- The lesson record is deterministic run-facts (status/steps/signals), not a
  model-authored reflection — mining *why* steps were wasted stays with the
  reader (or a future bounded reflection turn, a named follow-up).
- Recall quality is the store's quality: a misleading memory injects noise.
  The artifact's `memory.query`/`recalled` make that diagnosable (h7), and
  eidetic's reinforcement/shadowing is the long-term corrective, not colleague.
- daria (data-refinery) stays observational this increment (assumption c18):
  colleague's artifacts and lessons are material daria can observe; daria is
  not in the work loop. Deeper coupling is parked (v2) until this leg proves out.

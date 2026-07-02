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
| Remember-after | `colleague/loop.py` `_maybe_remember_lesson` | ONE deterministic lesson record per work item at exit — status, steps, tool counts, honesty signals (`finish_recovered`, capacity warnings, budget exhaustion) — upserted by id (`work-lesson-<task_id>`), so re-runs never duplicate. INCOMPLETE runs are recorded too: failures are the most valuable lessons. |
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
`WorkStats`. Recorded here when run; per h3, a no-saving result retracts the
warm-start claim rather than massaging it.

**Status: PENDING** — to be run as plan task t4 against the live rig.

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

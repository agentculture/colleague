# Colleague finishes what it starts: a run that stalls mid-task is nudged to continue instead of ending on a half-done file, and at the finish boundary it auto-compacts its history — freeing context so it keeps working and leaving a clean model-authored summary instead of trailing prose.

> Colleague finishes what it starts: a run that stalls mid-task is nudged to continue instead of ending on a half-done file, and at the finish boundary it auto-compacts its history — freeing context so it keeps working and leaving a clean model-authored summary instead of trailing prose.

## Audience

- Colleague's bounded tool-loop, and the ask-colleague callers who delegate write tasks to a smaller backend that intermittently stalls mid-task (the t5 case).

## Before → After

- Before: Today a no-tool-call turn ends the run immediately as stopped_without_finish even with work remaining, and the artifact summary can be raw trailing prose ('Let me check:') — exactly how t5 stopped after editing 1 of 4 files.
- After: On a stall (a no-tool-call turn that never called finish) colleague injects one bounded continuation nudge and resumes; at the finish/stop boundary it auto-compacts history to free context for continuation AND to emit a clean model-authored summary; the run keeps working until truly done or its step/token budget is spent.

## Why it matters

- Delegating field-work to colleague only pays off if a run finishes what it started; a half-done write plus a junk summary forces the caller to salvage or redo it — a cost we hit live on t5.

## Requirements

- continue-working: on a no-tool-call turn that did not call finish, inject ONE continuation nudge ('you stopped without calling finish — continue working or call finish') and resume the loop, letting the model disambiguate stall-vs-done by either continuing or finishing. Sequences BEFORE the t3 forced-synthesis give-up (#191).
  - honesty: Termination is guaranteed: a small consecutive-empty-turn cap plus the existing step/token budget bound the loop; the nudge is a strict no-op when the model called finish — a genuine completion is never overridden.
- auto-compact-on-finish: at the finish/stop boundary the loop runs the existing fill-line compact move to (a) free context so a continued run does not overflow AND (b) produce the run's summary, so the artifact summary is always a model-authored compaction rather than trailing prose.
  - honesty: Reuses the existing fill-line compact machinery (no new summarizer, zero new deps); on the compaction turn's own overflow it falls back to the documented lossy-windowing floor; strict no-op (byte-identical TaskResult) when there is no finish/stop boundary with content.
  - honesty: The only added cost is at most one extra model turn at the boundary; off/at-floor it adds nothing, and it composes with the existing mid-run fill-line compact (#156) as a second trigger point for the same move.

## Honesty conditions

- Runtime-owned (all-engines rule): every backend behaves identically, and the change is a strict no-op — byte-identical TaskResult and success path — when no stall or finish-with-content boundary occurs.
- Scoped to colleague's own bounded loop and ask-colleague's existing verbs — no new caller-facing surface or flag is required for the default behavior to apply.
- The continue+compact behavior is observable in the artifact (a completed run reaches more files / carries a clean summary) and reproducible on the mock backend, not only on a live model.
- The t5 failure is recorded evidence, not anecdote: stopped_without_finish=True, summary trailing at 'Let me check:', files_changed=1 — the run JSON exists.
- The cost is concrete: on t5 the caller had to salvage the shell work and hand-finish 3 of 4 files — payoff is measured against that exact rework.
- Success is testable on the mock backend without a live model: a scripted stall-then-resume run completes, a stop-without-finish run yields a compacted (non-prose) summary, and a no-trigger run stays byte-identical.
- Every exclusion is enforced, not just stated: caps bound termination (test-proven), zero new runtime deps (zero-deps guard holds), same code path for mock and vllm (all-engines e2e shape test).
- No second compaction or summary implementation is added — both features reuse _compact_history / fillline.apply_compaction and the t3 _maybe_force_synthesis floor (#191), which still produces findings when even a nudged run yields nothing.

## Success signals

- A write run that previously stopped after file 1 of 4 now completes all four (or hands back a clean continuation summary at budget), and a t5-class 'Let me check:' artifact summary never ships again; strict no-op TaskResult when nothing triggers.

## Scope / boundaries

- NOT an unbounded loop — continuation stays inside the existing step/token caps plus a small consecutive-empty-turn cap; NOT a multi-model router; NOT a new daemon/socket/runtime dep; NOT a new summarizer (reuses the fill-line compact move). Runtime-owned so it fires identically for every backend (all-engines rule).

## Decisions

- Composition, not duplication: continue-working reuses the loop's existing turn boundary + nudge-injection pattern; auto-compact reuses _compact_history/fillline.apply_compaction (#156) and the t3 forced-synthesis floor (#191) — the change is trigger/sequencing, no new machinery, zero new deps.

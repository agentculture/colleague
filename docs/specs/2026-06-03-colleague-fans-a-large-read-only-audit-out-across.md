# colleague fans a large read-only audit out across scoped subagents and aggregates their findings into one ranked report — past the single-drive context wall

> colleague fans a large read-only audit out across scoped subagents and aggregates their findings into one ranked report — past the single-drive context wall

## Audience

- an agent or operator outsourcing a repo-wide audit (e.g. doc-review) to colleague on a small-context local model

## Before → After

- Before: a full-repo audit accumulates all content into one growing drive context; each turn slows until a request exceeds the per-request timeout (#104 runs 2-4); only a bounded-scope audit completes (README-sized: 7 steps / 355s)
- After: the audit is split by surface; each child drive gets a small fixed context, completes fast and reliably calls finish, and the per-surface findings are aggregated into one ranked report

## Why it matters

- reliability, not speed: on a serializing vLLM there is no wall-clock speedup, but a small per-child context fixes the timeout that kills the single growing drive

## Requirements

- honest coverage accounting: when the fan-out cap (MAX_SUBAGENT_FANOUT=4 -> <=3 children) bounds coverage, log() exactly which surfaces were dropped — never silently truncate
  - honesty: when more surfaces exist than the cap allows, the report names exactly which surfaces were NOT covered (no silent truncation)

## Honesty conditions

- a repo-wide audit that exceeds one drive's context/timeout on the reference 27B completes when fanned out, yielding one ranked report — proven by a doc-review that fails as a single drive but succeeds fanned out
- the target user is an agent/operator whose audit is too large for one drive on a small-context model — pitched at reliability for the constrained case, not speedup for a fast machine
- on the reference 27B a full-repo audit measurably grows per-turn latency until a request exceeds the timeout, while a bounded-scope audit on the same model completes — both observed (#104 runs 2-4 vs the 7-step README run), not assumed
- after the split, each scoped drive's context stays small enough to finish, and the per-surface results combine into one report with no surface silently lost
- fan-out is justified by reliability even at zero wall-clock speedup on a serializing server; if it delivered neither speed nor reliability it would not be worth building
- the design adds NO parallelism beyond the existing caps and NO routing policy; any in-drive fan-out still obeys one-level / <=3 children / nested-batches-forbidden
- a read-only audit's output is findings text; git-merging sub-branches would not combine it, so the chosen aggregation is text-level, not a git merge
- concrete acceptance: a doc-review that fails as one drive on the rig completes via fan-out, yields one ranked report covering every surface, and logs any surface dropped to the cap

## Success signals

- a full doc-review that times out as a single drive completes when fanned out, producing one ranked report covering every surface, with what-was-dropped logged when coverage is capped

## Scope / boundaries

- not a general parallel-speedup feature and not a task->backend routing policy; in-drive subagents fan-out stays bounded by the existing caps (one level, <=3 children + 1 merge)
- not git-merge aggregation for read-only audits: a text audit yields findings text, not commits, so the merge child's git-branch merge (subagents.py merge child) does not fit

## Non-goals

- no nested batches (v0 forbids a batch child spawning another batch — subagents.py:182-188); no raising MAX_SUBAGENT_DEPTH/FANOUT; no automatic task->backend routing

## Decisions

- operator-driven fan-out (assign-to-workforce: N scoped 'colleague drive --command doc-review <surface>' in parallel worktrees, then synthesize) is the reliable path today; in-drive subagents fan-out is bounded to 3 parallel/one level and assumes a git-merge that does not fit a text audit

## Open / follow-up

- in-drive subagents text-aggregation merge mode (for a template-driven fan-out path) — deferred follow-up, not v0; revisit if/when in-drive read-only fan-out is wanted

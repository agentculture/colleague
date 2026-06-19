# explore-never-wastes — a read-only explore that runs out of steps still answers

> A read-only explore/review/drive that exhausts its step budget is never a
> silent no-result. When the loop runs out of steps having read context but never
> produced a usable summary, it forces ONE no-tools synthesis turn ("answer now
> from what you've read") and uses that as the summary; a non-finished outcome
> reports `status: incomplete` with a non-zero exit, so a caller can branch on it.

Four threads (#194 / #192 / #191 / #190 / #188) make an explore robust.

## 1. Forced synthesis (#191, extended #202/#197)

When `_work_loop` exits via `_EXIT_BUDGET` / `_EXIT_STOPPED` having read context
(`step_count > 0`) but with no usable summary, `_maybe_force_synthesis` injects
ONE no-tools turn and uses its text as the summary (reusing
`_complete_with_degradation`). It **also** fires on an explicit `_EXIT_FINISHED`
when a `finish` carries an empty/whitespace summary (a review's deliverable *is*
the text). `NO_RESULT_PRODUCED` is reached only when even that turn is empty. A
`COLLEAGUE_SYNTHESIS_RESERVE_STEPS` knob holds steps back so a big-diff review's
verdict turn runs with fresher context.

## 2. Honest status (#192)

Any non-`_EXIT_FINISHED` outcome reports `status: incomplete`
(`colleague/contract.py` `INCOMPLETE`) with a non-zero `work`/`drive` exit (code
2; `ok`→0, `error`→1), so a caller branches on status/exit without sentinel
string-matching.

## 3. Advisory fan-out (#188)

Once a survey reads more than `COLLEAGUE_FANOUT_FILES` files
(`EngineConfig.fanout_files`, default 12), `_maybe_offer_mapping_fanout` injects
ONE advisory recommendation pointing the model at the existing `subagents` tool
with a per-folder partition. Backend-judged; reuses `make_batch_spawn` /
`batch_spawn` with no new worktree/merge code; a strict no-op when dormant /
under-threshold / already-offered.

## 4. Loud partials (#194)

`ask-colleague explore` defaults to `--max-steps 30` (write/review stay 20; an
explicit flag overrides either), and the partial warning names the reached step
count + a concrete larger `--max-steps`.

## Honest limits

- Runtime-owned (all-engines): forced synthesis + incomplete status + fan-out
  fire identically for `mock` and `vllm-openai`.
- The fan-out merge child no-ops for read-only children (they write nothing) —
  the FANOUT-slot optimisation is a documented follow-up.

## Key files

- `colleague/loop.py` — `_maybe_force_synthesis`, `_maybe_offer_mapping_fanout`.
- `colleague/contract.py` — `INCOMPLETE`.
- `colleague/autosplit.py` — `build_mapping_fanout_recommendation`.

## Spec + plan

- [`docs/specs/2026-06-14-colleague-never-wastes-an-explore-a-read-only-expl.md`](../specs/2026-06-14-colleague-never-wastes-an-explore-a-read-only-expl.md)
- [`docs/plans/2026-06-14-colleague-never-wastes-an-explore-a-read-only-expl.md`](../plans/2026-06-14-colleague-never-wastes-an-explore-a-read-only-expl.md)

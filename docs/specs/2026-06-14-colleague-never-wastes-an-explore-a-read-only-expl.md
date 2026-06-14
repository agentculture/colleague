# colleague never wastes an explore: a read-only explore/drive that exhausts its step budget forces one final no-tools synthesis turn and returns a usable partial answer; a run that truly produces nothing reports a distinct non-ok status instead of a misleading status:ok so callers like ask-colleague can detect-and-retry without sentinel string-matching; explore gets a step budget tuned for codebase-mapping; and the ask-colleague wrapper resolves the colleague CLI with zero external-tool dependencies.

> colleague never wastes an explore: a read-only explore/drive that exhausts its step budget forces one final no-tools synthesis turn and returns a usable partial answer; a run that truly produces nothing reports a distinct non-ok status instead of a misleading status:ok so callers like ask-colleague can detect-and-retry without sentinel string-matching; explore gets a step budget tuned for codebase-mapping; and the ask-colleague wrapper resolves the colleague CLI with zero external-tool dependencies.

## Audience

- Agents and wrappers that delegate read-only mapping to colleague: ask-colleague explore callers, culture front-door surveys, and any orchestrator batching explore or drive runs and keying off their status.

## Before → After

- Before: A read-only explore that exhausts its step budget mapping a large codebase burns the whole budget (up to ~500K tokens) on serial list_dir and read_file, then returns the __COLLEAGUE_NO_RESULT_PRODUCED__ sentinel while reporting status:ok with not_finished or stopped_without_finish set. The most expensive failure mode: full token spend, zero output, misleading success that callers can only detect by string-matching a sentinel.
- After: When a read-only mapping run detects it has read more than N files (or context is filling toward the budget), it strategizes a subagent fan-out: partition the unmapped surface into small per-folder or N-file chunks explored by parallel subagents whose findings the parent synthesizes, instead of grinding serially or merely demanding a bigger budget. If the run still exhausts the budget or stops without finishing, the loop forces one final no-tools synthesis turn so the caller still gets a usable partial. Any run that did not cleanly finish reports status:incomplete with a non-zero exit, never status:ok. And the ask-colleague wrapper resolves the colleague CLI with zero external-tool dependencies (no grep).

## Why it matters

- explore is the headline read-only verb; a survey one step too broad must not return nothing after reading everything it needed. A no-result or unfinished run must be detectable by callers at the contract boundary (status plus exit code) without sentinel string-matching, so orchestrators can retry, widen the budget, or escalate.

## Requirements

- R1 (#191): When _work_loop exits via _EXIT_BUDGET or _EXIT_STOPPED with non-trivial context read but no finish, force ONE final no-tools synthesis turn (out of steps; stop using tools and answer now from what you have read) before assembling the result; fall back to NO_RESULT_PRODUCED only when that forced turn also yields nothing. Mirror the existing _finalize_after_cap precedent at colleague/loop.py:835, runtime-owned so it fires for every backend.
  - honesty: The forced synthesis turn fires for BOTH mock and vllm (runtime-owned in loop.py); a regression test asserts a scripted run consuming the whole max_steps budget on tool calls yields the forced-synthesis text as summary, not NO_RESULT_PRODUCED; existing test_loop / test_clone_lifecycle assertions for the genuinely-empty case still hold.
- R2 (#192): A run that did not cleanly finish (any exit other than _EXIT_FINISHED) reports a distinct status:incomplete and a non-zero exit code; status:ok is reserved for a clean finish via the finish tool. The new status value is part of the contract for every backend (all-engines rule; the e2e mock-vs-vllm shape test is updated to pin it).
  - honesty: The e2e mock-vs-vllm shape test pins status:incomplete for an unfinished run and status:ok only for a clean finish; ask-colleague.sh branches on the status and exit code with no sentinel string-match; genuine successful runs stay status:ok with exit 0.
- R3 (#188 + #194): During a read-only mapping run the runtime detects read-more-than-N-files (and/or context filling toward the fill-line threshold) and injects ONE structured fan-out recommendation handing the model a concrete per-folder or N-file partition pointed at the existing subagents tool. Backend-judged and advisory (strict no-op if declined), reusing make_batch_spawn / batch_spawn with no new worktree or merge code; read-only fan-out collects child findings without a merge child and respects MAX_SUBAGENT_FANOUT and MAX_SUBAGENT_DEPTH.
  - honesty: The fan-out is a strict no-op (byte-identical TaskResult) when not triggered or declined; it adds no new worktree or merge code (reuses make_batch_spawn / batch_spawn); it fires identically for mock and vllm; read-only children open no PR and perform no merge; the existing FANOUT and DEPTH caps are respected.
- R4 (#194): The partial-summary warning gains an exact re-run hint (the step count reached plus the concrete larger --max-steps value to retry with); --max-steps still overrides the default in both directions; explore's default budget is reconsidered in light of fan-out (kept modest because fan-out, not a bigger number, handles breadth) and any change to write or review defaults is deliberate and documented in SKILL.md and the --help usage block.
  - honesty: The re-run hint prints the actual step count reached and a concrete larger --max-steps value; --max-steps still overrides the default in both directions; any default change to write or review is reflected in SKILL.md and the --help usage block; a test asserts the hint text contains the reached count and a larger budget.
- R5 (#190): ask-colleague.sh _colleague_via_uv resolver is grep-free via a pure-bash _pyproject_is_colleague check, resolving a colleague checkout on a PATH that has no grep; the stale comment claiming grep is only used by the uv-fallback resolver is corrected (grep is no longer used at all); a regression test mirrors the existing no-python3 and no-mktemp tests in tests/test_ask_colleague_skill.py.
  - honesty: No grep invocation remains anywhere in ask-colleague.sh; a regression test resolves a checkout on a grep-less PATH (stub colleague off PATH, point --repo at a checkout, assert resolution via uv run --project); black, isort, flake8, bandit and teken cli doctor --strict stay clean.

## Honesty conditions

- Each of the four threads is independently verifiable by a test: a budget-exhausted explore returns synthesized text not the sentinel; an unfinished run reports status:incomplete with non-zero exit; a wide map can fan out to subagents; ask-colleague resolves with no grep.
- The audience is real and already keys off run status/exit today: ask-colleague explore, culture front-door surveys, and batching orchestrators exist, so the contract change is observable by them.
- The failure reproduces: a broad explore at --max-steps 20 on a medium repo lands an artifact with summary == __COLLEAGUE_NO_RESULT_PRODUCED__ and large usage.prompt_tokens (the #191 and #192 repros).
- Each behavior is demonstrable end to end on both mock and vllm: fan-out yields a synthesized map, the forced turn yields a partial, and an unfinished run reports status:incomplete.
- A caller can branch on the outcome using status plus exit code alone with no sentinel string-match, proven by ask-colleague.sh keying off them.
- The non-goals hold structurally: no new runtime dependency, socket, or daemon (zero-deps guard green); fan-out reuses existing subagents code with no new worktree or merge; and MAX_SUBAGENT_FANOUT=4 / MAX_SUBAGENT_DEPTH=2 are unchanged.
- Each success signal is pinned by a test: synthesized map not the sentinel, status:incomplete plus non-zero exit for the empty run, grep-less PATH resolution, and the e2e shape and zero-deps guards stay green.

## Success signals

- A whole-repo explore on an 80-plus-module package returns a usable synthesized map (via fan-out and/or the forced-synthesis turn) rather than the no-result sentinel; a genuinely empty run reports status:incomplete with a non-zero exit; ask-colleague resolves a colleague checkout on a PATH that has no grep; the e2e mock-vs-vllm shape test and the zero-deps guard stay green.

## Scope / boundaries

- Out of scope: a raw max-steps bump as the primary fix (fan-out replaces grinding); a new daemon, multi-backend router, or execution sandbox; forced delegation (fan-out stays backend-judged and advisory, a strict no-op when not triggered or declined). Read-only fan-out does no git merge: children return findings only, nothing is written or merged. The subagent caps are unchanged (MAX_SUBAGENT_FANOUT=4, MAX_SUBAGENT_DEPTH=2). No new runtime dependency, socket, or daemon.

## Assumptions

- The served model can act on the injected fan-out recommendation by calling subagents; on a serializing vLLM server the real wall-clock speedup is bounded by overlapped I/O wait, not model compute (honest limit carried verbatim from the existing subagents feature). The forced-synthesis turn costs one extra model turn beyond the budget.

## Decisions

- The codebase-mapping fix is subagent fan-out across small folders, NOT a raw step-budget bump; this supersedes the announcement phrase step budget tuned for codebase-mapping. A modest budget plus the re-run hint remain as the floor for runs that decline to fan out.

## Open questions (parked, non-blocking — resolve in the plan)

- v1: Default value of N (the files-read fan-out trigger) and whether the trigger keys off files-read count, the existing context fill-line threshold, or both. Proposed default: fire on whichever crosses first, N env-tunable, reusing the existing fill-line plumbing.
- v2: Whether read-only fan-out may use all 4 MAX_SUBAGENT_FANOUT slots (no merge child reserved for a read-only map) or stays capped like the write path. Proposed: read-only fan-out reserves no merge slot but stays within the existing cap.

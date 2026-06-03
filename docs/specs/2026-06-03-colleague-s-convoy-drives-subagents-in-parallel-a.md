# Colleague's convoy drives subagents in parallel: a single delegation fans out a batch of child drives that run concurrently, each isolated in its own throwaway git worktree, so an engine can exploit model-gear's concurrent-request support instead of paying sequential wall-clock. Bounded by the existing depth(2)/fan-out(4) caps plus a new opt-in concurrency-width knob that defaults to 1 (off — byte-identical to today's sequential path). Threads are confined to subagents.py as a newly-sanctioned concurrency consumer; the rest of colleague stays zero-thread, zero-async, zero-daemon.

> Colleague's convoy drives subagents in parallel: a single delegation fans out a batch of child drives that run concurrently, each isolated in its own throwaway git worktree, so an engine can exploit model-gear's concurrent-request support instead of paying sequential wall-clock. Bounded by the existing depth(2)/fan-out(4) caps plus a new opt-in concurrency-width knob that defaults to 1 (off — byte-identical to today's sequential path). Threads are confined to subagents.py as a newly-sanctioned concurrency consumer; the rest of colleague stays zero-thread, zero-async, zero-daemon.

## Audience

- An engine driving colleague mid-drive (the model in the tool-loop) that wants to fan a scoped task across several children at once; plus the operator who opts concurrency on, and colleague maintainers who own the boundary conventions.

## Before → After

- Before: Subagents run strictly one-at-a-time, in-process and synchronous (subagents.py docstring: 'launch is SYNCHRONOUS ... no thread'); a 3-way audit pays ~3x wall-clock even though model-gear now serves concurrent requests. CLAUDE.md documents parallel subagents and per-subagent worktree isolation as PARKED follow-ups ('v0 is SEQUENTIAL only').
- After: A single subagent delegation can carry a BATCH of instructions; colleague runs those child drives concurrently via a ThreadPoolExecutor confined to subagents.py, each child isolated in its own throwaway git worktree, and folds the SubResults back into TaskResult.sub_results identically for mock and vllm-openai.

## Why it matters

- model-gear gained concurrent-request support (issue #86; PR #87 took the context half); without parallel children the convoy cannot exploit it, so outsourced fan-out work stays needlessly serial.

## Requirements

- threading/concurrent.futures is sanctioned in exactly ONE new file (subagents.py) via a confinement allow-list in test_boundary.py, mirroring the existing subprocess-confinement check; threads stay forbidden in every other colleague module (the mesh-module daemon-primitive check is unchanged).
  - honesty: test_boundary.py gains a thread-confinement check that FAILS if threading/concurrent.futures is imported in any colleague module other than subagents.py and PASSES for subagents.py; the existing asyncio/multiprocessing/subprocess/mesh-daemon checks are unchanged and still pass.
- Each parallel child runs in its OWN throwaway git worktree (created/removed via subprocess in a sanctioned module); the parallel phase never writes the shared working tree, and bringing child changes back to the main tree is a SEQUENTIAL post-join step so the merge phase is race-free too.
  - honesty: Two parallel children that write the same repo-relative path do not corrupt each other because each writes only inside its own git worktree; the main working tree is untouched until the sequential post-join merge step.
- An opt-in concurrency-width knob (e.g. COLLEAGUE_SUBAGENT_CONCURRENCY on EngineConfig, default 1) gates parallelism; it is bounded by MAX_SUBAGENT_FANOUT=4 and MAX_SUBAGENT_DEPTH=2, both unchanged.
  - honesty: With COLLEAGUE_SUBAGENT_CONCURRENCY unset or 1, the boundary test, the e2e shape test, and tests/test_zero_deps.py all pass and a batch runs sequentially with NO thread spawned; raising it to k>1 spawns at most min(k, MAX_SUBAGENT_FANOUT) workers.
- Worktree + branch teardown is IDEMPOTENT (resolves v2): on drive finish, on a child that errored mid-run, or on a re-run, cleanup removes every per-child worktree and every sub/<child-id> branch and leaves nothing dangling; running teardown twice is a safe no-op, never an error.
  - honesty: After any drive outcome (success, partial, or a child error mid-run), 'git worktree list' shows no leftover child worktrees and 'git branch' shows no leftover sub/<child-id> branches; invoking teardown a second time is a no-op, not an error.

## Honesty conditions

- The shipped feature matches the announcement end-to-end and is test-verifiable: a 'subagents' batch tool runs children concurrently in isolated per-branch worktrees, a sequential merge-subagent integrates them, it is opt-in (default width=1 = byte-identical sequential), threads are confined to subagents.py, and the full existing suite (e2e shape, boundary confinement, zero-deps) stays green.
- Both audiences are served and test-exercised: an engine can trigger a parallel batch via the subagents tool mid-drive with no operator step, while the operator alone controls whether parallelism is active via the width knob (engine cannot force width>1 past the operator's setting).
- With width>1 a batch delegation runs children concurrently (wall-clock < sequential sum on a concurrent-serving model) AND the SubResult/TaskResult.sub_results shape is unchanged vs the sequential path, so tests/test_e2e_mock.py passes either way.
- The before-state is accurate at HEAD: subagents.py is synchronous/sequential (no thread/executor), test_boundary.py has no thread-confinement entry for subagents.py, and CLAUDE.md states 'v0 is SEQUENTIAL only' — this change updates all three.
- The motivation holds: model-gear supports concurrent requests as of the v0.28.0 context bump (issue #86); a sequential convoy provably leaves that server capacity unused, which parallel children reclaim only when the operator opts in.
- The boundary holds in code: after this change the package still imports no asyncio, forks no daemon/server, and adds no automatic task->engine routing policy — verifiable by the (updated) boundary test still forbidding asyncio/multiprocessing and by the absence of any router module.
- The speedup claim is qualified: real wall-clock reduction requires the served model to handle concurrent requests; on a serializing server the gain is bounded by overlapped I/O wait, not model compute.
- The merge-subagent runs AFTER the parallel join (sequential), so conflict resolution never races with child writes; a merge it cannot resolve surfaces the conflict in the result rather than silently dropping or force-overwriting a child's work.
- A subagents batch with more than FANOUT-1 (=3) instructions is refused with a clear error BEFORE any thread or worktree is created, mirroring the existing fan-out ToolError; the reserved slot guarantees the merge-subagent always fits within FANOUT=4.

## Success signals

- A parallel batch of N children completes in wall-clock well under the sequential sum; SubResults fold into sub_results identically across mock and vllm-openai (the e2e shape test holds); and with the width knob at its default of 1, behavior is byte-identical to today's sequential path.

## Scope / boundaries

- Not a multi-engine router/'gearbox' (no automatic task->engine routing policy); not an asyncio/event-loop rewrite; not a daemon/server; not a within-single-child concurrent-request pool. Concurrency comes ONLY from running multiple isolated children at once.

## Non-goals

- No per-child git/PR handoff (unchanged): only the top-level drive hands off. Children return SubResults (+ their changed files / a patch), never their own branch or PR.

## Assumptions

- model-gear (the served vLLM model) genuinely serves concurrent requests, so blocking-urllib-per-thread yields real wall-clock parallelism; if the server serialized requests, threads would only overlap I/O wait, not model compute.

## Decisions

- Parallelism is expressed as a SINGLE tool call carrying a batch of instructions (the model cannot issue parallel tool calls in a sequential loop), not as the model firing multiple separate subagent calls. The existing one-instruction subagent tool stays as the width=1 / single-child case.
- Stats/usage/telemetry for parallel children are collected AFTER the join and folded in the main thread, so no shared mutable accumulation happens during the concurrent phase (preserving always-on DriveStats correctness).
- Merge-back model (answers q1): each parallel child commits to its OWN branch (sub/<child-id>) inside its worktree; after the join, a DEDICATED sequential merge-subagent ('child C') is spawned to git-merge the child branches into the main tree and resolve conflicts using the engine's judgment. The parent never mechanically force-merges; an unresolvable conflict surfaces in the result, it does not silently drop or clobber a child's work.
- Worktree home (answers q1): git worktree add/remove + per-child branch bookkeeping live in a NEW colleague/worktrees.py, added to the test_boundary.py subprocess allow-list as one new sanctioned consumer; the mesh-module daemon-primitive check still excludes it.
- Batch interface (answers q2): a NEW 'subagents' (plural) loop tool takes an instructions[] array and runs the children concurrently; the existing single-child 'subagent' tool is unchanged (byte-identical schema + behavior). subagents.py owns the ThreadPoolExecutor and the worktree-per-child orchestration.
- Fan-out accounting (resolves v1): the merge-subagent ('child C' that wraps the change) COUNTS against MAX_SUBAGENT_FANOUT=4. A parallel batch is therefore capped at FANOUT-1 (=3) concurrent workers, reserving exactly one slot for the sequential merge/wrap subagent — at most 3 parallel children + 1 merge child = 4 total, so the existing fan-out cap is never exceeded.

## Hard questions

- Where does 'git worktree add/remove' live: extend handoff.py (already a sanctioned subprocess consumer) or add a new worktrees.py to the subprocess allow-list? And how are child changes brought back to the main tree?
- Is the batch a NEW 'subagents' (plural) tool, or the existing 'subagent' tool extended with an optional instructions[] array? One tool keeps the surface small; two keeps single-child calls unchanged.
- risk: If model-gear serializes requests under the hood, wall-clock gains shrink to I/O-wait overlap only, so the success_signal speedup must be qualified as 'on a concurrent-serving model'.

## Open / follow-up

- Cleanup ordering of N worktrees + branches on drive finish (and on a child that errored mid-run) — must be idempotent and leave no dangling worktree/branch; exact teardown sequence is a plan-time detail.

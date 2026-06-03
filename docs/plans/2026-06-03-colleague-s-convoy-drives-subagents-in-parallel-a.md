# Build Plan — Colleague's convoy drives subagents in parallel: a single delegation fans out a batch of child drives that run concurrently, each isolated in its own throwaway git worktree, so an engine can exploit model-gear's concurrent-request support instead of paying sequential wall-clock. Bounded by the existing depth(2)/fan-out(4) caps plus a new opt-in concurrency-width knob that defaults to 1 (off — byte-identical to today's sequential path). Threads are confined to subagents.py as a newly-sanctioned concurrency consumer; the rest of colleague stays zero-thread, zero-async, zero-daemon.

slug: `colleague-s-convoy-drives-subagents-in-parallel-a` · status: `exported` · from frame: `colleague-s-convoy-drives-subagents-in-parallel-a`

> Colleague's convoy drives subagents in parallel: a single delegation fans out a batch of child drives that run concurrently, each isolated in its own throwaway git worktree, so an engine can exploit model-gear's concurrent-request support instead of paying sequential wall-clock. Bounded by the existing depth(2)/fan-out(4) caps plus a new opt-in concurrency-width knob that defaults to 1 (off — byte-identical to today's sequential path). Threads are confined to subagents.py as a newly-sanctioned concurrency consumer; the rest of colleague stays zero-thread, zero-async, zero-daemon.

## Tasks

### t1 — New colleague/worktrees.py: per-child git worktree + sub/<id> branch lifecycle with idempotent teardown

- covers: c9, h3, c19, h8
- acceptance:
  - worktree_add(repo, child_id) creates an isolated git worktree checked out on a fresh branch sub/<child-id>, using subprocess only (module is added to the boundary subprocess allow-list).
  - Teardown is idempotent: after success, partial, or a simulated mid-run child error, 'git worktree list' shows no child worktrees and 'git branch' lists no sub/<child-id> branches; a second teardown call is a no-op that raises nothing.
  - A write to the same repo-relative path from two different child worktrees does not affect the other worktree or the main working tree (proven by a test).

### t2 — Width knob: COLLEAGUE_SUBAGENT_CONCURRENCY on EngineConfig (default 1)

- covers: c10, h4
- acceptance:
  - EngineConfig.subagent_concurrency resolves from COLLEAGUE_SUBAGENT_CONCURRENCY via the existing EngineConfig.resolve precedence; unset/empty/non-numeric yields the default 1.
  - Effective worker count is min(requested, MAX_SUBAGENT_FANOUT-1); a value of 1 guarantees no ThreadPoolExecutor/thread is ever created (sequential path).

### t3 — Parallel orchestration in subagents.py: ThreadPoolExecutor over per-worktree children + sequential merge-subagent

- depends on: t1, t2
- covers: c1, h9, c3, h1, c7
- acceptance:
  - subagents.py runs a batch of child instructions concurrently via concurrent.futures.ThreadPoolExecutor (confined to this file), each child driven inside its own worktree/branch from worktrees.py; SubResults are collected AFTER the join in the main thread (no shared mutable accumulation during the concurrent phase).
  - After the join, a dedicated SEQUENTIAL merge-subagent git-merges the child branches into the main tree and resolves conflicts via the engine; an unresolvable conflict is surfaced in the result, never force-merged or silently dropped.
  - Concurrency proof: a width>1 batch of N artificially-delayed mock children completes in wall-clock well under the sequential sum (e.g. < 0.6x); the module docstring no longer claims 'SYNCHRONOUS ... no thread' for the batch path.

### t4 — New 'subagents' (plural) loop tool taking instructions[]; single-child 'subagent' unchanged

- depends on: t3, t2
- covers: c2, h10
- acceptance:
  - ToolExecutor exposes a 'subagents' tool whose schema accepts an instructions[] array (+ optional per-item engine/model); the existing single-child 'subagent' tool schema and behavior are byte-identical (pinned by a test).
  - A batch with more than MAX_SUBAGENT_FANOUT-1 (=3) instructions is refused with a clear ToolError BEFORE any thread or worktree is created.
  - The engine triggers the batch with no operator step; actual parallelism is capped by the operator's COLLEAGUE_SUBAGENT_CONCURRENCY (the engine cannot exceed it).

### t5 — Loop wiring: build + inject the batch spawn so the subagents tool is offered to every engine (all-engines rule)

- depends on: t3, t4
- covers: c2
- acceptance:
  - loop.py constructs the batch spawn (analogous to make_spawn) and injects it into ToolExecutor; config.subagent_concurrency is forwarded; mock and vllm-openai are wired identically (no engine module touches it).
  - An all-engines test confirms the 'subagents' tool is present in the tool set for both mock and vllm-openai.

### t6 — Boundary test: thread-confinement (subagents.py only) + worktrees.py on the subprocess allow-list

- depends on: t1, t3
- covers: c8, h2, c6, h13
- acceptance:
  - test_boundary.py gains a check that FAILS if threading/concurrent.futures is imported in any colleague/*.py other than subagents.py, and asserts subagents.py DOES import it (no allow-list drift).
  - colleague/worktrees.py is added to _SUBPROCESS_ALLOWED and excluded from _MESH_MODULES; the existing asyncio/multiprocessing/os.fork/socket/mcp checks are unchanged and still pass.
  - After the change the whole package still imports no asyncio and contains no daemon/server or task->engine router (boundary holds in code).

### t7 — e2e shape parity: sub_results identical across engines and across sequential vs parallel; width-1 byte-identical

- depends on: t3, t4, t5
- covers: c7, h4, h9
- acceptance:
  - tests/test_e2e_mock.py asserts TaskResult.sub_results has identical shape whether a child ran via the sequential path or a parallel batch, for both mock and vllm-openai.
  - With COLLEAGUE_SUBAGENT_CONCURRENCY unset/1, a batch produces byte-identical results to running the same children sequentially, and tests/test_zero_deps.py + the boundary test stay green.

### t8 — Docs: CLAUDE.md (sequential->parallel + boundary), feature doc, honest speedup limit

- depends on: t3, t5, t6
- covers: c4, h11, c5, h12, h5
- acceptance:
  - CLAUDE.md's subagent + boundary bullets are updated: the 'v0 is SEQUENTIAL only' / 'parked follow-up' language is replaced with parallel-subagents-landed (threads confined to subagents.py; worktrees.py on the subprocess allow-list; merge-subagent; opt-in width knob).
  - A feature doc (docs/features/parallel-subagents.md) records the motivation (model-gear concurrency, issue #86), usage of the subagents tool + width knob, and the HONEST limit: real speedup needs a concurrent-serving model; on a serializing server the gain is bounded by I/O overlap.
  - The before-state references are corrected wherever the change touches them (the three HEAD facts in h11: subagents.py docstring, test_boundary entry, CLAUDE.md).

## Risks

- [unknown_nonblocking] Merge-subagent conflict-resolution quality is engine-dependent: an engine may produce a poor or incomplete merge. Mitigated by surfacing unresolved conflicts in the result rather than force-merging, but merge correctness is not guaranteed by the harness. (task t3)
- [unknown_nonblocking] Nested batches (a depth-1 child issuing its own subagents batch at depth 2): fan-out/width accounting across depth is unspecified; v0 may restrict batch parallelism to the top-level drive and keep depth-2 children sequential. (task t4)
- [follow_up] Exact git merge mechanic (sequential 'git merge' per sub/<id> branch vs alternatives) and handling of an empty-diff or failed child branch — pinned during t3 implementation. (task t3)

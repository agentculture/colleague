# Convertible drives can delegate sub-tasks to subagents — each a nested drive on any engine or model — and fold the results back into the main loop; the engine decides per sub-task whether to do the work itself or hand it off.

> Convertible drives can delegate sub-tasks to subagents — each a nested drive on any engine or model — and fold the results back into the main loop; the engine decides per sub-task whether to do the work itself or hand it off.

## Audience

- Operators driving multi-step repo tasks who want a cheaper, faster, or specialist model to handle scoped sub-tasks while a capable 'driver' model orchestrates — plus engine authors, who inherit the capability for free via the chassis (all-engines rule).

## Before → After

- Before: Today a drive is single-engine, single-model end to end. The only model switch is --engine at the top level; mid-drive there is no way for the model to hand a scoped sub-task to a different (cheaper/specialist) engine. loop.run drives one 'complete' closure start to finish.
- After: Mid-drive, an engine can call a 'subagent' (delegate) tool: it names a scoped sub-task and optionally an engine and/or model. The chassis runs a nested in-process drive on that engine/model through the SAME loop path, then folds the child's result summary back into the parent's tool-loop as the tool result.

## Why it matters

- It applies Convertible's 'one harness, many engines' promise WITHIN a single drive: a strong orchestrator can delegate narrow or expensive sub-tasks to the right-sized engine, instead of paying top-tier cost for every step or being locked to one model for the whole job.

## Requirements

- A subagent is an in-process nested drive: the loop offers a 'subagent' tool that builds a child Task (same repo_path), resolves a child engine+model, runs the SAME loop.run/drive path WITHOUT a git handoff, and returns the child result summary as the tool result fed back to the parent loop.
  - honesty: The subagent dispatch opens no socket, forks no process, and starts no daemon: it reuses loop.run in-process and adds no runtime dependency (zero-deps guard stays green). It performs no branch/commit/PR — only the top-level execute_drive hands off.
- The subagent tool accepts an OPTIONAL engine and/or model override; both resolve through the existing registry.load + EngineConfig.resolve path. Omitted -> inherit the parent's engine+model. Switching engine/model is a config-level choice, never an engine code change (consistent with 'retargeting is config, not code').
  - honesty: A mock->mock and a mock->(different model string/base_url) delegation both succeed via registry.load + EngineConfig.resolve alone, with zero changes to either engine's code; an omitted engine/model inherits the parent's.
- Because a subagent runs through the same loop path, it inherits the full chassis — hooks (incl. per-model overlay), telemetry (nested spans), approval policy (incl. per-model overlay), identity, neighbours, and AGENTS/skills layers — all resolved for the SUBAGENT's model via the existing exact-path (layers.sanitize_model) resolution, never a sibling model's.
  - honesty: A subagent launched on model X loads X's per-model hooks/approvals/AGENTS/skills layers (not the parent's, not a sibling's) via the existing layers.sanitize_model exact-path construction; telemetry OFF is a strict no-op and child spans nest under the parent tool span when ON.
- The subagent tool belongs to the chassis (convertible/tools.py schema + loop wiring), not to any engine: no engine module imports or special-cases it. The all-engines rule applies — mock and vllm-openai expose the identical tool, guarded by the e2e shape test.
  - honesty: No module under convertible/engines/ imports or references the subagent tool; the schema lives in convertible/tools.py and the wiring in the loop/drive path; the e2e shape test proves mock and vllm-openai expose the identical tool surface.
- Subagent recursion depth and per-drive fan-out are bounded with sane defaults; the parent TaskResult gains a sub-results field OMITTED when empty (byte-identical no-subagent artifact); child changed_files merge into the parent's changed set for the single top-level handoff.
  - honesty: The e2e shape test stays green for a no-subagent drive (sub-results key omitted when empty, exactly like destination/announcement); a documented depth+fan-out cap guarantees the subagent tree terminates; a delegated drive's artifact shows the nested sub-result and the parent's changed_files include the child's writes.

## Honesty conditions

- End-to-end truth: a single drive can, mid-loop, delegate a scoped sub-task to a nested drive on a different engine/model and fold its result back — demonstrated by a mock->mock delegation test whose parent step-trace shows the subagent call and whose summary reflects the child's work.
- The benefit needs no operator wiring to enable: the subagent tool is present for every engine by default (like read_file/finish), so the cheaper/specialist sub-task use case works out of the box and engine authors add zero code (the tool is chassis-owned).
- Verifiable baseline: in today's code (loop.run + the seven existing tools) there is no tool by which the model can invoke a second engine/model mid-loop; --engine is resolved once in cmd_drive and never re-entered during the loop.
- The folded-back tool result is the child's summary plus a compact changed-files signal, returned as a plain string fed to the parent loop like any other tool result, so the parent model can read it and continue or finish.
- The win is observable as model-appropriate cost: the artifact records which engine/model ran each child drive, so a strong-orchestrator + cheap-sub-task split is visible in the dashboard, not hand-waved.
- No file or config maps task->engine automatically; the ONLY routing is the orchestrator model's per-call tool choice, and a drive that never calls the subagent tool is byte-identical to today. (This is the recorded resolution of gearbox risk q1.)
- The subagent dispatch runs the child drive synchronously and returns before the parent loop continues: no thread/process pool, no asyncio loop, no socket — the subagent path is a direct in-process call into the existing drive machinery.
- The child drive runs the loop WITHOUT calling handoff(): no branch/commit/PR per subagent; only the top-level execute_drive hands off once, and the child's changed files merge into the parent result so that single handoff stages them.
- tests/test_e2e_mock.py asserts the no-subagent artifact is unchanged; the new sub-results key is OMITTED (not null) when empty, exactly like destination/announcement in TaskResult.to_dict().
- A test drives mock with a scripted subagent call to mock and asserts the parent step-trace contains the subagent step, the nested sub-result is recorded, and the identical tool schema is present for vllm-openai.
- A test proves a subagent recursing past the depth cap is refused — the tool returns an error string fed back to the model, never an unbounded stack — so the subagent tree provably terminates, analogous to max_steps.

## Success signals

- A drive that calls no subagent tool serializes a byte-identical artifact to today (the e2e shape test stays green); the parent TaskResult gains a sub-results field that is OMITTED when empty, mirroring destination/announcement. A delegated drive records the nested sub-result(s) and the merged changed_files in the artifact.
- The subagent tool is offered identically to mock and vllm-openai (all-engines rule), and a mock->mock (and mock->different-model) delegation round-trips in a test: the child runs the same loop and its summary returns as the parent tool result.
- Subagent depth and fan-out are bounded with sane defaults, and the whole subagent tree is guaranteed to terminate (no infinite recursion) — analogous to the loop's max_steps termination guarantee.

## Scope / boundaries

- NOT the out-of-scope multi-engine router/'gearbox': there is no operator-configured automatic task->engine routing policy. Delegation is engine-judged — a loop tool the model chooses per call, exactly like the optional devague destination tool. A drive that never calls it behaves identically to today.
- NOT a daemon/server and NOT concurrent in v0: subagents are SEQUENTIAL, in-process nested drives via the existing loop path — no fork, no socket, no thread pool, no new runtime dependency. Parallel/concurrent subagents (and per-subagent worktree isolation) are a parked follow-up needing their own re-spec.
- Subagents do NOT each hand off: only the top-level drive branches/commits/opens a PR. A subagent shares the parent working tree; its changed files merge into the parent result's changed set for the single top-level handoff.

## Decisions

- Car-metaphor framing: a subagent drive is a dispatched follower car in a 'convoy' led by the main drive (proposed name; the main agent keeps the wheel and hands a leg to a chosen engine). Final metaphor noun is cosmetic and not convergence-blocking.

## Hard questions

- risk: Risk: this feature is adjacent to the explicitly out-of-scope 'multi-engine router/gearbox'. It must stay engine-judged delegation (a loop tool the model chooses), never an operator policy that auto-routes task->engine. If a config-driven router creeps in, scope has crept.

## Open / follow-up

- Parallel/concurrent subagents and per-subagent git-worktree isolation — deliberately deferred; needs concurrency machinery and its own re-spec.

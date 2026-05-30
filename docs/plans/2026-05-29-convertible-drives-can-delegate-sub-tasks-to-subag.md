# Build Plan — Convertible drives can delegate sub-tasks to subagents — each a nested drive on any engine or model — and fold the results back into the main loop; the engine decides per sub-task whether to do the work itself or hand it off.

slug: `convertible-drives-can-delegate-sub-tasks-to-subag` · status: `exported` · from frame: `convertible-drives-can-delegate-sub-tasks-to-subag`

> Convertible drives can delegate sub-tasks to subagents — each a nested drive on any engine or model — and fold the results back into the main loop; the engine decides per sub-task whether to do the work itself or hand it off.

## Tasks

### t1 — Contract: add SubResult dataclass + TaskResult.sub_results (omitted-when-empty), per-child engine/model/usage attribution

- covers: c5, h10, c9, h14, c16
- acceptance:
  - A no-subagent TaskResult.to_dict() is byte-identical to today: the sub_results key is ABSENT (not null) when empty, exactly like destination/announcement
  - A populated sub_results round-trips to_dict -> from_dict to an equal object
  - SubResult records task_id, engine, model, status, summary, changed_files, and its own usage (nested-only cost attribution; parent.usage is NOT silently summed)

### t2 — Config: add EngineConfig.subagent_spawn runtime-only field + depth/fan-out bound constants (default depth=2, fan-out=4)

- acceptance:
  - subagent_spawn defaults None and is excluded from eq/repr and to_dict (mirrors the progress field exactly)
  - EngineConfig.to_dict() output is unchanged from today
  - Bound constants MAX_SUBAGENT_DEPTH=2 and MAX_SUBAGENT_FANOUT=4 are defined and importable

### t3 — Launcher convertible/subagents.py run_subagent(): resolve child engine+model, run child via engine.drive WITHOUT handoff, enforce depth cap, return SubResult

- depends on: t1, t2
- covers: c12, c13, h3, c14, c11, h16, c7, h12, c8, h13
- acceptance:
  - A mock->mock run_subagent returns a SubResult whose summary reflects the child's work
  - Omitted engine/model inherits the parent's; a provided engine and/or model is resolved via registry.load + EngineConfig.resolve with ZERO change to any engine's code
  - Recursion past the depth cap (default 2) is refused with a clear message and never recurses unbounded; the subagent tree provably terminates
  - run_subagent runs the child via engine.drive (loop.run), performs NO git handoff (no branch/commit/PR), and runs synchronously with no thread/process pool and no socket

### t4 — Tools: add 'subagent' schema to SCHEMAS + ToolExecutor injected spawn callback + _subagent dispatch (fan-out cap, changed_files merge, absent-callback ToolError)

- depends on: t1, t3
- covers: c4, h9, c15, h5, c3, h8
- acceptance:
  - SCHEMAS includes a 'subagent' function with required 'instruction' and optional 'engine'/'model' params
  - No module under convertible/engines/ is imported or referenced by convertible/tools.py (the cycle is avoided via callback injection)
  - _subagent with no spawn callback returns a ToolError string fed back to the model, never raising out of the executor
  - _subagent returns the child summary + a compact changed-files signal and merges the child's changed_files into the parent executor.changed; per-drive fan-out beyond the cap (default 4) is refused

### t5 — Zero-deps guard: extend tests/test_zero_deps.py to import convertible.subagents and assert no third-party leak

- depends on: t3
- covers: h2
- acceptance:
  - Importing convertible.subagents leaks no third-party module
  - The guard imports loop/tools/subagents/cli and passes even with the [otel] extra installed

### t6 — Wire spawn through loop.run -> ToolExecutor; execute_drive builds the callback from run_subagent; both engines forward config.subagent_spawn; record sub_results + merge changed_files; advertise the tool in _DEFAULT_SYSTEM

- depends on: t3, t4
- covers: c1, h1, c2, h7, c6, h11
- acceptance:
  - A mock drive that scripts a subagent call records one entry on the parent artifact's sub_results and the child's changed_files appear in the parent result.changed_files for the single top-level handoff
  - _DEFAULT_SYSTEM advertises the subagent tool as OPTIONAL and engine-judged (same framing as the devague tool); a drive that never calls it is byte-identical to today
  - Both convertible/engines/mock.py and vllm_openai.py forward config.subagent_spawn to loop.run (all-engines rule); no engine special-cases the tool
  - A subagent launched on model X resolves X's per-model hooks/approvals/AGENTS/skills layers via the existing exact-path resolution

### t7 — E2E tests: byte-identical no-subagent artifact (test_e2e_mock.py) + mock->mock round-trip, all-engines schema parity, telemetry nesting (test_subagent_e2e.py)

- depends on: t6
- covers: c10, h15, h6, h4
- acceptance:
  - test_e2e_mock asserts the no-subagent artifact is unchanged (sub_results key absent)
  - A mock->mock e2e drive: the parent step-trace contains the subagent call and result.sub_results has one entry whose summary reflects the child's work
  - The 'subagent' tool schema is present and IDENTICAL for mock and vllm-openai
  - Telemetry OFF is a strict no-op (no spans, artifact unchanged); ON, the child drive spans nest under the parent tool-call span

### t8 — Docs: CLAUDE.md car-metaphor Subagents/convoy bullet + scope/honest-limits, and an explain catalog entry for the subagent tool

- depends on: t6
- acceptance:
  - CLAUDE.md documents Subagents (convoy): in-process nested drives, sequential-only, NOT the gearbox, no daemon/socket/fork, parallel subagents parked as a follow-up
  - An explain catalog entry documents the subagent tool including its honest limits (sequential-only, depth/fan-out caps, no per-subagent handoff)

### t9 — Version bump (minor) + CHANGELOG entry for the subagent feature (version-check CI gate)

- depends on: t6
- acceptance:
  - Version is bumped (minor) in pyproject.toml and convertible/__init__.py, kept in sync
  - CHANGELOG.md has a Keep-a-Changelog entry describing subagent delegation

## Risks

- [out_of_scope] Scope creep: must stay engine-judged delegation (a loop tool the model chooses), never an operator policy that auto-routes task->engine. A config-driven router would be the out-of-scope 'gearbox'. (task t6)
- [follow_up] Parallel/concurrent subagents + per-subagent git-worktree isolation are deliberately deferred — needs concurrency machinery and its own re-spec.

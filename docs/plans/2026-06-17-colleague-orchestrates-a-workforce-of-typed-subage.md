# Build Plan — Colleague orchestrates a workforce of typed subagents, each a role with its own prompt, curated tools, and skills — nesting agents of agents, with read-only roles that cannot write

slug: `colleague-orchestrates-a-workforce-of-typed-subage` · status: `exported` · from frame: `colleague-orchestrates-a-workforce-of-typed-subage`

> Colleague orchestrates a workforce of typed subagents, each a role with its own prompt, curated tools, and skills — nesting agents of agents, with read-only roles that cannot write

## Tasks

### t1 — Role model + built-in defaults + per-model loader (colleague/roles.py, new)

- covers: c11, h2, c2, h10
- acceptance:
  - A Role dataclass carries name, prompt_fragment, tool_allowlist, skill_subset, and a read_only flag; a built-in registry defines explorer/planner/reviewer (read-only), validator (read + run_tests, no write), and writer (full surface).
  - load_role(name, repo_path, model) reads .colleague/agents/<name>.md then composes the per-model overlay .colleague/<model>/agents/<name>.md by exact path with no sibling globbing; an absent file falls back to the built-in default.
  - With no .colleague/agents config and no role requested, role resolution yields the full-surface role so behavior is byte-identical to today (additive); a test asserts the default allow-list equals the full base+curated tool set.

### t2 — Curate the offered tool schema per role + executor refuses withheld tools + add role param to subagent/subagents schemas (colleague/tools.py)

- depends on: t1
- covers: c12, h3, c5, h13, c14, h5
- acceptance:
  - curate_schemas(role) returns only the tool schemas whose names are in the roles allow-list (a subset of base+curated tools); a writer role yields todays full SCHEMAS unchanged.
  - ToolExecutor is role-aware and raises ToolError when asked to execute a tool absent from the active roles allow-list, so a hallucinated withheld call is refused, not run.
  - A read-only roles curated schema contains NO write_file, edit_file, or run_command, and the executor refuses all three (closing the out-of-the-box-writing hole).
  - The subagent and subagents tool schemas gain an optional role parameter; omitting it is byte-identical to todays delegation.

### t3 — Raise recursion caps + add global agent-budget config fields (colleague/config.py)

- covers: c15
- acceptance:
  - MAX_SUBAGENT_DEPTH is raised from 2 to 4 and a constant MAX_SUBAGENT_TOTAL (global per-top-level agent budget) is set to 24.
  - EngineConfig gains resolvable fields for the depth cap and the total-agent budget (env COLLEAGUE_SUBAGENT_DEPTH / COLLEAGUE_SUBAGENT_TOTAL), defaulting to 4 and 24 through the existing resolve precedence.

### t4 — Thread the role through spawn + enforce the global agent budget + lift the nested-batch ban (colleague/subagents.py)

- depends on: t1, t3
- covers: h6
- acceptance:
  - make_spawn/make_batch_spawn and run_subagent accept an optional role and a shared global agent counter; the child is launched with the resolved role at depth+1 and the counter increments per spawned agent.
  - A spawn is refused (SubagentError, zero work, no worktree) when depth exceeds MAX_SUBAGENT_DEPTH OR the global agent count would exceed MAX_SUBAGENT_TOTAL, checked before any child work so every nesting shape terminates.
  - Nested batches are permitted (a depth>1 child may call subagents) but every child counts against the single global budget; a test drives a 4-level nesting and asserts total spawned agents never exceed the cap.

### t5 — Compose a roles tailored prompt fragment + curated skill subset via the layered-config seam (colleague/layers.py)

- depends on: t1
- covers: c13, h4
- acceptance:
  - Given a role, the layered-config path composes base prompt + the roles prompt_fragment + only the roles curated skill subset, deterministically and in fixed order, adding no second prompt-assembly code path.
  - A per-model role prompt overlay (.colleague/<model>/agents/<name>.md) composes ahead of the base by exact path with no sibling globbing, matching the skills/hooks overlay convention.

### t6 — Wire role-curated tools + role prompt + global budget into the child work item (colleague/loop.py)

- depends on: t2, t3, t4, t5
- covers: c3, h11, c16
- acceptance:
  - When a child is launched with a role, the loop builds its offered tool schema from curate_schemas(role) and its system prompt from the role-composed layers, instead of the global SCHEMAS / default prompt.
  - The role applied to each child is recorded on its SubResult/TaskResult (or step trace) so the run artifact shows which role ran (the prompt/tools/skills change is observable).
  - A run with no role requested produces a TaskResult byte-identical in shape to today.

### t7 — Add a dedicated read-only run_tests loop tool reusing the affected-tests/pytest machinery (colleague/tools.py)

- depends on: t2
- covers: c21, h9
- acceptance:
  - A run_tests tool runs the repos tests (reusing the affected-tests pytest invocation) and returns a pass/fail summary; it writes no file and shells no arbitrary command.
  - run_tests is in the validator roles allow-list, yet the validator curated schema still has no write_file, edit_file, or run_command, so it tests without any write or arbitrary-exec surface.
  - A missing/unrunnable pytest degrades to a recorded skipped message, never a traceback that aborts the work item.

### t8 — Both backends forward role config and build child tools from the role; all-engines shape parity (colleague/engines/vllm_openai.py, mock.py)

- depends on: t6
- covers: c17, h8, c4, h12
- acceptance:
  - vllm-openai and mock both forward the role via ContextControls/EngineConfig so a role-typed child yields the same TaskResult/SubResult shape on both; the e2e mock shape contract is unchanged for a default no-role run.
  - A back-compat characterization test asserts that with no role requested the subagent/subagents tools and child work behave byte-identically to the pre-role contract (instruction/engine/model only), proving the change is purely additive.

### t9 — Surface roles for inspection via an agents CLI noun (colleague/cli/_commands/agents.py, new; wired in cli/__init__.py)

- depends on: t1
- covers: c2, h10
- acceptance:
  - colleague agents list shows every resolved role (built-in + operator-declared) with its read_only flag, tool allow-list, and skill subset; agents overview prints the surface description; both support --json.
  - An agents explain catalog entry exists; results go to stdout and diagnostics to stderr per the agent-first CLI convention.

### t10 — Let ask-colleague verbs and the colleague plan workforce request a role per child (.claude/skills/ask-colleague + colleague/plan/workforce.py)

- depends on: t6
- covers: c16, h7
- acceptance:
  - The ask-colleague explore/review/write verbs accept an optional role and pass it to colleague work, so the same role machinery serves read-only explore/review and the write path (one mechanism, not five).
  - The colleague plan workforce stage can assign a role per child task when fanning out via make_batch_spawn, with no new fan-out/merge code.

### t11 — Integration proof: e2e mock==vllm role shape, additive back-compat, zero-deps/boundary guards (tests)

- depends on: t8
- covers: c1, h1, c6, h14, c10, h15
- acceptance:
  - An e2e test drives a role-typed child on mock and asserts a read-only role child has no write_file/edit_file/run_command in its offered schema, the role prompt+skills compose deterministically, and the global cap bounds total agents (each success signal is a concrete assertion).
  - The zero-deps guard (tests/test_zero_deps.py) and the boundary test still pass: roles add no runtime dependency, open no socket/daemon, and keep threads/subprocess confined to the sanctioned modules.
  - A test asserts that with no .colleague/agents config the whole pipeline is byte-identical to today (the additive invariant).

### t12 — Write-confinement test + feature doc + CLAUDE.md bullet + version bump (tests/docs)

- depends on: t11
- covers: c22, h16
- acceptance:
  - A test asserts no offered tool (for any role) can write outside the repo/worktree box and there is NO code path enabling a cross-repo out-of-repo write (free-run mode absent), confirming writes stay repo-confined.
  - docs/features/subagent-roles.md documents roles, the read-only guarantee, the depth-4/cap-24 recursion bound, and the parked free-run mode; CLAUDE.md gains a Subagent roles bullet; the version is bumped via the version-bump convention.

## Risks

- [unknown_nonblocking] Role-definition files are NOT approval-gated by checksum in v1 (unlike hooks/commands); agent-type files are a new trust surface — deferred follow-up.
- [unknown_nonblocking] Depth-4 nested orchestration buys real wall-clock speedup only on a concurrent-serving model; on a serializing server (the reference 27B) gain is bounded by overlapped I/O, not model compute. (task t4)
- [follow_up] Orchestrator meta-role (a role that dynamically plans a chain of differently-typed children) is out of scope — v2.
- [follow_up] Cross-repo free-run write mode (requires an issue + deliberate thinking) is out of scope — v2.

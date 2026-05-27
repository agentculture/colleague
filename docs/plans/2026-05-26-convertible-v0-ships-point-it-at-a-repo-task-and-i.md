# Build Plan — Convertible v0 ships: point it at a repo task and it drives the work through a swappable coder engine behind one shared task contract — the first real engine is a local coding model served via a vLLM OpenAI-compatible API.

slug: `convertible-v0-ships-point-it-at-a-repo-task-and-i` · status: `exported` · from frame: `convertible-v0-ships-point-it-at-a-repo-task-and-i`

> Convertible v0 ships: point it at a repo task and it drives the work through a swappable coder engine behind one shared task contract — the first real engine is a local coding model served via a vLLM OpenAI-compatible API.

## Tasks

### t1 — Task contract: typed Task and TaskResult with JSON (de)serialization (convertible/contract.py)

- covers: c8, h1
- acceptance:
  - Task(id, repo_path, instruction, context, constraints, engine) and TaskResult(status, summary, changed_files, steps, usage, artifacts_path) are typed and importable from convertible.contract
  - TaskResult round-trips: to_dict -> json.dumps -> json.loads -> from_dict yields an equal TaskResult (test asserts equality)

### t2 — Repo-confined tool set + executor: read_file, write_file, list_dir, run_command, finish (convertible/tools.py)

- covers: c10, h3
- acceptance:
  - Each tool exposes an OpenAI function/tool JSON schema; tools.SCHEMAS lists all five
  - Executor runs the tools against a given repo root; write_file/run_command targeting a path outside the repo root (../ traversal) raises and makes no change
  - finish returns a terminal sentinel the loop recognizes

### t3 — Packaging: convertible-cli dist, console_script convertible, convertible.engines entry points (pyproject.toml, convertible/__init__.py)

- covers: c11
- acceptance:
  - pyproject sets project.name=convertible-cli, console_scripts convertible -> convertible.cli:main, and entry-points group convertible.engines declaring mock and vllm-openai
  - Editable install exposes the convertible command and importable convertible package; convertible --version prints the version

### t4 — Engine config loading: base_url, api_key, model, max_steps, defaults (convertible/config.py)

- covers: c9
- acceptance:
  - convertible.config loads engine settings from CLI flags + env with documented precedence; defaults include base_url http://localhost:8001/v1 and the vLLM reference model
  - Missing api_key uses a placeholder (vLLM ignores it) and does not crash

### t5 — Engine protocol: abstract Engine with drive(task, repo, tools, budget) -> TaskResult (convertible/engine.py)

- depends on: t1
- covers: c9
- acceptance:
  - convertible.engine.Engine is an abstract base/Protocol exposing name and drive(task, repo, tools, budget) -> TaskResult; a subclass missing drive cannot instantiate

### t6 — Bounded agentic tool-loop (convertible/loop.py)

- depends on: t1, t2
- covers: c10, h3
- acceptance:
  - loop.run(completion_fn, tools, task, repo, max_steps) sends tool schemas, parses tool_calls, executes them via the executor, appends results, and repeats
  - loop terminates on model finish() OR when steps reach max_steps; a never-finishing completion_fn stops at max_steps
  - loop records a per-step trace (tool name, args, result) carried in the TaskResult

### t7 — Result artifact writer + structured logging (convertible/artifact.py)

- depends on: t1
- covers: c12, h5
- acceptance:
  - artifact.write(result, dir) writes valid JSON containing at least {status, changed_files, steps, usage} that reloads
  - On a raised/failed drive an artifact with status=error and the failure reason is still written

### t8 — Git/PR handoff: branch, commit, push, gh pr create, with offline/--no-pr gating (convertible/handoff.py)

- depends on: t1
- covers: c21, h7
- acceptance:
  - With a remote + gh available, handoff creates a branch, commits changed files, pushes, runs gh pr create, and returns {branch, pr_url}
  - With --no-pr or no configured remote, handoff commits locally and returns pr_url=None without pushing (verified in a local-only git repo)

### t9 — Mock engine: deterministic, networkless (convertible/engines/mock.py)

- depends on: t5, t6
- covers: c13, h6
- acceptance:
  - MockEngine.drive performs scripted tool calls (write_file then finish) through the shared loop with zero network access
  - Two runs of the same Task produce identical TaskResult content (deterministic), with network monkeypatched off

### t10 — vLLM OpenAI-compatible engine driver (convertible/engines/vllm_openai.py)

- depends on: t5, t6, t4
- covers: c9, h2
- acceptance:
  - VllmOpenAIEngine.drive POSTs to {base_url}/chat/completions with tools and feeds tool_calls through the shared loop
  - Driver uses only base_url/api_key/model config; a mocked-HTTP unit test drives a full loop, and pointing base_url at another OpenAI-compatible server needs no code change

### t11 — Wheel/engine discovery + selection via entry points (convertible/registry.py)

- depends on: t3, t9, t10
- covers: c11, h4
- acceptance:
  - registry.discover() reads importlib.metadata entry points group convertible.engines into name->Engine; registry.get(name) selects one
  - Both bundled engines appear; an out-of-tree entry point registered in the same group is also discovered (fake entry point in test)

### t12 — CLI wiring: convertible drive and convertible wheels list (convertible/cli.py)

- depends on: t5, t6, t7, t8, t11, t4, t3
- covers: c4, c2
- acceptance:
  - convertible wheels list prints discovered engines (mock, vllm-openai)
  - convertible drive --repo PATH --engine NAME --instruction TEXT [--no-pr] selects the engine, runs the loop, writes the artifact, performs handoff, exits 0 on success; same invocation works for both engines

### t13 — End-to-end mock test: identical-shaped results, engine swap, wheels list (tests/test_e2e_mock.py)

- depends on: t12
- covers: c1, c7, h8, h11, h12, h14
- acceptance:
  - A test drives the same Task on the mock engine end-to-end (drive -> artifact) with no network and asserts the TaskResult/artifact shape
  - Test asserts engine swap via --engine with zero change to the Task, and wheels list shows both engines

### t14 — vLLM driver HTTP-mocked test + opt-in live e2e proof (tests/test_vllm_openai.py)

- depends on: t10, t12
- covers: h8, h2, c1
- acceptance:
  - An HTTP-mocked test drives VllmOpenAIEngine through a full tool-loop (tool_call -> write_file -> finish) with no live server
  - An opt-in test (skipped unless CONVERTIBLE_VLLM_E2E=1) runs convertible drive against localhost:8001 Qwen3-32B, verifies a real edit, and opens a PR (or --no-pr local commit)

### t15 — Docs + CLAUDE.md /init expansion: metaphor, boundary, non-goals, vLLM flags (README.md, CLAUDE.md)

- depends on: t12
- covers: c3, c5, c6, h9, h10, h13, h12
- acceptance:
  - README documents the car metaphor (engine/driver/chassis/gearbox/wheels/dashboard/garage), the v0 boundary + non-goals, and quickstart for mock and vLLM (incl. vLLM --enable-auto-tool-choice --tool-call-parser hermes)
  - CLAUDE.md is expanded from the /init seed into a runtime prompt for convertible; steward doctor invariants prompt-file-present and backend-consistency still hold

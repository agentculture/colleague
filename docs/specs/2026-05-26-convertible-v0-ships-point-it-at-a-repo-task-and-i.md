# Convertible v0 ships: point it at a repo task and it drives the work through a swappable coder engine behind one shared task contract — the first real engine is a local coding model served via a vLLM OpenAI-compatible API.

> Convertible v0 ships: point it at a repo task and it drives the work through a swappable coder engine behind one shared task contract — the first real engine is a local coding model served via a vLLM OpenAI-compatible API.

## Audience

- Culture/Guildmaster/Taskmaster operators who assign repo work without caring which coding engine runs it, plus Convertible developers who build engine wheels.

## Before → After

- Before: Each coder backend (Codex, Claude Code, local models) has its own invocation, controls, and output shape; assigning repo work means coding against one specific backend, and swapping engines means rewriting the integration.
- After: An operator runs 'convertible drive' against a task + repo; Convertible executes it via a selected engine (mock or vLLM-OpenAI) and emits structured logs + a result artifact for handoff — the caller never needs to know which engine ran.

## Why it matters

- Culture can assign repo work behind one contract; the model becomes a swappable engine, not a hardwired dependency.

## Requirements

- R1 Task contract: a typed Task (id, repo path, instruction, optional context/constraints, engine selection) and typed TaskResult (status, summary, changed_files, step trace, usage, artifacts path) that every engine driver consumes/produces identically.
  - honesty: A Task and TaskResult round-trip through any engine unchanged in shape: the mock and vllm-openai engines both consume the same Task and produce a TaskResult with the same fields; serializing a TaskResult to JSON and reloading yields an identical object.
- R2 Engine driver protocol: an abstract Engine interface with a drive(task, repo, tools, budget) -> TaskResult; the vllm-openai driver implements it via an OpenAI-compatible /v1/chat/completions endpoint (configurable base_url, api_key, model) using tool/function calling.
  - honesty: The vllm-openai driver touches only the OpenAI-compatible surface (base_url/api_key/model + /v1/chat/completions with tools); pointing base_url at any OpenAI-compatible server is a config change, not a code change.
- R3 Agentic tool-loop: Convertible runs a bounded loop offering tools read_file, write_file, list_dir, run_command, finish; executes the model's tool_calls against the target repo working tree; feeds tool results back; terminates on finish() or a max_steps budget.
  - honesty: The agentic loop always terminates (model finish() OR max_steps reached), and write_file/run_command act only inside the target repo path — no writes escape it.
- R4 Wheel/plugin discovery: engines register as Python entry points (group convertible.engines); 'convertible wheels list' enumerates discovered engines; --engine <name>/config selects one; bundled mock and vllm-openai engines register through the same mechanism an external wheel would.
  - honesty: An engine shipped by an out-of-tree wheel installed in the same env appears in 'convertible wheels list' and is selectable via --engine with no core change, proven by the bundled engines using the identical entry-point mechanism.
- R5 Dashboard/handoff output: each run writes structured logs + a result artifact (JSON) capturing status, changed_files, step trace, and usage, suitable for handoff back to Guildmaster/Taskmaster/Steward.
  - honesty: Every drive run writes a result artifact that is valid JSON with at least {status, changed_files, steps, usage}; a failed run still writes one with status=error and the failure reason.
- R6 Mock engine: a deterministic in-process engine that performs scripted tool calls (e.g. write a file) so 'drive' works in CI with no network, exercising the same task contract + tool-loop as the real engine.
  - honesty: The mock engine completes a drive run with zero network access and deterministic output, exercising the full task contract + tool-loop, so CI validates the chassis without a live model.
- R7 Git/PR handoff: after a successful drive, Convertible edits the working tree, then creates a branch, commits, pushes, and opens a PR via the gh CLI; the result artifact records branch name + PR URL. PR creation is gated (a --no-pr flag or absent remote/auth) so the same drive completes edit+local-commit and records pr_url=null offline/in CI.
  - honesty: A drive with a configured remote + gh auth ends with a pushed branch and an open PR whose URL is in the result artifact; a drive with --no-pr or no remote completes edit + local commit and records pr_url=null.

## Honesty conditions

- End-to-end proof: 'convertible drive' against the live vLLM server at localhost:8001 (Qwen3-32B) edits a real repo correctly AND opens a PR; the same task on the mock engine yields an identically-shaped result with no network — demonstrating one contract, swappable engines.
- The audience is real and reachable: at least one concrete consumer (Guildmaster/Taskmaster/Steward, or a Convertible engine-wheel developer) can drive a task through v0 without bespoke per-backend integration.
- The pain is real today: adding a new coder backend currently requires backend-specific invocation and output handling — exactly what v0 removes behind one contract.
- After v0, 'convertible drive' produces the described handoff (logs + JSON result artifact + PR) for both engines, and the caller's invocation is identical regardless of which engine ran.
- Swapping the engine (mock <-> vllm-openai) requires no change to the task contract or caller code — only --engine/config selects it.
- v0 ships exactly the in-scope set (chassis + wheel discovery + 2 engines + PR handoff) and none of the excluded items (router/policy/sandbox/daemon); any excluded feature appearing means scope crept.
- The success signal is observable: one test/demo runs the same task on both mock and vllm-openai and asserts identically-shaped results, a working --engine swap, and 'wheels list' showing both engines.

## Success signals

- 'convertible drive' runs a task end-to-end against both a live vLLM OpenAI server and the mock engine, producing identically-shaped task results/artifacts; the engine is swappable via --engine/config with zero change to the task contract; wheels are discovered via Python entry points ('convertible wheels list').

## Scope / boundaries

- v0 is NOT a multi-engine router/policy selector, NOT a sandboxed execution environment, and NOT a daemon; it ships the chassis (task contract + lifecycle), the wheel/plugin discovery contract, and exactly two engine drivers — a mock/local wheel and a vLLM OpenAI-compatible wheel. No Codex/Claude/Gemini drivers in v0.

## Non-goals

- No gearbox in v0: no multi-engine routing/strategy/policy selection, no artifact-publisher/handoff-target wheels, and no repo-adapter abstraction beyond a local filesystem path.

## Assumptions

- The configured vLLM server is reachable and serves an OpenAI-compatible /v1/chat/completions with working tool/function calling for the model (Qwen3-32B may need vLLM's --enable-auto-tool-choice --tool-call-parser hermes).

## Decisions

- D1 CLI-first for v0 with an importable core library; daemon/library-server mode is reserved, not built.
- D2 Wheels are trusted code only in v0, loaded via entry points; no untrusted-plugin sandboxing. run_command executes in the target repo with the operator's privileges.
- D3 vLLM is driven purely through its OpenAI-compatible API (no vLLM-specific SDK), so the same driver works against any OpenAI-compatible server; reference config = base_url http://localhost:8001/v1, model Qwen3-32B (NVFP4).
- D4 PyPI distribution = convertible-cli; command + import package = convertible; a single distribution ships core + bundled engines.
- D5 Handoff model: working-tree edits are the substrate; git capture (branch/commit/push) + 'gh pr create' is the default handoff. Requires a git remote + gh auth on the target repo; --no-pr or a missing remote degrades gracefully to a local commit so CI/offline runs never push.

## Open / follow-up

- run_command sandboxing / resource limits — v0 trusts the operator's environment (D2); isolation is a later sandbox wheel.

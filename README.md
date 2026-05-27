# convertible

> Convertible CLI is a swappable coder-agent harness that turns different models
> into repo workers behind one shared task contract.
>
> **One harness, many engines.**

Convertible is the **car around the model**. The model is the engine;
Convertible is the chassis, controls, task contract, and handoff that turn that
engine into a usable repo worker. Point it at a repo task and it drives the work
through whichever coder engine you select — and the caller never has to care
which one ran.

## The metaphor, as architecture

| Part | In Convertible |
|------|----------------|
| **Engine** | the model/coder backend (a local vLLM model, …) |
| **Driver** | the adapter that invokes and controls one engine (`convertible/engines/`) |
| **Chassis** | the shared task contract + lifecycle (`Task` → `TaskResult`) |
| **Tool-loop** | the bounded agentic loop the engine drives the repo through |
| **Wheels** | replaceable engine plugins, discovered via Python entry points |
| **Dashboard** | the JSON result artifact + step trace each run writes |
| **Garage** | `convertible wheels list` — the engines installed in this env |

## What ships in v0

- A **shared task contract** — a typed `Task` and `TaskResult` that every engine
  consumes and produces identically.
- A **bounded agentic tool-loop** — the engine calls `read_file`, `write_file`,
  `list_dir`, `run_command`, and `finish`, confined to the target repo, until it
  finishes or hits the step budget.
- **Two engines**, both registered through the same `convertible.engines`
  entry-point group an out-of-tree wheel would use:
  - `mock` — deterministic and networkless; the CI workhorse.
  - `vllm-openai` — drives any **OpenAI-compatible** `/v1/chat/completions`
    endpoint with tool calling (the reference rig: Qwen3-32B on a vLLM server).
- **Git/PR handoff** — branch → commit → push → `gh pr create`, gated so
  `--no-pr` (or no remote) stays a local commit and CI never pushes.
- A **result artifact** (`.convertible/<task-id>.json`) for handoff back to
  Guildmaster / Taskmaster / Steward.

**Not in v0** (by design): a multi-engine router/policy gearbox, an execution
sandbox, a daemon mode, and Codex/Claude/Gemini drivers. The runtime package has
**no third-party dependencies** — the vLLM driver speaks the OpenAI wire format
over the standard library.

## Quickstart

```bash
uv sync
uv run pytest -n auto                          # full suite, no network needed

# Discover the engines installed in this environment:
uv run convertible wheels list

# Drive a task with the deterministic mock engine (no model, no network):
uv run convertible drive "add a CONTRIBUTING.md stub" --repo . --engine mock --no-pr
```

### Driving a real model (vLLM)

Start an OpenAI-compatible vLLM server with tool calling enabled:

```bash
vllm serve Qwen/Qwen3-32B \
  --port 8001 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

The `--tool-call-parser` is model-specific (`hermes` suits many models;
some Qwen3 builds want `qwen3_coder`). The engine is parser-agnostic — any
parser that makes the server emit OpenAI-format tool calls works.

Then point Convertible at it (defaults already target `localhost:8001`):

```bash
uv run convertible drive "fix the typo in the README title" \
  --repo /path/to/target/repo \
  --engine vllm-openai \
  --base-url http://localhost:8001/v1 \
  --model Qwen/Qwen3-32B
```

Configuration resolves in the order: explicit flag → `CONVERTIBLE_*` env →
`OPENAI_*` env → default. Because the driver only touches the OpenAI surface,
pointing `--base-url` at any compatible server (llama.cpp, an OpenAI proxy) needs
no code change.

The opt-in live end-to-end test proves this against a real server:

```bash
CONVERTIBLE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

## CLI

| Verb | What it does |
|------|--------------|
| `drive <instruction>` | Run a repo task through a coder engine; write the artifact; hand off. |
| `wheels list` | List discovered engine wheels (the garage). |
| `whoami` | Report this agent's nick, version, backend, and model. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Check the agent-identity invariants. |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

## Writing your own engine wheel

An engine is a class implementing `convertible.engine.Engine` (one method:
`drive(task, config) -> TaskResult`). Advertise it under the entry-point group
and `convertible wheels list` discovers it — no change to Convertible core:

```toml
[project.entry-points."convertible.engines"]
my-engine = "my_package.engine:MyEngine"
```

Most engines never re-implement the loop — they delegate to
`convertible.loop.run` and only supply *how the model is called*.

## License

MIT — see [`LICENSE`](LICENSE).

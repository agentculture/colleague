# Drive & the tool-loop

> The chassis: a shared task contract and a bounded agentic loop that every
> engine drives a repo through.

`colleague drive "<goal>"` is colleague's working surface. You hand it a
goal or instruction and it works autonomously — selecting an engine wheel,
running a bounded agentic tool-loop against the target repo, writing a result
artifact, and handing the change off as a branch/PR. The repo is the *target*
(`--repo`, default cwd), not the headline; the same invocation works for every
engine — only `--engine` changes.

## The task contract

Every engine consumes a `Task` and produces a `TaskResult` of the **same shape**,
regardless of which model ran underneath. That uniformity is the whole point of
colleague: the caller assigns repo work without caring which engine executed
it. Both are plain dataclasses with explicit `to_dict`/`from_dict`, so a result
round-trips through JSON unchanged (`colleague/contract.py`).

| `Task` field | Meaning |
|--------------|---------|
| `id` | Short uuid (12 hex chars), minted by `Task.new`. |
| `repo_path` | The target repository. |
| `instruction` | The goal/instruction text. |
| `context` | Optional extra context appended to the user message. |
| `constraints` | Optional list, rendered as a bulleted "Constraints:" block. |
| `engine` | The driver to run it through (default `mock`). |

| `TaskResult` field | Meaning |
|--------------------|---------|
| `task_id` / `status` | The task id and `ok` / `error`. |
| `summary` | The model's finish summary (or a budget/step fallback). |
| `changed_files` | Files the run touched (from the executor + `git status`). |
| `steps` | The per-step trace (one `Step` per tool call). |
| `usage` | Token accounting summed across model calls. |
| `artifacts_path` | Where the result JSON was written. |
| `error` | Set only when `status == error`. |
| `branch` / `pr_url` | Populated by the [handoff](handoff.md); `pr_url` is `None` when local-only. |
| `hook_firings` | Every [hook](hooks.md) invocation in order. |
| `command` | The originating [command template](command-templates.md) name, or `None` for ad-hoc. |

## The bounded tool-loop

The loop (`colleague/loop.py`) is **engine-agnostic**. It is handed a
`complete` callable that performs *one* model turn (given the running message
list, return the assistant reply and any tool calls) and drives it in a loop:
execute each requested tool against the repo, feed the result back, repeat. The
mock engine supplies a scripted `complete`; the vLLM engine supplies one that
POSTs to an OpenAI-compatible endpoint. The loop never knows the difference.

The model is offered **six tools** (`colleague/tools.py`), handed to it as
OpenAI function schemas — the original five base tools plus one curated
`culture` tool added via the mesh-member re-spec:

| Tool | What it does |
|------|--------------|
| `read_file` | Read a UTF-8 file, relative to the repo root. |
| `write_file` | Create/overwrite a UTF-8 file, relative to the repo root. |
| `list_dir` | List a directory's entries, relative to the repo root. |
| `run_command` | Run a shell command with `cwd` pinned to the repo root. |
| `culture` | Run an allow-listed AgentCulture CLI (`agtag` / `devex`) with the agent's identity injected. See [mesh-member.md](mesh-member.md). |
| `finish` | Signal completion with a short summary. |

### Confinement

`read_file` / `write_file` / `list_dir` resolve their path against the repo root
and refuse anything that escapes it (`..` traversal, absolute paths outside the
tree). `run_command` runs with `cwd` pinned to the root. v0 **trusts the command
itself** (decision D2) — there is no sandbox; that is a later wheel. Tool output
fed back to the model is truncated at 20,000 chars so a huge file or command
can't blow the context window.

### Guaranteed termination

Every path out of the loop is one of: a model-signalled `finish`, an
empty-tool-call turn (the model answered in prose), or the `max_steps` budget
(default 25, see [config](#configuration)). Hooks add no new exit path and
cannot extend the budget.

## Usage

```bash
# Deterministic mock engine — no model, no network:
colleague drive "add a CONTRIBUTING.md stub" --repo . --engine mock --no-pr

# A real model over an OpenAI-compatible endpoint:
colleague drive "fix the typo in the README title" \
  --repo /path/to/repo --engine vllm-openai \
  --base-url http://localhost:8001/v1 --model Qwen/Qwen3-32B

# Machine-readable result:
colleague drive "..." --engine mock --no-pr --json
```

Key flags: `--repo PATH`, `--engine NAME`, `--no-pr`, `--base BRANCH`, and the
engine overrides `--base-url / --model / --api-key / --max-steps`. The live
cockpit flags `--tui` / `--no-tui` (default: auto — on an interactive TTY) and
`--tui-events PATH` (append a live `DriveStep` JSONL stream) are documented in
[tui.md](tui.md). A failed drive still writes a `status=error` artifact before
exiting non-zero.

## Configuration

Engine settings resolve in precedence order (`colleague/config.py`): explicit
flag → `COLLEAGUE_*` env → `OPENAI_*` env → built-in default. Defaults target
the vLLM reference rig (`http://localhost:8001/v1`, `Qwen/Qwen3-32B`,
`max_steps=25`, `temperature=0.0`). Because the driver only speaks the OpenAI
surface, pointing `base_url` elsewhere is always a config change, never a code
change.

## Key files

- `colleague/contract.py` — `Task`, `TaskResult`, `Step`, `Usage`, `HookFiring`.
- `colleague/loop.py` — the bounded loop, hook firing, telemetry.
- `colleague/tools.py` — the six tools (five base + `culture`) and the repo-confined `ToolExecutor`.
- `colleague/config.py` — `EngineConfig` resolution.

## See also

- [engines.md](engines.md) — the drivers that supply `complete`.
- [handoff.md](handoff.md) — what happens after the loop edits the tree.
- [artifact.md](artifact.md) — the JSON result + step trace the loop produces.
- [hooks.md](hooks.md) and [telemetry.md](telemetry.md) — chassis behavior the
  loop owns for every engine.

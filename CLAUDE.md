# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What convertible is

**Convertible CLI is a swappable coder-agent harness that turns different models
into repo workers behind one shared task contract.** One harness, many engines.

The car metaphor *is* the architecture:

- **Engine** — the model/coder backend.
- **Driver** — the adapter for one engine, in `convertible/engines/` (an
  `Engine` subclass implementing `drive(task, config) -> TaskResult`).
- **Chassis** — the shared task contract (`convertible/contract.py`: `Task`,
  `TaskResult`) and lifecycle.
- **Tool-loop** — the bounded agentic loop (`convertible/loop.py`) the engine
  drives the repo through (`read_file`/`write_file`/`list_dir`/`run_command`/
  `finish`, confined to the repo by `convertible/tools.py`). Hook firing lives
  here — every engine inherits lifecycle behavior automatically.
- **Wheels** — engines are plugins discovered via the `convertible.engines`
  Python entry-point group (`convertible/registry.py`).
- **Dashboard** — the JSON result artifact + step trace (`convertible/artifact.py`).
- **GPS** — opt-in OpenTelemetry traces + metrics (`convertible/telemetry/`).
  Instrumented in the loop + the shared drive path so every engine emits it
  (all-engines rule), exactly like hooks. Off by default; the OpenTelemetry SDK
  is an optional `[otel]` extra, imported lazily, so the base install stays
  dep-free. Surfaced via the `telemetry` introspection noun.
- **Handoff** — branch/commit/push + `gh pr create`, gated for offline/CI
  (`convertible/handoff.py`).
- **Command templates** — named, parameterized task recipes in
  `.convertible/commands/*.md` (`convertible/commands.py`); expanded into a
  `Task` via `drive --command <name> [args…]`.
- **Hooks** — operator-authored shell commands in `.convertible/hooks.json`
  (`convertible/hooks.py`) that fire at `task_start`/`pre_tool`/`post_tool`/
  `finish`; a `pre_tool` hook can allow, deny, or rewrite a tool call.
- **Interactive palette** — `convertible session` (`convertible/cli/_commands/
  session.py`): a foreground TTY loop over the same drive path; no parallel
  code path, no daemon.
- **Config resolution** — `convertible/configdir.py`: repo-level
  `.convertible/` overrides user-level `~/.convertible/`.
- **Layered per-model config** — `convertible/layers.py`: AGENTS instructions
  (`AGENTS.md` → `AGENTS.convertible.md` → `AGENTS.convertible.<model>.md`, at
  the repo root with a `~/.convertible/` fallback) and skills
  (`.convertible/skills/*.md` → `.convertible/<model>/skills/*.md`) compose into
  the engine system prompt. Resolution builds exact paths for the current model
  and never globs sibling models — per-model isolation is structural. Injected
  once on the `Engine` base class (`system_prompt()`), so every engine inherits
  it (all-engines rule). Surfaced via the `agents` / `skills` introspection
  nouns. **MCP layering is not built** — convertible reads no `mcp.json` and has
  no `mcp` verb; a live MCP client is a re-spec (see scope below).

The buildable spec and plan this implementation converged from live in
[`docs/specs/`](docs/specs/) and [`docs/plans/`](docs/plans/) (authored via the
`/think` → `/spec-to-plan` devague workflow).

## v0 scope (hold this line)

In scope: the chassis, the entry-point wheel contract, exactly two engines
(`mock`, `vllm-openai`), the git/PR handoff, command templates, lifecycle
hooks, the foreground interactive palette, layered per-model AGENTS/skills
config (`convertible/layers.py`), and GPS — opt-in OpenTelemetry traces +
metrics (`convertible/telemetry/`), with the SDK as an optional `[otel]` extra.

**Out of scope for v0** — do not add without re-speccing: a multi-engine
router/policy "gearbox", an execution sandbox, a daemon/server mode,
Codex/Claude/Gemini drivers, a per-repo hook trust gate / `--no-hooks`
escape hatch (planned follow-up hardening — not yet built; document this gap
honestly, never invent a `--no-hooks` flag), and an **MCP execution runtime**
(a live MCP client — stdio/socket transport, tool discovery, dynamic tool
registration). The layered config ships AGENTS + skills only; `mcp.json` is
**not** read and there is no `mcp` verb. A live MCP client would breach the
no-deps / no-socket / no-daemon conventions and needs its own spec — document
this gap honestly, never invent an `mcp` surface. Adding an excluded feature
means scope crept.

## The all-engines rule

Mirror of culture's all-backends rule: behavior that belongs to *the contract*
(task fields, result shape, the loop, the artifact) must hold for **every**
engine. The `mock` engine is the contract's reference — if a change makes
`mock` and `vllm-openai` diverge in result shape, that is a bug. The e2e shape
test (`tests/test_e2e_mock.py`) is the guard.

## Conventions

- **No runtime dependencies.** `pyproject.toml` keeps `dependencies = []`; the
  vLLM driver speaks the OpenAI wire format over stdlib `urllib`; commands and
  hooks use only stdlib (`json`, `subprocess`, `pathlib`). Don't add a runtime
  dep without a strong reason — dev-only deps go in the `dev` group. The one
  documented exception is **GPS**: the OpenTelemetry SDK ships as an optional
  `[project.optional-dependencies] otel` extra, never a base dependency. It is
  imported **lazily** inside `convertible/telemetry/_otel.py` (only when
  telemetry is enabled), so `dependencies = []` and the zero-deps guard
  (`tests/test_zero_deps.py`) still hold — the guard imports `convertible.loop`
  / `convertible.telemetry` / `convertible.cli` and asserts no third-party leak
  even with the extra installed. Keep the SDK confined to `_otel.py`; never
  import `opentelemetry` from any other convertible module.
- **Agent-first CLI.** New verbs are `convertible/cli/_commands/` modules with a
  `register(sub)`, wired in `convertible/cli/__init__.py`. Results to stdout,
  diagnostics/errors to stderr (never mixed); every command supports `--json`;
  failures raise `CliError` (no tracebacks leak). A noun with action-verbs must
  expose `overview`. Add an `explain` catalog entry for each new verb.
- **The vLLM driver only touches the OpenAI surface** — `base_url`/`api_key`/
  `model` config, `/v1/chat/completions` with tools. Retargeting any
  OpenAI-compatible server must stay a config change, never a code change.
- **Hook commands run as subprocesses, never imported.** `convertible/hooks.py`
  uses `subprocess.run` (shell=True) in the repo working directory. Command
  templates are Markdown text files, never executed as Python. No code path
  opens a socket or forks a daemon.
- **Hooks belong to the chassis, not to engines.** `convertible/loop.py` owns
  hook firing — new engine wheels inherit the full lifecycle layer automatically
  and must not duplicate it. The all-engines rule applies: a hook config that
  fires on `mock` must fire identically on `vllm-openai`.
- **Telemetry belongs to the chassis too.** `convertible/loop.py` (per tool
  call) and the shared `execute_drive` path (root + handoff spans) own all
  telemetry; no engine module touches the `telemetry` package. Off by default it
  is a strict no-op (no spans, no SDK import, `TaskResult` unchanged) — protect
  that so the e2e shape test and zero-deps guard keep passing.
- **Repo-shipped hooks run by default (trusted-operator-env model D2).** There
  is no `--no-hooks` flag today. A per-repo trust gate is a tracked follow-up.
  Document this gap clearly; never document a non-existent flag.
- **The `doctor` verb is convertible's oilcheck.** It emits a configuration-readiness
  health check across identity, provider, engines, otel-readiness, and environment
  check-groups, in a rubric shape with exit-1-on-unhealthy semantics. See
  `convertible explain doctor` for details.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run pytest -n auto                     # tests (parallel)
uv run convertible wheels list            # discovered engines
uv run convertible drive "<task>" --repo . --engine mock --no-pr

# Extensibility layer:
uv run convertible drive --command <name> [args…] --repo . --engine mock --no-pr
uv run convertible commands list --repo .          # list discovered templates
uv run convertible commands overview               # surface description
uv run convertible hooks list --repo .             # list configured hooks
uv run convertible hooks overview                  # surface description
uv run convertible session --repo . --engine mock  # interactive palette

# GPS / telemetry (opt-in; needs the [otel] extra):
uv run convertible telemetry status                # resolved telemetry config
uv run convertible telemetry overview              # surface description
uv sync --extra otel                               # install the OpenTelemetry SDK
CONVERTIBLE_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  uv run convertible drive "<task>" --repo . --engine mock --no-pr  # emits a trace

# Lint + gates CI enforces:
uv run black --check convertible tests
uv run isort --check-only convertible tests
uv run flake8 convertible tests
uv run bandit -c pyproject.toml -r convertible
uv run teken cli doctor . --strict        # agent-first rubric gate
```

The live vLLM proof is opt-in (the reference rig must expose tool calling:
`--enable-auto-tool-choice` plus a model-appropriate `--tool-call-parser`, e.g.
`hermes` or `qwen3_coder`):

```bash
CONVERTIBLE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

## Git workflow

Branch out, implement, **bump the version every PR** (the `version-check` CI job
blocks merge otherwise — use the `version-bump` skill), create the PR via the
`cicd` skill, address review, merge. Distribution is `convertible-cli`; the
command and import package are `convertible`. PyPI publish is via Trusted
Publishing on merge to `main`.

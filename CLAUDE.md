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
  `finish`, confined to the repo by `convertible/tools.py`).
- **Wheels** — engines are plugins discovered via the `convertible.engines`
  Python entry-point group (`convertible/registry.py`).
- **Dashboard** — the JSON result artifact + step trace (`convertible/artifact.py`).
- **Handoff** — branch/commit/push + `gh pr create`, gated for offline/CI
  (`convertible/handoff.py`).

The buildable spec and plan this implementation converged from live in
[`docs/specs/`](docs/specs/) and [`docs/plans/`](docs/plans/) (authored via the
`/think` → `/spec-to-plan` devague workflow).

## v0 scope (hold this line)

In scope: the chassis, the entry-point wheel contract, exactly two engines
(`mock`, `vllm-openai`), and the git/PR handoff.

**Out of scope for v0** — do not add without re-speccing: a multi-engine
router/policy "gearbox", an execution sandbox, a daemon/server mode, and
Codex/Claude/Gemini drivers. Adding an excluded feature means scope crept.

## The all-engines rule

Mirror of culture's all-backends rule: behavior that belongs to *the contract*
(task fields, result shape, the loop, the artifact) must hold for **every**
engine. The `mock` engine is the contract's reference — if a change makes
`mock` and `vllm-openai` diverge in result shape, that is a bug. The e2e shape
test (`tests/test_e2e_mock.py`) is the guard.

## Conventions

- **No runtime dependencies.** `pyproject.toml` keeps `dependencies = []`; the
  vLLM driver speaks the OpenAI wire format over stdlib `urllib`. Don't add a
  runtime dep without a strong reason — dev-only deps go in the `dev` group.
- **Agent-first CLI.** New verbs are `convertible/cli/_commands/` modules with a
  `register(sub)`, wired in `convertible/cli/__init__.py`. Results to stdout,
  diagnostics/errors to stderr (never mixed); every command supports `--json`;
  failures raise `CliError` (no tracebacks leak). A noun with action-verbs must
  expose `overview`. Add an `explain` catalog entry for each new verb.
- **The vLLM driver only touches the OpenAI surface** — `base_url`/`api_key`/
  `model` config, `/v1/chat/completions` with tools. Retargeting any
  OpenAI-compatible server must stay a config change, never a code change.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run pytest -n auto                     # tests (parallel)
uv run convertible wheels list            # discovered engines
uv run convertible drive "<task>" --repo . --engine mock --no-pr

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

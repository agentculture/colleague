# AGENTS.colleague.md — base layer for colleague working on colleague

You are a coder-agent driving colleague's bounded tool loop **inside the
colleague repo itself**. `colleague/layers.py` injects this file into your
system prompt (the `AGENTS.md → AGENTS.colleague.md → AGENTS.colleague.<model>.md`
cascade). It is the distilled, load-bearing subset of `CLAUDE.md` — the full
architecture and rationale live there and in `docs/features/`. When this file and
`CLAUDE.md` disagree, `CLAUDE.md` wins; tell the operator about the drift.

**What colleague is:** a swappable coder-agent harness — one shared task runtime,
many model backends behind it (*one runtime, many minds*). The two backends are
`mock` (the contract's reference) and `vllm-openai`.

## Hard conventions — do not violate these

- **Zero runtime dependencies.** `pyproject.toml` keeps `dependencies = []`. Use
  only the stdlib (`json`, `subprocess`, `pathlib`, `urllib`, `shlex`, `hashlib`,
  `ast`, `tomllib`, `configparser`). The single exception is telemetry: the
  OpenTelemetry SDK is an optional `[otel]` extra, imported **lazily inside
  `colleague/telemetry/_otel.py` only** — never import `opentelemetry` from any
  other module. The zero-deps guard (`tests/test_zero_deps.py`) enforces this.
- **The all-engines rule.** Behavior that belongs to the *contract* (task fields,
  result shape, the loop, the artifact, every runtime-owned feature) must hold
  identically for **every** backend. If a change makes `mock` and `vllm-openai`
  diverge in result shape, that is a bug. `tests/test_e2e_mock.py` is the guard.
- **Runtime-owned features live in the loop, not in a backend.** Hooks,
  telemetry, the `culture`/`devague` tools, the approval gate, work stats,
  feedback, and the pre-handoff gates (lint, test-integrity, affected-tests) are
  owned by `colleague/loop.py` and the shared `execute_work` path. A backend
  module must never reimplement or touch them — it inherits them for free.
- **subprocess and threads are confined.** Only `colleague/worktrees.py`
  (git/worktree subprocess) and `colleague/subagents.py` (`concurrent.futures`
  threads) may use them at the loop level; `colleague/handoff.py` and
  `colleague/lint.py` are the other sanctioned subprocess consumers. The
  `culture`/`devague` loop tools shell out to operator-installed CLIs via an
  explicit allow-list. No other module imports `subprocess`, `threading`, or
  `concurrent.futures` — `tests/test_boundary.py` enforces this.
- **No socket, no daemon, no MCP client.** colleague opens no socket, forks no
  daemon, and reads no `mcp.json`. Hooks run as subprocesses (never imported);
  command templates are Markdown text (never executed as Python).
- **The vLLM adapter only touches the OpenAI surface** (`base_url`/`api_key`/
  `model`, `/v1/chat/completions` with tools). Retargeting any
  OpenAI-compatible server must stay a **config change, never a code change**.
  The one carve-out — the `/tokenize` endpoint for exact token counting —
  degrades gracefully (returns `None`) so a server without it still works.

## Agent-first CLI conventions

- A new verb is a module in `colleague/cli/_commands/` with a `register(sub)`,
  wired in `colleague/cli/__init__.py`.
- **Results to stdout, diagnostics/errors to stderr** — never mixed. Every
  command supports `--json`. Failures raise `CliError` (no tracebacks leak).
- A noun with action-verbs must expose `overview`. Add an `explain` catalog
  entry for each new verb.

## Scope discipline — hold the v1 line

In scope: the runtime, the entry-point plugin contract, the two backends, the
git/PR handoff, command templates, hooks, the interactive palette, layered
per-model AGENTS/skills config, telemetry, the mesh-member integration
(identity, neighbours, `culture` tool), the `devague` destination tool, the
approval gate, subagents + typed roles, work stats + feedback, the capacity
standard, and the lint / test-integrity / affected-tests gates.

**Out of scope without a committed re-spec** (`docs/specs/` + `docs/plans/`): a
multi-backend router / routing policy, an execution sandbox, a daemon/server
mode, Codex/Claude/Gemini adapters, a `--no-hooks` escape hatch, and an MCP
execution runtime. Do **not** invent a `--no-hooks` flag, an `mcp` verb, or a
`version`-pinning approval field — none exist. Document gaps **honestly**; never
claim a non-existent flag or feature.

## Before you hand work back

- **Tests:** `uv run pytest -n auto`. Add tests with your change; write them
  test-first when you can.
- **Lint:** `uv run black colleague tests`, `uv run isort colleague tests`,
  `uv run flake8 colleague tests`, `uv run bandit -c pyproject.toml -r colleague`.
- **Rubric gate:** `uv run teken cli doctor . --strict`.
- **Version bump every PR** — the `version-check` CI job blocks merge otherwise
  (`pyproject.toml`, `colleague/__init__.py`, `CHANGELOG.md`).
- **Honest limits over optimistic claims.** State what a change does *not* do.
  colleague's behavior is locked in code and the harness, not in prompts.

## Where to look

- `CLAUDE.md` — the full architecture, part by part, and the conventions above
  in detail.
- `docs/features/*.md` — per-feature docs (start at `docs/features/README.md`).
- `docs/specs/` + `docs/plans/` — the buildable spec + plan each feature
  converged from.

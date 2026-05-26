# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`culture-agent-template` is a **clonable template for AgentCulture mesh agents**.
It is a working, minimal example of the sibling pattern every Culture agent
follows: an agent-first CLI, a mesh identity, the canonical skill kit, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent that `steward doctor` recognizes.

It is a sibling to [`guildmaster`](https://github.com/agentculture/guildmaster)
(the **skills supplier**), [`steward`](https://github.com/agentculture/steward)
(**alignment** — `steward doctor`, the sibling-pattern baseline), and
[`teken`](https://github.com/agentculture/teken) (the **afi-cli** "Agent First
Interface" scaffolder this CLI is cited from) within the Organic Development
framework.

## Identity

Declared in `culture.yaml`:

```yaml
agents:
- suffix: culture-agent-template
  backend: claude
```

`backend: claude` fixes the runtime prompt file to **`CLAUDE.md`** (this file).
Together they satisfy the two invariants `steward doctor` verifies:
**prompt-file-present** (an agent is declared and the matching prompt file is on
disk) and **backend-consistency** (`claude` ↔ `CLAUDE.md`). The CLI's own
`culture-agent-template doctor` checks the same invariants locally.

## Cloning this template (re-initialization)

When you start a new agent from this template:

1. Rename the package directory `culture_agent_template/` → `<your_module>/` and
   replace `culture_agent_template` (module) / `culture-agent-template` (CLI and
   dist name) throughout `pyproject.toml`, the package, `tests/`, and
   `sonar-project.properties`.
2. Set your `suffix` (and `backend`) in `culture.yaml`. `whoami` and `doctor`
   then reflect the new identity with no further code change.
3. Rewrite **this file** to describe your agent, and run `/init` to regenerate
   guidance grounded in your actual repo.
4. Re-vendor the skill kit you need from guildmaster (see
   `docs/skill-sources.md`) — keep only the skills your agent uses.

## The CLI

The CLI is cited (cite-don't-import) from teken's `python-cli` reference
(`teken cli cite`), so the runtime package has **no third-party dependencies**;
`teken` (a.k.a. `afi-cli`) is a dev dependency only. Agent-first verbs:

- `culture-agent-template whoami` — identity from `culture.yaml`.
- `culture-agent-template learn` — structured self-teaching prompt.
- `culture-agent-template explain <path>` — markdown docs for any noun/verb.
- `culture-agent-template overview` — descriptive snapshot of the agent.
- `culture-agent-template doctor` — check the agent-identity invariants.
- `culture-agent-template cli overview` — describe the CLI surface itself.

Conventions: every command supports `--json`; results go to stdout, errors and
diagnostics to stderr (never mixed); exit codes are `0` success, `1` user error,
`2` environment error, `3+` reserved. The agent-first rubric is enforced in CI by
`teken cli doctor . --strict`.

## Skills

`.claude/skills/` vendors the **canonical guildmaster skill kit** (cite-don't-import).
Provenance and the re-sync procedure live in `docs/skill-sources.md`. Three skills
(`think`, `spec-to-plan`, `assign-to-workforce`) originate in `devague` and are
re-broadcast via guildmaster. Tooling prerequisites: **`agex`** on PATH (the
`cicd` skill delegates the PR lifecycle to `agex pr`) and **`agtag`** on PATH (the
`communicate` skill wraps `agtag issue`).

## Conventions

- **Every PR bumps the version** — even docs/config/CI. Use the `version-bump`
  skill; the `version-check` CI job blocks merge otherwise.
- **PRs** go through the `cicd` skill (`agex pr` + SonarCloud gating). Sign
  online posts as `- culture-agent-template (Claude)` — the `cicd` / `communicate`
  scripts resolve the nick from `culture.yaml` automatically.
- **Tests**: `uv run pytest -n auto`. **Lint**: black, isort, flake8 (line length
  100), bandit, markdownlint.
- **Deploy**: pushing to `main` publishes to PyPI via Trusted Publishing
  (`.github/workflows/publish.yml`); PRs do a TestPyPI dry-run. Configure the
  `pypi` / `testpypi` GitHub environments and a PyPI Trusted Publisher before the
  publish job can succeed.
- The vendored `.claude/skills/` are cited verbatim — do not reformat or edit
  their scripts; re-sync from guildmaster instead (see `docs/skill-sources.md`).

## Layout

```text
culture_agent_template/   agent-first CLI (cited from teken's python-cli reference)
  cli/                    parser, error/output contract, _commands/ (verbs)
  explain/                markdown catalog for `explain`
tests/                    pytest smoke + introspection tests
.claude/skills/           vendored guildmaster skill kit (cite-don't-import)
docs/skill-sources.md     skill provenance ledger
culture.yaml              mesh identity (suffix + backend)
.github/workflows/        tests + deploy (PyPI Trusted Publishing)
```

This file describes the repository **as it exists on disk today**. When you edit,
keep claims grounded in checked-in reality; if a section drifts ahead of reality,
mark it `(planned)` or move it under a `## Roadmap` heading.

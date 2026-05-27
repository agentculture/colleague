"""Markdown catalog for ``convertible explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("convertible",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# convertible

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

Run `convertible` with no verb at a terminal to open the interactive harness (the
`session` palette); piped or non-interactive, it prints this usage instead.

## Verbs

- `convertible drive <goal>` — drive toward a goal/instruction; work autonomously
  through a coder engine and hand off the result.
- `convertible session` — foreground interactive palette over the drive path.
- `convertible wheels list` — list discovered engine wheels.
- `convertible whoami` — identity probe from `culture.yaml`.
- `convertible learn` — structured self-teaching prompt.
- `convertible explain <path>` — markdown docs for any noun/verb.
- `convertible overview` — descriptive snapshot of the agent.
- `convertible doctor` — check the agent-identity invariants.
- `convertible cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `convertible explain drive`
- `convertible explain wheels`
- `convertible explain whoami`
"""

_WHOAMI = """\
# convertible whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    convertible whoami
    convertible whoami --json
"""

_LEARN = """\
# convertible learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    convertible learn
    convertible learn --json
"""

_EXPLAIN = """\
# convertible explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    convertible explain convertible
    convertible explain whoami
    convertible explain --json <path>
"""

_OVERVIEW = """\
# convertible overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    convertible overview
    convertible overview --json
"""

_DOCTOR = """\
# convertible doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`claude` → `CLAUDE.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    convertible doctor
    convertible doctor --json
"""

_CLI = """\
# convertible cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    convertible cli overview
    convertible cli overview --json
"""

_DRIVE = """\
# convertible drive

Drive toward a goal: hand convertible a request or instruction and it works
autonomously — selecting an engine wheel, running the bounded agentic tool-loop,
writing a result artifact, and handing off the change as a branch + PR. The repo
is the target (`--repo`, default cwd); the same invocation works for every
engine — only `--engine` changes.

## Usage

    convertible drive "add a CONTRIBUTING.md" --repo . --engine mock
    convertible drive "fix the typo in README" --engine vllm-openai --no-pr
    convertible drive "..." --engine vllm-openai --base-url http://localhost:8001/v1 --json

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — engine wheel to drive (default: `mock`; see `wheels list`).
- `--no-pr` — commit locally; do not push or open a PR.
- `--base-url / --model / --api-key / --max-steps` — engine overrides.

A failed drive still writes a `status=error` artifact before exiting non-zero.
"""

_WHEELS = """\
# convertible wheels

Discover the engine plugins ("wheels") installed in this environment. Engines
register under the `convertible.engines` entry-point group; bundled and
out-of-tree wheels are discovered identically.

## Usage

    convertible wheels list
    convertible wheels list --json
    convertible wheels overview
"""

_COMMANDS = """\
# convertible commands

Discover and list named command templates stored under `.convertible/commands/`
in the target repository (or user home).  Templates are Markdown files with an
optional YAML-like metadata block and a body using `$1`/`$2`/`$ARGUMENTS`
substitution.

## Usage

    convertible commands list
    convertible commands list --repo PATH
    convertible commands list --repo PATH --json
    convertible commands overview

## Template format

    ---
    description: Fix lint errors in a path
    engine: mock
    constraints: keep diffs minimal, run the formatter
    arg-hint: <path>
    ---
    Fix all lint errors under $1. Then run the formatter. $ARGUMENTS

## Running a template

    convertible drive --command <name> [args...]

## See also

- `convertible explain drive`
- `convertible explain hooks`
"""

_SESSION = """\
# convertible session

Open a foreground interactive palette that lists discovered command templates,
accepts free-text ad-hoc instructions, and runs every selection through the
**same drive path** as `convertible drive` (identical Task/loop/hooks/artifact).
The loop continues until you enter `q`, an empty line, or EOF.

## Usage

    convertible session
    convertible session --repo PATH --engine mock --no-pr

## Interaction

At the `>>>` prompt you can enter:

- A **number** (e.g. `1`) — selects that template from the numbered palette.
- A **template name** (e.g. `lint`) — runs that template directly.
- A **free-text instruction** — treated as an ad-hoc task (like `drive "<text>"`).
- `q`, `quit`, `exit`, or an **empty line** — ends the session.

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — engine wheel to drive (default: `mock`; see `wheels list`).
- `--no-pr` — commit locally; do not push or open a PR.
- `--base BRANCH` — base branch for the PR (default: `main`).
- `--base-url / --model / --api-key / --max-steps` — engine overrides.

## See also

- `convertible explain drive`
- `convertible explain commands`
"""

_HOOKS = """\
# convertible hooks

Inspect the lifecycle hook configuration loaded from `.convertible/hooks.json`
(repo-level, falling back to user-level at `~/.convertible/hooks.json`).

Hooks fire at four lifecycle events:
- `task_start` — before the agentic loop starts.
- `pre_tool` — before each tool call; can allow, deny, or rewrite arguments.
- `post_tool` — after each tool call.
- `finish` — after the loop ends.

## Usage

    convertible hooks list
    convertible hooks list --repo PATH
    convertible hooks list --repo PATH --json
    convertible hooks overview

## Hook decisions

- **allow** — permit the tool call (default on exit 0 / empty stdout).
- **deny** — block the tool call (non-zero exit or `{"decision":"deny"}`).
- **rewrite** — replace tool arguments (`{"decision":"rewrite","arguments":{}}`).
- Responses may include `"additionalContext"` for the model.

## See also

- `convertible explain commands`
- `convertible explain drive`
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("convertible",): _ROOT,
    ("drive",): _DRIVE,
    ("session",): _SESSION,
    ("wheels",): _WHEELS,
    ("wheels", "list"): _WHEELS,
    ("wheels", "overview"): _WHEELS,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
    ("commands",): _COMMANDS,
    ("commands", "list"): _COMMANDS,
    ("commands", "overview"): _COMMANDS,
    ("hooks",): _HOOKS,
    ("hooks", "list"): _HOOKS,
    ("hooks", "overview"): _HOOKS,
}

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

## Verbs

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

- `convertible explain whoami`
- `convertible explain doctor`
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


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("convertible",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
}

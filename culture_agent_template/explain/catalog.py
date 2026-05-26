"""Markdown catalog for ``culture-agent-template explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("culture-agent-template",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# culture-agent-template

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

## Verbs

- `culture-agent-template whoami` — identity probe from `culture.yaml`.
- `culture-agent-template learn` — structured self-teaching prompt.
- `culture-agent-template explain <path>` — markdown docs for any noun/verb.
- `culture-agent-template overview` — descriptive snapshot of the agent.
- `culture-agent-template doctor` — check the agent-identity invariants.
- `culture-agent-template cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `culture-agent-template explain whoami`
- `culture-agent-template explain doctor`
"""

_WHOAMI = """\
# culture-agent-template whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    culture-agent-template whoami
    culture-agent-template whoami --json
"""

_LEARN = """\
# culture-agent-template learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    culture-agent-template learn
    culture-agent-template learn --json
"""

_EXPLAIN = """\
# culture-agent-template explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    culture-agent-template explain culture-agent-template
    culture-agent-template explain whoami
    culture-agent-template explain --json <path>
"""

_OVERVIEW = """\
# culture-agent-template overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    culture-agent-template overview
    culture-agent-template overview --json
"""

_DOCTOR = """\
# culture-agent-template doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`claude` → `CLAUDE.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    culture-agent-template doctor
    culture-agent-template doctor --json
"""

_CLI = """\
# culture-agent-template cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    culture-agent-template cli overview
    culture-agent-template cli overview --json
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("culture-agent-template",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
}

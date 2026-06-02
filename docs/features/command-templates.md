# Command templates

> Named, parameterized task recipes — author a recipe once, invoke it by name
> with positional arguments.

Command templates let operators save reusable task recipes as Markdown files
under `.colleague/commands/<name>.md` and invoke them by name. A template
expands into the *same* `Task` shape a raw `drive "<text>"` produces — it is a
front-end over the drive path, not a parallel one (`colleague/commands.py`).

Templates resolve repo-level first, then user-level: `.colleague/commands/`
in the repo shadows `~/.colleague/commands/` by file stem
([config resolution](layered-config.md#config-resolution)).

`.colleague/commands/` is the one part of the otherwise-gitignored
`.colleague/` dir that git tracks, so recipes can be **committed and shared
in-repo** (run artifacts, `hooks.json`, and `approvals.json` stay local). For
cross-repo sharing, put recipes under `~/.colleague/commands/` instead. The
committed `doc-review` recipe is a worked example.

## Template file format

A template may open with an optional `---` metadata block; if absent, the entire
file is the body.

```markdown
---
description: Fix lint errors under a path
engine: mock
constraints: keep diffs minimal, run the formatter
arg-hint: <path>
---
Fix all lint errors under $1. Then run the formatter. $ARGUMENTS
```

| Metadata key | Meaning |
|--------------|---------|
| `description` | One-line description shown in listings. |
| `engine` | Engine to use when running this command (overridden by `--engine`). |
| `constraints` | Comma-separated constraints added to the `Task`. |
| `arg-hint` | Short argument hint shown in `commands list`. |

## Argument substitution

| Placeholder | Expands to |
|-------------|------------|
| `$ARGUMENTS` | All arguments joined by a space. |
| `$1`, `$2`, … | The N-th positional argument (empty string if not supplied). |

## Usage

```bash
# One-shot via drive — tokens after the name are template arguments:
colleague drive --command fix-lint src/ --repo /path/to/repo --engine mock --no-pr

# List discovered templates / describe the surface:
colleague commands list --repo .
colleague commands list --repo . --json
colleague commands overview
```

`--command <name>` and a positional instruction are **mutually exclusive**. The
originating command name is recorded as `TaskResult.command` in the
[artifact](artifact.md).

## Key files

- `colleague/commands.py` — discovery, parsing, `$ARGUMENTS`/`$N` expansion.
- `colleague/configdir.py` — repo-over-user `.colleague/` resolution.
- `colleague/cli/_commands/commands.py` — the `commands list`/`overview` verb.

## See also

- [hooks.md](hooks.md) — the other half of the extensibility layer.
- [session.md](session.md) — the interactive palette lists and runs templates.
- [drive-and-loop.md](drive-and-loop.md) — the `Task` a template expands into.

# Agent-first CLI

> A self-describing command surface: structured output, clean stream
> separation, and read-only introspection verbs an agent can consume.

Convertible is built as an **agent-first CLI** (cited from the teken `python-cli`
reference). Beyond the working verbs ([`drive`](drive-and-loop.md),
[`session`](session.md), [`wheels`](engines.md), [`commands`](command-templates.md),
[`hooks`](hooks.md), [`agents`/`skills`](layered-config.md),
[`telemetry`](telemetry.md), [`doctor`](doctor.md)), it carries a set of
**read-only introspection verbs** so an agent — or a person — can discover what
the tool is and how to use it without guessing.

## Conventions every verb follows

- **Structured output everywhere.** Every command supports `--json`.
- **Streams never mix.** Results go to **stdout**; diagnostics and errors go to
  **stderr**.
- **No tracebacks leak.** Failures raise `CliError`, routed to a structured
  `{code, message, remediation}` on stderr. Even argparse errors (unknown verb,
  missing arg) route through the same format and honor `--json`.
- **Exit-code policy:** `0` success, `1` user-input error, `2` environment/setup
  error, `3+` reserved.
- **Nouns expose `overview`.** A noun group with action-verbs (e.g. `wheels`,
  `commands`, `hooks`, `telemetry`) exposes an `overview`; the global `cli
  overview` describes the CLI surface itself.

New verbs are `convertible/cli/_commands/` modules with a `register(sub)`, wired
in `convertible/cli/__init__.py`, and each gets an `explain` catalog entry.

## The introspection verbs

| Verb | What it reports |
|------|-----------------|
| `whoami` | The agent's nick, version, backend, and served model — read from `culture.yaml`. |
| `learn` | A structured self-teaching prompt: purpose, command map, exit codes, `--json`, and the `explain` pointer. |
| `explain <path>` | Markdown docs for any noun/verb path — global and addressable, unlike terse `--help`. |
| `overview` | A read-only descriptive snapshot of the agent (identity + verb surface). |
| `cli overview` | Describes the CLI surface itself (distinct from the agent `overview`). |

```bash
convertible whoami
convertible whoami --json
convertible learn
convertible explain convertible        # the root entry
convertible explain doctor             # any verb
convertible overview
convertible cli overview
```

## Identity from `culture.yaml`

`whoami` (and the identity check in [`doctor`](doctor.md)) read this agent's own
`culture.yaml`, located by walking up from the package — not whatever
`culture.yaml` happens to sit in the caller's cwd. It is parsed without a YAML
dependency (runtime deps stay empty). When you clone this template, rename the
package and edit `culture.yaml`, and `whoami` reflects the new identity with no
code change. From a wheel install with no `culture.yaml`, it falls back to
literal defaults.

## Key files

- `convertible/cli/__init__.py` — parser build, dispatch, error routing.
- `convertible/cli/_commands/{whoami,learn,explain,overview,cli}.py` — the verbs.
- `convertible/explain/catalog.py` — the markdown `explain` entries.

## See also

- [doctor.md](doctor.md) — the read-only health check.
- The top-level [`CLAUDE.md`](../../CLAUDE.md) — the agent-first CLI conventions
  in full.

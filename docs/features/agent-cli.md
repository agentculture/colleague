# Agent-first CLI

> A self-describing command surface: structured output, clean stream
> separation, and read-only introspection verbs an agent can consume.

Colleague is built as an **agent-first CLI** (cited from the teken `python-cli`
reference). Beyond the working verbs ([`work`](work-and-loop.md),
[`session`](session.md), [`backends`](engines.md), [`commands`](command-templates.md),
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
- **Nouns expose `overview`.** A noun group with action-verbs (e.g. `backends`,
  `commands`, `hooks`, `telemetry`) exposes an `overview`; the global `cli
  overview` describes the CLI surface itself.

New verbs are `colleague/cli/_commands/` modules with a `register(sub)`, wired
in `colleague/cli/__init__.py`, and each gets an `explain` catalog entry.

## The introspection verbs

| Verb | What it reports |
|------|-----------------|
| `whoami` | The agent's nick + version + mesh backend (read from `culture.yaml`), plus the live `work_engine`/`work_model` a bare work item would actually run (resolved like a real work item; `work_model` is `null` for the `mock` engine). |
| `learn` | A structured self-teaching prompt that teaches an **AI agent** how to operate colleague (purpose, command map, exit codes, `--json`, the `explain` pointer). Read-only — nothing is written. Humans usually prefer `explain` / `overview`. Not to be confused with `learn-from` (see note below). |
| `explain <path>` | Markdown docs for any noun/verb path — global and addressable, unlike terse `--help`. |
| `overview` | A read-only descriptive snapshot of the agent (identity + verb surface). |
| `cli overview` | Describes the CLI surface itself (distinct from the agent `overview`). |

```bash
colleague whoami
colleague whoami --json
colleague learn
colleague explain colleague        # the root entry
colleague explain doctor             # any verb
colleague overview
colleague cli overview
```

> **`learn` vs `learn-from` — different commands.** `learn` (above) *teaches a
> reader* how to drive colleague and writes nothing. `colleague learn-from
> <source>` does the opposite: it *teaches colleague* by absorbing a peer agent's
> skills into `.colleague/skills/` (it **writes files**). See
> [`learn-from.md`](learn-from.md).

## Identity from `culture.yaml`

`whoami` (and the identity check in [`doctor`](doctor.md)) read this agent's own
`culture.yaml`, located by walking up from the package — not whatever
`culture.yaml` happens to sit in the caller's cwd. It is parsed without a YAML
dependency (runtime deps stay empty). When you clone this template, rename the
package and edit `culture.yaml`, and `whoami` reflects the new identity with no
code change. From a wheel install with no `culture.yaml`, it falls back to
literal defaults.

## Key files

- `colleague/cli/__init__.py` — parser build, dispatch, error routing.
- `colleague/cli/_commands/{whoami,learn,explain,overview,cli}.py` — the verbs.
- `colleague/explain/catalog.py` — the markdown `explain` entries.

## See also

- [doctor.md](doctor.md) — the read-only health check.
- The top-level [`CLAUDE.md`](../../CLAUDE.md) — the agent-first CLI conventions
  in full.

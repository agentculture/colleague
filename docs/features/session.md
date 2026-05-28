# Interactive palette

> A foreground TTY loop that runs every selection through the same drive path —
> no parallel code path, no daemon.

`convertible session` opens a foreground interactive palette
(`convertible/cli/_commands/session.py`). It lists discovered
[command templates](command-templates.md), accepts a selection or a free-text
instruction, and runs each through the **same `drive` path** as `convertible
drive` — identical `Task`, loop, hooks, telemetry, and artifact. It is a thin
front-end, not a second engine path, and it is **not** a daemon: it is a plain
foreground loop over the shared drive code.

## Interaction

At the `>>>` prompt you can enter:

- A **number** (e.g. `1`) — selects that template from the numbered palette.
- A **template name** (e.g. `lint`) — runs that template directly.
- A **free-text instruction** — treated as an ad-hoc task (like `drive "<text>"`).
- `q`, `quit`, `exit`, or an **empty line** — ends the session.

The loop continues until you quit or hit EOF.

## Bare `convertible` opens it

Running `convertible` with no arguments **at a terminal** opens this same palette
(with the default engine and repo) — the natural "get in and drive" gesture.
Piped, redirected, or otherwise non-interactive, bare `convertible` prints usage
instead, so scripts and agents keep a discoverable surface. Both stdin and
stdout must be a TTY for the palette to open (`-h/--help` is unaffected either
way).

## Usage

```bash
convertible session --repo /path/to/repo --engine vllm-openai
convertible                       # at a terminal: opens the palette
convertible | cat                 # piped: prints usage instead
```

Any driver flag accepted by `drive` (`--engine`, `--no-pr`, `--base`,
`--base-url`, `--model`, `--api-key`, `--max-steps`) is also accepted by
`session`. Errors/diagnostics route to stderr and `--json` is honored (one JSON
result per drive on stdout, palette chrome to stderr).

## Key files

- `convertible/cli/_commands/session.py` — the palette loop.
- `convertible/cli/__init__.py` — bare-`convertible` → palette routing.

## See also

- [command-templates.md](command-templates.md) — what the palette lists.
- [drive-and-loop.md](drive-and-loop.md) — the shared path the palette runs.

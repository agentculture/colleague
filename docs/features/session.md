# Interactive palette

> A foreground TTY loop that runs every selection through the same drive path —
> no parallel code path, no daemon.

`colleague session` opens a foreground interactive palette
(`colleague/cli/_commands/session.py`). It lists discovered
[command templates](command-templates.md), accepts a selection or a free-text
instruction, and runs each through the **same `drive` path** as `colleague
drive` — identical `Task`, loop, hooks, telemetry, and artifact. It is a thin
front-end, not a second code path, and it is **not** a daemon: it is a plain
foreground loop over the shared drive code.

## Interaction

Input is **line-based**. Plain text runs a drive:

- A **number** (e.g. `1`) — selects that template from the palette.
- A **template name** (e.g. `lint`) — runs that template directly.
- A **free-text instruction** — treated as an ad-hoc task (like `drive "<text>"`).
- `q`, `quit`, `exit`, or an **empty line** — ends the session.

A line starting with `/` is a **slash command** — the meta/system namespace (akin
to Claude Code / Codex), independent of the render tier:

| Slash | Effect |
|-------|--------|
| `/help` | List the slash commands. |
| `/commands` | List discovered [command templates](command-templates.md). |
| `/skills` | Resolved skill docs (`skills list`). |
| `/agents` | Resolved AGENTS instruction layers (`agents list`). |
| `/config` | Configuration readiness (the `doctor` rubric). |
| `/engines` | Discovered backend plugins (`backends list`). |
| `/telemetry` | Telemetry configuration (`telemetry status`). |
| `/feedback` | Feedback record for the last drive (`feedback show last`). |
| `/engine <name>` | Switch the engine used by the next drive (validated). |
| `/model <name>` | Switch the model. |
| `/base <branch>` | Set the PR base branch. |
| `/pr` | Toggle push + open PR on each drive. |
| `/quit` | End the session. |

Introspection commands run the real noun **in-process** (no subprocess) and fold
its output into the cockpit conversation. Config commands mutate the session live —
no restart. The loop continues until you quit or hit EOF.

## Three render tiers

The session renders the one `CockpitState` through whichever view fits the
context — the same three views the [`tui`](tui.md) verb exposes:

- **Interactive (a colour TTY)** — the dynamic ANSI cockpit: redraw-in-place, with
  popups on real events (an `error` popup when a drive step fails).
- **Non-interactive (piped / captured)** — **Markdown** menus: the static but
  *full* agent-readable view, the default off a TTY. `--no-tui` forces it on a TTY.
- **`--json`** — stdout carries only the drive `TaskResult` (one JSON object each,
  preserving the machine contract); the Markdown cockpit renders to stderr as
  chrome. The TAUI JSON mirror itself is `colleague tui state`.

Errors (a bad selection, an unknown engine, a drive failure) go to **stderr**
(agent-first); in the dynamic ANSI tier they are also folded into the conversation
so a redraw never hides them.

## Bare `colleague` opens it

Running `colleague` with no arguments **at a terminal** opens this same palette
— the natural "get in and drive" gesture. The engine is resolved like `drive`
(`--engine` > `COLLEAGUE_ENGINE` > `vllm-openai`); it never silently falls back
to the no-op `mock`. Piped, redirected, or otherwise non-interactive, bare
`colleague` prints usage instead, so scripts and agents keep a discoverable
surface. Both stdin and stdout must be a TTY for the palette to open (`-h/--help`
is unaffected either way).

## Handoff: commit-local by default

A session is a "talk + iterate" loop: by default each drive commits locally on a
`colleague/<task_id>` branch but does **not** push or open a PR (so chatting
with the palette never opens surprise PRs). Pass `--pr` to push and open a PR
after every drive. This differs from `drive`, which opens a PR by default.

## Usage

```bash
colleague session --repo /path/to/repo --engine vllm-openai
colleague                       # at a terminal: opens the palette
colleague | cat                 # piped: prints usage instead
```

Backend flags accepted by `drive` (`--engine`, `--base`, `--base-url`, `--model`,
`--api-key`, `--max-steps`) are also accepted by `session`; in place of `drive`'s
`--no-pr`, session takes `--pr` (handoff is opt-in here — commit-local is the
default). Errors/diagnostics route to stderr and `--json` is honored (one JSON
result per drive on stdout, palette chrome to stderr).

## Key files

- `colleague/cli/_commands/session.py` — the palette loop.
- `colleague/cli/__init__.py` — bare-`colleague` → palette routing.

## See also

- [command-templates.md](command-templates.md) — what the palette lists.
- [drive-and-loop.md](drive-and-loop.md) — the shared path the palette runs.

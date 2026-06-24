# Interactive palette

> A foreground TTY loop that runs every selection through the same work path —
> no parallel code path, no daemon.

`colleague session` opens a foreground interactive palette
(`colleague/cli/_commands/session.py`). It lists discovered
[command templates](command-templates.md), accepts a selection or a free-text
instruction, and runs each through the **same `work` path** as `colleague
work` — identical `Task`, loop, hooks, telemetry, and artifact. It is a thin
front-end, not a second code path, and it is **not** a daemon: it is a plain
foreground loop over the shared work code.

## Interaction

Input is **line-based**. Plain text runs a work item:

- A **number** (e.g. `1`) — selects that template from the palette.
- A **template name** (e.g. `lint`) — runs that template directly.
- A **free-text instruction** — intent-routed by `classify_intent` to `work`
  (the default) or `plan`; a `→ work:` / `→ plan:` line confirms the dispatch.
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
| `/feedback` | Feedback record for the last work item (`feedback show last`). |
| `/engine <name>` | Switch the engine used by the next work item (validated). |
| `/model <name>` | Switch the model. |
| `/base <branch>` | Set the PR base branch. |
| `/pr` | Toggle push + open PR on each work item. |
| `/quit` | End the session. |

Introspection commands run the real noun **in-process** (no subprocess) and fold
its output into the cockpit conversation. Config commands mutate the session live —
no restart. The loop continues until you quit or hit EOF.

## Three render tiers

The session renders the one `CockpitState` through whichever view fits the
context — the same three views the [`tui`](tui.md) verb exposes:

- **Interactive (a colour TTY)** — the dynamic ANSI cockpit: redraw-in-place, with
  popups on real events (an `error` popup when a work item step fails).
- **Non-interactive (piped / captured)** — **Markdown** menus: the static but
  *full* agent-readable view, the default off a TTY. `--no-tui` forces it on a TTY.
- **`--json`** — stdout carries only the work item `TaskResult` (one JSON object each,
  preserving the machine contract); the Markdown cockpit renders to stderr as
  chrome. The TAUI JSON mirror itself is `colleague tui state`.

Errors (a bad selection, an unknown engine, a work item failure) go to **stderr**
(agent-first); in the dynamic ANSI tier they are also folded into the conversation
so a redraw never hides them.

## Agent-native default (#233/#234/#235)

Three co-shipped improvements make `colleague session` the natural agent-native
entry point:

### Intent routing (#234)

Free-text input is classified by `colleague/session_intent.py`
`classify_intent(text) -> "work"|"plan"` (stdlib `re` only, zero deps) and
routed to the right verb without the operator typing a subcommand.

- A **`→ work:`** / **`→ plan:`** line is logged so the dispatch is always
  visible.
- Numbers and known template names are always work-template selections, never
  reclassified.
- The default is `work`, so a misclassification can only ever down-route to
  the safe default, never silently invoke plan.
- The plan branch runs a quick, non-interactive spec→plan (`quick=True,
  workforce=False`). On a non-live backend (e.g. `mock`) a `CliError` is
  surfaced cleanly — never a crash.

**Non-goals:** `colleague work` / `colleague plan` still work for scripting
and agents that name a subcommand explicitly. Intent routing fires ONLY on
genuine free text inside `colleague session`. No new GUI.

### Session backend override (#234)

The session resolves its backend via `colleague/config.py`
`resolve_session_engine()`:

```text
explicit --engine flag
  > COLLEAGUE_SESSION_ENGINE  (session-only env-var override, new)
  > COLLEAGUE_ENGINE          (global default)
  > vllm-openai               (built-in default)
```

There is **no `--session-engine` flag** — only the `COLLEAGUE_SESSION_ENGINE`
env var. This lets an operator point the conversational session at a different
backend than a bare `colleague work` without touching `COLLEAGUE_ENGINE`. The
existing `--engine` flag still overrides everything.

### Legible action feed (#233)

The live cockpit feed is now legible at a glance:

- **Grouping** — consecutive identical feed lines collapse into a single
  `<line> ×N` entry (e.g. four back-to-back `[culture]` calls become
  `[culture] agtag issues ×4`). Logic lives in
  `colleague/tui/reducer.py` `_collapse_repeat`.
- **Tool targets** — the `culture` and `devague` loop tools now surface as
  `<cli> <args>` / `<move> <args>` in the feed hint (e.g.
  `[culture] agtag issues fetch`) instead of a bare `[culture]` sentinel.
  Logic lives in `colleague/tui/from_work.py` `progress_target`.
- **Longer hints** — the per-step hint cap is raised from 48 to 120 characters
  (`_MAX_TARGET = 120` in `colleague/tui/from_work.py`) so long commands are
  no longer truncated mid-word.

This is a pure display change — the underlying `TaskResult` and step trace are
unchanged.

### AgentFront probe reflex (#235)

`_DEFAULT_SYSTEM` in `colleague/loop.py` now instructs the backend: before the
**first** real use of a CLI or tool it has not used in this run, read its
`learn` / `explain` / `--help` / `--json` affordance first, then act on what
you found instead of guessing flags or output shape. A tool already used in the
run needs no re-probe.

**Non-goals:** this is advisory and **read-only** — the reflex instructs the
model to read a surface, never to install, approve, or trust the tool. An
enforced harness-level probe is a named follow-up, **not shipped**.

## Bare `colleague` opens it

Running `colleague` with no arguments **at a terminal** opens this same palette
— the natural "get in and work" gesture. The engine is resolved via
`resolve_session_engine` (`--engine` > `COLLEAGUE_SESSION_ENGINE` >
`COLLEAGUE_ENGINE` > `vllm-openai`); it never silently falls back to the no-op
`mock`. Piped, redirected, or otherwise non-interactive, bare `colleague` prints
usage instead, so scripts and agents keep a discoverable surface. Both stdin and
stdout must be a TTY for the palette to open (`-h/--help` is unaffected either way).

## Handoff: commit-local by default

A session is a "talk + iterate" loop: by default each work item commits locally on a
`colleague/<task_id>` branch but does **not** push or open a PR (so chatting
with the palette never opens surprise PRs). Pass `--pr` to push and open a PR
after every work item. This differs from `work`, which opens a PR by default.

## Usage

```bash
colleague session --repo /path/to/repo --engine vllm-openai
colleague                       # at a terminal: opens the palette
colleague | cat                 # piped: prints usage instead
```

Backend flags accepted by `work` (`--engine`, `--base`, `--base-url`, `--model`,
`--api-key`, `--max-steps`) are also accepted by `session`; in place of `work`'s
`--no-pr`, session takes `--pr` (handoff is opt-in here — commit-local is the
default). Errors/diagnostics route to stderr and `--json` is honored (one JSON
result per work item on stdout, palette chrome to stderr).

## Key files

- `colleague/cli/_commands/session.py` — the palette loop.
- `colleague/cli/__init__.py` — bare-`colleague` → palette routing.

## See also

- [command-templates.md](command-templates.md) — what the palette lists.
- [work-and-loop.md](work-and-loop.md) — the shared path the palette runs.

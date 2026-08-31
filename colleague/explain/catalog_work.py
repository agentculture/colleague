"""Work-item and session-surface catalog entries (work, backends, session, hooks, ...).

Split out of ``colleague/explain/catalog.py`` (docstring constants only, one
per ``colleague explain <path>`` topic group); see that module for ``ENTRIES``.
"""

from __future__ import annotations

_WORK = """\
# colleague work

Work toward a goal: hand colleague a request or instruction and it works
autonomously — selecting a backend plugin, running the bounded agentic tool-loop,
writing a result artifact, and handing off the change as a branch + PR. The repo
is the target (`--repo`, default cwd); the same invocation works for every
engine — only `--engine` changes.

`drive` is a **deprecated alias** of `work` (the old car-themed verb) — it still
resolves and its `--help` row is labelled deprecated, but prefer `work`.

## Usage

    colleague work "add a CONTRIBUTING.md" --repo . --engine mock --no-pr
    colleague work "fix the typo in README" --engine vllm-openai --no-pr
    colleague work "..." --engine vllm-openai --base-url http://localhost:8001/v1 --json

## Backend selection

Resolved highest-first: the `--engine` flag, then the `COLLEAGUE_ENGINE` env
var, then the built-in default `vllm-openai` (the real bundled backend). A bare
`work` never silently falls back to the no-op `mock` reference — use
`--engine mock` (or `COLLEAGUE_ENGINE=mock`) when you explicitly want it.

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — backend plugin (default: `COLLEAGUE_ENGINE` env, else `vllm-openai`).
- `--no-pr` — commit locally; do not push or open a PR.
- `--allow-dirty` — run even when the working tree has uncommitted tracked
  changes (they get committed onto the work branch). Default: refuse, so a work
  item never silently sweeps your in-progress edits onto a branch (#149).
- `--base-url / --model / --api-key / --max-steps` — backend overrides.

A failed work item still writes a `status=error` artifact before exiting non-zero.
"""

_BACKENDS = """\
# colleague backends

Discover the backend plugins (the "minds") installed in this environment.
Backends register under the `colleague.engines` entry-point group; bundled and
out-of-tree plugins are discovered identically.

`wheels` is a **deprecated alias** of `backends` (the old car-themed name) — it
still resolves and its `--help` row is labelled deprecated, but prefer `backends`.

## Usage

    colleague backends list
    colleague backends list --json
    colleague backends overview
"""

_COMMANDS = """\
# colleague commands

Discover and list named command templates stored under `.colleague/commands/`
in the target repository (or user home).  Templates are Markdown files with an
optional YAML-like metadata block and a body using `$1`/`$2`/`$ARGUMENTS`
substitution.

## Usage

    colleague commands list
    colleague commands list --repo PATH
    colleague commands list --repo PATH --json
    colleague commands overview

## Template format

    ---
    description: Fix lint errors in a path
    engine: mock
    constraints: keep diffs minimal, run the formatter
    arg-hint: <path>
    ---
    Fix all lint errors under $1. Then run the formatter. $ARGUMENTS

## Running a template

    colleague work --command <name> [args...]

## See also

- `colleague explain work`
- `colleague explain hooks`
"""

_SESSION = """\
# colleague session

Open a foreground interactive palette that lists discovered command templates,
accepts free-text ad-hoc instructions, and runs every selection through the
**same work path** as `colleague work` (identical Task/loop/hooks/artifact).
The loop continues until you enter `q`, an empty line, or EOF.

## Usage

    colleague session
    colleague session --repo PATH --engine mock
    colleague session --pr            # opt back into push + PR per work item

## Interaction

At the `colleague ❯` prompt you can enter:

- A **number** (e.g. `1`) — selects that template from the numbered palette.
- A **template name** (e.g. `lint`) — runs that template directly.
- A **free-text instruction** — treated as an ad-hoc task (like `work "<text>"`).
- A **slash command** (e.g. `/help`, `/engine mock`) — the meta namespace:
  introspection of existing nouns plus live config actions. `/help` lists them all.
- `q`, `quit`, `exit`, or an **empty line** — ends the session.

## Slash autocomplete (colour TTY)

On an interactive colour TTY, typing `/` opens a **live popup** of slash
commands that **autofilters** as you type (`/co` → `commands`, `config`),
restores as you delete, and disappears when nothing matches. **Tab**/**Enter**
completes the selection, **arrows** move it, **Esc** dismisses. This is a
TTY-only nicety built on a stdlib raw-mode reader (no new dependency); off a
colour TTY — piped input, `--json`, `--no-tui`, or Windows — the prompt falls
back to plain line input, byte-identical to before, so agents and pipelines are
unaffected.

## Handoff

By default a session is a "talk + iterate" loop: each work item commits locally on a
`colleague/<task_id>` branch but does **not** push or open a PR. Pass `--pr` to
push and open a PR after every work item. (This differs from `work`, which opens a
PR by default.) Engine selection matches `work`: `--engine` > `COLLEAGUE_ENGINE`
> `vllm-openai`.

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — backend plugin (default: `COLLEAGUE_ENGINE` env, else `vllm-openai`).
- `--pr` — push and open a PR after each work item (default: commit locally only, no PR).
- `--allow-dirty` — run work items even when the working tree has uncommitted
  tracked changes (they get committed onto the work branch). Default: refuse (#149).
- `--base BRANCH` — base branch for the PR (default: `main`).
- `--base-url / --model / --api-key / --max-steps` — backend overrides.

## See also

- `colleague explain work`
- `colleague explain commands`
"""

_HOOKS = """\
# colleague hooks

Inspect the lifecycle hook configuration loaded from `.colleague/hooks.json`
(repo-level, falling back to user-level at `~/.colleague/hooks.json`).

Hooks fire at four lifecycle events:
- `task_start` — before the agentic loop starts.
- `pre_tool` — before each tool call; can allow, deny, or rewrite arguments.
- `post_tool` — after each tool call.
- `finish` — after the loop ends.

## Usage

    colleague hooks list
    colleague hooks list --repo PATH
    colleague hooks list --repo PATH --json
    colleague hooks list --repo PATH --model <model> --json
    colleague hooks overview

## Per-model overlay (--model)

Pass `--model <name>` to `hooks list` to include per-model hook entries loaded
from `.colleague/<model>/hooks.json` (repo-level, falling back to
`~/.colleague/<model>/hooks.json`).

**Per-model-first precedence**: per-model entries are composed *ahead of* the
base entries for each event — so the loop's "first deny/rewrite wins" semantics
give the per-model hook priority. In the output, each entry carries a `scope`
tag (`per-model` or `base`) so you can see exactly which layer each hook comes
from. Without `--model`, output is identical to the base-only baseline (no
`scope` key is added).

The `<model>` token is sanitized the same way as in `agents list` and
`skills list` — runs of characters outside `[A-Za-z0-9._-]` collapse to a
single `-` (e.g. `Qwen/Qwen3-32B` → `Qwen-Qwen3-32B`). The overlay path is
constructed exactly, never globbed, so model X can never load model Y's overlay.

## Hook decisions

- **allow** — permit the tool call (default on exit 0 / empty stdout).
- **deny** — block the tool call (non-zero exit or `{"decision":"deny"}`).
- **rewrite** — replace tool arguments (`{"decision":"rewrite","arguments":{}}`).
- Responses may include `"additionalContext"` for the model.

## See also

- `colleague explain commands`
- `colleague explain work`
- `colleague explain agents`
- `colleague explain skills`
"""

_AGENTS = """\
# colleague agents

Inspect the layered AGENTS instruction files resolved for a model. The cascade,
read from the **repo root** with a `~/.colleague/` user-level fallback, is
composed general → specific into the system prompt every work item sends:

    AGENTS.md                       (shared base — sibling tools read this too)
    AGENTS.colleague.md           (colleague overlay)
    AGENTS.colleague.<model>.md   (model overlay)

The `<model>` token is sanitized — every run of characters outside
`[A-Za-z0-9._-]` collapses to a single `-` (e.g. `Qwen/Qwen3-32B` →
`Qwen-Qwen3-32B`). The layer name is *constructed* for the named model, never
globbed, so one model can never load another model's overlay (per-model
isolation is structural). Note the asymmetry: the repo-level layer lives at the
repo root, but the user-level fallback lives under `~/.colleague/`.

## Usage

    colleague agents list
    colleague agents list --model Qwen/Qwen3-32B --repo PATH
    colleague agents list --json
    colleague agents overview

## See also

- `colleague explain skills`
- `colleague explain work`
"""

_SKILLS = """\
# colleague skills

Inspect the layered skill docs resolved for a model. Skills live under
`.colleague/` (a colleague-internal concept):

    .colleague/skills/*.md            (base)
    .colleague/<model>/skills/*.md    (model overlay — shadows base by stem)

Repo-level `.colleague/` shadows user-level `~/.colleague/` underneath (two
orthogonal precedence axes). Resolved skills are folded into the system prompt as
a compact name + one-line-summary catalog. A skill is **instructional text
only** — there is no skill execution model in v0 (an execution sandbox is out of
scope); invokable skills are a tracked follow-up.

## Usage

    colleague skills list
    colleague skills list --model Qwen/Qwen3-32B --repo PATH
    colleague skills list --json
    colleague skills overview

## See also

- `colleague explain agents`
- `colleague explain work`
"""

_ROLES = """\
# colleague roles

Inspect the **typed subagent roles**. A *role* types a delegated subagent: it
gives the child a tailored prompt fragment, a *curated subset* of the tool
surface, and a curated skill subset. Built-in roles:

    explorer / planner / reviewer   read-only (read_file, list_dir,
                                    check_test_integrity, finish)
    validator                       read-only + a read-only `run_tests` capability
    writer                          the full tool surface (today's default)

Read-only roles withhold `write_file`, `edit_file`, AND `run_command`, so a
read-only role *provably cannot mutate the tree* — the executor refuses any
withheld tool even if the model hallucinates the call. Selecting a role on the
`subagent` / `subagents` tools is backend-judged and optional; omitting it is
byte-identical to today's full-surface delegation.

Operator prompt overlays at `.colleague/agents/<name>.md` (and the per-model
`.colleague/<model>/agents/<name>.md`, exact path, no sibling globbing) override
a built-in role's prompt. This noun is distinct from the sibling `agents` noun,
which inspects the AGENTS *instruction-file* cascade.

## Usage

    colleague roles list
    colleague roles list --model Qwen/Qwen3-32B --repo PATH
    colleague roles list --json
    colleague roles overview

## See also

- `colleague explain agents`
- `colleague explain subagents`
"""

_APPROVE = """\
# colleague approve

The ``approve`` verb is available on both the ``commands`` and ``hooks`` nouns.
It records a checksum approval for a command template file or a hook script file
into ``<repo>/.colleague/approvals.json``.

## Usage

    colleague commands approve <name> [--repo PATH] [--algo sha256|md5] [--json]
    colleague hooks approve <name>    [--repo PATH] [--algo sha256|md5] [--json]

## What it does

1. For **commands**: resolves the template file for ``<name>`` under
   ``.colleague/commands/<name>.md``; computes a checksum; writes it into
   ``approvals.json`` under the ``"commands"`` section.
2. For **hooks**: ``<name>`` is the **repo-relative path** of the hook script
   file (the same key used in the hooks approval section); the file must exist
   at ``<repo>/<name>``; its checksum is written into the ``"hooks"`` section.

Both operations **merge** into existing ``approvals.json`` without clobbering
other sections (``run_command``, ``hooks``, ``commands`` each live in their own
key). The file is created if it does not exist. Re-running with the same
unchanged file is idempotent (same checksum recorded).

## Approval policy semantics

When an ``approvals.json`` section is **present**, the approval gate is active:
only entries with matching checksums are allowed. When a section is **absent**,
the gate is a no-op (everything allowed — preserves back-compat for repos with
no approval config).

Status values shown by ``commands list`` and ``hooks list``:

- ``approved``   — entry exists and checksum matches the current file.
- ``drifted``    — entry exists but checksum mismatches (file changed after approval).
- ``unapproved`` — section present but no entry for this name.
- ``ungated``    — section absent from policy (gate not active).

Skills are never approval-gated (they are always ``accessible``).

## Checksum algorithms

- ``sha256`` (default) — ``sha256:<hex>`` format.
- ``md5`` — ``md5:<hex>`` format (weaker; use sha256 for new approvals).

## See also

- ``colleague explain commands``
- ``colleague explain hooks``
- ``colleague explain work``
"""

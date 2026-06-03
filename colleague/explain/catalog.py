"""Markdown catalog for ``colleague explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("colleague",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# colleague

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

Run `colleague` with no verb at a terminal to open the interactive harness (the
`session` palette); piped or non-interactive, it prints this usage instead.

## Verbs

- `colleague drive <goal>` — drive toward a goal/instruction; work autonomously
  through a coder backend and hand off the result.
- `colleague session` — foreground interactive palette over the drive path.
- `colleague wheels list` — list discovered backend plugins.
- `colleague whoami` — mesh identity (`culture.yaml`) + the live drive engine/model.
- `colleague learn` — structured self-teaching prompt.
- `colleague explain <path>` — markdown docs for any noun/verb.
- `colleague overview` — descriptive snapshot of the agent.
- `colleague doctor` — configuration-readiness health check.
- `colleague cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `colleague explain drive`
- `colleague explain wheels`
- `colleague explain whoami`
"""

_WHOAMI = """\
# colleague whoami

Reports two identities in one glance, plus the package version. Read-only.

- **Mesh identity** (from `culture.yaml`): `nick` (`suffix`) and `backend` — the
  persona this agent runs as in the Culture mesh.
- **Drive identity** (resolved live, the same way a real drive resolves it):
  `drive_engine` — the engine a bare `colleague drive` would pick
  (`--engine` > `COLLEAGUE_ENGINE` > default `vllm-openai`) — and `drive_model`,
  the model it would call (`null` for the no-op `mock` engine). This is the
  trust signal an agent checks before delegating: it names the *delegate*, not
  an unrelated persona backend.

## Usage

    colleague whoami
    colleague whoami --json
"""

_LEARN = """\
# colleague learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    colleague learn
    colleague learn --json
"""

_EXPLAIN = """\
# colleague explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    colleague explain colleague
    colleague explain whoami
    colleague explain --json <path>
"""

_OVERVIEW = """\
# colleague overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    colleague overview
    colleague overview --json
"""

_DOCTOR = """\
# colleague doctor

Colleague's health check: a configuration-readiness diagnostic emitting a
rubric-shaped report across ordered check-groups: **identity**, **provider**
(config + budget), **usage** (which backend a bare drive actually picks),
**engines** (all installed plugins), **otel-readiness**, and **environment**
(repo config / layering / handoff prereqs / CLI integrity).

Exits 1 when unhealthy (when any error-severity check fails). Only
error-severity failures make the report unhealthy; warnings and info are
advisory — e.g. `usage_effective_engine` warns (but stays healthy) when a bare
run would drive the no-op `mock` backend.

`--probe` adds an opt-in `provider_reachable` check that pings the provider
server (`{base_url}/models`). It is the one check that opens a network
connection, so it is off by default; an unreachable server is reported as a
warning, not an error.

## Usage

    colleague doctor
    colleague doctor --json
    colleague doctor --probe
"""

_CLI = """\
# colleague cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    colleague cli overview
    colleague cli overview --json
"""

_DRIVE = """\
# colleague drive

Drive toward a goal: hand colleague a request or instruction and it works
autonomously — selecting a backend plugin, running the bounded agentic tool-loop,
writing a result artifact, and handing off the change as a branch + PR. The repo
is the target (`--repo`, default cwd); the same invocation works for every
engine — only `--engine` changes.

## Usage

    colleague drive "add a CONTRIBUTING.md" --repo . --engine mock --no-pr
    colleague drive "fix the typo in README" --engine vllm-openai --no-pr
    colleague drive "..." --engine vllm-openai --base-url http://localhost:8001/v1 --json

## Backend selection

Resolved highest-first: the `--engine` flag, then the `COLLEAGUE_ENGINE` env
var, then the built-in default `vllm-openai` (the real bundled backend). A bare
`drive` never silently falls back to the no-op `mock` reference — use
`--engine mock` (or `COLLEAGUE_ENGINE=mock`) when you explicitly want it.

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — backend plugin (default: `COLLEAGUE_ENGINE` env, else `vllm-openai`).
- `--no-pr` — commit locally; do not push or open a PR.
- `--base-url / --model / --api-key / --max-steps` — backend overrides.

A failed drive still writes a `status=error` artifact before exiting non-zero.
"""

_WHEELS = """\
# colleague wheels

Discover the backend plugins installed in this environment. Backends
register under the `colleague.engines` entry-point group; bundled and
out-of-tree plugins are discovered identically.

## Usage

    colleague wheels list
    colleague wheels list --json
    colleague wheels overview
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

    colleague drive --command <name> [args...]

## See also

- `colleague explain drive`
- `colleague explain hooks`
"""

_SESSION = """\
# colleague session

Open a foreground interactive palette that lists discovered command templates,
accepts free-text ad-hoc instructions, and runs every selection through the
**same drive path** as `colleague drive` (identical Task/loop/hooks/artifact).
The loop continues until you enter `q`, an empty line, or EOF.

## Usage

    colleague session
    colleague session --repo PATH --engine mock
    colleague session --pr            # opt back into push + PR per drive

## Interaction

At the `>>>` prompt you can enter:

- A **number** (e.g. `1`) — selects that template from the numbered palette.
- A **template name** (e.g. `lint`) — runs that template directly.
- A **free-text instruction** — treated as an ad-hoc task (like `drive "<text>"`).
- `q`, `quit`, `exit`, or an **empty line** — ends the session.

## Handoff

By default a session is a "talk + iterate" loop: each drive commits locally on a
`colleague/<task_id>` branch but does **not** push or open a PR. Pass `--pr` to
push and open a PR after every drive. (This differs from `drive`, which opens a
PR by default.) Engine selection matches `drive`: `--engine` > `COLLEAGUE_ENGINE`
> `vllm-openai`.

## Key flags

- `--repo PATH` — target repository (default: cwd).
- `--engine NAME` — backend plugin (default: `COLLEAGUE_ENGINE` env, else `vllm-openai`).
- `--pr` — push and open a PR after each drive (default: commit locally only, no PR).
- `--base BRANCH` — base branch for the PR (default: `main`).
- `--base-url / --model / --api-key / --max-steps` — backend overrides.

## See also

- `colleague explain drive`
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
- `colleague explain drive`
- `colleague explain agents`
- `colleague explain skills`
"""


_AGENTS = """\
# colleague agents

Inspect the layered AGENTS instruction files resolved for a model. The cascade,
read from the **repo root** with a `~/.colleague/` user-level fallback, is
composed general → specific into the system prompt every drive sends:

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
- `colleague explain drive`
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
- `colleague explain drive`
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
- ``colleague explain drive``
"""

_FEEDBACK = """\
# colleague feedback

Grade a drive **after the fact** — the second half of the outsourcing-ROI loop.
A drive's artifact already records what it *cost* (the always-on `stats` block:
elapsed time, tokens read/generated, tools used, bytes written, reasoning-vs-answer
sizes); `feedback` records how *good* it was. Together they let a caller — human
or agent — decide whether outsourcing that task to colleague (and to which
backend) paid off.

A drive is named by its `task_id`, or the literal `last` for the most recent
drive in the repo. Feedback is a **single record per drive** (re-grading
overwrites), stored as `.colleague/<task_id>.feedback.json` beside the artifact.

## Verbs

- `feedback record <id|last> --rating N [--notes ...] [--by ...] [--repo P]` —
  write a 1-5 quality rating + notes. `--by` defaults to the resolved identity.
- `feedback show <id|last> [--repo P] [--json]` — read a drive's feedback. An
  ungraded drive reads back as `no feedback yet` (a clean state, exit 0 — not an error).
- `feedback overview` — describe this surface.

## Usage

    colleague feedback record last --rating 4 --notes "correct but verbose"
    colleague feedback record 9f2c1ab0 --rating 5 --repo . --json
    colleague feedback show last --repo .

## Record shape

    {"task_id": "...", "rating": 4, "notes": "...", "by": "...", "at": "<ISO-8601>"}

`rating` must be an integer 1-5. There is no tokenizer, so the artifact's
reasoning/written sizes are exact chars/bytes, never estimated tokens — see
`colleague explain drive` for the stats block.

## See also

- `colleague explain drive`
- `colleague explain outsource`
"""

_TELEMETRY = """\
# colleague telemetry

Telemetry for a drive: opt-in OpenTelemetry **traces + metrics** over OTLP. Telemetry
belongs to the runtime — it is instrumented once in the loop and the shared drive
path, so *every* backend emits identical signals (the all-engines rule), exactly
like lifecycle hooks.

Off by default. The OpenTelemetry SDK is an **optional extra** (the base install
keeps zero runtime dependencies); enable it with the env var and install the
extra:

    pip install 'colleague[otel]'
    export COLLEAGUE_OTEL_ENABLED=1
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # OTLP/HTTP collector

When requested without the extra installed, colleague degrades to a no-op with
a one-line stderr notice — it never fails the drive.

## Signals

- spans: `colleague.drive` (root) -> `colleague.tool.*` (per tool call) plus
  `colleague.handoff`.
- metrics: `colleague.steps`, `colleague.tokens` (attr `kind`),
  `colleague.generated.chars` (attr `kind`=reasoning|answer), `colleague.bytes_written`,
  `colleague.tool.latency`, `colleague.tool.calls`, `colleague.hook.denials`,
  `colleague.drive.duration` (attr `status`).

## Configuration

Precedence (highest first): explicit > `COLLEAGUE_OTEL_*` > standard `OTEL_*` >
default. `OTEL_SDK_DISABLED=true` is honored as a kill-switch.

- `COLLEAGUE_OTEL_ENABLED` — turn telemetry on (default: off).
- `COLLEAGUE_OTEL_ENDPOINT` / `OTEL_EXPORTER_OTLP_ENDPOINT` — collector URL.
- `COLLEAGUE_OTEL_SERVICE_NAME` / `OTEL_SERVICE_NAME` — resource `service.name`.
- `COLLEAGUE_OTEL_METRICS_ENABLED` — toggle metric emission (default: on).

## Usage

    colleague telemetry status
    colleague telemetry status --json
    colleague telemetry overview

## See also

- `colleague explain drive`
- `colleague explain hooks`
"""


_SUBAGENT = """\
# colleague subagent

Mid-drive, a backend can delegate a scoped sub-task to a nested in-process child
drive via the `subagent` loop tool. The child runs the same bounded tool-loop
with **no** git handoff; its result is returned to the parent as the tool result
and appended to `TaskResult.sub_results` (omitted when empty).

## Key properties

- **In-process** — a nested function call, no separate process, socket, or fork;
  zero new runtime dependencies. Children run sequentially by default; opt-in
  concurrency uses threads confined to `colleague/subagents.py`.
- **Backend/model switch** — the optional `engine` and `model` parameters let the
  child run on a different backend or model. Resolution goes through
  `registry.load` + `EngineConfig` inheritance (config-level switch only, no
  backend code change).
- **Bounded** — `MAX_SUBAGENT_DEPTH=2` (recursion cap, checked before any child
  work starts) and `MAX_SUBAGENT_FANOUT=4` (per-drive fan-out cap). A child
  refused at the depth cap does zero work and returns an error immediately.
- **Backend-judged, optional** — the model decides whether to delegate per call,
  like the `devague` destination tool. There is no operator-configured automatic
  task→backend routing.
- **Opt-in concurrency (shipped v0.29.0)** — `COLLEAGUE_SUBAGENT_CONCURRENCY`
  (default 1 = byte-identical sequential) runs up to
  `MIN(width, MAX_SUBAGENT_FANOUT-1)` children in parallel via
  `concurrent.futures`, reserving one slot for a sequential merge child that
  integrates the per-child branches.
- **Per-child worktree isolation** — each child runs in its own throwaway git
  worktree on a `sub/<id>` branch (`colleague/worktrees.py`); a sequential
  merge-subagent integrates them, surfacing (never force-merging) conflicts.
- **No per-subagent handoff** — only the top-level drive branches, commits, and
  opens a PR.
- **Runtime-owned (all-engines rule)** — the tool schema lives in
  `colleague/tools.py`; the launcher lives in `colleague/subagents.py`. No
  backend module touches either; the tool is offered to every backend identically.

## Not a router

This is **not** the out-of-scope multi-backend router: there is no
operator-configured policy that automatically routes a task to a particular
backend. Delegation is always the model's choice at call time.

## Tool parameters

- `instruction` (required) — the sub-task to hand to the child drive.
- `engine` (optional) — backend plugin name; defaults to the parent's backend.
- `model` (optional) — model override; defaults to the parent's model.

## Implementation

- `colleague/subagents.py` — `run_subagent` / `make_spawn` launcher.
- `colleague/tools.py` — tool schema + `ToolExecutor._subagent` dispatch.
- `colleague/config.py` — `MAX_SUBAGENT_DEPTH`, `MAX_SUBAGENT_FANOUT`.
- `colleague/contract.py` — `SubResult`, `TaskResult.sub_results`.

## See also

- `colleague explain drive`
- `colleague explain wheels`
"""

_OUTSOURCE = """\
# colleague outsource (a different mind)

`outsource` is a **first-party** Claude Code skill (`.claude/skills/outsource/`),
not a CLI verb — the inverse of the vendored skills (origin = colleague). It
lets another agent hand a scoped task to colleague: a *different* backend/mind,
not a stronger one. Diversity is the point — a second, independent perspective
catches what the author's mind glides past, which is why **review** is the
headline verb.

## Verbs

- `outsource explore "<question or area>"` — read-only investigation; the model
  reads and reports findings.
- `outsource review "<focus>" [--base main]` — a diverse second opinion on the
  committed diff (`<base>...HEAD`).
- `outsource write "<task>" [--apply|--pr]` — delegate a small implementation.
  Previews by default (throwaway worktree + would-be diff, no side effects);
  `--apply` lands a `colleague/<id>` drive branch, `--pr` opens a PR.

## Safety

- explore/review run in a throwaway `git worktree` at HEAD — they cannot touch
  your working tree or branch (read-only is enforced by isolation + a prompt
  constraint, not a sandbox).
- `write` previews by default (isolated worktree, safe even on a dirty tree);
  applying (`--apply` / `--pr`) refuses a dirty tree unless `--allow-dirty`
  (guards the dirty-tree hazard).

## Run

    bash .claude/skills/outsource/scripts/outsource.sh <verb> "<text>" [options]

Defaults to a local vLLM model; override with `--engine` / `--model` /
`--base-url` or `COLLEAGUE_*` env. See `docs/features/outsource.md`.

## See also

- `colleague explain drive`
"""

_TUI = """\
# colleague tui

Headless, agent-facing inspection of the TUI cockpit — a state machine whose
single agent-readable mirror is the **TAUI** (a plain JSON dict). This verb runs
entirely **without a terminal** and opens no socket: it is a set of pure
`state -> mirror/frame` transforms. The live TTY view is a separate concern.

The cockpit exposes **three views** of the same `CockpitState`:

- **JSON (TAUI)** — the programmatic/script contract and the source of truth;
  emitted by `tui state`.
- **ANSI** — the visual frame for a live terminal; emitted by `tui render` (default).
- **Markdown** — the agent-facing readable view; better than raw JSON for an agent
  to read at a glance. Emitted by `tui render --format markdown`. All three are pure
  functions of one `CockpitState`, so any disagreement between them is a
  render-fidelity bug — `tui diagnose` catches it. (Before this surface was added,
  no colleague command emitted Markdown and `diagnose` inspected the ANSI frame
  only.)

## Verbs

- `tui render --state <file> [--format ansi|markdown]` — render the chosen frame
  (default: `ansi`). `--json` wraps the result as `{"ansi": "<frame>"}` or
  `{"markdown": "<frame>"}` depending on `--format`.
- `tui state [--state <file>]` — print the TAUI mirror as JSON (default: a fresh
  empty cockpit).
- `tui inspect --select <selector> [--state <file>]` — resolve a dotted selector
  to its node (JSON). A bad selector is a user error.
- `tui action --select <selector> [--state <file>]` — operate the UI by selector:
  map a popup-action selector to an event, reduce it, and print the NEW mirror.
- `tui replay <events.jsonl> [--state <file>]` — fold an event log into a mirror.
- `tui snapshot --name <n> [--state/--events/--dir]` — write the snapshot **quad**:
  `<name>.taui.json`, `<name>.ansi`, `<name>.events.jsonl`, and `<name>.md` (the
  Markdown render). Legacy triples (no `.md`) still read fine — `<name>.md` defaults
  to empty when absent.
- `tui test --scenario <file.json>` — run a JSON scenario as an assertion;
  **exit 1 on FAIL**.
- `tui diagnose (--dir <d> --name <n> | --taui <f> --ansi <f> [--events <f>])` —
  classify cross-mirror bugs (no model/network). On a quad (`<name>.md` present)
  the RENDER faithfulness check runs against **both** the ANSI frame and the
  Markdown frame — proving the JSON mirror and the Markdown render agree. Zero
  findings = faithful; a finding = render-fidelity drift between JSON and Markdown.
  (Legacy triples without a `.md` file skip the Markdown check entirely, preserving
  the exact pre-quad behavior.)
- `tui overview` — describe this surface.

## Scenario format (JSON, not YAML)

colleague keeps zero runtime dependencies, so scenarios are **JSON**, never
YAML (PyYAML is forbidden):

    {
      "name": "boost popup appears when a skill is suggested",
      "initial": { "screen": "main" },
      "events": [ {"type": "skill_suggested", "skill": "boost",
                   "reason": "task_complexity_high"} ],
      "expect": {
        "popup": { "id": "popup.skill.boost", "visible": true, "blocking": false },
        "focused": "input.prompt",
        "action_available": "popup.skill.boost.accept"
      }
    }

The runner builds `CockpitState.from_dict(initial)`, folds each event via
`event_from_dict` + `reduce`, serializes the final state, and checks each
`expect` clause: `popup` (id/visible/blocking against the serialized popups),
`focused`, and `action_available` (present among the derived selectors /
`available_actions`). The report lists which clauses passed and which failed.

## Usage

    colleague tui state --json
    colleague tui render --state cockpit.json
    colleague tui render --state cockpit.json --format markdown
    colleague tui render --state cockpit.json --format markdown --json
    colleague tui inspect --select popup.skill.boost --state cockpit.json --json
    colleague tui action --select popup.skill.boost.accept --state cockpit.json --json
    colleague tui test --scenario colleague/tui/scenarios/boost-popup.scenario.json
    colleague tui snapshot --name baseline --state cockpit.json --dir ./snapshots
    colleague tui diagnose --dir ./snapshots --name baseline

## See also

- `colleague explain session`
- `colleague explain drive`
"""

ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("colleague",): _ROOT,
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
    ("commands", "approve"): _APPROVE,
    ("hooks",): _HOOKS,
    ("hooks", "list"): _HOOKS,
    ("hooks", "overview"): _HOOKS,
    ("hooks", "approve"): _APPROVE,
    ("agents",): _AGENTS,
    ("agents", "list"): _AGENTS,
    ("agents", "overview"): _AGENTS,
    ("skills",): _SKILLS,
    ("skills", "list"): _SKILLS,
    ("skills", "overview"): _SKILLS,
    ("approve",): _APPROVE,
    ("feedback",): _FEEDBACK,
    ("feedback", "record"): _FEEDBACK,
    ("feedback", "show"): _FEEDBACK,
    ("feedback", "overview"): _FEEDBACK,
    ("telemetry",): _TELEMETRY,
    ("telemetry", "status"): _TELEMETRY,
    ("telemetry", "overview"): _TELEMETRY,
    ("subagent",): _SUBAGENT,
    ("subagents",): _SUBAGENT,
    ("convoy",): _SUBAGENT,
    ("outsource",): _OUTSOURCE,
    ("tui",): _TUI,
    ("tui", "render"): _TUI,
    ("tui", "state"): _TUI,
    ("tui", "inspect"): _TUI,
    ("tui", "action"): _TUI,
    ("tui", "replay"): _TUI,
    ("tui", "snapshot"): _TUI,
    ("tui", "test"): _TUI,
    ("tui", "diagnose"): _TUI,
    ("tui", "overview"): _TUI,
}

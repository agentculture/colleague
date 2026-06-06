# colleague

> Colleague is a swappable coder-agent harness that turns different model
> backends into repo workers behind one shared task runtime.
>
> **One runtime, many minds.**

Colleague is the harness around the model. The model is the backend; Colleague
supplies the task runtime, controls, shared task contract, and handoff that turn
that backend into a usable repo worker. Point it at a repo task and it runs the
work through whichever coder backend you select — and the caller never has to
care which one ran.

## Architecture

| Part | In Colleague |
|------|----------------|
| **Mind / backend** | the model/coder backend (a local vLLM model, an OpenAI-compatible endpoint, …) |
| **Adapter** | the code that invokes and controls one backend (`colleague/engines/`) |
| **Task runtime** | the shared task contract + lifecycle (`Task` → `TaskResult`) |
| **Tool loop** | the bounded agentic loop the backend works the repo through |
| **Plugins** | replaceable backend adapters, discovered via Python entry points |
| **Run report** | the JSON result artifact + step trace each run writes |
| **Telemetry** | opt-in OpenTelemetry traces + metrics (`colleague/telemetry/`) |
| **Handoff** | branch/commit/push + `gh pr create`, gated for offline/CI (`colleague/handoff.py`) |
| **Doctor** | `colleague doctor` — read-only configuration-readiness health check (`colleague/oilcheck/`) |
| **Registry** | `colleague backends list` — the backend plugins installed in this environment |
| **Approval gate** | `colleague/policy.py` — operator-declared `.colleague/approvals.json` that controls what the harness executes |

## What ships in v0

- A **shared task contract** — a typed `Task` and `TaskResult` that every backend
  consumes and produces identically.
- A **bounded agentic tool-loop** — the backend calls `read_file`, `write_file`,
  `list_dir`, `run_command`, `culture` (AgentCulture CLIs), and `finish`,
  confined to the target repo, until it finishes or hits the step budget.
- **Two backends**, both registered through the same `colleague.engines`
  entry-point group an out-of-tree plugin would use:
  - `mock` — deterministic and networkless; the CI workhorse.
  - `vllm-openai` — drives any **OpenAI-compatible** `/v1/chat/completions`
    endpoint with tool calling. The built-in default model is
    `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP` (an NVFP4 Qwen3 checkpoint on a
    vLLM server — what `doctor` checks for); any tool-calling model works.
- **Git/PR handoff** — branch → commit → push → `gh pr create`, gated so
  `--no-pr` (or no remote) stays a local commit and CI never pushes.
- A **result artifact** (`.colleague/<task-id>.json`) for handoff back to
  Guildmaster / Taskmaster / Steward.
- **Command templates** — reusable, parameterized task recipes stored under
  `.colleague/commands/*.md`, invoked with `work --command <name> [args…]`
  or selected in the interactive palette.
- **Lifecycle hooks** — operator-authored shell commands that fire at
  `task_start`, `pre_tool`, `post_tool`, and `finish` events; a `pre_tool` hook
  can allow, deny, or rewrite tool calls before the backend executes them. A
  **per-model hooks overlay** (`.colleague/<model>/hooks.json`) layers
  model-specific fixes **ahead of** the base hooks, giving the operator a
  precision tool for recurring model biases — applied only for the targeted
  model, a strict no-op for all others; no new runtime dep, socket, or daemon.
- **Interactive palette** — `colleague session` opens a foreground command
  browser so operators can select templates and run ad-hoc instructions without
  leaving the shell.
- **Layered per-model config** — AGENTS instructions
  (`AGENTS.md` → `AGENTS.colleague.md` → `AGENTS.colleague.<model>.md`) and
  skills (`.colleague/skills/*.md` → `.colleague/<model>/skills/*.md`)
  compose into a model-specific system prompt, with strict per-model isolation;
  inspect them with `colleague agents list` / `colleague skills list`.
- **Telemetry: OpenTelemetry observability** — opt-in traces + metrics over OTLP,
  emitted identically by every backend; off by default and a strict no-op, with
  the SDK as an optional `[otel]` extra so the base install stays dep-free.
- **`doctor`** — a read-only configuration-readiness health check
  across identity, provider, engines, otel-readiness, and environment; emits a
  rubric-shaped report and exits non-zero when unhealthy.
- **Mesh-member integration** — a work item resolves a process-level identity (the
  repo's `culture.yaml` nick or `.colleague/identity.json`) and propagates it
  to subcommands via `COLLEAGUE_IDENTITY`. The loop exposes one curated
  `culture` tool (allow-list: `agtag`, `devex`) that shells out to the
  operator-installed CLIs with the identity injected. Operators opt into
  read-only ephemeral neighbour clones via `.colleague/neighbours.json`
  (defaults to empty; no new runtime dependency).
- **Destination** — colleague's sibling to telemetry. When a task warrants it, a
  backend can set a curated `devague` loop tool to open and converge a goal-frame
  before driving the repo, and declare the announcement on arrival. The
  destination (frame slug + announcement) is recorded in the JSON artifact; the
  curated allow-list excludes `confirm`/`reject` (user-only) and `export`
  (operator-only), and convergence is advisory — only human-confirmed claims are
  authoritative. Setting a destination is optional and backend-judged.
- **Approval gate** — an operator-declared `.colleague/approvals.json` that
  gates what the harness *executes*. Approval is tamper-protection, not just a
  name list: `approve` records a file's content checksum; if the file changes
  later the approval is void. Three categories are gated, each opt-in by presence
  of its section: `run_command` CLIs by program token (allow/deny lists),
  lifecycle hook scripts by checksum, and command templates by checksum. Skills
  and AGENTS instructions load freely — they are never gated. See the
  [Approval gate](#approval-gate) section below for the full config shape and
  usage.
- **Startup banner** — `colleague work` and `colleague session` greet an
  interactive terminal with an ASCII banner. It's decorative chrome: written to
  stderr, shown only on a TTY, and suppressed under `--json`, so it never
  pollutes the stdout result stream or agent-parsed output.

**Not in v0** (by design): a multi-backend router / routing policy, an execution
sandbox, a daemon mode, Codex/Claude/Gemini adapters, a `--no-hooks` escape hatch
(there is no such flag; the approval gate is the landed hook-trust increment —
a policy gate, not a sandbox), and a live MCP runtime (no `mcp.json`, no `mcp`
verb; the curated `culture` tool shells out to operator CLIs — no socket, no MCP
transport). The runtime package has **no third-party dependencies** — the vLLM
adapter speaks the OpenAI wire format over the standard library.

## Feature docs

Each shipped feature has a focused page under [`docs/features/`](docs/features/)
— start at the [feature index](docs/features/README.md). For the per-version
list of what shipped (and when), see [`CHANGELOG.md`](CHANGELOG.md).

| Feature | Doc |
|---------|-----|
| Work & the tool-loop | [work-and-loop.md](docs/features/work-and-loop.md) |
| Context budget / graceful degradation | [graceful-degradation.md](docs/features/graceful-degradation.md) |
| Capacity standard / fill-line decision (v1) | [spec](docs/specs/2026-06-06-colleague-holds-a-standard-for-its-own-capacity-it.md) |
| Backends & plugins | [engines.md](docs/features/engines.md) |
| Model & endpoint selection | [model-selection.md](docs/features/model-selection.md) |
| Git/PR handoff | [handoff.md](docs/features/handoff.md) |
| Result artifact | [artifact.md](docs/features/artifact.md) |
| Command templates | [command-templates.md](docs/features/command-templates.md) |
| Lifecycle hooks | [hooks.md](docs/features/hooks.md) |
| Interactive palette | [session.md](docs/features/session.md) |
| Cockpit views (tui / TAUI) | [tui.md](docs/features/tui.md) |
| Layered per-model config | [layered-config.md](docs/features/layered-config.md) |
| Telemetry: OpenTelemetry | [telemetry.md](docs/features/telemetry.md) |
| Work stats & feedback (ROI) | [stats-and-feedback.md](docs/features/stats-and-feedback.md) |
| `doctor` (health check) | [doctor.md](docs/features/doctor.md) |
| Agent-first CLI | [agent-cli.md](docs/features/agent-cli.md) |
| Mesh-member integration | [mesh-member.md](docs/features/mesh-member.md) |
| Destination | [destination.md](docs/features/destination.md) |
| Subagents | [subagents.md](docs/features/subagents.md) |
| Parallel subagents | [parallel-subagents.md](docs/features/parallel-subagents.md) |
| Audit fan-out | [audit-fanout.md](docs/features/audit-fanout.md) |
| Per-model configuration | [per-model-configuration.md](docs/features/per-model-configuration.md) |
| Approval gate | [See Approval gate section below](#approval-gate) |
| Ask colleague (a different mind) | [ask-colleague.md](docs/features/ask-colleague.md) |
| Escalation (agtag continuation) | [escalation.md](docs/features/escalation.md) |

The detailed sections below remain the canonical reference; the feature pages add
per-feature source pointers and cross-links.

## Before → after: the extensibility layer

**Before** this layer, `colleague work` accepted one raw instruction string
and ran the tool-loop with no operator gate and no saved recipes: `run_command`
and `write_file` executed unconditionally, and every task had to be typed from
scratch.

**After**, operators drop files into `.colleague/` and gain three things that
work identically across every backend (the all-engines rule):

1. **Command templates** — author a recipe once, invoke it by name with
   positional arguments; `work --command <name> [args…]` expands it into the
   same `Task` shape a raw `work "…"` produces.
2. **Lifecycle hooks** — `pre_tool` hooks can allow, deny (reason fed back to
   the model), or rewrite tool arguments before they execute; `post_tool` hooks
   run formatters or linters after; `task_start` and `finish` hooks bracket the
   whole work item. Every firing is recorded in the result artifact.
3. **Interactive palette** — `colleague session` lists discovered templates,
   accepts a selection (by number or name) plus optional arguments, and runs the
   chosen task through the same work path, loop, hooks, and artifact — no
   parallel code path.

This extensibility lives in the runtime (`colleague/loop.py`), not in any one
backend, so it binds equally to `mock`, `vllm-openai`, and any future plugin.

## Quickstart

```bash
uv sync
uv run pytest -n auto                          # full suite, no network needed

# Open the interactive harness (the session palette) at a terminal:
uv run colleague

# Discover the backends installed in this environment:
uv run colleague backends list

# Work toward a goal with the deterministic mock backend (no model, no network):
uv run colleague work "add a CONTRIBUTING.md stub" --repo . --engine mock --no-pr
```

### Driving a real model (vLLM)

Start an OpenAI-compatible vLLM server with tool calling enabled:

```bash
vllm serve Qwen/Qwen3-32B \
  --port 8001 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

The right `--tool-call-parser` depends on the model **and** the vLLM build:
`hermes` works for many models (including `Qwen/Qwen3-32B` above), while other
builds need a different one — e.g. an NVFP4 Qwen3 checkpoint served via vLLM may
want `qwen3_coder`. The backend itself is parser-agnostic — any parser that makes
the server emit OpenAI-format tool calls works.

> **Tip (anecdotal).** With an NVFP4 Qwen3 checkpoint, `qwen3_coder` handled
> tool-argument escaping more reliably than `hermes` in our testing: a `hermes`
> run over-escaped the triple-quotes in a generated docstring (writing `\"\"\"`
> instead of `"""`), producing a `SyntaxError`, where `qwen3_coder` wrote the
> same file cleanly. This is a single observation, not a benchmark — but if a
> parser garbles quote-heavy edits, trying the other one is worth a shot.

Then point Colleague at it (defaults already target `localhost:8001`):

```bash
uv run colleague work "fix the typo in the README title" \
  --repo /path/to/target/repo \
  --engine vllm-openai \
  --base-url http://localhost:8001/v1 \
  --model Qwen/Qwen3-32B
```

Configuration resolves in the order: explicit flag → `COLLEAGUE_*` env →
`OPENAI_*` env → default. The built-in default `--model` is
`sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP`; the example above overrides it with
`--model` to match the server you started. Because the adapter only touches the
OpenAI surface, pointing `--base-url` at any compatible server (llama.cpp, an
OpenAI proxy) needs no code change.

The opt-in live end-to-end test proves this against a real server:

```bash
COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

## Command templates

Operators save reusable task recipes as Markdown files under
`.colleague/commands/<name>.md` (repo-level or `~/.colleague/commands/` for
user-level; repo-level shadows user-level by stem).

`.colleague/commands/` is **committable** — it is the one part of the otherwise
gitignored `.colleague/` dir that git tracks, so a team can share recipes in-repo
(run artifacts, `hooks.json`, and `approvals.json` stay local). The committed
`doc-review` recipe is a worked example.

### Template file format

A template may open with an optional `---` metadata block:

```markdown
---
description: Fix lint errors under a path
engine: mock
constraints: keep diffs minimal, run the formatter
arg-hint: <path>
---
Fix all lint errors under $1. Then run the formatter. $ARGUMENTS
```

Supported metadata keys:

| Key | Meaning |
|-----|---------|
| `description` | One-line description shown in listings |
| `engine` | Engine to use when running this command (overridden by `--engine`) |
| `constraints` | Comma-separated constraints added to the `Task` |
| `arg-hint` | Short argument hint shown in `commands list` |

If no `---` block is present, the entire file content is the body.

### Argument substitution

| Placeholder | Expands to |
|-------------|------------|
| `$ARGUMENTS` | All arguments joined by a space |
| `$1`, `$2`, … | The N-th positional argument (empty string if not supplied) |

### Running a command template

```bash
# One-shot via work:
uv run colleague work --command fix-lint src/ --repo /path/to/repo --engine mock --no-pr

# List all discovered templates:
uv run colleague commands list --repo .

# Surface overview:
uv run colleague commands overview
```

The `--command` flag and a positional instruction are mutually exclusive; any
tokens after `--command <name>` are passed as template arguments (`$1`, `$2`,
`$ARGUMENTS`).

## Lifecycle hooks

Hooks are operator-authored shell commands registered in
`.colleague/hooks.json` (repo-level or `~/.colleague/hooks.json` for
user-level; repo-level wins).

### Config format

```json
{
  "hooks": {
    "pre_tool":  [{ "matcher": "run_command", "command": "my-policy-gate.sh" }],
    "post_tool": [{ "matcher": "write_file",  "command": "black $file 2>/dev/null; true" }],
    "task_start":[{ "command": "echo task starting" }],
    "finish":    [{ "command": "echo done" }]
  }
}
```

Each entry has:

| Field | Meaning |
|-------|---------|
| `matcher` | Regex (`re.fullmatch`) tested against the tool name. Absent or empty matches every tool. Ignored for `task_start` / `finish` events. |
| `command` | Shell command run in the target repo directory. |

### Lifecycle events

| Event | When it fires | Pre/post effect |
|-------|--------------|-----------------|
| `task_start` | Before the first tool call | Observe only |
| `pre_tool` | Before each tool call | Can allow, deny, or rewrite |
| `post_tool` | After each tool call | Observe only (side-effects OK) |
| `finish` | After the loop ends | Observe only |

### Hook I/O contract

The hook receives a JSON payload on **stdin**:

```json
{
  "event": "pre_tool",
  "tool": "run_command",
  "arguments": { "command": "pytest" },
  "task_id": "<uuid>",
  "repo_path": "/path/to/repo"
}
```

The hook signals its decision via **exit code** and optional **structured stdout**:

| Exit code | Stdout | Decision |
|-----------|--------|----------|
| non-zero | any | **deny** — stderr (fallback: stdout) is fed back to the model as the tool result |
| 0 | empty or non-JSON | **allow** — tool runs as-is |
| 0 | `{"decision":"allow", ...}` | **allow** |
| 0 | `{"decision":"deny", "reason":"..."}` | **deny** — reason fed back to model |
| 0 | `{"decision":"rewrite","arguments":{...}}` | **rewrite** — tool runs with the supplied replacement arguments |

Any response may carry an `"additionalContext"` string. Every firing (event,
matched command, decision, exit code) is recorded in `TaskResult.hook_firings`
and appears in the result artifact JSON.

`post_tool`, `task_start`, and `finish` hooks are observe-only: a deny from
these events is recorded but does not halt the loop.

### Inspecting hooks

```bash
uv run colleague hooks list --repo .
uv run colleague hooks overview
```

## Interactive cockpit (session)

`colleague session` opens a foreground interactive **cockpit** (#74 A2): it
renders one `CockpitState` — a command palette + a running conversation + popups —
and runs each selection through the same `work` path (same `Task`, loop, hooks,
and artifact — no parallel code path):

```bash
uv run colleague session --repo /path/to/repo --engine vllm-openai
```

**Input is line-based.** At the prompt, plain text runs a work item — a **number**
(palette entry), a **template name**, or a **free-text instruction** (ad-hoc
task). A line starting with `/` is a **slash command** — the meta/system
namespace, akin to Claude Code / Codex:

- Introspection (surface an existing noun in the cockpit): `/help`, `/commands`,
  `/skills`, `/agents`, `/config` (the `doctor` readiness view), `/engines`,
  `/telemetry`, `/feedback`.
- Live config: `/engine <name>`, `/model <name>`, `/base <branch>`, `/pr` (toggle
  push + PR) — change the session without restarting it.
- `/quit` (or `q` / empty line) ends the session.

**Three render tiers of the one state, chosen automatically:**

- **Interactive (a colour TTY)** — the dynamic ANSI cockpit: redraw-in-place, and
  popups on real events (an `error` popup when a work item step fails).
- **Non-interactive (piped / captured)** — **Markdown** menus (the static but
  *full* agent-readable view), the default off a TTY. `--no-tui` forces it on a TTY.
- **`--json`** — stdout carries only the work item `TaskResult` (one JSON object each,
  preserving the machine contract); the cockpit renders to stderr as chrome.

Running `colleague` with no arguments **at a terminal** opens this same cockpit
(backend resolved like `work`: `--engine` > `COLLEAGUE_ENGINE` > `vllm-openai`,
never a silent `mock`). By default it is a "talk + iterate" loop — each work item
commits locally but does **not** push or open a PR; `/pr` or `--pr` opts in.

## Cockpit views (tui)

`colleague tui` exposes a **headless, stdlib-only cockpit** in three views of one
`CockpitState`: a **JSON/TAUI** mirror (the agent-readable, selector-addressed
source of truth — `tui state`), an **ANSI** frame (the visual render — `tui render`,
the default), and a **Markdown** view (the agent-facing readable render —
`tui render --format markdown`). TAUI (*Textual Agentic UI*) lets an agent read and
operate the UI without screen-scraping, an LLM, or any `colleague` import.

The cockpit is a pure reducer (`event → reduce(state, event) → CockpitState`) and
its state carries a **popup** model (`skill_suggestion` / `confirmation` / `error` /
`progress` / `diff` / `help`). `tui snapshot` captures a moment; `tui diagnose`
classifies cross-view disagreements (no LLM, no network); `tui live` opens the
foreground TTY cockpit.

```bash
uv run colleague tui state                          # the TAUI JSON mirror
uv run colleague tui render --state <file>          # the ANSI frame
uv run colleague tui render --format markdown --state <file>
uv run colleague tui overview
```

**Watching a live work item.** A real `work` feeds the cockpit (#74):

```bash
uv run colleague work "<task>" --engine mock       # auto: live cockpit on a TTY
uv run colleague work "<task>" --engine mock --no-tui   # force the plain step lines
uv run colleague work "<task>" --engine mock --tui-events run.jsonl   # live event stream
uv run colleague tui replay --trace .colleague/<id>.trace.jsonl      # replay a finished work item
```

- **Live cockpit (A1)** — on an interactive terminal a work item renders the cockpit
  as it runs (conversation per step, popups on real events — e.g. an `error`
  popup when a tool step fails). Auto-on a TTY; `--tui` / `--no-tui` force it.
  Off a TTY (pipes/agents/CI) it falls back to the plain `step N: <tool> [ok|err]`
  stderr lines, byte-for-byte unchanged.
- **Live event stream (A3)** — `--tui-events <path>` appends one `WorkStep` JSONL
  line per step as the work item runs, so an agent can follow it turn-by-turn or
  `tui replay` it. (A stream written into the driven repo is treated as harness
  telemetry — never swept into the work branch.)
- **Replay a real work item (A4)** — `tui replay --trace <id>.trace.jsonl` folds a
  finished work item's loop-step trace into the cockpit (live and replayed steps read
  identically — one shared converter).
- **Interactive cockpit (A2)** — `colleague session` is now cockpit-rendered with
  slash commands; see [Interactive cockpit (session)](#interactive-cockpit-session).

A mid-loop failure still writes a **partial artifact** (`status=error`) with the
steps, usage, and changed files accumulated so far.

See [`docs/features/tui.md`](docs/features/tui.md) for the full surface.

## Telemetry: OpenTelemetry observability

A work item can emit **OpenTelemetry traces + metrics** so it's observable against an
OTLP collector — not just the per-run JSON artifact. Telemetry lives in the
runtime (the loop + the shared work path), so **every backend** emits it
identically, exactly like lifecycle hooks.

It is **off by default** and a strict no-op when off (no spans, no SDK import,
the result artifact unchanged). The OpenTelemetry SDK is an **optional extra** —
the base install keeps zero runtime dependencies:

```bash
pip install 'colleague[otel]'                 # or: uv sync --extra otel
export COLLEAGUE_OTEL_ENABLED=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # OTLP/HTTP collector
uv run colleague work "<task>" --repo . --engine mock --no-pr
#   -> stderr prints "trace: <id>"; the collector receives the spans + metrics
```

Requested without the extra installed, colleague degrades to a no-op with a
one-line stderr notice — it never fails the work item.

**Signals.** Spans: `colleague.work` (root) → `colleague.tool.*` (per tool
call) → `colleague.handoff`. Metrics: `colleague.steps`, `colleague.tokens`,
`colleague.tool.latency`, `colleague.tool.calls`, `colleague.hook.denials`,
`colleague.work.duration`.

**Config** (precedence: explicit > `COLLEAGUE_OTEL_*` > standard `OTEL_*` >
default): `COLLEAGUE_OTEL_ENABLED`, `COLLEAGUE_OTEL_ENDPOINT` /
`OTEL_EXPORTER_OTLP_ENDPOINT`, `COLLEAGUE_OTEL_SERVICE_NAME` /
`OTEL_SERVICE_NAME`. `OTEL_SDK_DISABLED=true` is honored as a kill-switch.

```bash
uv run colleague telemetry status      # resolved config + whether the SDK is installed
uv run colleague telemetry overview    # describe the surface
```

## Work stats & the feedback loop (ROI)

Together these let a caller compute the **ROI of outsourcing** a task: the stats
say what a work item *cost*, a feedback record says how *good* it was.

**Always-on stats.** Every `TaskResult` carries a `stats` block
(`WorkStats`), written into the artifact on **every** work item — no flag, no opt-in.
It records the request, ISO start + wall-clock duration, model turns, step count,
per-tool counts, files changed, exact UTF-8 `bytes_written`, and
reasoning-vs-answer char/byte sizes. Exact token counts stay on `usage`, verbatim
from the model response (never estimated). Like hooks and telemetry, stats are
runtime-owned — identical for `mock` and `vllm-openai`.

> **Honest token limit.** Colleague has no tokenizer (zero deps), and the
> served model reports no reasoning-token breakdown — so "thought vs written" is
> measured as **chars/bytes**, not tokens.

**Feedback.** A single record per work item (re-grading overwrites) lives beside the
artifact at `.colleague/<task_id>.feedback.json`; a per-repo `last_work` pointer
lets you grade the most recent work item without quoting its id. An ungraded work item
reads back as a clean "no feedback yet" state, never an error.

```bash
uv run colleague feedback record last --rating 4 --notes "correct but verbose"
uv run colleague feedback show last --repo .
uv run colleague feedback overview
```

The agent-facing entry is the `ask-colleague feedback` skill verb. See
[`docs/features/stats-and-feedback.md`](docs/features/stats-and-feedback.md).

## Configuration readiness: `doctor`

Before you hand colleague work, `colleague doctor` answers "is this install
actually ready to work?" It is colleague's **read-only**, diagnose-only
**health check** (no `--fix`, zero new runtime deps) that emits a
rubric-shaped `{healthy, checks[]}` report across five ordered check-groups:

| Group | Checks (severity) |
|-------|-------------------|
| **identity** | `prompt_file_present` / `backend_consistency` (error), `skills_present` (warning) |
| **provider** | resolved `base_url`/`model` with redacted `api_key` (info); credentials + budget advisories (warning) on a non-default provider |
| **engines** | backends discovered + both bundled backends present + each plugin loads (error; all-engines rule) |
| **otel** | telemetry enabled / SDK importable / endpoint configured (info; error only when enabled but the `[otel]` extra is missing) |
| **environment** | `.colleague/` config, `hooks.json` validity, command-template parsing, AGENTS/skills layering, `git` (error) + `gh` (warning) on PATH, CLI integrity |

Only a **failed `error`** check flips the report unhealthy; warnings and info are
advisory. `doctor` exits `1` when unhealthy, else `0`. The diagnostic logic lives
in the runtime-level `colleague/oilcheck/` package (like telemetry); the verb
is a thin renderer. Add a check-group by appending a read-only `checks()` callable
to `CHECK_GROUPS` — see `colleague explain doctor` and
[`docs/features/doctor.md`](docs/features/doctor.md).

```bash
uv run colleague doctor          # human-readable rubric; exit 1 if unhealthy
uv run colleague doctor --json   # structured {healthy, checks[]}
uv run colleague doctor --probe  # + a live provider ping (the one networked check)
```

`--probe` adds two opt-in checks that open a network connection — `provider_reachable`
(can colleague reach the endpoint?) and `provider_model_available` (is the
configured model actually served at that endpoint?) — gated behind the flag so the
default `doctor` stays network-free.

## Per-model instructions & skills

Colleague composes a model-specific **system prompt** for every work item from two
layered families, resolved *relative to the model currently driving*. Strict
per-model isolation: driving model X reads only X's overlay plus the shared base
— it never even opens model Y's files (isolation is structural, built from exact
paths, not filtered).

**AGENTS instructions** cascade from the **repo root** (the cross-tool standard
location — sibling agent tools read `AGENTS.md` there too), general → specific,
with a `~/.colleague/` user-level fallback:

```text
AGENTS.md                       # shared base
AGENTS.colleague.md           # colleague overlay
AGENTS.colleague.<model>.md   # model overlay
```

**Skills** are markdown capability docs under `.colleague/`, folded into the
prompt as a compact name + one-line-summary catalog (a skill is instructional
text only — there is no skill *execution* in v0):

```text
.colleague/skills/*.md            # base
.colleague/<model>/skills/*.md    # model overlay (shadows base by stem)
```

`<model>` is sanitized to a filename-safe token (e.g. `Qwen/Qwen3-32B` →
`Qwen-Qwen3-32B`). Inspect what resolves for a model:

```bash
uv run colleague agents list --model Qwen/Qwen3-32B --repo .
uv run colleague skills list --model Qwen/Qwen3-32B --repo .
```

> **MCP layering is not built yet.** Colleague does not read `mcp.json` or
> connect to any MCP server today; a live MCP client needs its own spec. There
> is no `mcp` verb — don't rely on a non-existent surface.

## Subagents

Mid-work, a backend **may** delegate scoped sub-tasks via two loop tools:
`subagent` (a single child) or `subagents` (a batch that runs concurrently). Each
child runs the *same* bounded tool-loop as a nested in-process call, isolated in
its own throwaway git worktree on a `sub/<id>` branch; its result is returned to
the parent and folded into `TaskResult.sub_results` (omitted when empty). A
sequential **merge-subagent** integrates the branches afterward, surfacing (never
force-merging) unresolvable conflicts. An optional `engine`/`model` parameter lets
a child run on a different backend or model, resolved through the existing
`registry.load` + `EngineConfig` inheritance (a config-level switch, no backend
code change).

Concurrency is **opt-in**: `COLLEAGUE_SUBAGENT_CONCURRENCY` (default `1` =
byte-identical sequential behavior); with width > 1, up to
`MIN(width, MAX_SUBAGENT_FANOUT-1)` children run in parallel via
`concurrent.futures` (threads confined to `colleague/subagents.py`), reserving one
slot for the merge child. Delegation is **backend-judged and optional** (like the
`devague` destination tool), never a forced gate. Termination is structural:
`MAX_SUBAGENT_DEPTH=2` (checked before any child work) and `MAX_SUBAGENT_FANOUT=4`
(per-work-item, including the merge child). Only the top-level work item hands off —
sub-drives never branch, commit, or open a PR. This is runtime-owned (the tools
fire identically for every backend) and is explicitly **not** the out-of-scope
multi-backend router / routing policy: there is no automatic task→backend routing.

**Honest limit:** real wall-clock speedup requires the served model to handle
concurrent requests; on a serializing server, gain is bounded by overlapped I/O
wait, not model compute.

```bash
uv run colleague explain subagent   # the loop tool's contract (not a CLI verb)
```

## Ask colleague (a different mind)

`ask-colleague` is colleague's one **first-party** Claude Code skill — the inverse
of the vendored skills. It lets another agent hand a scoped task to colleague: a
*different* backend/model (e.g. a local vLLM Qwen), not a stronger one — **diversity
is the point**. Four verbs over `colleague work`:

| Verb | What it does |
|------|--------------|
| `ask-colleague explore` | Read-only investigation of an area (worktree-isolated). |
| `ask-colleague review` | A diverse second opinion on the committed `<base>...HEAD` diff (the headline verb). |
| `ask-colleague write` | Delegate a small change — previews by default; `--apply` lands a work branch, `--pr` opens a PR. |
| `ask-colleague feedback` | Grade a finished work item (close the ROI loop). |

`explore`/`review` run in a throwaway `git worktree` (no working-tree side effects);
`write` previews in one too unless `--apply`/`--pr`. (Renamed from `outsource`;
"outsource this" still triggers it.) See
[`docs/features/ask-colleague.md`](docs/features/ask-colleague.md).

## Approval gate

The approval gate is an operator-declared allow-list that controls what the
harness **executes** — not just what it discovers. Approval is tamper-protection:
`approve` records the file's current content checksum; if the file changes after
approval, the checksum no longer matches and the approval is void.

### Config shape

```json
{
  "run_command": { "allow": ["git", "pytest", "uv"], "deny": [] },
  "hooks":       { ".colleague/lint.sh": "sha256:<hex>" },
  "commands":    { "fix-lint": "sha256:<hex>" }
}
```

Place this file at `.colleague/approvals.json` in the target repo (or
`~/.colleague/approvals.json` for user-level defaults; repo-level wins). A
per-model overlay at `.colleague/<sanitized-model>/approvals.json` is composed
ahead — per-model keys replace base keys for the same section; no sibling model
is ever read.

### What is gated (and what is not)

| Category | Gated by | Absent section |
|----------|----------|----------------|
| `run_command` | Program token (`shlex` first token): allow/deny lists | No-op (all commands allowed) |
| `hooks` | Content checksum of the referenced hook script file | No-op (all hooks run) |
| `commands` | Content checksum of the template `.md` file (checked at expansion) | No-op (all templates expand) |
| Skills / AGENTS | **Never gated** — declarative, load freely | — |

A section is gated only when it is **present** in `approvals.json`. An absent
section is a strict no-op: byte-identical to behavior before the gate existed.
When a section is present, allow-list semantics apply: anything unlisted,
unapproved, or tampered is denied.

### Approving files

```bash
# Approve a command template by checksum (default: sha256):
uv run colleague commands approve fix-lint --repo .

# Approve a hook script by repo-relative path:
uv run colleague hooks approve .colleague/lint.sh --repo .

# Use md5 instead (drift detection; not recommended for integrity):
uv run colleague commands approve fix-lint --repo . --algo md5

# Both commands support --json for machine-readable output.
```

### Inspecting approval status

```bash
# commands list shows: approved | drifted | unapproved | ungated
uv run colleague commands list --repo .

# hooks list shows approval status per entry + the run_command policy if present
uv run colleague hooks list --repo .

# skills list always shows: accessible (never gated)
uv run colleague skills list --repo .
```

Status values:

| Status | Meaning |
|--------|---------|
| `approved` | Entry present, checksum matches current file content |
| `drifted` | Entry present, but file changed since approval — approval void |
| `unapproved` | Section present but no entry for this name |
| `ungated` | Section absent from `approvals.json` — gate not active |
| `accessible` | Skills / AGENTS — never gated, always accessible |

### Honest limits

> **This is a policy gate, not a sandbox.**

- The `run_command` check inspects the **first shell token** only. It is trivially
  bypassable by `sh -c '...'`, shell pipelines, command substitution, shell
  expansion, or an absolute path to a renamed binary. The gate encodes operator
  **intent**; it does not contain a hostile process. An airtight execution sandbox
  is explicitly out of v0 scope.
- `md5` detects **accidental drift** (file edited by mistake), not a deliberate
  attacker who can recompute a hash. Use `sha256` when integrity matters.
- **Checksum-only in v0.** There is no `version`-based pinning. Approvals are
  recorded and verified by content hash only. Version pinning is a documented
  follow-up that is **not yet built** — do not rely on it.
- This is the landed increment of the tracked "per-repo hook trust gate" from
  the security section below. There is still **no `--no-hooks` flag** — that
  remains a future follow-up.

## ⚠ Security: repo-shipped hooks run by default

> **This is a code-execution risk. Read before driving an untrusted repo.**

When you run `colleague work` (or `colleague session`) against a repo that
contains a `.colleague/hooks.json`, **those hooks execute automatically** with
your operating-system privileges. There is no confirmation prompt and no
sandboxing. Cloning a malicious repository and pointing Colleague at it will
run whatever shell commands that repository's hooks.json specifies.

This behavior is intentional under Colleague's **trusted-operator-env model**
(D2): the same design tradeoff Claude Code and Codex make for their `.claude/`
and `.codex/` hook configs. You are expected to trust (or audit) the repos you
work in.

**What is implemented:** the [approval gate](#approval-gate) lets you gate hook
scripts by checksum — an unapproved or tampered hook script is skipped (not a
hard deny of the tool call; it fires a `skipped` firing in the artifact). The
`run_command` allow/deny list gates which CLI programs the loop may invoke.

**What is NOT yet implemented:** a `--no-hooks` escape hatch or any other
mechanism to disable repo-shipped hooks without editing `.colleague/hooks.json`
yourself. The approval gate is a **policy gate, not a sandbox** — see its honest
limits above. A further hardening increment is tracked but has **not shipped**
in the current version. Do not rely on a non-existent flag.

**Safe practices until the trust gate ships:**

- Only run colleague on repos you own or have audited.
- Review `.colleague/hooks.json` before running `work` in an unfamiliar repo.
- Use user-level (`~/.colleague/hooks.json`) hooks as an allow-list approach
  if you want hooks without trusting any repo's config.

## CLI

| Verb | What it does |
|------|--------------|
| `work <goal>` | Work toward a goal/instruction: work autonomously through a coder backend; write the artifact; hand off. |
| `work --command <name> [args…]` | Expand a saved command template and run it. |
| `commands list` | List discovered command templates for a repo (shows approval status). |
| `commands approve <name>` | Record a checksum approval for a command template. |
| `commands overview` | Describe the commands surface. |
| `hooks list` | List configured hook entries for a repo (shows approval status + run_command policy). |
| `hooks approve <script>` | Record a checksum approval for a hook script file (repo-relative path). |
| `hooks overview` | Describe the hooks surface. |
| `agents list` | List resolved AGENTS instruction layers for a model. |
| `agents overview` | Describe the agents surface. |
| `skills list` | List resolved skill docs for a model. |
| `skills overview` | Describe the skills surface. |
| `telemetry status` | Show the resolved telemetry / OpenTelemetry config + whether the SDK is installed. |
| `telemetry overview` | Describe the telemetry surface. |
| `session` | Open a foreground interactive palette. |
| `backends list` | List discovered backend plugins (the registry; `wheels` is a deprecated alias). |
| `whoami` | Report nick, version, mesh backend, and the live work engine + model (the delegate an `ask-colleague` would actually run). |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Configuration-readiness health check: identity, provider, engines, otel, environment. |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

## Writing your own backend plugin

A backend is a class implementing `colleague.engine.Engine` (one method:
`work(task, config) -> TaskResult`). Advertise it under the entry-point group
and `colleague backends list` discovers it — no change to Colleague core:

```toml
[project.entry-points."colleague.engines"]
my-engine = "my_package.engine:MyEngine"
```

Most backends never re-implement the loop — they delegate to
`colleague.loop.run` and only supply *how the model is called*. Because the
loop owns hook firing, a custom backend inherits the full lifecycle extensibility
layer for free.

## License

MIT — see [`LICENSE`](LICENSE).

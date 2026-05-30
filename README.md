# convertible

```text
                      ,"^,::,:::::I::::::^                             
                     ^!'`       `"^,.    ::`                           
 `,;;i;,,'  .!^'`",. "<,"  "              ;,^                          
 ^       '"^";"^```,":::','"'^`"."'.,:^,i::,"".                        
.I.   '    I-l '",I;!ii,I.,,l;;IlIl:i!:::::,,,^^;",,'                  
 '^ ""::``':.        .`";,"```"^..                  '^^'":,''.         
   ::,`;!"..^..'^"^    .'  ..""   ..`"^                    ..`"`'"".   
    ;;l!i:' ^        '^"`.       `"`..   ',^..                   `` '^ 
     :i>I!lII".        .' .''^`       '`^'    .`".             ^. :;lI.
     ",l!`;"':l;,,`.   .'       '",'.      ^...'^`'"...^l'":;Ii!!l:!';.
      ^''^., '`^^`:l;"^"',!~ .^^^,""..'`^. .^l,I''^.:l!;;;i>|+,!IlI::^ 
                  `;. :>i":` "`, ',^^"     ";  I.'. :::"^:;iil;'":^; '"
                      '^"'"IlI,.:,::;:'  .`;"!l:``,,"``',,,^,,:ll!,,l^ 
                           ":^:,I^:"!;::  :I>l:::"`""::,:I>!<i^ " ;.   
                              ",;"Il;i^:  ',":;"`'`'^,   ><[il```'     
                              " ;;I"l:^.^;^''lI"   :^::",:,'           
                               ,`:;,I.^ ''                             
                                `.   " "                               
```

> Convertible CLI is a swappable coder-agent harness that turns different models
> into repo workers behind one shared task contract.
>
> **One harness, many engines.**

Convertible is the **car around the model**. The model is the engine;
Convertible is the chassis, controls, task contract, and handoff that turn that
engine into a usable repo worker. Point it at a repo task and it drives the work
through whichever coder engine you select — and the caller never has to care
which one ran.

## The metaphor, as architecture

| Part | In Convertible |
|------|----------------|
| **Engine** | the model/coder backend (a local vLLM model, …) |
| **Driver** | the adapter that invokes and controls one engine (`convertible/engines/`) |
| **Chassis** | the shared task contract + lifecycle (`Task` → `TaskResult`) |
| **Tool-loop** | the bounded agentic loop the engine drives the repo through |
| **Wheels** | replaceable engine plugins, discovered via Python entry points |
| **Dashboard** | the JSON result artifact + step trace each run writes |
| **GPS** | opt-in OpenTelemetry traces + metrics (`convertible/telemetry/`) |
| **Handoff** | branch/commit/push + `gh pr create`, gated for offline/CI (`convertible/handoff.py`) |
| **Oilcheck** | `convertible doctor` — read-only configuration-readiness health check (`convertible/oilcheck/`) |
| **Garage** | `convertible wheels list` — the engines installed in this env |
| **Approval gate** | `convertible/policy.py` — operator-declared `.convertible/approvals.json` that controls what the harness executes |

## What ships in v0

- A **shared task contract** — a typed `Task` and `TaskResult` that every engine
  consumes and produces identically.
- A **bounded agentic tool-loop** — the engine calls `read_file`, `write_file`,
  `list_dir`, `run_command`, `culture` (AgentCulture CLIs), and `finish`,
  confined to the target repo, until it finishes or hits the step budget.
- **Two engines**, both registered through the same `convertible.engines`
  entry-point group an out-of-tree wheel would use:
  - `mock` — deterministic and networkless; the CI workhorse.
  - `vllm-openai` — drives any **OpenAI-compatible** `/v1/chat/completions`
    endpoint with tool calling (the reference rig: Qwen3-32B on a vLLM server).
- **Git/PR handoff** — branch → commit → push → `gh pr create`, gated so
  `--no-pr` (or no remote) stays a local commit and CI never pushes.
- A **result artifact** (`.convertible/<task-id>.json`) for handoff back to
  Guildmaster / Taskmaster / Steward.
- **Command templates** — reusable, parameterized task recipes stored under
  `.convertible/commands/*.md`, invoked with `drive --command <name> [args…]`
  or selected in the interactive palette.
- **Lifecycle hooks** — operator-authored shell commands that fire at
  `task_start`, `pre_tool`, `post_tool`, and `finish` events; a `pre_tool` hook
  can allow, deny, or rewrite tool calls before the engine executes them. A
  **per-model hooks overlay** (`.convertible/<model>/hooks.json`) layers
  model-specific fixes **ahead of** the base hooks, giving the operator a
  precision tool for recurring model biases — applied only for the targeted
  model, a strict no-op for all others; no new runtime dep, socket, or daemon.
- **Interactive palette** — `convertible session` opens a foreground command
  browser so operators can select templates and run ad-hoc instructions without
  leaving the shell.
- **Layered per-model config** — AGENTS instructions
  (`AGENTS.md` → `AGENTS.convertible.md` → `AGENTS.convertible.<model>.md`) and
  skills (`.convertible/skills/*.md` → `.convertible/<model>/skills/*.md`)
  compose into a model-specific system prompt, with strict per-model isolation;
  inspect them with `convertible agents list` / `convertible skills list`.
- **GPS: OpenTelemetry observability** — opt-in traces + metrics over OTLP,
  emitted identically by every engine; off by default and a strict no-op, with
  the SDK as an optional `[otel]` extra so the base install stays dep-free.
- **`doctor` (oilcheck)** — a read-only configuration-readiness health check
  across identity, provider, engines, otel-readiness, and environment; emits a
  rubric-shaped report and exits non-zero when unhealthy.
- **Mesh-member integration** — a drive resolves a process-level identity (the
  repo's `culture.yaml` nick or `.convertible/identity.json`) and propagates it
  to subcommands via `CONVERTIBLE_IDENTITY`. The loop exposes one curated
  `culture` tool (allow-list: `agtag`, `devex`) that shells out to the
  operator-installed CLIs with the identity injected. Operators opt into
  read-only ephemeral neighbour clones via `.convertible/neighbours.json`
  (defaults to empty; no new runtime dependency).
- **Destination** — convertible's sibling to GPS. When a task warrants it, an
  engine can set a curated `devague` loop tool to open and converge a goal-frame
  before driving the repo, and declare the announcement on arrival. The
  destination (frame slug + announcement) is recorded in the JSON artifact; the
  curated allow-list excludes `confirm`/`reject` (user-only) and `export`
  (operator-only), and convergence is advisory — only human-confirmed claims are
  authoritative. Setting a destination is optional and engine-judged.
- **Approval gate** — an operator-declared `.convertible/approvals.json` that
  gates what the harness *executes*. Approval is tamper-protection, not just a
  name list: `approve` records a file's content checksum; if the file changes
  later the approval is void. Three categories are gated, each opt-in by presence
  of its section: `run_command` CLIs by program token (allow/deny lists),
  lifecycle hook scripts by checksum, and command templates by checksum. Skills
  and AGENTS instructions load freely — they are never gated. See the
  [Approval gate](#approval-gate) section below for the full config shape and
  usage.
- **Startup banner** — `convertible drive` and `convertible session` greet an
  interactive terminal with an ASCII banner. It's decorative chrome: written to
  stderr, shown only on a TTY, and suppressed under `--json`, so it never
  pollutes the stdout result stream or agent-parsed output.

**Not in v0** (by design): a multi-engine router/policy gearbox, an execution
sandbox, a daemon mode, Codex/Claude/Gemini drivers, a `--no-hooks` escape hatch
(there is no such flag; the approval gate is the landed hook-trust increment —
a policy gate, not a sandbox), and a live MCP runtime (no `mcp.json`, no `mcp`
verb; the curated `culture` tool shells out to operator CLIs — no socket, no MCP
transport). The runtime package has **no third-party dependencies** — the vLLM
driver speaks the OpenAI wire format over the standard library.

## Feature docs

Each shipped feature has a focused page under [`docs/features/`](docs/features/)
— start at the [feature index](docs/features/README.md):

| Feature | Doc |
|---------|-----|
| Drive & the tool-loop | [drive-and-loop.md](docs/features/drive-and-loop.md) |
| Engines & wheels | [engines.md](docs/features/engines.md) |
| Git/PR handoff | [handoff.md](docs/features/handoff.md) |
| Result artifact | [artifact.md](docs/features/artifact.md) |
| Command templates | [command-templates.md](docs/features/command-templates.md) |
| Lifecycle hooks | [hooks.md](docs/features/hooks.md) |
| Interactive palette | [session.md](docs/features/session.md) |
| Layered per-model config | [layered-config.md](docs/features/layered-config.md) |
| GPS: OpenTelemetry | [telemetry.md](docs/features/telemetry.md) |
| `doctor` (oilcheck) | [doctor.md](docs/features/doctor.md) |
| Agent-first CLI | [agent-cli.md](docs/features/agent-cli.md) |
| Mesh-member integration | [mesh-member.md](docs/features/mesh-member.md) |
| Destination | [destination.md](docs/features/destination.md) |
| Per-model configuration | [per-model-configuration.md](docs/features/per-model-configuration.md) |
| Approval gate | [See Approval gate section below](#approval-gate) |
| Outsource (a different mind) | [outsource.md](docs/features/outsource.md) |

The detailed sections below remain the canonical reference; the feature pages add
per-feature source pointers and cross-links.

## Before → after: the extensibility layer

**Before** this layer, `convertible drive` accepted one raw instruction string
and ran the tool-loop with no operator gate and no saved recipes: `run_command`
and `write_file` executed unconditionally, and every task had to be typed from
scratch.

**After**, operators drop files into `.convertible/` and gain three things that
work identically across every engine (the all-engines rule):

1. **Command templates** — author a recipe once, invoke it by name with
   positional arguments; `drive --command <name> [args…]` expands it into the
   same `Task` shape a raw `drive "…"` produces.
2. **Lifecycle hooks** — `pre_tool` hooks can allow, deny (reason fed back to
   the model), or rewrite tool arguments before they execute; `post_tool` hooks
   run formatters or linters after; `task_start` and `finish` hooks bracket the
   whole drive. Every firing is recorded in the result artifact.
3. **Interactive palette** — `convertible session` lists discovered templates,
   accepts a selection (by number or name) plus optional arguments, and runs the
   chosen task through the same drive path, loop, hooks, and artifact — no
   parallel code path.

This extensibility lives in the chassis (`convertible/loop.py`), not in any one
engine, so it binds equally to `mock`, `vllm-openai`, and any future wheel.

## Quickstart

```bash
uv sync
uv run pytest -n auto                          # full suite, no network needed

# Open the interactive harness (the session palette) at a terminal:
uv run convertible

# Discover the engines installed in this environment:
uv run convertible wheels list

# Drive toward a goal with the deterministic mock engine (no model, no network):
uv run convertible drive "add a CONTRIBUTING.md stub" --repo . --engine mock --no-pr
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
want `qwen3_coder`. The engine itself is parser-agnostic — any parser that makes
the server emit OpenAI-format tool calls works.

> **Tip (anecdotal).** With an NVFP4 Qwen3 checkpoint, `qwen3_coder` handled
> tool-argument escaping more reliably than `hermes` in our testing: a `hermes`
> run over-escaped the triple-quotes in a generated docstring (writing `\"\"\"`
> instead of `"""`), producing a `SyntaxError`, where `qwen3_coder` wrote the
> same file cleanly. This is a single observation, not a benchmark — but if a
> parser garbles quote-heavy edits, trying the other one is worth a shot.

Then point Convertible at it (defaults already target `localhost:8001`):

```bash
uv run convertible drive "fix the typo in the README title" \
  --repo /path/to/target/repo \
  --engine vllm-openai \
  --base-url http://localhost:8001/v1 \
  --model Qwen/Qwen3-32B
```

Configuration resolves in the order: explicit flag → `CONVERTIBLE_*` env →
`OPENAI_*` env → default. Because the driver only touches the OpenAI surface,
pointing `--base-url` at any compatible server (llama.cpp, an OpenAI proxy) needs
no code change.

The opt-in live end-to-end test proves this against a real server:

```bash
CONVERTIBLE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

## Command templates

Operators save reusable task recipes as Markdown files under
`.convertible/commands/<name>.md` (repo-level or `~/.convertible/commands/` for
user-level; repo-level shadows user-level by stem).

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
# One-shot via drive:
uv run convertible drive --command fix-lint src/ --repo /path/to/repo --engine mock --no-pr

# List all discovered templates:
uv run convertible commands list --repo .

# Surface overview:
uv run convertible commands overview
```

The `--command` flag and a positional instruction are mutually exclusive; any
tokens after `--command <name>` are passed as template arguments (`$1`, `$2`,
`$ARGUMENTS`).

## Lifecycle hooks

Hooks are operator-authored shell commands registered in
`.convertible/hooks.json` (repo-level or `~/.convertible/hooks.json` for
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
uv run convertible hooks list --repo .
uv run convertible hooks overview
```

## Interactive palette

`convertible session` opens a foreground interactive palette. It lists
discovered command templates, accepts a number, a name, or a free-text
instruction, and runs the selection through the same `drive` path (same `Task`,
loop, hooks, and artifact — no parallel code path):

```bash
uv run convertible session --repo /path/to/repo --engine vllm-openai
```

Running `convertible` with no arguments **at a terminal** opens this same palette
(resolving the engine like `drive`: `--engine` > `CONVERTIBLE_ENGINE` >
`vllm-openai`, never a silent `mock`) — the natural "get in and drive" gesture.
Piped, redirected, or otherwise non-interactive, bare `convertible` prints usage
instead, so scripts and agents keep a discoverable surface.

The session loops until the user enters `q`, `quit`, or an empty line. By
default it is a "talk + iterate" loop: each drive commits locally but does **not**
push or open a PR — pass `--pr` to opt back into push + PR per drive (unlike
`drive`, which opens a PR by default). Other driver flags accepted by `drive`
(`--engine`, `--base-url`, etc.) are also accepted by `session`.

## GPS: OpenTelemetry observability

A drive can emit **OpenTelemetry traces + metrics** so it's observable against an
OTLP collector — not just the per-run JSON artifact. Telemetry lives in the
chassis (the loop + the shared drive path), so **every engine** emits it
identically, exactly like lifecycle hooks.

It is **off by default** and a strict no-op when off (no spans, no SDK import,
the result artifact unchanged). The OpenTelemetry SDK is an **optional extra** —
the base install keeps zero runtime dependencies:

```bash
pip install 'convertible-cli[otel]'                 # or: uv sync --extra otel
export CONVERTIBLE_OTEL_ENABLED=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # OTLP/HTTP collector
uv run convertible drive "<task>" --repo . --engine mock --no-pr
#   -> stderr prints "trace: <id>"; the collector receives the spans + metrics
```

Requested without the extra installed, convertible degrades to a no-op with a
one-line stderr notice — it never fails the drive.

**Signals.** Spans: `convertible.drive` (root) → `convertible.tool.*` (per tool
call) → `convertible.handoff`. Metrics: `convertible.steps`, `convertible.tokens`,
`convertible.tool.latency`, `convertible.tool.calls`, `convertible.hook.denials`,
`convertible.drive.duration`.

**Config** (precedence: explicit > `CONVERTIBLE_OTEL_*` > standard `OTEL_*` >
default): `CONVERTIBLE_OTEL_ENABLED`, `CONVERTIBLE_OTEL_ENDPOINT` /
`OTEL_EXPORTER_OTLP_ENDPOINT`, `CONVERTIBLE_OTEL_SERVICE_NAME` /
`OTEL_SERVICE_NAME`. `OTEL_SDK_DISABLED=true` is honored as a kill-switch.

```bash
uv run convertible telemetry status      # resolved config + whether the SDK is installed
uv run convertible telemetry overview    # describe the surface
```

## Configuration readiness: `doctor` (the oilcheck)

Before you hand convertible work, `convertible doctor` answers "is this install
actually ready to drive?" It is convertible's **oilcheck**: a **read-only**,
diagnose-only health check (no `--fix`, zero new runtime deps) that emits a
rubric-shaped `{healthy, checks[]}` report across five ordered check-groups:

| Group | Checks (severity) |
|-------|-------------------|
| **identity** | `prompt_file_present` / `backend_consistency` (error), `skills_present` (warning) |
| **provider** | resolved `base_url`/`model` with redacted `api_key` (info); credentials + budget advisories (warning) on a non-default provider |
| **engines** | engines discovered + both bundled engines present + each wheel loads (error; all-engines rule) |
| **otel** | telemetry enabled / SDK importable / endpoint configured (info; error only when enabled but the `[otel]` extra is missing) |
| **environment** | `.convertible/` config, `hooks.json` validity, command-template parsing, AGENTS/skills layering, `git` (error) + `gh` (warning) on PATH, CLI integrity |

Only a **failed `error`** check flips the report unhealthy; warnings and info are
advisory. `doctor` exits `1` when unhealthy, else `0`. The diagnostic logic lives
in the chassis-level `convertible/oilcheck/` package (like telemetry); the verb
is a thin renderer. Add a check-group by appending a read-only `checks()` callable
to `CHECK_GROUPS` — see `convertible explain doctor` and
[`docs/features/doctor.md`](docs/features/doctor.md).

```bash
uv run convertible doctor          # human-readable rubric; exit 1 if unhealthy
uv run convertible doctor --json   # structured {healthy, checks[]}
```

## Per-model instructions & skills

Convertible composes a model-specific **system prompt** for every drive from two
layered families, resolved *relative to the model currently driving*. Strict
per-model isolation: driving model X reads only X's overlay plus the shared base
— it never even opens model Y's files (isolation is structural, built from exact
paths, not filtered).

**AGENTS instructions** cascade from the **repo root** (the cross-tool standard
location — sibling agent tools read `AGENTS.md` there too), general → specific,
with a `~/.convertible/` user-level fallback:

```text
AGENTS.md                       # shared base
AGENTS.convertible.md           # convertible overlay
AGENTS.convertible.<model>.md   # model overlay
```

**Skills** are markdown capability docs under `.convertible/`, folded into the
prompt as a compact name + one-line-summary catalog (a skill is instructional
text only — there is no skill *execution* in v0):

```text
.convertible/skills/*.md            # base
.convertible/<model>/skills/*.md    # model overlay (shadows base by stem)
```

`<model>` is sanitized to a filename-safe token (e.g. `Qwen/Qwen3-32B` →
`Qwen-Qwen3-32B`). Inspect what resolves for a model:

```bash
uv run convertible agents list --model Qwen/Qwen3-32B --repo .
uv run convertible skills list --model Qwen/Qwen3-32B --repo .
```

> **MCP layering is not built yet.** Convertible does not read `mcp.json` or
> connect to any MCP server today; a live MCP client needs its own spec. There
> is no `mcp` verb — don't rely on a non-existent surface.

## Approval gate

The approval gate is an operator-declared allow-list that controls what the
harness **executes** — not just what it discovers. Approval is tamper-protection:
`approve` records the file's current content checksum; if the file changes after
approval, the checksum no longer matches and the approval is void.

### Config shape

```json
{
  "run_command": { "allow": ["git", "pytest", "uv"], "deny": [] },
  "hooks":       { ".convertible/lint.sh": "sha256:<hex>" },
  "commands":    { "fix-lint": "sha256:<hex>" }
}
```

Place this file at `.convertible/approvals.json` in the target repo (or
`~/.convertible/approvals.json` for user-level defaults; repo-level wins). A
per-model overlay at `.convertible/<sanitized-model>/approvals.json` is composed
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
uv run convertible commands approve fix-lint --repo .

# Approve a hook script by repo-relative path:
uv run convertible hooks approve .convertible/lint.sh --repo .

# Use md5 instead (drift detection; not recommended for integrity):
uv run convertible commands approve fix-lint --repo . --algo md5

# Both commands support --json for machine-readable output.
```

### Inspecting approval status

```bash
# commands list shows: approved | drifted | unapproved | ungated
uv run convertible commands list --repo .

# hooks list shows approval status per entry + the run_command policy if present
uv run convertible hooks list --repo .

# skills list always shows: accessible (never gated)
uv run convertible skills list --repo .
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

When you run `convertible drive` (or `convertible session`) against a repo that
contains a `.convertible/hooks.json`, **those hooks execute automatically** with
your operating-system privileges. There is no confirmation prompt and no
sandboxing. Cloning a malicious repository and pointing Convertible at it will
run whatever shell commands that repository's hooks.json specifies.

This behavior is intentional under Convertible's **trusted-operator-env model**
(D2): the same design tradeoff Claude Code and Codex make for their `.claude/`
and `.codex/` hook configs. You are expected to trust (or audit) the repos you
drive.

**What is implemented:** the [approval gate](#approval-gate) lets you gate hook
scripts by checksum — an unapproved or tampered hook script is skipped (not a
hard deny of the tool call; it fires a `skipped` firing in the artifact). The
`run_command` allow/deny list gates which CLI programs the loop may invoke.

**What is NOT yet implemented:** a `--no-hooks` escape hatch or any other
mechanism to disable repo-shipped hooks without editing `.convertible/hooks.json`
yourself. The approval gate is a **policy gate, not a sandbox** — see its honest
limits above. A further hardening increment is tracked but has **not shipped**
in the current version. Do not rely on a non-existent flag.

**Safe practices until the trust gate ships:**

- Only drive repos you own or have audited.
- Review `.convertible/hooks.json` before running `drive` in an unfamiliar repo.
- Use user-level (`~/.convertible/hooks.json`) hooks as an allow-list approach
  if you want hooks without trusting any repo's config.

## CLI

| Verb | What it does |
|------|--------------|
| `drive <goal>` | Drive toward a goal/instruction: work autonomously through a coder engine; write the artifact; hand off. |
| `drive --command <name> [args…]` | Expand a saved command template and drive it. |
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
| `telemetry status` | Show the resolved GPS / OpenTelemetry config + whether the SDK is installed. |
| `telemetry overview` | Describe the telemetry surface. |
| `session` | Open a foreground interactive palette. |
| `wheels list` | List discovered engine wheels (the garage). |
| `whoami` | Report this agent's nick, version, backend, and model. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Configuration-readiness health check (convertible's oilcheck): identity, provider, engines, otel, environment. |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

## Writing your own engine wheel

An engine is a class implementing `convertible.engine.Engine` (one method:
`drive(task, config) -> TaskResult`). Advertise it under the entry-point group
and `convertible wheels list` discovers it — no change to Convertible core:

```toml
[project.entry-points."convertible.engines"]
my-engine = "my_package.engine:MyEngine"
```

Most engines never re-implement the loop — they delegate to
`convertible.loop.run` and only supply *how the model is called*. Because the
loop owns hook firing, a custom engine inherits the full lifecycle extensibility
layer for free.

## License

MIT — see [`LICENSE`](LICENSE).

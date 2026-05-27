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
| **Garage** | `convertible wheels list` — the engines installed in this env |

## What ships in v0

- A **shared task contract** — a typed `Task` and `TaskResult` that every engine
  consumes and produces identically.
- A **bounded agentic tool-loop** — the engine calls `read_file`, `write_file`,
  `list_dir`, `run_command`, and `finish`, confined to the target repo, until it
  finishes or hits the step budget.
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
  can allow, deny, or rewrite tool calls before the engine executes them.
- **Interactive palette** — `convertible session` opens a foreground command
  browser so operators can select templates and run ad-hoc instructions without
  leaving the shell.
- **Startup banner** — `convertible drive` and `convertible session` greet an
  interactive terminal with an ASCII banner. It's decorative chrome: written to
  stderr, shown only on a TTY, and suppressed under `--json`, so it never
  pollutes the stdout result stream or agent-parsed output.

**Not in v0** (by design): a multi-engine router/policy gearbox, an execution
sandbox, a daemon mode, and Codex/Claude/Gemini drivers. The runtime package has
**no third-party dependencies** — the vLLM driver speaks the OpenAI wire format
over the standard library.

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
(with the default engine and repo) — the natural "get in and drive" gesture.
Piped, redirected, or otherwise non-interactive, bare `convertible` prints usage
instead, so scripts and agents keep a discoverable surface.

The session loops until the user enters `q`, `quit`, or an empty line. Any
driver flags accepted by `drive` (`--engine`, `--no-pr`, `--base-url`, etc.)
are also accepted by `session`.

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

**What is NOT yet implemented:** a per-repo trust gate, a `--no-hooks` escape
hatch, or any other mechanism to disable repo-shipped hooks without editing the
`.convertible/hooks.json` file yourself. A follow-up hardening increment is
planned and tracked, but it has **not shipped** in the current version. Do not
rely on a non-existent flag.

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
| `commands list` | List discovered command templates for a repo. |
| `commands overview` | Describe the commands surface. |
| `hooks list` | List configured hook entries for a repo. |
| `hooks overview` | Describe the hooks surface. |
| `agents list` | List resolved AGENTS instruction layers for a model. |
| `agents overview` | Describe the agents surface. |
| `skills list` | List resolved skill docs for a model. |
| `skills overview` | Describe the skills surface. |
| `session` | Open a foreground interactive palette. |
| `wheels list` | List discovered engine wheels (the garage). |
| `whoami` | Report this agent's nick, version, backend, and model. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Check the agent-identity invariants. |
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

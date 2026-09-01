# Colleague feature docs

> One runtime, many minds. This directory holds one focused page per shipped
> feature. **New here? Jump to [Start here](#new-to-colleague-start-here).**

Colleague is the harness around the model: the model is the backend, and
colleague is the task runtime, controls, task contract, and handoff that turn
that backend into a usable repo worker. Each feature below is one part of that
runtime. For the narrative overview and quickstart, see the top-level
[`README.md`](../../README.md); for the design specs and plans these features
converged from, see [`docs/specs/`](../specs/) and [`docs/plans/`](../plans/).
Colleague is **v1** (see [`CHANGELOG.md`](../../CHANGELOG.md) for the per-version
history); the hard scope boundary — what is deliberately *not* built — is under
[Scope](#scope-what-is-deliberately-not-built).

## New to colleague? Start here

Read these three first — they cover 80% of day-to-day use:

1. **[work-and-loop.md](work-and-loop.md)** — what a `work` run *is*: the task
   contract and the bounded tool-loop the backend drives the repo through.
2. **[engines.md](engines.md)** — the backends (`mock`, `vllm-openai`) and how
   `--engine` picks one.
3. **[agent-cli.md](agent-cli.md)** — the read-only introspection verbs
   (`whoami`, `learn`, `explain`, `overview`) for finding your way around.

Then, if you want a *different mind* on a task, read
[ask-colleague.md](ask-colleague.md) (the first-party skill) and, to grow
colleague's skills from a peer, [learn-from.md](learn-from.md).

## The features, by area

### Core: running a task

| Feature | Doc | What it is | CLI surface |
|---------|-----|------------|-------------|
| Work & the tool-loop | [work-and-loop.md](work-and-loop.md) | Task runtime + the bounded tool-loop | `work` |
| Adopted harness mechanics | [adopt-from-qwen-code.md](adopt-from-qwen-code.md) | Mechanics ported from Qwen Code / Gemini CLI: clamp, batches, search tools, paging, guards, associate seat; credit in `NOTICE` | `doctor` (`harness_*`), `config show`, knobs |
| Backends & plugins | [engines.md](engines.md) | Backend + adapter + plugin discovery | `backends list`, `--engine` |
| Model & endpoint selection | [model-selection.md](model-selection.md) | Backend config (model + endpoint) | `--model`, `--base-url`, env |
| Per-model sampling + repetition guard | [sampling.md](sampling.md) | The model card's sampling values per effort half, the tracked `.colleague/models.json`, and the verbatim-tail turn guard | `config show`, `COLLEAGUE_SAMPLING` |
| Git/PR handoff | [handoff.md](handoff.md) | Branch/commit/push/PR, gated for offline/CI | `work` (`--no-pr`, `--base`) |
| Write isolation | [write-isolation.md](write-isolation.md) | A work item runs in a throwaway worktree; never touches your working tree | runtime (no verb) |
| Cleanup / reap | [cleanup-reap.md](cleanup-reap.md) | Self-heal a repo a crashed run left wedged | `clean` |
| Result artifact | [artifact.md](artifact.md) | The JSON run report + step trace | written by `work` |

### Front-ends: how you drive it

| Feature | Doc | What it is | CLI surface |
|---------|-----|------------|-------------|
| Agent-first CLI | [agent-cli.md](agent-cli.md) | Self-describing CLI + read-only introspection | `whoami`, `learn`, `explain`, `overview`, `cli` |
| Command templates | [command-templates.md](command-templates.md) | Named, parameterized task recipes | `commands`, `work --command` |
| Interactive palette | [session.md](session.md) | Foreground cockpit/session loop | `session`, bare `colleague` |
| Cockpit views (tui / TAUI) | [tui.md](tui.md) | Headless JSON/ANSI/Markdown views of one state | `tui` |

### Staying within capacity (reliability)

| Feature | Doc | What it is | CLI surface |
|---------|-----|------------|-------------|
| Context budget / graceful degradation | [graceful-degradation.md](graceful-degradation.md) | Window history; degrade on overflow/timeout instead of hard-failing | runtime (no verb) |
| Capacity standard / fill-line | [capacity-standard.md](capacity-standard.md) | Proactive compact \| split \| finish-with-handoff decision before the window fills | runtime (no verb) |
| Auto-split (too-large assignment) | [auto-split.md](auto-split.md) | Recommend splitting an over-large task into child work items | `subagents` loop tool |
| Continue-working / finish | [continue-working.md](continue-working.md) | Resume past a stall; a clean summary survives to the exit | runtime (no verb) |
| Indefinite run / episode chaining | [indefinite-run.md](indefinite-run.md) | Armed chaining past budget-exhausted exits with tree carry + handoff-once; ambient fill-line re-arm + validated compaction | `work`/`session --until-done`, `--max-episodes` |
| Explore never wastes a run | [explore-never-wastes.md](explore-never-wastes.md) | Forced synthesis + honest `incomplete` status on an out-of-steps explore | runtime (no verb) |
| Escalation (agtag continuation) | [escalation.md](escalation.md) | File one tracked agtag issue on abort / step-budget exhaustion | opt-in via `COLLEAGUE_ESCALATE` |

### Configuration & policy

| Feature | Doc | What it is | CLI surface |
|---------|-----|------------|-------------|
| Config resolution | [config-resolution.md](config-resolution.md) | Endpoint/model/config-dir precedence; `.colleague/config.json` | `config show` |
| Layered per-model config | [layered-config.md](layered-config.md) | AGENTS + skills compose into a per-model system prompt | `agents`, `skills` |
| Per-model configuration | [per-model-configuration.md](per-model-configuration.md) | Per-model hooks overlay (`.colleague/<model>/hooks.json`) | `hooks list --model` |
| Lifecycle hooks | [hooks.md](hooks.md) | Operator shell commands at task/tool lifecycle events | `hooks` |
| Approval gate | [approval-gate.md](approval-gate.md) | Allow-list what the harness executes (`run_command` token, hook/command checksum) | `hooks approve`, `commands approve` |
| Learn skills from a peer | [learn-from.md](learn-from.md) | Absorb another agent's skills into `.colleague/skills/` | `learn-from <source>` |

### Observability & ROI

| Feature | Doc | What it is | CLI surface |
|---------|-----|------------|-------------|
| Telemetry: OpenTelemetry | [telemetry.md](telemetry.md) | Opt-in OTLP traces + metrics, identical per backend | `telemetry` |
| Work stats & feedback (ROI) | [stats-and-feedback.md](stats-and-feedback.md) | Always-on per-run stats + the feedback ROI loop | always-on in the artifact; `feedback` |
| `doctor` (health check) | [doctor.md](doctor.md) | Read-only configuration-readiness check | `doctor` |

### Delegation: more minds on the work

| Feature | Doc | What it is | CLI surface |
|---------|-----|------------|-------------|
| Subagents | [subagents.md](subagents.md) | Nested in-process child work items (worktree-isolated) | `subagent` loop tool |
| Parallel subagents | [parallel-subagents.md](parallel-subagents.md) | A concurrent batch of children + a merge child | `subagents` loop tool |
| Audit fan-out | [audit-fanout.md](audit-fanout.md) | Operator-driven audit fan-out (assign-to-workforce) | `work --command` (per-surface) |
| Ask colleague (a different mind) | [ask-colleague.md](ask-colleague.md) | First-party skill: hand a task to a *different* backend | `ask-colleague` skill (runs `work`) |

### Mesh membership & direction

| Feature | Doc | What it is | CLI surface |
|---------|-----|------------|-------------|
| Mesh-member integration | [mesh-member.md](mesh-member.md) | Process identity + the curated `culture` tool + neighbours | `culture` loop tool |
| Resident promote (Culture member) | [resident-promote.md](resident-promote.md) | Graduate colleague into a long-lived Culture mesh peer | `promote` (`[culture]` extra) |
| Destination | [destination.md](destination.md) | Set + converge a `devague` goal-frame, declare arrival | `devague` loop tool |

## How the features fit together

A single `work` call exercises most of the runtime at once:

1. **Backends & plugins** resolve `--engine <name>` to an adapter via the
   `colleague.engines` entry-point group.
2. **Layered per-model config** composes a model-specific system prompt
   (AGENTS + skills) on the `Engine` base class; **per-model configuration**
   additionally layers a per-model hooks overlay ahead of the base hooks.
3. **Work & the tool-loop** runs the bounded agentic loop, where every tool
   call fires **lifecycle hooks** and emits **telemetry**, and the
   **context-budget** machinery keeps the running history within the model's window.
4. **Command templates** (and the **interactive palette**) are alternative
   front-ends that build the same `Task` and run the same loop.
5. **Git/PR handoff** captures the working-tree changes as a branch/commit/PR.
6. The **result artifact** records the whole run as JSON + a step trace, with the
   always-on **stats** block the **feedback** loop grades.
7. **`doctor`** and the **agent-first CLI** are read-only introspection over all
   of the above — they never run a task.

The unifying invariant is the **all-engines rule**: any behavior that belongs to
the contract (the loop, hooks, telemetry, the artifact, layered config) lives in
the runtime, so it binds *every* backend identically. `mock` is the reference
backend; if a change makes `mock` and `vllm-openai` diverge in result shape, that
is a bug.

## Scope: what is deliberately *not* built

The following are **not** built and require a re-spec before they land — don't
document them as if they exist:

- A multi-backend **router** / routing policy (no automatic task→backend routing).
- An execution **sandbox** (`run_command` trusts the operator, model D2; the
  approval gate is a *policy* gate, not a sandbox).
- A **daemon/server** mode (the palette is a foreground TTY loop, no daemon).
- **Codex / Claude / Gemini** adapters (the two bundled backends are `mock` and
  `vllm-openai`).
- A `--no-hooks` flag (the approval gate is the landed hook-trust increment; the
  flag itself does not exist today).
- A live **MCP** runtime — colleague reads no `mcp.json` and has no `mcp` verb.

See the top-level [`CLAUDE.md`](../../CLAUDE.md) for the authoritative scope
statement, including the v0→v1 graduation (the capacity standard, #156).

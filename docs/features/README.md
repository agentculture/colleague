# Colleague feature docs

> One runtime, many minds. This directory holds one doc per shipped feature —
> the **list of features** below, each linking to a focused page.

Colleague is the harness around the model: the model is the backend, and
colleague is the task runtime, controls, task contract, and handoff that turn
that backend into a usable repo worker. Each feature is one part of that runtime.
For the narrative overview and quickstart, see the top-level
[`README.md`](../../README.md); for the design specs and plans these features
converged from, see [`docs/specs/`](../specs/) and [`docs/plans/`](../plans/).

All features below ship in **v0** (see [`pyproject.toml`](../../pyproject.toml) /
[`CHANGELOG.md`](../../CHANGELOG.md) for the current release). The hard v0
boundary — what is deliberately *not* built — is restated under
[Scope](#scope-the-v0-line).

## The features

| Feature | Doc | Role | CLI surface |
|---------|-----|------|-------------|
| Drive & the tool-loop | [drive-and-loop.md](drive-and-loop.md) | Task runtime + tool loop | `drive` |
| Backends & plugins | [engines.md](engines.md) | Backend + adapter + plugins | `backends list`, `--engine` |
| Model & endpoint selection | [model-selection.md](model-selection.md) | Backend config (model + endpoint) | `--model`, `--base-url`, env |
| Git/PR handoff | [handoff.md](handoff.md) | Handoff | `drive` (`--no-pr`, `--base`) |
| Result artifact | [artifact.md](artifact.md) | Run report | written by `drive` |
| Command templates | [command-templates.md](command-templates.md) | Command templates | `commands`, `drive --command` |
| Lifecycle hooks | [hooks.md](hooks.md) | Hooks | `hooks` |
| Interactive palette | [session.md](session.md) | Interactive palette | `session`, bare `colleague` |
| Layered per-model config | [layered-config.md](layered-config.md) | Config resolution | `agents`, `skills` |
| Telemetry: OpenTelemetry | [telemetry.md](telemetry.md) | Telemetry | `telemetry` |
| `doctor` (health check) | [doctor.md](doctor.md) | Doctor / health check | `doctor` |
| Agent-first CLI | [agent-cli.md](agent-cli.md) | Controls / run report | `whoami`, `learn`, `explain`, `overview`, `cli` |
| Mesh-member integration | [mesh-member.md](mesh-member.md) | Runtime (identity + culture tool + neighbours) | `culture` loop tool |
| Destination | [destination.md](destination.md) | Destination (goal-frame + arrival) | `devague` loop tool |
| Subagents | [subagents.md](subagents.md) | Subagents (nested in-process child drives) | `subagent` loop tool (mid-drive) |
| Audit fan-out | [audit-fanout.md](audit-fanout.md) | Operator-driven audit fan-out (assign-to-workforce) | `drive --command` (per-surface) |
| Per-model configuration | [per-model-configuration.md](per-model-configuration.md) | Runtime (per-model hooks overlay) | `hooks list --model` |
| Ask colleague (a different mind) | [ask-colleague.md](ask-colleague.md) | A first-party skill that hands a task to a different mind | `ask-colleague` skill (drives `drive`) |
| Drive stats & feedback (ROI) | [stats-and-feedback.md](stats-and-feedback.md) | Run report (stats) + Feedback (the ROI loop) | always-on in the artifact; `feedback`, `ask-colleague feedback` |
| Escalation (agtag continuation) | [escalation.md](escalation.md) | Runtime finalize hook — files one tracked agtag continuation issue on abort or step-budget exhaustion | opt-in via `COLLEAGUE_ESCALATE`; no CLI verb |

## How the features fit together

A single `drive` call exercises most of the runtime at once:

1. **Backends & plugins** resolve `--engine <name>` to an adapter via the
   `colleague.engines` entry-point group.
2. **Layered per-model config** composes a model-specific system prompt
   (AGENTS + skills) on the `Engine` base class; **per-model configuration**
   additionally layers a per-model hooks overlay ahead of the base hooks.
3. **Drive & the tool-loop** runs the bounded agentic loop, where every tool
   call fires **lifecycle hooks** and emits **telemetry**.
4. **Command templates** (and the **interactive palette**) are alternative
   front-ends that build the same `Task` and run the same loop.
5. **Git/PR handoff** captures the working-tree changes as a branch/commit/PR.
6. The **result artifact** records the whole run as JSON + a step trace.
7. **`doctor`** and the **agent-first CLI** are read-only introspection over all
   of the above — they never drive a task.

The unifying invariant is the **all-engines rule**: any behavior that belongs to
the contract (the loop, hooks, telemetry, the artifact, layered config) lives in
the runtime, so it binds *every* backend identically. `mock` is the reference
backend; if a change makes `mock` and `vllm-openai` diverge in result shape, that
is a bug.

## Scope: the v0 line

These features are the *whole* of v0. The following are deliberately **not**
built and require a re-spec before they land — don't document them as if they
exist:

- A multi-backend router / routing policy.
- An execution **sandbox** (`run_command` trusts the operator, model D2).
- A **daemon/server** mode (the palette is a foreground TTY loop, no daemon).
- **Codex / Claude / Gemini** adapters.
- A per-repo **hook trust gate** / `--no-hooks` flag (planned hardening; the
  flag does not exist today).
- A live **MCP** runtime — colleague reads no `mcp.json` and has no `mcp` verb.

See the top-level [`CLAUDE.md`](../../CLAUDE.md) for the authoritative scope
statement.

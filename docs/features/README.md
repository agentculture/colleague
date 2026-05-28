# Convertible feature docs

> One harness, many engines. This directory holds one doc per shipped feature —
> the **list of features** below, each linking to a focused page.

Convertible is the **car around the model**: the model is the engine, and
convertible is the chassis, controls, task contract, and handoff that turn that
engine into a usable repo worker. Each feature is one part of that car. For the
narrative overview and quickstart, see the top-level [`README.md`](../../README.md);
for the design specs and plans these features converged from, see
[`docs/specs/`](../specs/) and [`docs/plans/`](../plans/).

All features below ship in **v0** (currently `0.8.0`). The hard v0 boundary —
what is deliberately *not* built — is restated under [Scope](#scope-the-v0-line).

## The features

| Feature | Doc | Car part | CLI surface |
|---------|-----|----------|-------------|
| Drive & the tool-loop | [drive-and-loop.md](drive-and-loop.md) | Chassis + Tool-loop | `drive` |
| Engines & wheels | [engines.md](engines.md) | Engine + Driver + Wheels | `wheels list`, `--engine` |
| Git/PR handoff | [handoff.md](handoff.md) | Handoff | `drive` (`--no-pr`, `--base`) |
| Result artifact | [artifact.md](artifact.md) | Dashboard | written by `drive` |
| Command templates | [command-templates.md](command-templates.md) | Command templates | `commands`, `drive --command` |
| Lifecycle hooks | [hooks.md](hooks.md) | Hooks | `hooks` |
| Interactive palette | [session.md](session.md) | Interactive palette | `session`, bare `convertible` |
| Layered per-model config | [layered-config.md](layered-config.md) | Config resolution | `agents`, `skills` |
| GPS: OpenTelemetry | [telemetry.md](telemetry.md) | GPS | `telemetry` |
| `doctor` (oilcheck) | [doctor.md](doctor.md) | Oilcheck | `doctor` |
| Agent-first CLI | [agent-cli.md](agent-cli.md) | Controls/dashboard | `whoami`, `learn`, `explain`, `overview`, `cli` |

## How the features fit together

A single `drive` call exercises most of the car at once:

1. **Engines & wheels** resolve `--engine <name>` to a driver via the
   `convertible.engines` entry-point group.
2. **Layered per-model config** composes a model-specific system prompt
   (AGENTS + skills) on the `Engine` base class.
3. **Drive & the tool-loop** runs the bounded agentic loop, where every tool
   call fires **lifecycle hooks** and emits **GPS** telemetry.
4. **Command templates** (and the **interactive palette**) are alternative
   front-ends that build the same `Task` and run the same loop.
5. **Git/PR handoff** captures the working-tree changes as a branch/commit/PR.
6. The **result artifact** records the whole run as JSON + a step trace.
7. **`doctor`** and the **agent-first CLI** are read-only introspection over all
   of the above — they never drive a task.

The unifying invariant is the **all-engines rule**: any behavior that belongs to
the contract (the loop, hooks, telemetry, the artifact, layered config) lives in
the chassis, so it binds *every* engine identically. `mock` is the reference
engine; if a change makes `mock` and `vllm-openai` diverge in result shape, that
is a bug.

## Scope: the v0 line

These features are the *whole* of v0. The following are deliberately **not**
built and require a re-spec before they land — don't document them as if they
exist:

- A multi-engine router/policy **gearbox**.
- An execution **sandbox** (`run_command` trusts the operator, model D2).
- A **daemon/server** mode (the palette is a foreground TTY loop, no daemon).
- **Codex / Claude / Gemini** drivers.
- A per-repo **hook trust gate** / `--no-hooks` flag (planned hardening; the
  flag does not exist today).
- A live **MCP** runtime — convertible reads no `mcp.json` and has no `mcp` verb.

See the top-level [`CLAUDE.md`](../../CLAUDE.md) for the authoritative scope
statement.

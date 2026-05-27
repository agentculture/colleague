# Convertible gains an extensibility layer like Claude Code and Codex: reusable custom commands (named, parameterized task templates discovered from the repo/user config) plus hooks (operator-configured shell commands that fire at tool-loop lifecycle events — task start, pre-tool-call, post-tool-call, finish — and can gate, deny, or augment a tool call), both layered on the shared chassis so they fire identically for every engine.

> Convertible gains an extensibility layer like Claude Code and Codex: reusable custom commands (named, parameterized task templates discovered from the repo/user config) plus hooks (operator-configured shell commands that fire at tool-loop lifecycle events — task start, pre-tool-call, post-tool-call, finish — and can gate, deny, or augment a tool call), both layered on the shared chassis so they fire identically for every engine.

## Audience

- Convertible operators who drive repos with models and want a safety/policy gate plus reusable task recipes, and engine-wheel developers who need lifecycle behavior to live in the chassis (not per-engine).

## Before → After

- Before: Today 'convertible drive' takes one raw instruction string and runs the tool-loop with no operator-authored gate: run_command/write_file execute whatever the model emits (D2 trusts the operator env), and every task must be retyped from scratch — there is no way to deny a tool call by policy or save a reusable recipe.
- After: An operator drops command templates and a hooks config under .convertible/; they can run 'convertible drive --command <name> [args]' (one-shot) OR open an interactive palette session that browses/selects discovered commands and accepts ad-hoc tasks. During every loop, hooks fire at task-start / pre-tool / post-tool / finish: a pre-tool hook can ALLOW, DENY (reason fed back to the model), or REWRITE the tool arguments in-flight; a post-tool hook runs formatters/linters; repo-shipped hooks run by default. Every hook firing and the originating command are recorded in the result artifact.

## Why it matters

- Running models against repos needs an operator-owned gate (the parked sandbox is still deferred; hooks are deterministic policy, not isolation) and recurring repo chores need reusable recipes — both are exactly the extensibility Claude Code and Codex ship, and putting them in the chassis means they bind every engine under the all-engines rule.

## Requirements

- R1 Commands: named task templates discovered from convertible config (repo-level and user-level), each a file with optional metadata (description, engine, constraints, arg-hint) and a body that becomes the instruction with positional/$ARGUMENTS substitution; 'convertible drive --command <name> [args...]' expands it into the same Task the contract already defines.
  - honesty: A command template round-trips into a Task: 'drive --command <name> args' produces the identical Task shape (id/repo/instruction/context/constraints/engine) that a raw 'drive "..."' produces, with args substituted, and runs unchanged on both engines.
- R4 Lifecycle integration in the chassis: the events fire inside convertible/loop.py (and the drive boundary) so they apply to every engine identically; the mock engine is the reference and a hook firing on mock vs vllm-openai must be indistinguishable in the result shape (all-engines rule; guarded by the e2e shape test).
  - honesty: The same hook config produces the same firings and same artifact entries whether --engine is mock or vllm-openai; the e2e shape test asserts a hook-driven run is identically shaped across both engines.
- R5 Dashboard honesty: the result artifact records every hook firing (event, matched command, decision, exit code) and which command template (if any) produced the Task, so the JSON dashboard stays a faithful trace; a denied tool call appears as a non-ok step with the hook's reason.
  - honesty: Every hook firing and the originating command appear in the result artifact JSON (valid, with event/command/decision fields), and a denied tool call is recorded as a non-ok step carrying the hook's reason.
- R6 Agent-first CLI surface: new verbs 'convertible commands list/overview' and 'convertible hooks list/overview' follow the conventions (register(sub), --json, noun-groups expose overview, an explain catalog entry each) and pass 'teken cli doctor . --strict'.
  - honesty: 'convertible commands list --json' and 'convertible hooks list --json' emit structured output, the noun groups expose 'overview', each has an explain entry, and 'teken cli doctor . --strict' passes.
- R7 Zero runtime deps preserved: command/hook discovery, config parsing, and hook execution use only the stdlib (subprocess, json, and a config format with a stdlib reader) — pyproject 'dependencies' stays [].
  - honesty: After the feature, 'pip show convertible-cli' / pyproject shows dependencies = [] and the test suite runs with no third-party runtime import added.
- R2 Hooks (revised): a hooks config maps lifecycle events (task-start, pre-tool, post-tool, finish) to matcher+command entries; a matching event runs the operator's shell command. A pre-tool hook returns one of ALLOW (run as-is), DENY (skip the tool; feed the reason back to the model as the tool result), or REWRITE (run with hook-supplied replacement arguments). Post-tool hooks observe and run side-effects (formatters/linters); task-start/finish bracket the drive.
  - honesty: A pre-tool hook proves all three outcomes: a deny-hook on run_command stops the command and the model receives the reason; a rewrite-hook on write_file changes the path/content actually written; an allow-hook is a no-op — each observable in the artifact and identical on mock and vllm-openai.
- R3 Hook I/O contract (revised): a hook receives a JSON event payload on stdin (event, tool, arguments, task id, repo path); it signals outcome by exit code (0=allow, non-zero=deny with stderr fed back to the model) PLUS optional structured JSON stdout carrying decision (allow|deny|rewrite), replacement arguments (for rewrite), and additionalContext — mirroring Claude Code's hook protocol. The contract is identical across all events.
  - honesty: The hook reads the documented JSON payload on stdin and the loop honors exit code AND structured stdout: exit!=0 denies with stderr fed back; stdout {decision:'rewrite', arguments:{...}} replaces the tool arguments; the same payload schema is sent for every event.
- R8 Interactive palette: a foreground session verb (e.g. 'convertible session') opens an interactive palette that lists discovered commands, takes a selection + args (or an ad-hoc instruction), and runs it through the chassis. It is a front-end over 'drive' — identical Task, loop, hooks, and artifact — never a parallel code path, and adds no engine-specific behavior.
  - honesty: Running a command via the interactive palette yields a TaskResult + artifact byte-identical in shape to 'drive --command <name>'; the palette imports and calls the same drive path (no duplicated loop), proven by a test that drives one command both ways and asserts identical result shape.

## Honesty conditions

- One drive run on each engine exercises both halves: a saved command template expands into a Task AND a configured hook fires during that run's loop, with both visible in the result artifact — demonstrating commands+hooks on the shared chassis.
- A concrete operator can name a recurring task they'd save as a command and a tool call they'd want gated by a hook; the engine-wheel-developer benefit holds because lifecycle behavior lives in the chassis, not in each wheel.
- On main today, 'convertible drive' exposes no command-template flag and no hook config, and run_command/write_file execute unconditionally — verifiable by inspecting drive.py / loop.py / tools.py.
- The operator gate and reusable recipes cannot be had with today's convertible without editing source; Claude Code and Codex both ship exactly these two mechanisms, confirming the need is real.
- A single test/demo runs the same command + hook config on mock and vllm-openai and asserts identical result shape, a working pre-tool deny, and an observable post-tool effect.
- After the feature the described flow works end-to-end: a command file expands into a Task, a configured hook fires mid-loop, and both appear in the artifact — on both engines, with no per-engine code.
- No code path opens a socket, forks a daemon, or imports a command file as Python; hooks are only ever executed as subprocesses and the palette runs in the foreground — verifiable by review.

## Success signals

- On both mock and vllm-openai engines: a saved command expands into the same Task shape, a pre-tool deny-hook blocks a run_command and the artifact records the denial + the model's continuation, and a post-tool hook's effect is observable — proving the lifecycle is chassis-level and engine-agnostic.

## Scope / boundaries

- NOT a sandbox / resource-isolation layer (D2's trusted-operator-env model is unchanged; hooks are operator-authored policy gates, not confinement). NOT a long-running daemon/server or networked control plane (the interactive palette is a FOREGROUND TTY session, not a background service). NOT a plugin marketplace or MCP transport. Commands are Task templates, not arbitrary importable code.

## Non-goals

- Out of scope: MCP server hooks, a plugin marketplace, networked/remote hook transport, and a background daemon. The interactive palette IS in scope (per the scope decision); only non-foreground and networked machinery is excluded.

## Assumptions

- Operators author their own command templates and hook scripts; Convertible discovers and runs them but never generates or fetches them.

## Decisions

- D-config: commands and hooks live under a '.convertible/' config dir — commands as individual template files, hooks as a single JSON settings file (JSON keeps the zero-dep rule with a stdlib reader); both resolve repo-level then user-level, mirroring Claude Code's .claude/ layout.
- D-scope (RESOLVED): hooks + commands + an interactive palette mode are folded INTO the v0 line (re-spec), not deferred to a later increment. This widens D1's 'CLI-first; REPL/daemon reserved' stance to admit an interactive FOREGROUND palette session (still no daemon/server), and widens the v0 boundary accordingly.
- D-interactive (RESOLVED): convertible gains an interactive foreground session (palette) in ADDITION to one-shot 'drive'; both are thin front-ends over the same chassis (Task contract + loop + hooks + artifact). The palette adds no engine-specific behavior. This is the one change that revises convertible's documented non-interactive identity.
- D-trust (RESOLVED): repo-shipped '.convertible/' hooks RUN BY DEFAULT on 'convertible drive', under D2's trusted-operator-env model — the user accepted the code-execution tradeoff for Claude/Codex-like ergonomics. A per-repo trust gate / escape hatch is a tracked follow-up, not a v0 blocker.

## Hard questions

- If repo-local '.convertible/' hooks auto-run on 'convertible drive', a malicious target repo gets arbitrary code execution on the operator's machine. Do repo-shipped hooks run by default, require an explicit opt-in/trust step, or are only user-level hooks honored in this increment?
- risk: Auto-running repo-shipped hooks is a code-execution vector against the operator; mitigations (trust gate, --enable-hooks flag, user-level only) trade safety against the 'just works' ergonomics Claude/Codex offer.
- risk: The interactive palette reverses convertible's documented non-interactive, agent-first identity (CLAUDE.md: results-to-stdout, one-shot; D1 reserved REPL). Widening v0 here risks scope sprawl and a second interaction model to maintain; mitigated by making the palette a thin front-end over the same chassis with no parallel code path.
- risk: Repo-shipped hooks running by default is a code-execution vector: cloning + driving a malicious repo executes its hooks with operator privileges. Accepted under D2 for ergonomics; the follow-up trust gate / --no-hooks escape hatch is the mitigation and must be documented loudly.

## Open / follow-up

- Follow-up hardening: an optional per-repo trust gate / --no-hooks escape hatch for repo-shipped hooks. DECIDED this increment: repo hooks run by default (see D-trust c25).
- Whether a finish-event hook may requeue/continue the loop (re-drive) or only observe + optionally fail the run; this increment likely observe-only

# Build Plan — Convertible gains an extensibility layer like Claude Code and Codex: reusable custom commands (named, parameterized task templates discovered from the repo/user config) plus hooks (operator-configured shell commands that fire at tool-loop lifecycle events — task start, pre-tool-call, post-tool-call, finish — and can gate, deny, or augment a tool call), both layered on the shared chassis so they fire identically for every engine.

slug: `convertible-gains-an-extensibility-layer-like-clau` · status: `exported` · from frame: `convertible-gains-an-extensibility-layer-like-clau`

> Convertible gains an extensibility layer like Claude Code and Codex: reusable custom commands (named, parameterized task templates discovered from the repo/user config) plus hooks (operator-configured shell commands that fire at tool-loop lifecycle events — task start, pre-tool-call, post-tool-call, finish — and can gate, deny, or augment a tool call), both layered on the shared chassis so they fire identically for every engine.

## Tasks

### t1 — Config-dir resolution: a .convertible/ loader (repo-level then user-level)

- acceptance:
  - load_config_dirs() returns repo then user .convertible/ in precedence order; a fixture with both present asserts repo entries shadow user entries
  - an absent .convertible/ returns no entries and never raises

### t2 — Contract+artifact: record hook firings and the originating command

- covers: c12, h5
- acceptance:
  - TaskResult gains a hook_firings list and records the originating command; to_dict/from_dict round-trips the new fields (extends the existing round-trip test)
  - a denied tool call serializes as a non-ok Step carrying the hook reason and the artifact JSON validates with the new fields present

### t3 — Command templates: discover under .convertible/commands and expand into a Task

- depends on: t1
- covers: c8, h1
- acceptance:
  - discover_commands() finds template files under .convertible/commands; a fixture command expands with positional/$ARGUMENTS substitution
  - expand_command(name,args) yields a Task whose shape (id/repo/instruction/context/constraints/engine) matches Task.new(...), proven by a field-by-field test

### t4 — Hook config + runner: load hooks JSON, match events, run the I/O contract

- depends on: t1
- covers: c26, c27, h10
- acceptance:
  - load_hooks() parses the .convertible hooks JSON into event->matcher->command entries and selects the right hook by tool-name match
  - run_hook() sends the documented JSON payload on stdin and maps outcome: exit!=0 -> deny(reason=stderr); stdout {decision:rewrite,arguments} -> rewrite; else allow — table-driven tests with stub hook scripts cover all three

### t5 — Lifecycle integration in loop.py: fire task-start/pre-tool/post-tool/finish

- depends on: t2, t4
- covers: c11, h4, h9
- acceptance:
  - the loop fires pre-tool/post-tool hooks around executor.execute and brackets the run with task-start/finish; a deny-hook on run_command prevents execution and feeds the reason back as the tool result so the model continues
  - a rewrite-hook on write_file changes the path/content actually written, an allow-hook is a no-op, and each firing is recorded in TaskResult.hook_firings identically for mock and a stub engine

### t6 — Agent-first CLI surface: commands/hooks noun groups + drive --command + explain

- depends on: t3, t4
- covers: c13, h6
- acceptance:
  - convertible commands list --json and hooks list --json emit structured output, both noun groups expose overview, and drive --command <name> [args] expands a template into the Task
  - the explain catalog has entries for commands/hooks/session and 'teken cli doctor . --strict' passes

### t7 — Interactive palette: a foreground 'session' verb over the drive path

- depends on: t6, t3
- covers: c28, h11
- acceptance:
  - convertible session opens a foreground palette listing discovered commands; selecting one runs it through the same drive path with no duplicated loop
  - a test drives one command via the palette and via drive --command and asserts identical TaskResult shape

### t8 — Zero-runtime-deps guard test

- depends on: t3, t4
- covers: c14, h7
- acceptance:
  - a test asserts pyproject [project].dependencies == [] and that importing convertible.commands / convertible.hooks introduces no third-party top-level import

### t9 — Boundary guard test: subprocess-only hooks, no socket/daemon, no import-as-Python

- depends on: t4, t5, t7
- covers: c21, h17
- acceptance:
  - a test asserts hooks are executed only via subprocess (hook files are never imported as Python), command files are read as text not imported, and no code path opens a socket or forks a daemon

### t10 — Docs: commands/hooks/palette + before-after + loud repo-hooks-by-default trust warning

- depends on: t6, t7
- covers: c2, c3, c5, h12, h13, h14
- acceptance:
  - README + CLAUDE.md document commands, hooks, and the palette, the before->after, and the rationale; repo-hooks-run-by-default is documented prominently with the --no-hooks / trust-gate follow-up
  - doc examples match the shipped CLI surface (verified against commands/hooks/session --help)

### t11 — Capstone cross-engine e2e: same command+hook config, identical result shape on both engines

- depends on: t5, t6, t7
- covers: c1, c7, c20, h8, h15, h16
- acceptance:
  - an e2e test runs the same command + hook config on mock and a second engine path and asserts identical result shape, a working pre-tool deny, and an observable post-tool effect
  - the test exercises the full after-state flow: a command file expands into a Task, a hook fires mid-loop, and both appear in the result artifact

## Risks

- [follow_up] Per-repo trust gate / --no-hooks escape hatch for repo-shipped hooks (which run by default) — carried from the spec as hardening
- [unknown_nonblocking] cli/__init__.py and explain/catalog.py are shared edit points for every new verb; t7 (palette) depends on t6 (CLI surface) specifically so they never land in the same wave and collide at merge (task t7)
- [follow_up] finish-event hook requeueing the loop (re-drive) is out of scope this increment; hooks observe + may fail the run only (task t5)

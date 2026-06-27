# Build Plan — Colleague's agent-first CLI is rendered from an imported agentfront App registry instead of hand-maintained scaffolding — and because the operations live in that one registry, colleague also gets an MCP server (a bonus for platforms like Cowork) for free

slug: `colleague-s-agent-first-cli-is-rendered-from-an-im` · status: `exported` · from frame: `colleague-s-agent-first-cli-is-rendered-from-an-im`

> Colleague's agent-first CLI is rendered from an imported agentfront App registry instead of hand-maintained scaffolding — and because the operations live in that one registry, colleague also gets an MCP server (a bonus for platforms like Cowork) for free

## Tasks

### t1 — Packaging: agentfront>=0.14.0 as the one base runtime dep + a colleague[mcp] extra + zero-deps guard update

- covers: c6, h6, c7, h7, c10, h10
- acceptance:
  - pyproject.toml declares agentfront>=0.14.0 as the sole base runtime dependency and a [mcp] extra pinning mcp>=1.28.0; a base 'uv pip install colleague' resolves exactly agentfront with zero third-party transitive deps
  - tests/test_zero_deps.py allow-lists exactly agentfront on the base import path and asserts the mcp SDK is absent unless the [mcp] extra is installed (still fails on any stray third-party dep)

### t2 — App assembly: build_app() renders colleague's CLI from one agentfront App via auto-discovered register_into(app) hooks; bridge CliError<->AgentfrontError and the stdout/stderr output split; wire the no-command handler (TTY->session vs help)

- depends on: t1
- covers: c1, h1, c3, h3
- acceptance:
  - colleague/cli/_app.py exposes build_app() that iterates the colleague/cli/_commands package and calls each module's register_into(app) (auto-discovery, no per-verb edit to _app.py); main() dispatches via agentfront's run_cli with no hand-rolled argparse dispatch on the core path
  - a handler raising colleague's CliError surfaces as a structured {code,message,remediation} on stderr with non-zero exit and clean stdout via agentfront's dispatch; a bare 'colleague' invocation routes through the App no-command handler (session at a TTY, help otherwise), matching pre-migration behavior

### t3 — Migration pattern: convert the feedback verb-group to register_into(app) as the worked reference for every other verb

- depends on: t2
- covers: c4, h4
- acceptance:
  - feedback record|show|list register into the App as a nested group; 'colleague feedback record ... --json' dispatches behavior-identically to the pre-migration verb and bare 'colleague feedback' renders the group overview
  - explain feedback record and overview feedback are derived from the registry (no hand-written per-command catalog); the existing feedback CLI tests pass unchanged

### t4 — Migrate the flag-heavy core verbs work + plan to register_into(app)

- depends on: t3
- covers: c4, h4
- acceptance:
  - work registers with ALL its flags via signature-derivation + explicit agentfront Flag(): positional goal, typed options, bool on/off incl. default-ON --lint/--no-lint, alias/dest-rename (--repo/-r -> repo_path), hyphenated names (--max-steps -> max_steps), nargs (--test); 'colleague work --help' lists every flag and dispatch is behavior-identical
  - plan run|status|overview register as a nested group; existing work/plan CLI tests pass unchanged; neither module edits colleague/cli/_app.py

### t5 — Host launcher carve-out: register session + tui via app.add_command (host-owned interactive surfaces, not generated)

- depends on: t3
- covers: c9, h9
- acceptance:
  - session and tui register via app.add_command with their own configure() flags; 'colleague session'/'colleague tui' launch the existing raw-mode palette / live cockpit unchanged and coexist with generated verbs in one CLI
  - session/tui tests stay green; the modules touch only session.py/tui.py (no edit to _app.py)

### t6 — Migrate the inspect/identity verbs: backends, config, doctor, whoami, quickstart, telemetry

- depends on: t3
- covers: c8
- acceptance:
  - each of backends/config/doctor/whoami/quickstart/telemetry registers into the App via register_into and keeps its stdout/stderr split, --json shape, exit codes, and overview; their existing CLI tests pass unchanged
  - the six modules are file-disjoint from every other fan-out task and never edit _app.py

### t7 — Migrate the extensibility/mesh verbs: hooks, commands, roles, agents, skills, flight, clean, learn-from, promote

- depends on: t3
- covers: c8
- acceptance:
  - these verbs register via register_into; nested groups (flight status|guide|stop|list|overview, hooks list|approve, commands list|approve) render from the registry with --json + bare-noun overview preserved; existing tests pass unchanged
  - the nine modules are file-disjoint from every other fan-out task and never edit _app.py

### t8 — Retire hand-rolled scaffolding: learn/explain/overview become agentfront registry-derived meta-verbs; remove colleague's hand-rolled argparse dispatch

- depends on: t4, t5, t6, t7
- covers: c14, h11
- acceptance:
  - learn/explain/overview are served by agentfront's registry-derived meta-verbs (colleague's hand-rolled versions removed); a grep of colleague/cli/ shows the CLI is built from the agentfront import with no hand-rolled argparse subparser dispatch except the session/tui launchers

### t9 — Cross-surface parity test: port the coverage spike into tests/ asserting catalog-level CLI==MCP-catalog==learn set-equality (the reworded #246 invariant)

- depends on: t8
- covers: c5, h5, c16, h13
- acceptance:
  - tests/test_cross_surface_parity.py asserts, on colleague's one App, catalog-level set-equality: the CLI verb path set == the single MCP dispatch tool's command catalog (agentfront _build_catalog) == the learn catalog; it does NOT assert len(mcp_tools)==len(cli_verbs); adding/removing an op updates all three together

### t10 — MCP server verb + round-trip test, behind the [mcp] extra (server-only, opt-in)

- depends on: t3
- covers: c15, h12
- acceptance:
  - 'colleague mcp serve' exposes app.mcp_server() (the single run dispatch tool) only when [mcp] is installed; an end-to-end round-trip test (with the extra) lists the run tool and invokes a colleague op via {command:[path], args:{...}} and gets its result; a bad path yields a structured {code,message,remediation}
  - without the [mcp] extra, the serve path raises a clean 'install colleague[mcp]' error (not a bare ImportError), binds no socket, and starts no daemon; a test asserts the base install imports no mcp SDK

### t11 — Behavior-compat e2e: the full existing CLI/e2e suite stays green against the agentfront-rendered CLI

- depends on: t8
- covers: c8, h8
- acceptance:
  - the existing CLI/e2e suite (stdout/stderr split, --json shapes, exit codes, hint lines, explain/overview catalog, the test_e2e_mock shape test) passes against the rendered CLI; any deliberately-changed observable contract is called out explicitly in the PR

### t12 — Affordance checklist: prove no interactive affordance is silently dropped; session/tui green

- depends on: t5
- covers: c9, h9
- acceptance:
  - a checklist (in the feature doc) enumerates every interactive affordance (raw-mode session palette, slash autocomplete, shift-tab modes, live TUI cockpit) and marks each as expressed-via-agentfront or kept host-owned-behind-a-launcher — none silently dropped; session/tui tests stay green

### t13 — Maintainer-win measurement + docs + version bump

- depends on: t9, t10, t11, t12
- covers: c2, h2, c3, h3
- acceptance:
  - net agent-first scaffolding LOC removed from colleague/cli/ is measured and recorded (the maintainer win); CLAUDE.md + docs/features/cli-on-agentfront.md describe the agentfront-rendered CLI and the colleague[mcp] MCP bonus; CHANGELOG updated and the version bumped per the repo version-bump rule

## Risks

- [unknown_nonblocking] agentfront's registry-derived explain/overview may not reproduce colleague's richer hand-authored explain catalog verbatim; each migrated op must carry doc= metadata ported from the current explain entries (task t8)
- [unknown_nonblocking] behavior-compat across ~26 verbs is the main risk; a subtle --json shape or exit-code drift could slip past a per-verb test — the full e2e suite (t11) is the backstop (task t11)
- [follow_up] the served 27B workforce has large-file + concurrency limits; the risky core (t2 assembly, t9 parity, t11 e2e) should be built by Claude, with only mechanical per-verb conversions delegated to colleague

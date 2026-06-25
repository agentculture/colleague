# Colleague's agent-first CLI is rendered from an imported agentfront App registry instead of hand-maintained scaffolding — and because the operations live in that one registry, colleague also gets an MCP server (a bonus for platforms like Cowork) for free

> Colleague's agent-first CLI is rendered from an imported agentfront App registry instead of hand-maintained scaffolding — and because the operations live in that one registry, colleague also gets an MCP server (a bonus for platforms like Cowork) for free

## Audience

- Colleague maintainers (less scaffolding to maintain), the AgentCulture org (one shared agent-first CLI standard across tools), and — as a bonus — MCP platforms like Cowork that can then drive colleague

## Before → After

- Before: Colleague hand-maintains its entire agent-first CLI in colleague/cli/ (dispatch, CliError->stderr, --json, exit codes, explain/overview/doctor); agentfront is used only as a dev-time 'cli doctor --strict' gate; and agentfront's App today CANNOT build a consumer CLI (App.cli() yields only learn/doctor), so there is nothing yet to import to replace the scaffolding
- After: Colleague's CLI is rendered from an imported agentfront App registry — nested verbs, custom flags, --json, structured errors, explain/overview all come from agentfront's published consumer CLI API; colleague keeps no hand-maintained agent-first scaffolding (only interactive surfaces App cannot express stay colleague-owned behind a launcher). The same registry yields app.mcp_server() (MCP for Cowork) and app.http_app() as free bonuses

## Why it matters

- One source of the agent-first standard across the org (no drift, far less scaffolding for colleague to maintain), AND colleague becomes MCP-accessible for free — a platform like Cowork can discover and drive it without the bespoke ask-colleague wrapper

## Requirements

- PRECONDITION: agentfront must FIRST publish a public, importable consumer CLI API (promoting its internal nested-noun/structured-error/explain/overview/--json machinery to a host-facing surface) that colleague's CLI is rendered from; colleague's migration is GATED on this precondition existing and being versioned. This agentfront work is done separately in the agentfront repo, not in colleague
  - honesty: Once agentfront publishes the consumer CLI API, a spike proves it renders colleague's full nested-verb surface (groups, flags, --json, explain/overview); colleague pins a tested agentfront version floor and the migration proceeds only against that published API
- Zero-deps reconciliation: agentfront (pure-stdlib) becomes the one base runtime dependency; the mcp SDK is an opt-in colleague[mcp] extra; tests/test_zero_deps.py is updated to allow exactly agentfront at base and assert mcp is absent without the extra
  - honesty: A base 'uv pip install colleague' pulls exactly agentfront (zero third-party transitively) and the mcp SDK appears only under [mcp]; test_zero_deps asserts that allow-list and still fails on any stray dep
- Behavior-compat: every existing colleague CLI verb keeps its observable contract (stdout result, stderr diagnostics, --json shape, exit codes, hint line) after being rendered from agentfront — verified by the existing CLI/e2e suite staying green
  - honesty: The CLI/e2e suite (stdout/stderr split, --json shape, exit codes, hint line, explain/overview catalog) passes unchanged against the agentfront-rendered CLI; any contract that must change is called out explicitly

## Honesty conditions

- After the migration, colleague's CLI is built by importing agentfront's consumer CLI API (no hand-rolled argparse dispatch remains except the documented interactive launcher) AND every verb keeps its observable contract — verified by the existing CLI/e2e suite staying green against the agentfront-rendered CLI
- The maintainer win is measurable (net agent-first scaffolding LOC removed from colleague/cli/) and the org-consistency win is real (colleague + agentfront render their CLIs from the same published API), while the Cowork bonus is genuinely free (no colleague code beyond registering operations enables it)
- Verified against agentfront 0.11.1: App.cli() registers only learn/doctor (cli_surface.make_cli), @app.tool is MCP/HTTP-only and never CLI-dispatched, and the rich CLI machinery is internal to agentfront.cli with no consumer extension hook
- Colleague's nested noun/verb groups, per-verb flags, --json, and the explain/overview catalog are all produced by agentfront's published API (not re-hand-rolled in colleague), proven by the CLI tests passing against the imported surface
- A test asserts the CLI command set, the MCP tool list, and the learn catalog all enumerate the SAME registry entries, so an operation added once appears on every surface — no drift, no per-surface duplication
- The affordance checklist shows every interactive affordance either expressed via agentfront or explicitly kept colleague-owned behind a launcher — none silently dropped; session/tui tests stay green
- With no [mcp] extra installed, colleague imports no mcp SDK, binds no socket, and starts no daemon — asserted by a test; the MCP server runs only when the operator installs the extra and explicitly starts it
- Grepping colleague/cli/ post-migration shows the CLI built from the agentfront import (registry-driven), not hand-rolled argparse; the full CLI/e2e suite plus doctor are green
- An end-to-end MCP round-trip test (with the extra) connects, lists, and invokes at least one colleague operation and gets its result; without the extra the same import path raises a clean 'install colleague[mcp]' error, not a crash
- The test enumerating CLI commands vs MCP tools vs learn entries asserts set-equality over the registry, so adding/removing an operation updates all three surfaces at once

## Success signals

- Colleague's CLI is rendered from the imported agentfront API (no hand-rolled argparse dispatch remains except the launcher) and behaves byte-compatibly; the e2e suite and 'agentfront cli doctor . --strict' are green
- With the [mcp] extra installed, an MCP client lists + invokes colleague's operations over the served MCP server (the Cowork bonus works); the base install is byte-identical and binds no socket
- One agentfront registry feeds the CLI command set, the MCP tool list, and the learn catalog — a test asserts they enumerate the same operation set (no drift)

## Scope / boundaries

- Interactive surfaces agentfront's API cannot structurally express (the raw-mode session palette, the live TUI cockpit) stay colleague-owned behind an agentfront-registered launcher verb — preserved, never dropped
- The MCP-server bonus is OPT-IN: the mcp SDK and the daemon ship behind the colleague[mcp] extra; a base install runs no daemon, binds no socket, and is byte-identical to today

## Non-goals

- Building agentfront's consumer CLI API is OUT OF SCOPE for the colleague work and for this environment — it is done separately in the agentfront repo; the colleague spec/plan assumes it as an external dependency and implements only colleague's side
- NOT a live MCP client (colleague consuming other MCP servers) — out of scope; MCP here is server-only and a bonus
- NOT a rewrite of colleague's domain runtime — the loop, contract, engines, and gates are untouched; operations are registered as tools, not reimplemented (all-engines rule preserved)

## Decisions

- Path is UPSTREAM-FIRST: agentfront publishes the consumer CLI API first (built in the agentfront repo, separately), then colleague imports it; colleague's implementation is gated on that precondition
- agentfront is the one base runtime dep; the MCP server + the mcp SDK + the daemon live behind a colleague[mcp] extra (matching colleague's otel/tui/culture extras pattern)
- MCP and HTTP are BONUSES derived from the same registry, not the headline; the CLI is the primary surface
- Version-pin agentfront's consumer CLI API with a tested floor and pin the mcp SDK in the extra; a major agentfront/mcp bump is a deliberate, tested colleague update, never an automatic float

## Tracking

- **Phase 1 precondition (external):** the agentfront consumer CLI API is filed as
  [agentculture/agentfront#35](https://github.com/agentculture/agentfront/issues/35).
  Colleague's Phase 2 (this spec) is gated on it; do not start colleague-side
  implementation until that API ships and a spike confirms it renders colleague's
  full nested-verb surface (assumption c21 / honesty on requirement c6).

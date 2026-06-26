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
- A test asserts the CLI verb set, the single MCP dispatch tool's command catalog, and the learn catalog all enumerate the SAME registry operations — catalog-level set-equality (the MCP surface is one dispatching tool, not one tool per op), so an operation added once appears on every surface — no drift, no per-surface duplication
- The affordance checklist shows every interactive affordance either expressed via agentfront or explicitly kept colleague-owned behind a launcher — none silently dropped; session/tui tests stay green
- With no [mcp] extra installed, colleague imports no mcp SDK, binds no socket, and starts no daemon — asserted by a test; the MCP server runs only when the operator installs the extra and explicitly starts it
- Grepping colleague/cli/ post-migration shows the CLI built from the agentfront import (registry-driven), not hand-rolled argparse; the full CLI/e2e suite plus doctor are green
- An end-to-end MCP round-trip test (with the extra) connects, lists, and invokes at least one colleague operation and gets its result; without the extra the same import path raises a clean 'install colleague[mcp]' error, not a crash
- The test enumerating CLI verbs vs the single MCP dispatch tool's command catalog vs learn entries asserts catalog-level set-equality over the registry (NOT len(mcp_tools)==len(cli_verbs); the MCP surface is a single dispatch tool whose command catalog lists the ops), so adding/removing an operation updates all three surfaces at once

## Success signals

- Colleague's CLI is rendered from the imported agentfront API (no hand-rolled argparse dispatch remains except the launcher) and behaves byte-compatibly; the e2e suite and 'agentfront cli doctor . --strict' are green
- With the [mcp] extra installed, an MCP client lists + invokes colleague's operations over the served MCP server (the Cowork bonus works); the base install is byte-identical and binds no socket
- One agentfront registry feeds the CLI verb set, the single MCP dispatch tool's command catalog, and the learn catalog — a test asserts they enumerate the same operation set at the catalog level (no drift; the MCP surface is one dispatching tool, not N)

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

**Phase 1 precondition — SHIPPED (gate lifted).** The agentfront consumer CLI
API was filed as
[agentculture/agentfront#35](https://github.com/agentculture/agentfront/issues/35)
and is now merged on agentfront `main` (commit `fb16272`, "feat: public consumer
CLI API implementation (closes #35)", released in **agentfront 0.14.0**). It
ships exactly the host-facing surface this spec assumed: tool→CLI dispatch from
the registry, nested noun/verb groups to arbitrary depth (`App.tool(group=…)` /
`App.group(*prefix)`), per-verb signature-derived args plus rich explicit
`Flag(...)` declarations, per-verb `--json`, structured
`{code,message,remediation}` errors to stderr with non-zero exit, `explain` /
`overview` from the registry, a host extension hook for hand-written subcommands
(`App.add_command`) and a no-command handler (`App.set_no_command_handler`).

**#246 applied — single-dispatch MCP reword.** agentfront chose to expose the
MCP surface as a **single-dispatch "CLI on MCP" tool** (one `run` tool whose
`inputSchema`/description embeds the command catalog), not one MCP tool per
operation. Per
[agentculture/colleague#246](https://github.com/agentculture/colleague/issues/246)
the cross-surface parity honesty conditions (h5, h13) and the success-signal
claim (c16) were reworded from MCP-tool-**count** equality
(`N CLI == N MCP == N learn`) to **catalog-level** set-equality: the CLI verb
set == the single MCP dispatch tool's command catalog == the `learn` catalog,
all enumerated from the one registry.

**Coverage spike — PASSED (discharges assumption c21 / honesty c6).** A spike
registered a representative-hardest slice of colleague's CLI (the ~18-flag
`work` verb — positional + typed + bool on/off + default-ON opt-out + flag alias
+ dest-rename + hyphenated flag name + `nargs`; a nested `feedback
record|show|list` group; an arbitrary-depth `a b deep` path; per-verb `--json`;
a forced structured error; bare-noun→overview; `explain`/`overview`; a
host-owned `session` launcher via the extension hook; a bare-invocation
no-command handler) into an agentfront `App` and rendered it via the shipped
`run_cli`/`App.cli()`. **All 12 checks pass against agentfront 0.14.0**,
including the reworded #246 catalog-parity invariant
(`registry == single MCP-tool catalog == learn catalog`). agentfront expresses
colleague's full nested-verb surface; the migration is unblocked. The spike is
the seed of the cross-surface parity + coverage test that the implementation
must port into `tests/`.

**Next:** `/spec-to-plan` against this (revised, converged) frame to produce the
buildable Phase-2 plan, then implement colleague's side (packaging:
`agentfront` as the one base dep + a `colleague[mcp]` extra; render every verb
from the registry; keep `session`/`tui` as host-owned launcher verbs).

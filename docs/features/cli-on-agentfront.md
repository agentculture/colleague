# cli-on-agentfront — colleague's CLI is rendered from an imported agentfront App registry

> Colleague's agent-first CLI is **rendered from an imported
> [agentfront](https://github.com/agentculture/agentfront) `App` registry**
> instead of hand-maintained argparse scaffolding ("import, don't duplicate").
> The generic agent-first machinery — nested noun/verb dispatch, structured
> `{code, message, remediation}` errors to stderr, per-verb `--json`, the
> bare-invocation no-command handler, `KeyboardInterrupt` → 130 — now comes from
> agentfront's one published consumer-CLI API, not from colleague code. And
> because every operation lives in that one registry, colleague also gets a
> **single-dispatch MCP server** (a bonus for platforms like Cowork) and an HTTP
> app for free, from the same registry, with no extra colleague code.

agentfront is colleague's **first sanctioned base runtime dependency** — a
deliberate, recorded break from the historical `dependencies = []` convention,
justified because agentfront's own core is pure-stdlib (zero third-party deps),
it is an AgentCulture sibling, and it is foundational to the org's shared
agent-first CLI standard. The MCP SDK is **never** a base dependency: it ships
behind the opt-in `colleague[mcp]` extra, so a base `pip install colleague`
pulls exactly agentfront (no socket, no daemon) and `tests/test_zero_deps.py`
enforces that allow-list.

Spec + plan:

- `docs/specs/2026-06-25-colleague-s-agent-first-cli-is-rendered-from-an-im.md`
- `docs/plans/2026-06-26-colleague-s-agent-first-cli-is-rendered-from-an-im.md`

Following [colleague#246](https://github.com/agentculture/colleague/issues/246)
(single-dispatch MCP) and gated on
[agentfront#35](https://github.com/agentculture/agentfront/issues/35) (the
consumer CLI API, shipped in agentfront **0.14.0**).

## What it does

`colleague/cli/_app.py` `build_app()` assembles one agentfront `App` by
auto-discovering every verb module's `register_into(app)` hook under
`colleague/cli/_commands/`, then wiring the bare-invocation no-command handler.
`colleague/cli/__init__.py` `main()` dispatches argv against that App via
agentfront's `run_cli`. The same assembled App backs three surfaces from one
registry:

| Surface | How | Bonus? |
|---------|-----|--------|
| **CLI** | `run_cli(build_app(), argv)` | the primary surface |
| **MCP server** | `app.mcp_server()` → `serve_stdio(app)` (`colleague mcp serve`) | yes — needs `colleague[mcp]` |
| **HTTP** | `app.http_app()` | yes — derived, not yet surfaced as a verb |

An operation registered once in the registry appears on every surface — no
per-surface duplication, no drift (proven by the cross-surface parity test
below).

## Two verb classes: rendered tools vs host commands

Not every verb fits agentfront's rendered-tool shape, so colleague registers
each verb as one of two kinds. The distinction is **structural**, not stylistic:

### Rendered tools (`app.tool(...)`)

A rendered tool is a plain function: agentfront derives its CLI flags from the
signature, calls it, emits the return value (dual-rendered — `json.dump` under
`--json`, else the value's `__str__`), and **always exits 0**. Failure is
signalled *only* by `raise` (a `CliError`, which subclasses agentfront's
`AgentfrontError`, renders natively as structured stderr). This fits every
read-only inspection / identity verb:

`whoami`, `backends`/`wheels`, `config`, `telemetry`, `quickstart`, `cli`,
`agents`, `skills`, `roles`, `commands`, `hooks`, `feedback`.

The `rendered(data, text)` helper (a dict/list subclass with a custom
`__str__`) lets one return value dual-render: the structured payload under
`--json`, the human text otherwise.

### Host commands (`app.add_command(name, handler, configure=...)`)

A host command keeps full `(args) -> int` control: custom exit codes, streaming
output, hyphenated / `None`-default flags, and long-running blocking work.
Registered via agentfront's host-extension hook, it reuses colleague's existing
`cmd_*` handlers verbatim. This fits every verb that needs an exit code other
than 0/raise, or that an exit-0 tool cannot express:

| Host command | Why it can't be a rendered tool |
|--------------|--------------------------------|
| `work` / `drive` | exits **2** on `INCOMPLETE` (#192) with the result still on stdout |
| `plan` | `plan run` exits **1** when the spec does not converge |
| `session` | interactive raw-mode TTY cockpit (blocks; agentfront can't express raw-mode) |
| `tui` | `tui test` exits **1** on a scenario FAIL |
| `flight` | `flight status --follow` streams a live feed |
| `clean` / `learn-from` / `promote` | hyphenated / engine-driving flags + custom reporting |
| `mcp` | `mcp serve` blocks on a long-running stdio server |

### The reserved-meta-verb shim

agentfront **reserves** four meta-verbs (`doctor`, `overview`, `learn`,
`explain`) and renders trivial, registry-derived versions of them. Colleague's
own versions are materially richer — `doctor` is a real configuration-readiness
health check, `explain` is the per-verb markdown catalog (which also documents
the host-command launchers agentfront's registry-driven `explain` cannot reach).
So `main()` routes exactly those four through colleague's retained legacy parser
(`_build_parser`) before ever reaching the rendered App; the rendered App never
registers them, so agentfront's generic versions are simply never hit.

## The MCP bonus — single-dispatch (`colleague mcp serve`)

Per #246 the MCP surface is **one** `run` tool whose description embeds the
command catalog (a "CLI on MCP"), **not** one MCP tool per operation. A platform
like Cowork connects, reads the catalog from the single tool's schema, and
dispatches `{command: [path...], args: {...}}`, which agentfront resolves via
`app.get_by_path(tuple(command)).func(**args)` — the SAME registry operation the
CLI verb runs.

- **Opt-in:** needs the `colleague[mcp]` extra. Absent it, `mcp serve` fails
  with a clean `CliError` naming the install (`pip install 'colleague[mcp]'`),
  binds no socket, starts no daemon — never a bare `ImportError` traceback.
- **No socket/daemon code in colleague:** the blocking stdio loop is agentfront's
  `serve_stdio`; colleague only assembles the App and hands it over. This holds
  the no-socket / no-daemon convention.
- **Server-only:** this is the MCP *server* bonus. colleague reads no `mcp.json`
  and registers no external MCP tools — a live MCP *client* remains explicitly
  out of scope.

## Cross-surface parity (the no-drift proof)

`tests/test_cross_surface_parity.py` pins **catalog-level set-equality** across
the three catalogs derived from the one registry: the CLI registry tools == the
single MCP dispatch tool's command catalog == the `learn` catalog, with host
commands consistently absent from all three. This is set-equality over the
registry, **not** `len(mcp_tools) == len(cli_verbs)` — the MCP surface is one
dispatching tool whose catalog lists the ops. Adding or removing an operation
updates all three surfaces at once.

## Affordance checklist — nothing silently dropped

Every interactive affordance is either expressed via agentfront or explicitly
kept colleague-owned behind an agentfront-registered launcher verb. None is
silently dropped; `session`/`tui` tests stay green.

| Affordance | Disposition |
|------------|-------------|
| Nested noun/verb groups (`feedback record\|show\|list`, …) | **expressed via agentfront** (registry groups) |
| Per-verb `--json` | **expressed via agentfront** (per-verb flag) |
| Structured `{code, message, remediation}` errors + `hint:` line | **expressed via agentfront** (`AgentfrontError`; `CliError` subclasses it) |
| Bare-invocation no-command handler | **expressed via agentfront** (`set_no_command_handler`) |
| `--version` / `-V` | **colleague-owned** (the rendered parser carries no version action) |
| Grouped `--help` epilog (getting-started / working / inspecting) | **colleague-owned** (routed through the legacy parser to preserve the epilog) |
| `doctor` / `overview` / `learn` / `explain` | **colleague-owned** (the reserved-meta-verb shim — richer than agentfront's generic versions) |
| Raw-mode `session` palette + slash autocomplete + shift-tab modes | **host-owned behind a launcher** (`app.add_command("session", …)`) |
| Live `tui` cockpit (JSON/ANSI/Markdown views, scenario runner) | **host-owned behind a launcher** (`app.add_command("tui", …)`) |
| `flight status --follow` live feed | **host-owned behind a launcher** (streaming) |

## The maintainer win — measured honestly

The spec's honesty condition (h2) requires the maintainer win to be
**measurable**. Measured against `main`, the **transitional** reality is:

- `colleague/cli/` net change: **+1468 / −445** (net **+1023** lines) — the CLI
  grew, it did not shrink, because the migration deliberately carries **both**
  paths: the live rendered path (`build_app` + 21 per-verb `register_into`
  hooks) **and** the retained legacy argparse parser.
- The legacy parser (`_build_parser` + `_dispatch` + `_CliArgumentParser` +
  epilog, ~**154 lines** in `colleague/cli/__init__.py`) survives **only** as
  the backend for the four reserved meta-verbs, the interactive session's
  in-process noun introspection, and the `doctor` parser self-check. It is no
  longer the live dispatch path.

So the win today is **structural, not a net-LOC reduction**:

1. The generic agent-first machinery (nested dispatch, structured errors,
   `--json`, no-command handling, `KeyboardInterrupt` → 130) is now **sourced
   from agentfront's one published API** — it evolves once in agentfront, for
   the whole org, instead of being re-hand-rolled per repo.
2. The **same registry yields the MCP server + HTTP for free** — the #246
   parity test proves zero colleague code beyond `register_into` enables the
   Cowork bonus (h3's "genuinely free" condition).
3. The **raw-LOC reduction lands when the retained legacy parser is fully
   retired** — a documented follow-up. At that point ~154 lines of
   `colleague/cli/__init__.py` scaffolding are deleted and the net-negative
   maintainer win is realized.

This is recorded honestly rather than overclaimed: the net colleague/cli/ LOC is
**up** in the transitional state, and the LOC win is **deferred** to the
legacy-parser-retirement follow-up.

## Honest limits

- **Dual-path during transition.** `_build_parser` is retained (see above);
  fully retiring it — and realizing the raw-LOC win — is a documented follow-up,
  not done here.
- **MCP is server-only and opt-in.** No `mcp.json` is read; no live MCP client
  exists; the server runs only when the operator installs `colleague[mcp]` and
  explicitly runs `mcp serve`.
- **agentfront is now a base dep.** This is the one deliberate, recorded break
  from `dependencies = []`. agentfront's core is pure-stdlib, so a base install
  still pulls zero third-party transitive deps; `tests/test_zero_deps.py` is an
  allow-list of exactly agentfront and asserts the MCP SDK is absent without the
  extra.
- **Domain runtime untouched.** The loop, contract, engines, and gates are
  unchanged — operations are *registered* as tools, not reimplemented (the
  all-engines rule is preserved).

## See also

- `colleague/cli/_app.py` — `build_app()`, the registry assembly keystone
- `colleague/cli/__init__.py` — `main()`, the rendered-dispatch entry + meta-verb shim
- `colleague/cli/_commands/mcp.py` — the `mcp serve` / `mcp overview` host command
- `tests/test_cross_surface_parity.py` — catalog-level set-equality (no-drift proof)
- `tests/test_mcp_serve.py` — the single-dispatch MCP round-trip (behind `[mcp]`)
- `tests/test_zero_deps.py` — the agentfront allow-list + MCP-SDK-absent assertion

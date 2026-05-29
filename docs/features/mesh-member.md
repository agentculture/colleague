# Mesh-member integration

> A convertible drive runs as a named AgentCulture mesh member: it acts under a
> specific mesh identity, natively reaches the curated AgentCulture CLIs, and
> can read sibling repos via operator-configured ephemeral neighbour clones.

## Before → after

**Before** this feature, a `convertible drive` was a **sealed single-repo box**:

- No first-class identity concept — the drive had no nick and produced no
  attributed mesh artifacts.
- No native culture surface — reaching `agtag` (mesh issues) or `devex` (inspect
  a repo's agent-first surface) meant crafting an ad-hoc `run_command` string;
  nothing was declared, nothing was structural.
- No neighbour awareness — a drive could only read files in the target repo; it
  had no mechanism to consult a sibling repo's source.

The communicate and cicd skills could bridge some of these gaps for a human
operator, but they were external to the drive contract — the model inside the
loop had no declared tool for them and no injected identity.

**After** this feature:

- A drive resolves a **process-level identity** (the repo's `culture.yaml` nick,
  or a `.convertible/identity.json` `as` field) and propagates it to every
  culture-CLI subprocess via `CONVERTIBLE_IDENTITY` — no per-call flag.
- The model is offered a single curated **`culture` loop tool** that shells out
  to the allow-listed AgentCulture CLIs (`agtag`, `devex`) with the identity
  already injected and `cwd` pinned at the repo root. Reaching the mesh is a
  *declared capability*, not an improvised shell string.
- Operators can list repos in `.convertible/neighbours.json`; the
  `NeighbourManager` shallow-clones them into `.convertible/neighbours/<name>/`
  on demand — read-only, gitignored, ephemeral.

## Enabling it

An operator already running convertible in an AgentCulture workspace enables
this feature by **installing only the culture CLIs they want** — no bespoke
wiring. The identity and neighbour configuration slots into the existing
`.convertible/` config layer; nothing else changes.

### Identity (zero config needed in many cases)

If the repo already has a `culture.yaml` at its root with a top-level `nick:`
field, that nick is resolved automatically:

```yaml
# culture.yaml (already present in an AgentCulture repo)
nick: convertible
```

If there is no `culture.yaml`, or the nick field is absent, add
`.convertible/identity.json` with an `"as"` key:

```json
{ "as": "convertible" }
```

The user-level `~/.convertible/identity.json` is a fallback (the same
repo-over-user precedence the rest of `.convertible/` config uses). When
neither source has an identity the `culture` tool still works — it just runs
without injecting `CONVERTIBLE_IDENTITY`.

### Culture CLIs

Install whichever CLIs you want available:

```bash
uv tool install agtag          # mesh issue tracker (agtag issue post/fetch/reply)
uv tool install agex-cli       # agent-first surface inspector (devex explain/overview)
```

Only `agtag` and `devex` are in the curated allow-list. Asking the `culture` tool
to run any other CLI name returns a clean error rather than launching an
arbitrary binary.

The inspection CLI is invoked under the `devex` name (the `agex-cli`
distribution ships both `agex` and `devex` console scripts for the same tool).
Convertible's culture tool standardizes on the `devex` name here, matching the
cicd skill's PR lifecycle (`devex pr`) (issue #33). Some vendored skill scripts
still print `agex` in help text — those are upstream-owned (tracked via
`docs/skill-sources.md`) and migrate on their own re-vendor, independent of this
chassis allow-list.

### Neighbour repos (opt-in, defaults to empty)

With no `.convertible/neighbours.json` present, **no clones are created** — the
neighbour set defaults to empty. To add neighbours, create the file:

```json
[
  { "name": "culture",  "url": "https://github.com/agentculture/culture.git" },
  { "name": "steward",  "url": "https://github.com/agentculture/steward.git" }
]
```

The manager shallow-clones each entry into `.convertible/neighbours/<name>/`
inside the repo root (gitignored). That path falls inside the existing
`read_file` confinement zone, so the model can read neighbour files naturally.
Clones are refresh-on-demand (no background daemon) and ephemeral — they are
removed when the drive ends.

## How it works

### Identity resolution (`convertible/identity.py`)

`resolve_identity(repo_path)` checks two ordered sources:

1. `<repo_root>/culture.yaml` — scanned line-by-line for a top-level `nick:`
   field (stdlib only, no PyYAML dependency).
2. `.convertible/identity.json` (repo-level first, then `~/.convertible/`) —
   the `"as"` key.

The result is exposed to subcommands via the `CONVERTIBLE_IDENTITY` environment
variable so the identity flows down without a per-call flag.

### The `culture` loop tool (`convertible/culture.py` + `convertible/tools.py`)

The loop's tool surface now includes a single `culture` tool alongside the five
base tools. It:

- Validates the requested CLI name against `ALLOWED_CLIS = {"agtag", "devex"}` —
  any other name is rejected before a subprocess is spawned.
- Runs the CLI as `subprocess.run` (no socket, no daemon, no import) with
  `cwd` pinned at the repo root and `CONVERTIBLE_IDENTITY` injected.
- Maps a missing CLI (`FileNotFoundError`) to a clean `ToolError` string fed
  back to the model — never a traceback.
- Caps output at 20,000 chars and enforces a 300-second timeout.

The tool is **ungated** — it follows the same trusted-operator-env model (D2)
as `run_command`.

Because the `culture` tool is registered in `convertible/tools.py` (the shared
`SCHEMAS` list), every engine sees it identically — the all-engines rule. The
chassis owns it; no engine module touches `convertible/culture.py`.

### Neighbour clone manager (`convertible/neighbours.py`)

`NeighbourManager` is a stdlib-only helper that:

- Reads `.convertible/neighbours.json` (a list of `{"name", "url"}` objects);
  returns an empty list when absent.
- `clone_all()` — shallow-clones each entry into
  `.convertible/neighbours/<name>/` (idempotent).
- `refresh(name)` — `git fetch --depth 1` + hard reset to `FETCH_HEAD`, no
  local commits.
- `cleanup()` — `shutil.rmtree` the entire `.convertible/neighbours/` tree.
- Never runs `git commit` or `git push` — no code path writes to any clone's
  history.

Clones live under the gitignored `.convertible/neighbours/` path, inside the
repo-confined read zone.

## Boundaries that still hold

- **No live MCP runtime.** Every culture integration shells out to an
  operator-installed CLI via subprocess — no socket, no daemon, no MCP transport.
  Convertible reads no `mcp.json` and has no `mcp` verb. A live MCP client would
  need its own spec.
- **No new runtime dependency.** `identity.py`, `neighbours.py`, and
  `culture.py` are all stdlib-only. The zero-deps guard and the
  `dependencies = []` invariant still hold.
- **Clones are strictly read-only and inert.** `NeighbourManager` never commits
  or pushes. Clone paths fall inside the existing `read_file` confinement zone so
  the model can read them, while `run_command` refuses any command that targets a
  path under `.convertible/neighbours/` — clones are never executed. (That guard
  is a best-effort substring check on the command string, not an airtight sandbox;
  an execution sandbox remains out of v0 scope.)
- **Clone lifecycle is wired into the loop.** The loop clones the allow-listed
  neighbours at drive start and removes the whole tree on the `finish` lifecycle
  event — which fires on every loop exit (model finish, empty turn, or step-budget
  exhaustion) — so clones are ephemeral and leave no residue between drives.
- **The allow-list is fixed by the builder.** The curated set (`agtag`, `devex`)
  is hardcoded in `ALLOWED_CLIS`. Adding further culture tools is a builder
  decision, not an operator config option.

## Key files

- `convertible/identity.py` — `resolve_identity()`, `identity_env()`.
- `convertible/neighbours.py` — `NeighbourManager` (clone/refresh/cleanup).
- `convertible/culture.py` — `run_culture()`, `ALLOWED_CLIS`, `normalize_args()`.
- `convertible/tools.py` — `culture` tool schema in `SCHEMAS`; `_culture`
  dispatch in `ToolExecutor`.

## See also

- [drive-and-loop.md](drive-and-loop.md) — the bounded tool-loop and the full
  tool surface.
- [hooks.md](hooks.md) — the lifecycle (hooks own the `finish` event that
  triggers neighbour cleanup).
- [layered-config.md](layered-config.md) — the `.convertible/` config layer the
  identity and neighbour configs slot into.

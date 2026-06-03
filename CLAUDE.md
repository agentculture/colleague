# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What colleague is

**Colleague CLI is a swappable coder-agent harness that turns different models
into repo workers behind one shared task contract.** One harness, many engines.

The car metaphor *is* the architecture:

- **Engine** — the model/coder backend.
- **Driver** — the adapter for one engine, in `colleague/engines/` (an
  `Engine` subclass implementing `drive(task, config) -> TaskResult`).
- **Chassis** — the shared task contract (`colleague/contract.py`: `Task`,
  `TaskResult`) and lifecycle.
- **Tool-loop** — the bounded agentic loop (`colleague/loop.py`) the engine
  drives the repo through (`read_file`/`write_file`/`list_dir`/`run_command`/
  `culture`/`finish`, confined to the repo by `colleague/tools.py`). The base
  five tools plus one curated `culture` tool (allow-list: `agtag`, `devex`) —
  added via the mesh-member re-spec (spec/plan committed on this branch). Hook
  firing lives here — every engine inherits lifecycle behavior automatically.
- **Wheels** — engines are plugins discovered via the `colleague.engines`
  Python entry-point group (`colleague/registry.py`).
- **Dashboard** — the JSON result artifact + step trace (`colleague/artifact.py`).
  Includes an **always-on per-drive statistics block** (`TaskResult.stats`,
  `colleague/contract.py` `DriveStats`): request, ISO start + wall-clock
  duration, model turns, step count, per-tool counts, files changed, exact UTF-8
  `bytes_written`, and reasoning-vs-answer char/byte sizes. Tokens stay on
  `usage` (exact, verbatim from the model response — never estimated); since the
  served model reports no reasoning-token breakdown, "thought vs written" is
  measured as chars/bytes, not tokens (no tokenizer, zero deps). Populated
  chassis-side in `colleague/loop.py` (`run`/`_drive_loop` + `_finalize_stats`)
  so every engine fills it identically; the vLLM engine captures
  `message.reasoning` (previously discarded).
- **Feedback** — the ROI loop (`colleague/feedback.py` + `colleague/cli/_commands/
  feedback.py`). Drive stats say what a drive *cost*; a feedback record says how
  *good* it was — together they let a caller compute the ROI of outsourcing a task
  to colleague. A single record per drive (`<task_id>.feedback.json` beside the
  artifact, re-grade overwrites): `{task_id, rating 1-5, notes, by, at}`; a per-repo
  `last_drive` pointer (written by `execute_drive`) lets `feedback ... last`
  resolve the most recent drive. Stdlib JSON only; an ungraded drive reads back as
  a clean "no feedback yet" state, never an error. Surfaced as `colleague
  feedback record|show|overview` and as the `outsource feedback` skill verb.
- **GPS** — opt-in OpenTelemetry traces + metrics (`colleague/telemetry/`).
  Instrumented in the loop + the shared drive path so every engine emits it
  (all-engines rule), exactly like hooks. Off by default; the OpenTelemetry SDK
  is an optional `[otel]` extra, imported lazily, so the base install stays
  dep-free. Surfaced via the `telemetry` introspection noun.
- **Identity** — process-level identity resolution (`colleague/identity.py`):
  `culture.yaml` nick → `.colleague/identity.json` `as` → None; propagated to
  every culture-CLI subprocess via `COLLEAGUE_IDENTITY` (no per-call flag).
  Part of the chassis; inherited by every engine (all-engines rule).
- **Neighbours** — operator-configured read-only neighbour clones
  (`colleague/neighbours.py`): a `.colleague/neighbours.json` allow-list of
  `{name, url}` entries; shallow-cloned on demand into
  `.colleague/neighbours/<name>/` (gitignored); refresh-on-demand, ephemeral
  (cleaned up on drive finish). Defaults to empty when no config is present.
- **Culture tool** — one curated loop tool (`colleague/culture.py` +
  `colleague/tools.py`) that shells out to the allow-listed AgentCulture CLIs
  (`agtag`, `devex`) with the resolved identity injected; no socket, no daemon,
  no runtime dep. Lives in the chassis tool surface so every engine exposes it
  identically.
- **Destination** — the car-metaphor sibling to GPS. GPS tells colleague where
  it *is* (telemetry); the destination is where it's *going*. An engine MAY,
  when a task is vague/new enough to warrant a clear goal, use a curated
  **`devague` loop tool** to open/converge a devague goal-frame, drive toward it,
  and declare the announcement on arrival. The destination is recorded lightweight
  in the JSON artifact (`TaskResult.destination` + `announcement`), not a per-drive
  spec file. The `devague` tool shells out to the operator-installed `devague` CLI
  with cwd + resolved identity injected (like the culture tool); the curated
  allow-list excludes `confirm`/`reject` (user-only moves) and `export`
  (operator-only). Setting a destination is OPTIONAL and engine-judged, never a
  forced gate; convergence is ADVISORY, and only operator-confirmed claims are
  authoritative. Specification + plan: `docs/specs/2026-05-29-colleague-knows-its-destination-before-it-drives.md`
  and `docs/plans/2026-05-29-colleague-knows-its-destination-before-it-drives.md`.
- **Approval gate** — operator-declared allow-list that controls what the
  harness *executes* (`colleague/policy.py`). The policy lives in
  `.colleague/approvals.json` (repo-level, resolved via `configdir`; a
  per-model overlay at `.colleague/<sanitized-model>/approvals.json` is
  composed ahead via exact-path construction — no sibling globbing). Three
  gated categories, each opt-in via presence of its section:
  - `run_command` — gates CLI invocations by program token (`shlex` first
    token); allow/deny lists; absent section is a strict no-op.
  - `hooks` — gates lifecycle hook script files by content checksum; a
    section present but listing no entry is still a gate (allow-list
    semantics: unlisted = denied).
  - `commands` — gates command template files by content checksum at
    expansion time.
  Skills and AGENTS instructions are **never gated** — they are declarative
  and load freely. Approval values are algorithm-prefixed strings
  `"sha256:<hex>"` (default) or `"md5:<hex>"` (honored). `approve` records
  the file's current checksum; a subsequent content change voids the approval
  (checksum mismatch → denied). Absent or malformed `approvals.json` is a
  strict no-op. Spec + plan: `docs/specs/2026-05-29-colleague-only-runs-the-executables-you-ve-appro.md`
  and `docs/plans/2026-05-29-colleague-only-runs-the-executables-you-ve-appro.md`.
  **Honest limits:** this is a policy gate, not a sandbox — the token check
  is bypassable by `sh -c`, pipelines, and shell expansion; `md5` detects
  accidental drift, not a malicious editor (use `sha256` for integrity);
  v0 is checksum-only (`version` pinning is a documented follow-up, not
  built). This is the tracked "per-repo hook trust gate" from the conventions
  section, now partially landed; there is still no `--no-hooks` flag.
- **Subagents (convoy)** — mid-drive, an engine MAY delegate scoped sub-tasks
  via two loop tools: (1) `subagent` for a single child, or (2) `subagents`
  (plural) for a batch that runs concurrently (`colleague/subagents.py` +
  `colleague/tools.py`). Each child runs the SAME bounded tool-loop as a nested
  in-process call and is isolated in its own throwaway git worktree on a
  `sub/<id>` branch (`colleague/worktrees.py`). The parent receives each child's
  `SubResult` as the tool result; completed sub-results are folded into
  `TaskResult.sub_results` (omitted when empty). A SEQUENTIAL merge-subagent
  integrates the branches afterward, surfacing (never force-merging) unresolvable
  conflicts. Concurrency is opt-in: `COLLEAGUE_SUBAGENT_CONCURRENCY` (default 1 =
  byte-identical sequential behavior); with width > 1, up to `MIN(width,
  MAX_SUBAGENT_FANOUT-1)` children run in parallel via `concurrent.futures`
  (threads confined to `subagents.py`), reserving one slot for the merge child.
  Delegation is ENGINE-JUDGED and OPTIONAL (like the `devague` destination tool),
  never a forced gate. An optional `engine`/`model` switch resolves through the
  existing `registry.load` + `EngineConfig` inheritance — a config-level switch,
  no engine code change. Termination is structural: `MAX_SUBAGENT_DEPTH=2`
  (recursion cap, checked *before* any child work) and `MAX_SUBAGENT_FANOUT=4`
  (per-drive fan-out cap, including the merge child). No per-subagent git
  handoff — only the top-level drive hands off. **Honest limit:** real wall-clock
  speedup requires the served model to handle concurrent requests; on a
  serializing server, gain is bounded by overlapped I/O wait, not model compute.
  Specification + plan: `docs/specs/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md`
  and `docs/plans/2026-06-03-colleague-s-convoy-drives-subagents-in-parallel-a.md`.
  This is explicitly NOT the out-of-scope multi-engine router/"gearbox": there is
  no operator-configured automatic task→engine routing policy. Chassis-owned
  (all-engines rule): the tools fire identically for every engine.
- **Handoff** — branch/commit/push + `gh pr create`, gated for offline/CI
  (`colleague/handoff.py`).
- **Command templates** — named, parameterized task recipes in
  `.colleague/commands/*.md` (`colleague/commands.py`); expanded into a
  `Task` via `drive --command <name> [args…]`.
- **Hooks** — operator-authored shell commands in `.colleague/hooks.json`
  (`colleague/hooks.py`) that fire at `task_start`/`pre_tool`/`post_tool`/
  `finish`; a `pre_tool` hook can allow, deny, or rewrite a tool call.
  A **per-model hooks overlay** at `.colleague/<model>/hooks.json`
  (`<model>` sanitized via `colleague.layers.sanitize_model`, e.g.
  `mmangkad/Qwen3.6-27B-NVFP4` → `mmangkad-Qwen3.6-27B-NVFP4`) is composed
  **ahead of** the base entries for each event — per-model-first precedence
  gives operator-declared model fixes priority via the loop's existing
  first-deny/rewrite-wins rule. Exact-path isolation: model X never loads model
  Y's overlay (no sibling globbing). Strict no-op with no overlay file present.
  No new runtime dep, socket, or daemon. Inspect via
  `colleague hooks list --model <m>` (per-model entries tagged `per-model`).
- **Interactive palette** — `colleague session` (`colleague/cli/_commands/
  session.py`): a foreground TTY loop over the same drive path; no parallel
  code path, no daemon.
- **Cockpit views (tui)** — `colleague tui` provides three headless, pure-stdlib
  views of one `CockpitState`: **JSON/TAUI** (programmatic contract + source of truth,
  `tui state`), **ANSI** (visual frame, `tui render` default), and **Markdown**
  (agent-facing readable view — better than raw JSON for an agent to glance at,
  `tui render --format markdown`). The snapshot is now a **quad**: `tui snapshot`
  writes `<name>.taui.json` / `<name>.ansi` / `<name>.events.jsonl` / `<name>.md`.
  `tui diagnose` on a quad verifies **JSON↔Markdown alignment** — the RENDER
  faithfulness check runs against both frames; zero findings = faithful. Before this
  surface was added, no colleague command emitted Markdown and `diagnose` inspected
  the ANSI frame only. Legacy triples (no `.md`) still read fine.
- **Context budget / graceful degradation** — the bounded tool-loop windows its
  running message history to a configurable token budget before each model turn
  (`colleague/context.py` + `colleague/loop.py` `_complete_with_degradation`)
  and, on a detected context-overflow error, trims history harder and retries a
  bounded number of times before preserving a readable partial result — so a
  multi-file drive on a small-context model degrades instead of hard-failing. The
  knob is `COLLEAGUE_CONTEXT_BUDGET` (tokens, on `EngineConfig.context_budget_tokens`,
  default 192000, env `COLLEAGUE_CONTEXT_BUDGET`) — sized for the 256k (262144-token)
  reference rig, leaving headroom for the completion; lower it for a small-context
  model. A companion knob caps each tool result fed back to the model:
  `COLLEAGUE_MAX_OUTPUT_CHARS` (chars, on `EngineConfig.max_output_chars`, default
  100000, raised from the old hardcoded 20000 so a large `read_file`/`run_command`
  result isn't truncated inside the bigger window); both resolve via the same
  `EngineConfig.resolve` precedence and the engines forward them to the loop
  identically (all-engines rule). The drive step budget default is
  `COLLEAGUE_MAX_STEPS` (`EngineConfig.max_steps`, default 40). Token counting goes
  through a pluggable `count_tokens` seam — the vLLM engine counts exactly via the
  server's `/tokenize` endpoint, falling back to a zero-dep char heuristic
  (`count_tokens_chars`) when `/tokenize` is absent. **Honest limits:** the budget is best-effort exact
  (exact via `/tokenize`, char-approximate fallback) — NO third-party tokenizer
  library is bundled (`dependencies = []` holds); windowing DROPS oldest history
  with a placeholder note (there is **no LLM-generated summary** in v0); there is
  **no multi-model router/"gearbox"** (an overflow never switches models); retries
  are bounded (termination preserved). Chassis-owned (all-engines rule): the feature
  fires identically for every engine. Specification + plan:
  `docs/specs/2026-06-02-colleague-drives-degrade-gracefully-when-a-task.md`
  and `docs/plans/2026-06-02-colleague-drives-degrade-gracefully-when-a-task.md`.
- **Config resolution** — `colleague/configdir.py`: repo-level
  `.colleague/` overrides user-level `~/.colleague/`.
- **Rename back-compat (`convertible` → `colleague`)** — the project was renamed
  from *convertible*. The import package, the `colleague`/`clg` commands, the
  `.colleague/` config dir, and the `COLLEAGUE_*` env vars are the canonical
  names; the PyPI distribution is `colleague` (no longer `convertible-cli`). The
  legacy names are still honored as **deprecated read fallbacks**: `.convertible/`
  config/artifact dirs (read-only, writes go to `.colleague/`; see
  `configdir.LEGACY_CONFIG_DIR_NAME`, `artifact.artifact_read_dirs`,
  `layers._LEGACY_USER_CONFIG_SUBDIR`) and `CONVERTIBLE_*` env vars (each read
  prefers `COLLEAGUE_*` then falls back to `CONVERTIBLE_*`). `identity_env`
  emits **both** `COLLEAGUE_IDENTITY` and `CONVERTIBLE_IDENTITY` so sibling
  CLIs that only know the old name keep working. Historical artifacts
  (`CHANGELOG.md`, `docs/specs/`, `docs/plans/`, `.devague/`, dated drive-notes)
  intentionally keep the old name. The SonarCloud `projectKey` in
  `sonar-project.properties` is `agentculture_colleague`; that is an EXTERNAL
  identity, so the SonarCloud project itself must be re-keyed/recreated to match
  or coverage uploads 404 until it is.
- **Layered per-model config** — `colleague/layers.py`: AGENTS instructions
  (`AGENTS.md` → `AGENTS.colleague.md` → `AGENTS.colleague.<model>.md`, at
  the repo root with a `~/.colleague/` fallback) and skills
  (`.colleague/skills/*.md` → `.colleague/<model>/skills/*.md`) compose into
  the engine system prompt. Resolution builds exact paths for the current model
  and never globs sibling models — per-model isolation is structural. Injected
  once on the `Engine` base class (`system_prompt()`), so every engine inherits
  it (all-engines rule). Surfaced via the `agents` / `skills` introspection
  nouns. The companion **per-model hooks overlay** (`.colleague/<model>/hooks.json`)
  extends this isolation to the hooks layer — see the Hooks bullet above.
  **MCP layering is not built** — colleague reads no `mcp.json` and has
  no `mcp` verb; a live MCP client is a re-spec (see scope below).

The buildable spec and plan this implementation converged from live in
[`docs/specs/`](docs/specs/) and [`docs/plans/`](docs/plans/) (authored via the
`/think` → `/spec-to-plan` devague workflow).

## v0 scope (hold this line)

In scope: the chassis, the entry-point wheel contract, exactly two engines
(`mock`, `vllm-openai`), the git/PR handoff, command templates, lifecycle
hooks, the foreground interactive palette, layered per-model AGENTS/skills
config (`colleague/layers.py`), GPS — opt-in OpenTelemetry traces +
metrics (`colleague/telemetry/`), with the SDK as an optional `[otel]` extra —
the **mesh-member integration**: process-level identity (`colleague/identity.py`),
read-only neighbour clones (`colleague/neighbours.py`), and the curated
`culture` loop tool (`colleague/culture.py`; allow-list: `agtag`, `devex`) —
and the **destination/`devague` tool** (`colleague/devague.py`; curated allow-list
excluding `confirm`/`reject`/`export`), which lets an engine set and converge a
goal-frame when a task warrants one, drive toward it, and declare the announcement
on arrival — and the **approval gate** (`colleague/policy.py`):
`.colleague/approvals.json` gating `run_command` CLIs by program token and
hook/command files by checksum — and the **subagent/convoy tools** (`subagent` + `subagents`)
(`colleague/subagents.py` + `colleague/worktrees.py` + `colleague/tools.py`):
engine-judged, optional in-process child drives with engine/model switch, depth
cap (2), fan-out cap (4), no per-subagent handoff, isolated per-child git
worktrees, opt-in concurrency via `COLLEAGUE_SUBAGENT_CONCURRENCY` (default 1 =
byte-identical sequential) — and the **drive statistics + feedback loop** (the
ROI loop):
always-on per-drive `DriveStats` in the artifact (`colleague/contract.py` +
`colleague/loop.py`) and a single-record-per-drive feedback store
(`colleague/feedback.py`) surfaced as `colleague feedback` and the
`outsource feedback` skill verb. All integrated features (mesh-member, culture
tool, destination, approval gate, subagents, and stats+feedback) were added via
explicit re-specs (spec + plan committed under `docs/specs/` / `docs/plans/`);
they extend the chassis within the zero-deps / no-socket / no-daemon conventions.

**Out of scope for v0** — do not add without re-speccing: a multi-engine
router/policy "gearbox", an execution sandbox, a daemon/server mode,
Codex/Claude/Gemini drivers, a `--no-hooks` escape hatch (there is still no
such flag — the approval gate's checksum-based trust model is the landed
increment of the planned hook trust gate, but it is a policy gate, not a
sandbox; document this gap honestly, never invent a `--no-hooks` flag), and an **MCP execution runtime**
(a live MCP client — stdio/socket transport, tool discovery, dynamic tool
registration). The layered config ships AGENTS + skills only; `mcp.json` is
**not** read and there is no `mcp` verb. A live MCP client would breach the
no-deps / no-socket / no-daemon conventions and needs its own spec — document
this gap honestly, never invent an `mcp` surface. Adding an excluded feature
means scope crept.

## The all-engines rule

Mirror of culture's all-backends rule: behavior that belongs to *the contract*
(task fields, result shape, the loop, the artifact) must hold for **every**
engine. The `mock` engine is the contract's reference — if a change makes
`mock` and `vllm-openai` diverge in result shape, that is a bug. The e2e shape
test (`tests/test_e2e_mock.py`) is the guard.

## Conventions

- **No runtime dependencies.** `pyproject.toml` keeps `dependencies = []`; the
  vLLM driver speaks the OpenAI wire format over stdlib `urllib`; commands and
  hooks use only stdlib (`json`, `subprocess`, `pathlib`). Don't add a runtime
  dep without a strong reason — dev-only deps go in the `dev` group. The one
  documented exception is **GPS**: the OpenTelemetry SDK ships as an optional
  `[project.optional-dependencies] otel` extra, never a base dependency. It is
  imported **lazily** inside `colleague/telemetry/_otel.py` (only when
  telemetry is enabled), so `dependencies = []` and the zero-deps guard
  (`tests/test_zero_deps.py`) still hold — the guard imports `colleague.loop`
  / `colleague.telemetry` / `colleague.cli` / `colleague.culture` /
  `colleague.neighbours` and asserts no third-party leak even with the extra
  installed. Keep the SDK confined to `_otel.py`; never import `opentelemetry`
  from any other colleague module.
- **Agent-first CLI.** New verbs are `colleague/cli/_commands/` modules with a
  `register(sub)`, wired in `colleague/cli/__init__.py`. Results to stdout,
  diagnostics/errors to stderr (never mixed); every command supports `--json`;
  failures raise `CliError` (no tracebacks leak). A noun with action-verbs must
  expose `overview`. Add an `explain` catalog entry for each new verb.
- **The vLLM driver only touches the OpenAI surface** — `base_url`/`api_key`/
  `model` config, `/v1/chat/completions` with tools. Retargeting any
  OpenAI-compatible server must stay a config change, never a code change. ONE
  deliberate carve-out: the vLLM `/tokenize` endpoint is used for exact token
  counting in the context-budget feature (`colleague/engines/vllm_openai.py`
  `_make_count_tokens`); it **degrades gracefully** (returns `None` on any error)
  so retargeting a non-vLLM OpenAI-compatible server WITHOUT `/tokenize` stays a
  config change, never a code change (token precision downgrades to char-approximate
  fallback, correctness unchanged).
- **Hook commands run as subprocesses, never imported.** `colleague/hooks.py`
  uses `subprocess.run` (shell=True) in the repo working directory. Command
  templates are Markdown text files, never executed as Python. No code path
  opens a socket or forks a daemon.
- **Threads and subprocesses are sanctioned in exactly two modules.**
  `colleague/worktrees.py` manages git worktree/branch operations (subprocess);
  `colleague/subagents.py` runs parallel children via `concurrent.futures`
  (threads). No other colleague module imports `subprocess` at the loop level,
  `threading`, or `concurrent.futures` — enforced by boundary tests
  (`test_boundary.py`). The `culture` and `devague` tools (both in the loop)
  shell out to operator-installed CLIs, a permitted exception handled via
  explicit allow-listing.
- **Hooks belong to the chassis, not to engines.** `colleague/loop.py` owns
  hook firing — new engine wheels inherit the full lifecycle layer automatically
  and must not duplicate it. The all-engines rule applies: a hook config that
  fires on `mock` must fire identically on `vllm-openai`.
- **Telemetry belongs to the chassis too.** `colleague/loop.py` (per tool
  call) and the shared `execute_drive` path (root + handoff spans) own all
  telemetry; no engine module touches the `telemetry` package. Off by default it
  is a strict no-op (no spans, no SDK import, `TaskResult` unchanged) — protect
  that so the e2e shape test and zero-deps guard keep passing.
- **Repo-shipped hooks run by default (trusted-operator-env model D2).** There
  is no `--no-hooks` flag today. The approval gate (`colleague/policy.py`)
  is the landed increment of the per-repo hook trust gate: it gates hook
  scripts by checksum and `run_command` CLIs by token. It is a **policy gate,
  not a sandbox** — it is bypassable by `sh -c`, pipelines, and shell
  expansion. Document this gap clearly; never document a non-existent
  `--no-hooks` flag.
- **Per-model hooks overlay belongs to the chassis, not to engines.**
  `colleague/loop.py` passes `model=config.model` to `load_hooks` — both
  bundled engines do this. New engine wheels inherit the per-model overlay for
  free (all-engines rule). The overlay is operator-declared and file-based;
  colleague does not auto-detect model biases. Exact-path isolation and strict
  no-op match the AGENTS/skills layering conventions (`colleague/layers.py`).
- **The `culture` tool belongs to the chassis, not to engines.** `colleague/tools.py`
  owns the tool schema and the `ToolExecutor._culture` dispatch; `colleague/culture.py`
  owns the subprocess launch and identity injection. No engine module touches either.
  The all-engines rule applies: the culture tool is offered to every engine identically.
  Every culture integration shells out to an operator-installed CLI — no socket, no
  daemon, no import; `colleague` reads no `mcp.json` and adds no live MCP client.
- **The `devague` tool belongs to the chassis, not to engines.** `colleague/tools.py`
  owns the tool schema and the `ToolExecutor._devague` dispatch; `colleague/devague.py`
  owns the subprocess launch, identity injection, and allow-list enforcement.
  No engine module touches either. The all-engines rule applies: the devague tool is
  offered to every engine identically. The curated allow-list (`new`, `capture`,
  `interrogate`, `park`, `converge`, `status`, `show`) structurally excludes
  `confirm`/`reject` (user-only moves — the engine cannot self-confirm) and `export`
  (operator-only — arrival is recorded as a lightweight announcement, not a spec file).
  Every devague integration shells out to an operator-installed CLI — no socket, no
  daemon, no import.
- **The approval gate belongs to the chassis, not to engines.**
  `colleague/policy.py` is loaded once in `colleague/loop.py` (via
  `load_policy(task.repo_path, model=model)`) and consulted at two points:
  `_deny_by_policy` (for `run_command` calls) and `_fire_hooks` (for hook
  script files before they run). `colleague/commands.py` consults it at
  command-template expansion time. No engine module touches `policy.py`
  directly. The all-engines rule applies: the gate fires identically for
  `mock` and `vllm-openai`. Absent or malformed `approvals.json` is a strict
  no-op — byte-identical to pre-gate behavior. Zero new runtime deps (stdlib
  `json`/`shlex`/`hashlib`/`hmac`). **Checksum-only in v0** — `version`
  pinning is a documented follow-up, not built; do not document it as
  existing.
- **The `doctor` verb is colleague's oilcheck.** It emits a configuration-readiness
  health check across identity, provider, usage, engines, otel-readiness, and
  environment check-groups, in a rubric shape with exit-1-on-unhealthy semantics. The
  **usage** group warns (advisory — stays healthy) when a bare drive would pick the
  no-op `mock` engine. `doctor --probe` adds an opt-in `provider_reachable` ping —
  the one check that opens a network connection, so it is gated behind the flag and
  invoked outside the (no-network) registered check-groups. See `colleague explain
  doctor` for details.
- **Drive statistics belong to the chassis, not to engines.** `colleague/loop.py`
  owns `DriveStats` population (`_drive_loop` per-turn + `_finalize_stats` on every
  exit path); `colleague/tools.py` accumulates `bytes_written`; the vLLM engine
  only *captures* `message.reasoning` into `ModelResponse`. The all-engines rule
  applies: stats are always-on and identical for `mock` and `vllm-openai`
  (`tests/test_e2e_mock.py` pins the `stats` key). **Honest token limit:** tokens
  are exactly what the response `usage` reports — never estimated. The served model
  reports no reasoning-token breakdown, so reasoning is measured as chars/bytes,
  not tokens; there is no tokenizer and no `bytes/4` heuristic. The optional OTel
  path mirrors the new metrics (`colleague.generated.chars`,
  `colleague.bytes_written`) as a strict no-op when off.
- **The feedback store belongs to the chassis, not to engines.**
  `colleague/feedback.py` is a stdlib JSON store (one record per drive,
  re-grade overwrites) + a per-repo `last_drive` pointer written by
  `execute_drive`. No engine touches it. Absent file/pointer is a clean no-op
  (`read_feedback` / `get_last_drive` return `None`, never raise). It is **not**
  gated by the approval gate and opens no socket/daemon — zero new runtime deps.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run pytest -n auto                     # tests (parallel)
uv run colleague wheels list            # discovered engines
uv run colleague drive "<task>" --repo . --engine mock --no-pr
# Engine resolution: --engine > COLLEAGUE_ENGINE > vllm-openai (never silent mock, #53).

# Extensibility layer:
uv run colleague drive --command <name> [args…] --repo . --engine mock --no-pr
uv run colleague commands list --repo .          # list discovered templates
uv run colleague commands overview               # surface description
uv run colleague hooks list --repo .             # list configured hooks (shows run_command policy + approval status)
uv run colleague hooks overview                  # surface description
uv run colleague hooks approve <script> --repo . # record checksum approval for a hook script (repo-relative path)
uv run colleague commands approve <name> --repo . # record checksum approval for a command template
# Both approve commands accept --algo sha256|md5 (default: sha256) and --json.
uv run colleague session --repo . --engine mock  # interactive palette (commits locally, no PR; --pr to push+PR)

# ROI loop: drive stats (always-on in the artifact) + feedback (grade a drive):
uv run colleague feedback record last --rating 4 --notes "…" --repo .  # grade the most recent drive (or <task_id>)
uv run colleague feedback show last --repo .                           # read a drive's feedback (clean no-op if ungraded)
uv run colleague feedback overview                                     # surface description

# GPS / telemetry (opt-in; needs the [otel] extra):
uv run colleague telemetry status                # resolved telemetry config
uv run colleague telemetry overview              # surface description
uv sync --extra otel                               # install the OpenTelemetry SDK
COLLEAGUE_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  uv run colleague drive "<task>" --repo . --engine mock --no-pr  # emits a trace

# Lint + gates CI enforces:
uv run black --check colleague tests
uv run isort --check-only colleague tests
uv run flake8 colleague tests
uv run bandit -c pyproject.toml -r colleague
uv run teken cli doctor . --strict        # agent-first rubric gate
```

The live vLLM proof is opt-in (the reference rig must expose tool calling:
`--enable-auto-tool-choice` plus a model-appropriate `--tool-call-parser`, e.g.
`hermes` or `qwen3_coder`):

```bash
COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live.py -v
```

## The `outsource` skill (first-party)

colleague ships one **first-party** Claude Code skill,
[`outsource`](.claude/skills/outsource/) — the *inverse* of the vendored skills
(origin = colleague; see [`docs/skill-sources.md`](docs/skill-sources.md)). It
lets another agent hand a scoped task to colleague — a *different* engine/mind,
not a stronger one; diversity is the point. Three verbs over `colleague drive`:
`outsource explore` (read-only investigation), `outsource review` (a diverse
second opinion on the committed `<base>...HEAD` diff — the headline verb), and
`outsource write` (delegate a small change — previews by default; `--apply` lands
a drive branch, `--pr` opens a PR). explore/review run in a throwaway `git
worktree` (no side effects); `write` previews in one too unless `--apply`/`--pr`,
and guards against a dirty tree when applying. Details + worked examples:
[`docs/features/outsource.md`](docs/features/outsource.md).

## Git workflow

Branch out, implement, **bump the version every PR** (the `version-check` CI job
blocks merge otherwise — use the `version-bump` skill), create the PR via the
`cicd` skill, address review, merge. Distribution is `colleague`; the
command and import package are `colleague`. PyPI publish is via Trusted
Publishing on merge to `main`.

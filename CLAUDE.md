# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

Each architecture part below is a few lines + a pointer to its feature doc; the deep detail (history, invariants, honest limits, full module list, spec+plan) lives in [`docs/features/`](docs/features/), which links its spec/plan
under [`docs/specs/`](docs/specs/) / [`docs/plans/`](docs/plans/). A bare `Doc:`
name is a file under `docs/features/`. Trim discipline (decision c17 / honesty h4):
no fact was dropped — everything moved to its pointer target.

## What colleague is

**Colleague CLI is a swappable coder-agent harness that turns different model
backends into repo workers behind one shared task runtime.** One runtime, many
minds. The architecture, part by part:

- **Mind / backend** — the model/coder backend.
- **Adapter** — invokes one backend (`colleague/engines/`, an `Engine` subclass
  with `work(task, config) -> TaskResult`). Doc: `engines.md`.
- **Task runtime** — the shared contract (`colleague/contract.py`:
  `Task`/`TaskResult`); optional `Task.goal`/`acceptance` → an **advisory**
  acceptance self-check (never flips status). Doc: `task-goals.md`.
- **Tool loop** — the bounded agentic loop (`colleague/loop.py`) over repo-confined
  tools (`colleague/tools.py`: base six + `culture`). Hooks, the progress sink
  (#38), phase notices (#206), finish recovery (#248/#231) live here (all-engines);
  **a phase notice never advances `step_count`**. Doc: `work-and-loop.md`.
- **Plugins** — backends discovered via the `colleague.engines` entry-point group
  (`colleague/registry.py`).
- **Run report + feedback (ROI loop)** — JSON artifact + step trace + always-on
  `WorkStats` (`colleague/artifact.py`; tokens exact from `usage`, never estimated),
  plus a per-work-item feedback store (`colleague/feedback.py`) with a per-repo
  `last_work` pointer (writes-only across ask-colleague, #132). Docs: `artifact.md`,
  `stats-and-feedback.md`.
- **Telemetry** — opt-in OpenTelemetry, loop-instrumented; off by default, the lazy
  `[otel]` extra. Doc: `telemetry.md`.
- **Mesh-member integration** — process identity (`colleague/identity.py`, via `COLLEAGUE_IDENTITY`), read-only neighbour clones from a `.colleague/neighbours.json` allow-list (`colleague/neighbours.py`), and a curated `culture` tool (`colleague/culture.py`) shelling out to `agtag`/`devex`. Doc:
  `mesh-member.md`.
- **Destination** — a curated `devague` loop tool to converge a goal-frame +
  declare arrival; allow-list excludes `confirm`/`reject`/`export`; optional. Doc:
  `destination.md`.
- **Approval gate** — operator allow-list over what the harness runs (`colleague/policy.py`): `run_command` by token, `hooks`/`commands` by checksum;
  absent = strict no-op. Doc: `approval-gate.md`.
- **Subagents** — delegate sub-tasks via `subagent`/`subagents`
  (`colleague/subagents.py`), each child in a `sub/<id>` worktree + a sequential
  merge child; caps `MAX_SUBAGENT_DEPTH`/`_FANOUT`; concurrency opt-in (default 1). Doc: `subagents.md`.
- **Subagent roles** — a subagent can be a **typed role** (`colleague/roles.py`); a
  read-only role **provably cannot mutate the tree**; caps depth 4 / total 24. Doc:
  `subagent-roles.md`.
- **Rig budget** — a file-based cooperative slot across separate colleague processes sharing one endpoint; a caller degrades OPEN, never deadlocks. Doc: `rig-budget.md`.
- **Deepthink / dual-model** — a MAIN model + an operator-declared **deepthink**
  reasoner on an **enumerated** escalation surface; absent = byte-identical. Doc: `deepthink.md`.
- **Cortex / senses** — minds resolved **by role** from an operator `lobes` gateway:
  cortex drives, senses is a tools-off front door; absent = byte-identical. Doc: `cortex-senses.md`.
- **Media input** — images/audio ride to a multimodal main model;
  delivery **verified** onto `TaskResult.media`.
  Doc: `media-input.md`.
- **Integration front (#291)** — colleague is the operator front of the Culture.dev
  organism; landed the coherence gate, the experiment noun, `organs list`,
  the artifact contract + `feedback export`. Index: `docs/organs.md`.
- **Senses live presence + voice** — the operator converses with **senses** while cortex drives; words → guidance at the next tool-call boundary; audio
  via `stt`/`tts` (`[voice]` extra); senses never produces the task answer. Doc: `senses-live-presence.md`.
- **Talking to one (middle-manager presence)** — in `colleague session` senses
  acks/narrates/clarifies + delivers conversationally; cortex still does the task;
  clarify never withholds work. Doc: `talking-to-one.md`.
- **Talking to one teammate (senses front door)** — senses answers non-repo turns
  FIRST via a **deterministic** classifier (`colleague/frontdoor.py`,
  ambiguous→cortex); anything touching the repo → cortex, the ONLY repo actor. Doc: `talking-to-one-teammate.md`.
- **Memory (best-colleague R1)** — recall-before / remember-after every run (eidetic) onto `TaskResult.memory`; triple-gated; isolated runs target the OPERATOR repo. Doc: `memory.md`.
- **Finish recovery + grounded reads (R2)** — the loop recovers
  literal-markup/thin/meta finishes (#248/#231) onto `TaskResult.finish_recovered`;
  `read_file` is `cat -n` grounded (#240). Doc: `work-and-loop.md`.
- **Honest incompletion (#313)** — a no-deliverable run reports non-`ok`
  (`INCOMPLETE`) + `TaskResult.incompletion`; **soft rule**: a
  substantive non-meta finish = delivered. Doc: `honest-incompletion.md`.
- **At home on your machine** — global config **per-key merge** (a machine-wide `~/.colleague/config.json` arms every repo); **the owned input line** (4th
  sanctioned reader thread); **self-knowledge** (#306). Doc: `at-home-on-your-machine.md`.
- **Background one-shot + mesh residency (c17)** — `work --background` detaches a
  session-leader child (`colleague/background.py`); residency
  (`colleague/resident/appserver.py`, `[resident]` extra) embeds
  `agent_lifecycle.runtime` — **zero socket/daemon code of colleague's own**; trust
  c19 (non-operator read-only or refused). Doc: `resident.md` (+ `background.md`).
- **Auto-split** — a too-large assignment gets a split recommendation into ~4 children (via `subagents`, reusing `batch_spawn`); strict no-op when dormant. Doc:
  `auto-split.md`.
- **Handoff** — branch/commit/push + `gh pr create`, gated for offline/CI
  (`colleague/handoff.py`); crash-resilient (#162 — a catchable pre-commit interruption restores the ref + reaps the orphan branch). Doc: `handoff.md`.
- **Write isolation (#196/#201)** — `work`/`drive` run in a throwaway worktree at HEAD on `colleague/<id>` (`colleague/worktrees.py`); the operator's
  tree + branch are **never touched**; `--allow-dirty` (#149) is the gate. Doc:
  `write-isolation.md`.
- **Lint pre-finish gate (#200)** — auto-fixes changed files with configured linters (`black`/`isort`/`ruff`/`flake8`); default-ON,
  non-blocking. Doc: `lint-gate.md`.
- **Test-integrity gate (#203)** — flags the **mirror signature** (a novel id
  co-introduced in a changed test + its module, found nowhere else) onto
  `TaskResult.test_integrity_report`; + a diverse-model reviewer; advisory. Doc:
  `test-integrity.md`.
- **Affected-tests gate (#213)** — runs the tests that **transitively import** the changed module(s) (`ast` graph, depth 3, capped 20); default-ON,
  degrade-to-skipped without pytest. Doc: `affected-tests.md`.
- **Cleanup / reap** — `colleague clean` self-heals a repo a crashed `work` wedged
  (#162); the git reap lives in `colleague/handoff.py`; scoped to `colleague/*` refs + `.colleague/` artifacts. Doc: `cleanup-reap.md`.
- **Command templates** — named recipes in `.colleague/commands/*.md`, via `work --command <name>`. Doc: `command-templates.md`.
- **Hooks** — operator shell commands in `.colleague/hooks.json` at four lifecycle
  points (`pre_tool` can allow/deny/rewrite); a per-model overlay composed **ahead**
  (exact-path). Docs: `hooks.md`, `per-model-configuration.md`.
- **Interactive palette** — `colleague session` (`colleague/cli/_commands/session.py`):
  a foreground TTY loop, no daemon; a `SlashSpec` catalog; a delegation cockpit
  (#158); agent-native default (#234/#233/#235); mode selection (shift-tab / `/mode`). Off a colour TTY
  = byte-identical. Docs: `session.md`, `session-modes.md`.
- **Cockpit / tui (#285/#249)** — `colleague tui` gives three headless views of one
  `TAUIState` (JSON/ANSI/Markdown) + snapshot/diagnose; the session cockpit changes
  idle→running (claiming only ENFORCED gates, never "sandboxed"); the generic cockpit
  is IMPORTED from `agentfront.taui`, not duplicated. Docs: `tui.md`, `cockpit-ux.md`.
- **Mode profiles** — each mode carries its own compute/context profile
  (`colleague/profiles.py`); `apply_mode_profile` fills only untouched knobs after `resolve()`. Doc: `mode-profiles.md`.
- **Context budget / graceful degradation** — the loop windows history to a token
  budget (`colleague/context.py`) + trims/retries on overflow/timeout before
  preserving a partial. Knobs `COLLEAGUE_CONTEXT_BUDGET`/`_MAX_OUTPUT_CHARS`/
  `_MAX_STEPS`/`_TIMEOUT`; adaptive backpressure (#255) + timeout survival (#268).
  Docs: `graceful-degradation.md`, `backpressure.md`.
- **Capacity standard / fill-line (v1, #156)** — crossing `COLLEAGUE_FILLLINE_THRESHOLD` (0.8) injects ONE decision prompt (compact | split
  | finish-with-handoff, `colleague/fillline.py`); **compact** = a model-authored summary — the v0→v1 graduation superseding "no LLM summary". Doc: `capacity-standard.md`.
- **Config resolution** — `colleague/configdir.py` (repo > user) + a persistent
  `.colleague/config.json` override (flag > env > config.json > default); `colleague
  config show` (redacted); includes the `convertible`→`colleague` rename
  back-compat. Doc: `config-resolution.md`.
- **Layered per-model config** — `colleague/layers.py`: AGENTS + skills compose into
  the system prompt with **exact-path per-model isolation**; injected once on
  `Engine.system_prompt()`. **MCP layering is NOT built** — reads no `mcp.json`.
  Docs: `layered-config.md`, `per-model-configuration.md`.
- **Learn-from** — `colleague learn-from claude` copies/LLM-adapts Claude skills into `.colleague/skills/*.md`; colleague LOADS skills as text,
  does not execute them. Doc: `learn-from.md`.
- **Piloting / flight (#307-#311)** — a file-based flight plane
  (`.colleague/flight/<id>.*`) the loop feeds + reads stop/guidance from;
  pilot via `flight`/`talk`/`ask-colleague` (no daemon/socket). Armed **by default**
  at the OPERATOR repo (#310, opt out `--no-watch`/`COLLEAGUE_WATCH=0`) with a
  heartbeat (#308); plan-mode steering (#309); a senses-direct `SensesDirectRecord`
  (#311). Docs: `flight.md`, `pilotable-runs.md`.
- **Explore never wastes a run** — a read-only explore that exhausts its budget is never silent: forced synthesis (#191), honest `INCOMPLETE` (#192),
  advisory fan-out (#188), loud partials (#194). Doc: `explore-never-wastes.md`.
- **Colleague finishes what it starts** — continue-working
  (`COLLEAGUE_MAX_CONTINUE_NUDGES`, default 2) + auto-compact-on-finish (summary
  precedence in `_resolve_terminal_summary`). Doc: `continue-working.md`.
- **Plan mode** — colleague plans a task itself (spec→plan→workforce), gated at
  every step, **never self-confirms** (`colleague/plan/`); degradation-aware proposals + a honesty-only pass converge a weak model; needs a live backend.
  Doc: `plan-mode.md`.
- **CLI surface (cli-on-agentfront)** — the agent-first CLI is **rendered from one
  imported agentfront `App`** (`colleague/cli/_app.py`), not argparse; each verb is
  a rendered **tool** or **host command**; yields a single-dispatch MCP server
  (`mcp serve`, `[mcp]`) + an HTTP app; four reserved meta-verbs stay colleague-owned. Doc: `cli-on-agentfront.md`.

## v1 scope (hold this line)

**v0 → v1 graduation.** Four deliberate, **recorded** convention changes since v0
— never silent breaches: (1) *"no LLM-generated summary"* superseded by the
fill-line `compact` move (lossy windowing retained as the floor, #156); (2) *"zero
base dependencies"* superseded by **one** sanctioned base dep, `agentfront` (base
install still pulls zero third-party transitive deps; `[mcp]` stays an opt-in
extra; `test_zero_deps.py` allow-lists exactly agentfront); (3) the no-daemon line
re-specced by the best-colleague arc (decision c17 — background one-shot + mesh
residency via the agent-lifecycle embed); (4) *"threads confined to subagents"*
extended to the session's input-line reader thread (q1, at-home arc). Everything
else holds.

**In scope:** the runtime + every architecture part listed above (each added via an
explicit re-spec under `docs/specs/` / `docs/plans/`), within the zero-deps /
no-socket / no-daemon conventions — the daemonless line now reads: colleague ships
no socket/daemon code of its own (supervision is imported from agent-lifecycle
behind an opt-in extra; background execution is a one-shot detached child). Exactly
two backends: `mock` (the contract reference) and `vllm-openai`.

**Out of scope for v0** — do not add without re-speccing: **a multi-backend
router / routing policy** (equally the multi-model router: any automatic
task→model or task→backend routing decision). **Five sanctioned increments** have landed at this line, each a
re-spec'd, FIXED, ENUMERATED surface — never a routing policy (fuller descriptions
in the architecture bullets above + their docs): (1) **dual-model deepthink
escalation** (ONE declared second model); (2) **cortex/senses role split** (TWO
declared roles, FIXED boundary — cortex acts, senses perceives/presents — resolved
BY NAME from `lobes`; no senses-decides-to-answer-itself); (3) **senses live
presence + voice** (a concurrent conversational lane + two more FIXED named-role
consumers, `stt` + `tts`; the task always goes to cortex); (4)
**presence-default-everywhere** (senses gains its OWN bounded coordination-only
agentic loop — `colleague/senses_loop.py`/`senses_moves.py`, prompted-JSON moves
over a tools-off completion, nothing tool-shaped on the wire — default on all
fronts, closes #300; one recorded break: an off-TTY/piped session with senses armed
carries labeled `senses:` lines, `--json` stays machine-parseable); (5)
**talking-to-one-teammate senses front door** (#276/senses-direct as a FIXED,
repo-untouching surface via a deterministic classifier, ambiguous→cortex;
SUPERSEDES "#276 stays parked").

Anything beyond those five is still the excluded router; document the distinction
honestly. **Still explicitly OUT**, each parked pending its own re-spec: the
**retrieval-consumption lane of #277** (`embedder`/`reranker` roles are
discoverable in the lobes `/capabilities` contract but colleague consumes only
`cortex`/`senses`/`stt`/`tts`); an **execution sandbox**; a **colleague-owned
persistent daemon/server, socket code, or transport** (background one-shot + mesh
residency via the agent-lifecycle embed ARE in scope per c17; anything beyond is
excluded); **Codex/Claude/Gemini adapters**; a **`--no-hooks` escape hatch** (no
such flag — the approval gate is a policy gate, not a sandbox; never invent it);
and a **live MCP *client*** (colleague reads no `mcp.json`, registers no external
MCP tools; never invent an MCP-client surface). **Re-spec'd IN scope:** the **MCP
*server* bonus** — `colleague mcp serve`, a single-dispatch surface from the same
agentfront `App`, behind `[mcp]`; NOT a colleague-owned daemon (the blocking stdio
loop is agentfront's `serve_stdio`; base install byte-identical). Adding an
excluded feature means scope crept.

## The all-engines rule

Mirror of culture's all-backends rule: contract behavior (task fields, result shape, the loop, the artifact) must hold for **every** backend. `mock` is the contract reference — a change that makes `mock` and `vllm-openai` diverge in result shape is a bug (guarded by `tests/test_e2e_mock.py`).

## Conventions

- **One sanctioned base dependency: agentfront.** `pyproject.toml` declares
  `dependencies = ["agentfront>=0.15.0"]` — the first and only sanctioned base dep (a recorded break from `dependencies = []`; agentfront's core is pure-stdlib) — so
  a base `pip install colleague` still pulls **zero third-party** beyond agentfront
  (the vLLM adapter speaks OpenAI over `urllib`; commands/hooks use `json`/
  `subprocess`/`pathlib`). Don't add a *second* base dep without a re-spec (dev-only deps → the `dev` group). Two opt-in extras, never base: `[otel]` (the OTel SDK,
  imported lazily in `colleague/telemetry/_otel.py` only) and `[mcp]` (no
  socket/daemon at base). `tests/test_zero_deps.py` allow-lists exactly agentfront.
- **Agent-first CLI — rendered from an imported agentfront `App`.** A new verb is a
  `colleague/cli/_commands/` module with a **`register_into(app)`** hook, registered
  as a **rendered tool** (`app.tool`, read-only, exits 0, fails only by `raise`) or
  a **host command** (`app.add_command`, custom exit / streaming / blocking TTY).
  Results→stdout, errors→stderr; every command supports `--json`; failures raise
  `CliError`. The four reserved meta-verbs (`doctor`/`overview`/`learn`/`explain`)
  stay colleague-owned via the legacy-parser shim in `main()`. Doc: `cli-on-agentfront.md`.
- **The vLLM adapter only touches the OpenAI surface** — retargeting any
  OpenAI-compatible server must stay a config change, never a code change. ONE
  carve-out: the `/tokenize` endpoint for exact token counting, which degrades
  gracefully (`None` on error), so a server without it stays a config change.
- **Hook commands run as subprocesses, never imported.** `colleague/hooks.py` uses
  `subprocess.run` (shell=True) in the repo working dir; command templates are
  Markdown text, never executed. No code path opens a socket or forks a daemon.
- **Threads and subprocesses are confined to an explicit sanctioned list.**
  `tests/test_boundary.py`'s `_SUBPROCESS_ALLOWED` is the authority — a module
  imports `subprocess` only by joining that list with a stated reason. The
  sanctioned subprocess consumers: `hooks.py`, `tools.py`, `handoff.py`,
  `neighbours.py`, `culture.py`, `devague.py`, `worktrees.py`, `lint.py`,
  `resident/steward.py`, `affectedtests.py`, `background.py` (the one-shot detach —
  `Popen(start_new_session=True)`, no `.wait()`/`.poll()`), `memory.py`, and
  `livecheck.py`. Threads (`concurrent.futures`) stay confined to
  `colleague/subagents.py` and `colleague/cli/_commands/_input_line.py` (the
  session's colour-TTY reader thread; any failure degrades to cooked-mode). Every
  shell-out targets an operator-installed CLI via explicit allow-listing; none opens
  a socket or forks a daemon. `worktrees.py`'s admin mutations are serialized by an
  advisory `fcntl` lock (#239).
- **The runtime owns hooks, telemetry, the per-model-hooks overlay, the `culture` /
  `devague` tools, the approval gate, `WorkStats`, and the feedback store — not
  backends** (all load in `colleague/loop.py`; a hook that fires on `mock` fires
  identically on `vllm-openai`). Telemetry off, and an absent
  feedback/`approvals.json`, are strict no-ops. **Tokens are exactly what `usage`
  reports — never estimated** (reasoning is chars/bytes; no tokenizer, no `bytes/4`).
  The `devague` allow-list excludes `confirm`/`reject`/`export`; each tool shells out
  to an operator CLI — no socket/daemon/import; colleague reads no `mcp.json` and
  adds no live MCP client. Approvals are **checksum-only in v0** (`version` pinning
  is a follow-up, not built — do not document it as existing).
- **Repo-shipped hooks run by default (trusted-operator model D2).** There is no
  `--no-hooks` flag today. The approval gate (`colleague/policy.py`) is the landed
  increment of the per-repo hook trust gate (checksum on hook scripts, token on
  `run_command`); it is a **policy gate, not a sandbox** (bypassable by
  `sh -c`/pipelines). Document this gap; never document a non-existent `--no-hooks`
  flag.
- **The `doctor` verb is colleague's health check.** A configuration-readiness
  rubric (identity/provider/usage/engines/otel/environment), exit-1 on unhealthy;
  the **usage** group warns when a bare work item would pick the no-op `mock`
  backend. `doctor --probe` adds the one gated network check (`provider_reachable`).

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run pytest -n auto                     # tests (parallel)
uv run colleague backends list          # discovered backends (wheels = deprecated alias)
uv run colleague work "<task>" --repo . --engine mock --no-pr
# Backend resolution: --engine > COLLEAGUE_ENGINE > vllm-openai (never silent mock, #53).

# Extensibility layer (templates / hooks / approvals / session):
uv run colleague work --command <name> [args…] --repo . --engine mock --no-pr
uv run colleague commands list --repo .          # discovered templates (also: hooks list)
uv run colleague hooks approve <script> --repo . # checksum-approve a hook (also: commands approve)
# approve verbs accept --algo sha256|md5 (default sha256) and --json.
uv run colleague session --repo . --engine mock  # interactive palette (--pr to push+PR)

# ROI loop (feedback; work stats are always-on in the artifact):
uv run colleague feedback record last --rating 4 --notes "…" --repo .  # grade the last work item
uv run colleague feedback show last --repo .                           # read it (no-op if ungraded)

# Telemetry (opt-in): uv sync --extra otel; then COLLEAGUE_OTEL_ENABLED=1 +
# OTEL_EXPORTER_OTLP_ENDPOINT=… to emit traces.

# Lint + gates CI enforces:
uv run black --check colleague tests && uv run isort --check-only colleague tests
uv run flake8 colleague tests && uv run bandit -c pyproject.toml -r colleague
uv run teken cli doctor . --strict        # agent-first rubric gate
```

The live vLLM proof is opt-in (`COLLEAGUE_VLLM_E2E=1 uv run pytest
tests/test_vllm_live.py`) and needs a rig exposing tool calling
(`--enable-auto-tool-choice` + a model-appropriate `--tool-call-parser`, e.g.
`hermes` / `qwen3_coder`).

## The `ask-colleague` skill (first-party)

colleague ships one **first-party** Claude Code skill,
[`ask-colleague`](.claude/skills/ask-colleague/) — the *inverse* of the vendored
skills. It hands a scoped task to a *different* backend/mind (not a stronger one;
diversity is the point). Four verbs over `colleague work`/`plan`: **explore**
(read-only), **review** (a diverse second opinion on the committed `<base>...HEAD`
diff — the headline verb), **write** (a small change — previews by default;
`--apply` lands a branch, `--pr` opens a PR), **plan** (the whole
spec→plan→workforce arc — the inverse of `/think`). explore/review run in a
throwaway `git worktree` (no side effects; "outsource this" still triggers it).
Details: [`docs/features/ask-colleague.md`](docs/features/ask-colleague.md).

**Claude thinks and designs; Colleague does the field-work.** Delegate mechanical
field-work (sweeps, scoped edits, residual-reference checks, a second opinion on a
diff) to Colleague **reflexively**, and **prefer it over spawning a Claude
sub-agent** (a different, worktree-isolated, verifiable mind); keep sub-agents only
for work needing Claude's judgment or context. Multiple instances run in parallel,
but the local GPU serializes requests — cap at ~2 loops and raise
`COLLEAGUE_TIMEOUT=300` (~4 at the default 120s time out with zero commits).
Colleague's output is a **second opinion to verify and own, never authority**:
`git diff main` and re-run the tests before trusting a landed change (a local model
can drop or misreport edits). **A bare `colleague work`/`drive`/`session --repo .`
refuses a dirty tree** unless `--allow-dirty` (#149, `handoff.working_tree_dirty`) —
it blocks sweeping your uncommitted **tracked** edits onto the work branch (the
`ask-colleague` verbs stay worktree-isolated and propagate `--allow-dirty`).

## Git workflow

Branch out, implement, **bump the version every PR** (the `version-check` CI job
blocks merge otherwise — use the `version-bump` skill), create the PR via the
`cicd` skill, address review, merge. Distribution / command / import package are
all `colleague`. PyPI publish is via Trusted Publishing on merge to `main`.

## Conventions and workflow

**Memory discipline — recall before, remember after.** This repo keeps its eidetic
memory **in-repo and public**: records resolve to `<repo-root>/.eidetic/memory` —
committed and shared with the team and mesh peers (the `claude` and `colleague`
backends both read the same `colleague` scope). Make it a per-task habit:

- **`/recall` before non-trivial tasks** — search the area you're about to touch
  (prior decisions, gotchas, "have we done this before?") so you build on what's
  known instead of re-deriving it.
- **`/remember` when something worth keeping surfaces** — a non-obvious decision +
  its rationale, a constraint, a fix and *why*, a gotcha that cost time — as it
  happens.

A plain `/remember` lands the note in `./.eidetic/memory` (public; in-repo routing
needs `eidetic >= 0.10.0`); `--visibility private` keeps it in `$HOME` (uncommitted)
and `/recall` reads both. Don't store what the repo already records (code structure,
git history, this file, `CHANGELOG.md`) — store what you'd have to re-derive. These
are the `recall`/`remember` skills, backed by the `eidetic` store.

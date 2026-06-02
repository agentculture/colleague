# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.27.1] - 2026-06-03

### Fixed

- Stop tracking `.devex/data/pr/events.jsonl` — a per-machine devex PR event log that was committed by mistake. Untracked (kept on disk) and added `/.devex/data/` to `.gitignore` so `devex pr` runs no longer dirty the working tree.

## [0.27.0] - 2026-06-02

### Added

- Deprecated back-compat fallbacks for the rename (read-only): the legacy `.convertible/` config + artifact directories are still read (new writes always target `.colleague/`), `CONVERTIBLE_*` environment variables are honored as a fallback (`COLLEAGUE_*` takes precedence), and `identity_env` emits BOTH `COLLEAGUE_IDENTITY` and `CONVERTIBLE_IDENTITY` so sibling AgentCulture CLIs keep inheriting the identity.

### Changed

- **Renamed the project from `convertible` to `colleague`.** The import package is now `colleague`, the CLI ships as two console scripts (`colleague` and its short alias `clg`), and the PyPI distribution is `colleague` (no longer `convertible-cli`).
- Config directory is now `.colleague/` and the environment variables are `COLLEAGUE_*` (e.g. `COLLEAGUE_ENGINE`, `COLLEAGUE_MODEL`, `COLLEAGUE_OTEL_ENABLED`, `COLLEAGUE_IDENTITY`, `COLLEAGUE_VLLM_E2E`).
- Engine/renderer entry-point groups are now `colleague.engines` / `colleague.renderers`; OpenTelemetry service/tracer/meter names and span/metric names are now `colleague.*`.
- pyproject URLs point at `github.com/agentculture/colleague`; SonarCloud `sonar.sources` is now `colleague` and `sonar.projectKey` is now `agentculture_colleague` (the SonarCloud project must be re-keyed externally to match, or coverage uploads 404).

## [0.26.0] - 2026-06-02

### Added

- doc-test-alignment skill is now implemented (issue #76 C3), replacing the stub check.sh: a portable, stdlib-only verifier with four checks behind `scripts/check.sh [--only readme|claude|skills|tests] [--repo PATH] [--json]` (exit 0 aligned / 1 drift / 2 usage). (c) SKILL.md script-claims-vs-scripts is deterministic and GATES CI; (a) README + (b) CLAUDE.md commands run safe networkless introspection and statically validate networked/drive commands against `convertible --help` (never executing them); (d) test-name-vs-assertion drift is an advisory AST heuristic with inline/file suppression. JSON shape mirrors doctor: {aligned, checks[{id,passed,severity,message,remediation}]}.
- CI now gates on doc-test-alignment check (c) (deterministic) and runs (a)/(b)/(d) as advisory (non-blocking) in the lint job.

### Changed

- docs/skill-sources.md records doc-test-alignment as a first-party implementation diverged from the guildmaster stub (do not re-vendor over it; upstreaming is a follow-up).

## [0.25.0] - 2026-06-02

### Added

- Context-budget graceful degradation in the bounded tool-loop: the running message history is windowed to a configurable token budget (CONVERTIBLE_CONTEXT_BUDGET / EngineConfig.context_budget_tokens, default 24000) before each model turn, and a detected context-overflow error triggers a bounded trim-and-retry before a readable partial result is preserved — a multi-file drive on a small-context model degrades instead of hard-failing (#76 C1).
- Pluggable count_tokens seam (convertible/context.py): the vLLM engine counts tokens exactly via the server /tokenize endpoint, falling back to a zero-dep char heuristic when /tokenize is absent — no third-party tokenizer library, dependencies = [] holds.
- docs/features/graceful-degradation.md documenting the behavior, the /tokenize OpenAI-surface carve-out, and the honest limits.

### Changed

- convertible drive --json now emits the preserved partial TaskResult to stdout on the failure/overflow path (still exiting non-zero, diagnostics on stderr) so a --json consumer gets a parseable result instead of empty stdout (fixes the #76 "convertible produced no result on stdout" symptom).

### Fixed

- A context-window overflow on a small-context model no longer surfaces as an opaque "no result on stdout"; the loop windows + retries, and any unrecoverable drive returns a status=error result with a non-empty step trace.

## [0.24.0] - 2026-06-02

### Added

- Interactive cockpit session (#74 A2): `convertible session` is rebuilt onto the TAUI cockpit. It renders one `CockpitState` (command palette + conversation + popups) through three tiers chosen automatically — the dynamic ANSI cockpit on a colour TTY (redraw-in-place, error popups on failed steps), static **Markdown** menus when piped/captured (`--no-tui` forces it), and `--json` keeping stdout as pure result JSON with the cockpit as stderr chrome.
- Session slash commands (akin to Claude Code / Codex): read-only introspection that folds an existing noun's output into the cockpit (`/help`, `/commands`, `/skills`, `/agents`, `/config`, `/engines`, `/telemetry`, `/feedback`) and live config actions that mutate the session without a restart (`/engine`, `/model`, `/base`, `/pr`). Plain text (number / template name / free-text) still runs a drive.
- A `command_palette` cockpit widget (`convertible/tui/widgets/command_palette.py`) renders a `commands` panel as a numbered menu (ANSI); the Markdown/TAUI views pick it up via generic panel rendering.

### Changed

- `convertible session` non-interactive output is now the full Markdown cockpit (was a terse numbered list); `--json` stdout is unchanged (one `TaskResult` JSON per drive).
- `execute_drive` accepts an optional `progress_sink` so the session injects a sink bound to its own cockpit state (default `None` keeps the `drive` path byte-identical); the live drive frame-writer is factored into a shared `FrameWriter`.

## [0.23.0] - 2026-06-02

### Added

- Live cockpit during a drive (#74 A1): `convertible drive` renders the TAUI cockpit on stderr as it runs — conversation per step and popups on real events (an `error` popup when a tool step fails). Auto-on an interactive TTY; `--tui` / `--no-tui` force it; off a TTY it falls back to the plain `step N:` lines, byte-identical.
- Live `DriveStep` event stream (#74 A3): `drive --tui-events PATH` appends one JSONL event per step as the drive runs (the format `tui replay` / `tui snapshot` consume); a stream written into the driven repo is treated as harness telemetry, never swept into the drive branch.
- `tui replay --trace <id>.trace.jsonl` (#74 A4): fold a finished drive's loop-step trace into the cockpit. Live and replayed steps read identically — one shared converter (`convertible/tui/from_drive.py`) and the same pure reducer.
- NO_COLOR / TTY-aware color gating helpers (`convertible/tui/colors.py`, #74 A5): the live cockpit strips ANSI escapes when `NO_COLOR` is set or the stream is not a terminal.

### Changed

- A failed `DriveStep` now opens an `error` popup in the pure reducer (so it surfaces identically live, in `tui replay`, and in `tui replay --trace`).
- The ANSI conversation widget now renders the reducer-produced `panel.conversation` and accepts a multi-line per-step summary, so a live drive shows its steps.

## [0.22.0] - 2026-06-02

### Added

- outsource explore/review now copy their artifact (plus a last_drive pointer) back to the real repo before the throwaway worktree is removed, so a read-only outsourced drive can be graded with `outsource feedback last` / `convertible feedback record last` (#75 C4).
- Command-template recipes can be committed in-repo: `.convertible/commands/` is no longer gitignored (run artifacts, hooks.json, approvals.json stay local), with a committed `doc-review` example recipe (#75 C5).
- Reverse-coverage test: every registered CLI verb must have an `explain` catalog entry and every action-noun must expose `overview` (#75 D1).

### Changed

- `convertible drive` now returns you to the branch (or detached commit) you started on after it commits — the `convertible/<id>` drive branch keeps the commit, but a drive no longer strands you on it (all commit paths, incl. `--no-pr` and `session`) (#75 C2). Side effect: successive `session` drives now branch independently from your base rather than chaining on the previous drive.

### Fixed

- The read-only outsource artifact-preservation path (#75 C4) now validates the drive `task_id` as a single safe path segment before joining it into a copy destination (mirroring `convertible/feedback.py`), so a malformed/hostile TaskResult can no longer escape `.convertible/`; and it only reports the preserved real-repo path (and writes `last_drive`) when the copy actually succeeds, never claiming an artifact that isn't there.

## [0.21.1] - 2026-06-02

### Added

- docs/features/subagents.md — the missing feature page for the subagent/convoy loop tool; added to the README feature table and the docs/features index.
- README sections for the tui cockpit, the drive-stats/feedback ROI loop, subagents (convoy), and an outsource narrative (all shipped features that the README narrative omitted).

### Changed

- README: corrected the stale Qwen3-32B reference to the current default model sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP; documented doctor --probe (provider_reachable + provider_model_available); added a CHANGELOG pointer and the missing model-selection/tui/stats-and-feedback feature-table rows. Docs-only — no behavior change (#73, umbrella #72).

## [0.21.0] - 2026-06-01

### Added

- `convertible tui render --format ansi|markdown` — a Markdown render of the cockpit, the agent-facing readable third view beside the JSON (TAUI) mirror and the ANSI live screen; `--json` wraps the chosen format (`{"markdown": ...}`).
- `tui snapshot` now writes a quad — a 4th file `<name>.md` (the Markdown render) alongside `<name>.taui.json` / `<name>.ansi` / `<name>.events.jsonl`; legacy triples without a `.md` still read fine.
- `diagnose` now verifies the Markdown frame too — its RENDER faithfulness check runs against the Markdown when present, so `tui diagnose` on a quad proves the JSON mirror and the Markdown agree (zero findings = faithful; a finding = drift). Markdown and JSON are both pure functions of one `CockpitState`, so any disagreement is a render-fidelity bug, never a data divergence.

### Changed

- diagnose success message now reads "the captured views agree" (a snapshot is a quad, no longer a triple).

## [0.20.0] - 2026-06-01

### Added

- `tui` command — an agent-readable terminal UI (issue #69). Every visual frame has a TAUI (Textual Agentic UI) semantic mirror an agent can read, operate by stable dotted-path selector, snapshot, replay deterministically, and diagnose — no OCR or terminal guessing.
- TAUI semantic mirror (`convertible/tui/taui.py`, schema 0.1): the live sibling of the drive artifact, derived via `serialize(state)` from a canonical `CockpitState`; selectors are dotted paths into the tree (no second table to drift).
- Pure Elm-style core: `event -> reduce(state, event) -> State -> serialize()=TAUI + ANSI render`. The reducer is pure (no clock/randomness); animation advances only via injected `tick` events, so replays are byte-identical.
- Snapshot triple (`<name>.taui.json` + `.ansi` + `.events.jsonl`) + deterministic replay; `tui` headless subcommands `render`/`state`/`inspect`/`action`/`replay`/`snapshot`/`test`/`diagnose`/`overview`, all `--json`, plus a guarded `tui live` foreground TTY driver.
- `diagnose`: a pure stdlib cross-mirror differ that classifies 7 bug classes (state/render/layout/focus/input-routing/theme/popup-lifecycle) with no LLM and no network.
- Renderer-is-a-wheel: a hand-rolled stdlib ANSI renderer ships zero-deps as the default; Rich/Textual is an opt-in `[tui]` extra discovered via a new `convertible.renderers` entry-point group.
- JSON scenario runner (`tui test --scenario`) + bundled `boost-popup.scenario.json`; docs at `docs/features/tui.md`.

## [0.19.0] - 2026-06-01

### Added

- doctor --probe provider_model_available check: warns (advisory) when the configured model is not in the provider/v1/models list, naming both the configured id and the served ids with a remediation; omitted when the list cannot be enumerated
- vLLM engine _post_json now folds the HTTP error body into the raised HTTPError, so a wrong-model 404 reads "…model `X` does not exist" instead of a bare "HTTP Error 404: Not Found"

### Changed

- Built-in default model is now sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP (the model the reference rig serves at localhost:8001), so a bare drive reaches a live model instead of a 404; override with CONVERTIBLE_MODEL or --model

## [0.18.0] - 2026-05-31

### Added

- **Drive statistics + feedback loop (the ROI loop)** — calculate the ROI of outsourcing to convertible. Every drive artifact now carries an always-on `stats` block (`TaskResult.stats` / `DriveStats`): request, ISO start + wall-clock duration, model turns, step count, per-tool counts, files changed, exact UTF-8 `bytes_written`, and reasoning-vs-answer char/byte sizes. Populated chassis-side in `convertible/loop.py` so every engine fills it identically (all-engines rule).
- `convertible feedback record|show|overview` — grade a finished drive by `task_id` or `last` with a 1-5 rating + notes, stored as a single record per drive (`<task_id>.feedback.json`) beside the artifact via a stdlib JSON store (`convertible/feedback.py`). A per-repo `last_drive` pointer (written by `execute_drive`) resolves `last`. An ungraded drive reads back as a clean no-op, never an error.
- `outsource feedback <id|last>` skill verb — grade an outsourced drive (with `--rating`) or show its feedback (without), shelling to `convertible feedback`.
- vLLM engine now captures `message.reasoning` (the chain-of-thought, previously discarded) into `ModelResponse`, measured as reasoning chars/bytes in the stats.
- OpenTelemetry parity: two new metrics `convertible.generated.chars` (attr `kind`=reasoning|answer) and `convertible.bytes_written`, a strict no-op when telemetry is off.

### Changed

- Tokens stay verbatim from the model response `usage` (never estimated). Since the served model reports no reasoning-token breakdown, thought-vs-written is measured as chars/bytes, not tokens (no tokenizer, zero deps) — documented honestly.

## [0.17.0] - 2026-05-31

### Changed

- `outsource write` now **previews by default** (#61): without `--apply`/`--pr` it runs the change in a throwaway `git worktree` at HEAD, prints the would-be diff, and discards it — nothing touches your working tree. New `--apply` flag lands the change on a `convertible/<id>` drive branch in place; `--pr` implies `--apply`. The dirty-tree guard now applies only when actually applying.
- The git-repo guard now covers **every** `outsource` verb (previously only the read-only verbs): a non-repo `--repo` fails fast with a clear message instead of an opaque mid-drive error. `git -C`-style targeting is unchanged.

### Fixed

- outsource: `mktemp -d` is given an explicit template (`${TMPDIR:-/tmp}/outsource.XXXXXX`) so the read-only/preview worktree setup is portable on BSD/macOS mktemp (#61).
- outsource: `print_result` routes the result digest to **stderr** on a failed drive (status != ok), keeping stdout clean for scripting; it still exits non-zero (#61).
- outsource: `review` validates that `--base` resolves to a real commit/ref before interpolating it into the LLM review instruction — fails fast on a bogus/unknown ref (#61).
- outsource: `render_prompt` substitutes `$ARGUMENTS`/`$BASE` in a single `re.sub` pass, so a literal `$BASE` inside the user argument survives verbatim instead of being clobbered by a second replace pass (#61).

## [0.16.1] - 2026-05-31

### Added

- `docs/features/model-selection.md`: an operator guide for how convertible
  resolves the engine/model/endpoint (`--engine`/`--model`/`--base-url` → env
  (`CONVERTIBLE_*`, `OPENAI_*`) → defaults), the fact that there is **no model
  config file**, how to point `vllm-openai` at any OpenAI-compatible server, and
  a recipe to keep `CONVERTIBLE_MODEL` auto-synced to a locally-served model
  (generic `/v1/models` lookup, plus model-gear's `model whoami`). Notes that
  subagents inherit the parent model. Linked from `engines.md` and listed in the
  features index (`docs/features/README.md`). Docs only — no behavior change.

## [0.16.0] - 2026-05-30

### Added

- `outsource` skill (first-party, `.claude/skills/outsource/`): hand a scoped repo task to convertible — a *different* engine/model than the calling agent (the value is diversity, not raw power). Three verbs over `convertible drive`: `explore` (read-only investigation → findings), `review` (an independent second opinion on the committed `<base>...HEAD` diff), and `write` (delegate a small implementation). Read-only verbs run in a throwaway `git worktree` at HEAD, so they cannot touch the working tree; `write` refuses a dirty tree unless `--allow-dirty`. Defaults to a local vLLM model (`mmangkad/Qwen3.6-27B-NVFP4`), overridable via flags/env. Advertised in `convertible learn` and `convertible explain outsource`.

## [0.15.0] - 2026-05-30

### Added

- Subagent delegation ("convoy"): mid-drive, an engine can call a `subagent` tool to delegate a scoped sub-task to a nested in-process child drive on an optional different engine and/or model; the child runs the same bounded loop with no git handoff, and its result is folded back into the parent loop and recorded on `TaskResult.sub_results` (omitted when empty). Engine-judged and optional (like the devague tool), NOT an automatic router/gearbox. Sequential-only and bounded (depth 2 / fan-out 4); parallel subagents are a parked follow-up. Chassis-owned (all-engines rule), zero new runtime deps, no daemon/socket/fork.

## [0.14.0] - 2026-05-30

### Added

- Approval gate: operator-declared `.convertible/approvals.json` gates what the harness executes — `run_command` CLIs by program token (allow/deny, shlex) and hook scripts + command templates by checksum. Approval is tamper-protection: `approve` records a file checksum and a later edit voids it (sha256-default, md5 honored). Skills/AGENTS load freely (declarative, never gated). Per-model overlay, strict no-op default, chassis-owned (all-engines rule), stdlib only. Policy gate, not a sandbox.
- `commands approve <name>` / `hooks approve <name>` CLI verbs record a checksum approval; `commands`/`hooks`/`skills list` show approval/accessibility status and `hooks list` shows the run_command policy; `explain approve`.

## [0.13.0] - 2026-05-29

### Added

- `CONVERTIBLE_ENGINE` environment variable for engine selection; the engine now resolves `--engine` > `CONVERTIBLE_ENGINE` > `vllm-openai` and never silently falls back to the no-op `mock` (#53).
- `usage` oilcheck check-group (`usage_effective_engine`): `convertible doctor` now warns (advisory, stays healthy) when a bare drive would pick the no-op `mock` engine.
- `convertible doctor --probe`: opt-in provider-reachability ping (`provider_reachable`), the one check that opens a network connection — invoked outside the no-network registered check-groups.
- `convertible session --pr`: opt back into push + PR per drive.

### Changed

- Default engine for `drive`/`session` is now `vllm-openai` (the real bundled engine) instead of `mock`; `mock` is reachable only via an explicit `--engine mock` / `CONVERTIBLE_ENGINE=mock`.
- `convertible session` commits locally by default and no longer pushes or opens a PR per typed line; use `--pr` to enable handoff (replaces session's `--no-pr`). `drive` is unchanged (PR by default).

### Fixed

- Talking to `convertible session` (or driving a question like `drive "what can you do?"`) no longer opens surprise PRs via the no-op mock engine, and `convertible doctor` no longer reports a misleading clean bill of health while a bare run would silently drive `mock` (#53).

## [0.12.4] - 2026-05-29

### Added

- Per-step progress output during a drive: each loop step emits a concise line to **stderr** (`step N: <tool> <target> [ok|err]`) in all modes, so long drives are observable while stdout stays the single parseable `--json` result (#38). Chassis-owned in the loop and threaded via `EngineConfig.progress`; both engines forward it (all-engines rule).

### Changed

- Refactored `loop.run` to extract the bounded turn loop into `loop._drive_loop`, enabling clean partial-result preservation and bringing `run`'s cognitive complexity back under threshold (SonarCloud S3776).

### Fixed

- A drive that raises mid-loop (e.g. a per-request timeout) now preserves the partial result: the accumulated `steps`, `usage`, and `changed_files` are written to the artifact with `status=error` and the `*.trace.jsonl` is populated, instead of being discarded for an empty `failed_result` (#37). The CLI still exits non-zero and surfaces the error.
- The per-step progress sink is fail-safe: a raising progress callback is suppressed and never aborts the drive (same observability-not-control guarantee as hooks and neighbour clones).
- The engine-failure remediation hint only claims a "partial trace" when one was actually written; the no-partial fallback path (fresh `failed_result`, empty trace) says "a result artifact was still written".

## [0.12.3] - 2026-05-29

### Changed

- Handoff commit subject is now a concise single line (`convertible: <first line of instruction, truncated>`, falling back to the task id); the full instruction is preserved in the commit body, and the PR title uses the short subject (#40).

### Fixed

- Handoff now commits **only the task's own work** (#39): all tracked modifications (so `run_command` edits to tracked files are captured) plus the new untracked files the drive itself produced — never pre-existing operator work-in-progress, prior runs' `.convertible/` artifacts, or other incidental untracked files. The drive snapshots untracked files before running and passes that baseline to the handoff. `changed_files` is derived from the staged set so the artifact agrees with what actually landed.
- Gitignored task output (e.g. a gitignored `site/`) is now surfaced in the handoff note (`N file(s) produced but not committed (gitignored): …`) instead of being silently dropped (#39); the gitignore check uses `check-ignore --stdin` (no argv limit, no leading-dash ambiguity).
- A no-op handoff (nothing of the task's own to commit) no longer strands the operator on a freshly-created task branch — staging happens before `checkout -B`, so operator state is left untouched.

## [0.12.2] - 2026-05-29

### Changed

- Refactored `loop.run`, `session.run_session`, and `commands.load_command` into focused helpers to bring cognitive complexity under the threshold (SonarCloud S3776); behavior-preserving (all 799 tests pass).
- Collapsed `telemetry status` to a single return path (SonarCloud S3516 BLOCKER).

## [0.12.1] - 2026-05-29

### Changed

- SonarCloud: stop excluding `.claude/skills/**` — skill scripts are production code and are now analyzed and gated like the rest of the tree.
- Coverage: emit repo-relative paths in `coverage.xml` (`[tool.coverage.run] relative_files`) so SonarCloud imports coverage instead of reporting none.

### Fixed

- Skill shell scripts: 47 lint findings across agent-config/cicd/communicate/assign-to-workforce/think/spec-to-plan/sonarclaude — use `[[ ]]` tests (S7688), name positional params as locals (S7679), route an error to stderr (S7677).
- Code smells in convertible/: dedupe the `--json` help and `.convertible` literals into constants (S1192), give the no-op telemetry methods docstrings (S1186), merge implicit string concatenations (S5799), rename the `_Span._span` field (S1700), tidy the `$N` placeholder regex (S6353), drop the redundant `JSONDecodeError` except clause (S5713), and fix a malformed `noqa` comment (S7632).
- Tests: stop using publicly-writable `/tmp` paths — switch real artifact writes to the `tmp_path` fixture and string-only paths to a neutral placeholder (S5443).

## [0.12.0] - 2026-05-29

### Added

- Per-model fixes — adapt the harness to a model's known biases. `load_hooks` now resolves a per-model hooks overlay `.convertible/<model>/hooks.json` (model token sanitized via `layers.sanitize_model`) and composes its entries ahead of the base `.convertible/hooks.json` per event, so the loop's first-deny/rewrite-wins gives the per-model fix priority. Exact-path per-model isolation (model X never loads model Y's overlay, no sibling globbing); strict no-op for models without an overlay; the driving model is threaded into the loop's hook load automatically (both engines). `convertible hooks list --model <m>` shows the composed set with per-model entries first, scope-tagged; `explain hooks` documents the overlay + precedence. New feature doc `docs/features/per-model-configuration.md` (the car-metaphor: convertible 'adjusts seat and mirrors' to fit the driving model) with an F9 footer-bias worked example. No new runtime dependency, socket, daemon, or `mcp.json`. Built via /assign-to-workforce — 6 TDD-gated tasks across 3 file-disjoint waves.

## [0.11.3] - 2026-05-29

### Added

- Build plan for per-model fixes (`docs/plans/2026-05-29-convertible-lets-an-operator-configure-per-model-f.md`): 6 TDD-gated tasks across 3 dependency waves covering all 15 spec coverage targets — per-model hooks overlay resolution + composition (`hooks.py`), loop wiring, an isolation test, a zero-deps/no-op guard, a `hooks list --model` CLI surface, and an F9 worked example plus a `per-model-configuration.md` feature doc (the car-metaphor 'adjust seat and mirrors'). Converged via devague /spec-to-plan. Plan only; not yet built.

## [0.11.2] - 2026-05-29

### Added

- Spec: per-model fixes that adapt the harness to a model's known biases (`docs/specs/2026-05-29-convertible-lets-an-operator-configure-per-model-f.md`) — converged via devague `/think`. Proposes a per-model hooks overlay (`.convertible/<model>/hooks.json`) resolved with the same `sanitize_model` + `configdir` machinery as `layers.py` and composed with the base model-blind `.convertible/hooks.json`, with the per-model fix evaluated first (first deny/rewrite wins). Spec only; not yet planned or built.

## [0.11.1] - 2026-05-29

### Added

- Drive-evaluation log under `docs/drive-notes/`: a repeatable, time-series record of convertible self-drive experiments — per-run `stats.json` (timing, iterations, operator nudges, tokens, validation, factual findings), qualitative `notes.md`, preserved `output/` (the built site + render) and raw drive `artifacts/`, a cross-run `index.csv`, a `README.md` defining the schema, and a `repro.sh`. First entry: the 2026-05-29 website-self-build drive.

## [0.11.0] - 2026-05-29

### Changed

- culture loop tool: the inspection-CLI allow-list entry is renamed `agex` -> `devex` (issue #33), matching the cicd skill's standardization on the `devex` name in PR #32 (devex is the same tool as agex, invoked under the `devex` name). The engine-visible `culture` tool schema `enum` is now {agtag, devex}. `agtag` is unaffected. Chassis-owned, so every engine sees the renamed allow-list identically (all-engines rule).

## [0.10.0] - 2026-05-29

### Added

- Destination: an engine can set and converge a devague goal-frame via a curated `devague` loop tool when a task warrants one, drive toward it, and declare the announcement on arrival (the car-metaphor sibling to GPS).
- `devague` loop tool (convertible/devague.py + convertible/tools.py): shells out to the operator-installed devague CLI with cwd + CONVERTIBLE_IDENTITY injected; curated move allow-list (new/capture/interrogate/park/converge/status/show) that structurally excludes the user-only confirm/reject and operator-only export. No runtime dep, no import, no socket, no daemon (the culture-tool pattern; all-engines rule).
- Lightweight arrival declaration: additive optional TaskResult.destination + announcement fields (omitted from the JSON artifact when unset, so a no-destination drive serializes byte-identically); finish gains optional destination/announcement, recorded by the loop.
- Chassis system-prompt guidance (inherited by every engine): setting a destination is optional and engine-judged; convergence is advisory and operator-authoritative; the engine cannot self-confirm.

### Changed

- Boundary guards (tests/test_boundary.py) sanction convertible/devague.py as a subprocess transport with no daemon primitives; the zero-deps guard now imports convertible.devague.
- cicd skill (.claude/skills/cicd): the PR lifecycle now drives `devex pr` instead of `agex pr` (devex is the same tool as agex, invoked under the `devex` name); `workflow.sh open` opens PRs via `devex`, never `gh` directly. Agent env override renamed to `STEWARD_DEVEX_AGENT` (legacy `STEWARD_AGEX_AGENT` still honored).

### Fixed

- The `devague` and `culture` loop tools now map a CLI timeout (`subprocess.TimeoutExpired`) and other launch failures (`OSError`) to a clean tool error instead of letting it escape `ToolExecutor` and crash the drive (Qodo review on #32).

## [0.9.0] - 2026-05-28

### Added

- Mesh-member integration: a convertible drive can run as a named AgentCulture identity (convertible/identity.py — culture.yaml nick / .convertible/identity.json, propagated via CONVERTIBLE_IDENTITY)
- Curated culture loop tool (convertible/culture.py): one identity-injected tool shelling out to allow-listed AgentCulture CLIs (agtag, agex) — the documented re-spec of the closed five-tool surface
- Read-only neighbour clones (convertible/neighbours.py): operator-configured .convertible/neighbours.json allow-list, shallow clone, refresh-on-demand, cloned at drive start and cleaned up at finish (ephemeral, empty by default)
- Per-feature mesh-member doc + feature-index and README updates

### Changed

- Tool-loop surface extended from five to six tools (added culture); loop wires neighbour clone-at-start and cleanup-at-finish into the chassis so every engine inherits it (all-engines rule)
- run_command refuses to execute paths inside the neighbour clone tree (best-effort; clones are inert read-only source)

## [0.8.1] - 2026-05-28

### Added

- docs/features/ — a feature index plus one focused doc per shipped feature (drive/loop, engines, handoff, artifact, command templates, hooks, session, layered config, telemetry, doctor, agent-first CLI), each with source pointers and cross-links

### Changed

- README: documented the doctor/oilcheck check-groups, added a Feature docs index, and filled the What-ships-in-v0 list with the layered-config, GPS/telemetry, and doctor features it was missing

## [0.8.0] - 2026-05-28

### Added

- `convertible/oilcheck/` package — a read-only check-group registry + `diagnose()` aggregator that the `doctor` verb renders (chassis-level, like telemetry).

### Changed

- `doctor` is now a configuration-readiness health check (convertible's "oilcheck"), broadened from agent-identity invariants to a full read-only battery: identity, provider config (with redacted api_key + advisory provider_budget warning), engine wheels (all-engines, asserts bundled mock + vllm-openai), otel readiness, and environment (.convertible/hooks.json/command templates, AGENTS/skills layering, git/gh handoff prereqs, CLI integrity). Emits the rubric-shaped {healthy, checks[]} report; exits 1 on any error-severity check. Diagnose-only (no --fix); zero new runtime deps.

## [0.7.0] - 2026-05-28

### Added

- GPS: opt-in OpenTelemetry traces + metrics for a drive (issue #22). Spans (`convertible.drive` -> `convertible.tool.*` -> `convertible.handoff`) and metrics (steps, tokens, tool latency, tool calls, hook denials, drive duration) emit over OTLP from the loop + the shared drive path, so every engine is instrumented identically (all-engines rule).
- `convertible telemetry status` / `overview` introspection noun, plus an explain catalog entry.
- `TelemetryConfig` resolved from `CONVERTIBLE_OTEL_*` / standard `OTEL_*` env vars (`OTEL_SDK_DISABLED` honored as a kill-switch).
- Optional `[otel]` extra (opentelemetry SDK + OTLP/HTTP exporter); install with `pip install "convertible-cli[otel]"`.

### Changed

- `loop.run()` and `execute_drive` accept/own telemetry, defaulting to a no-op resolved from the environment (mirrors the hooks pattern). Off by default it is a strict no-op: no spans, no SDK import, `TaskResult` unchanged.

## [0.6.0] - 2026-05-28

### Added

- Layered per-model config: AGENTS instructions (`AGENTS.md` -> `AGENTS.convertible.md` -> `AGENTS.convertible.<model>.md` at the repo root, with a `~/.convertible/` fallback) and skills (`.convertible/skills/*.md` -> `.convertible/<model>/skills/*.md`) compose into the engine system prompt via `convertible/layers.py`
- `convertible agents` and `convertible skills` introspection nouns (list + overview, `--json`, `--model`)
- `Engine.system_prompt()` base-class helper injects the layered prompt for every engine (all-engines rule)

### Changed

- Both engines (mock, vllm-openai) now pass a model-specific `system_prompt` to the loop; behavior is byte-identical when no AGENTS/skills files exist

## [0.5.0] - 2026-05-27

### Changed

- Bare `convertible` (no subcommand) now opens the interactive harness (the `session` palette) when run at a terminal — the natural "get in and drive" gesture. Piped, redirected, or otherwise non-interactive, it still prints usage, preserving the discoverable surface for scripts and agents. `-h/--help` is unaffected.
- Reframed `convertible drive` help and `explain` text to lead with the goal/instruction ("drive toward a goal") rather than "run a repo task"; the repo is the target, not the headline. No behavior change.

## [0.4.0] - 2026-05-27

### Added

- Convertible ASCII banner on 'drive' and 'session' start (issue #15): decorative chrome shown only on an interactive TTY and suppressed in --json, so it never pollutes the stdout result stream or agent-parsed stderr.

## [0.3.0] - 2026-05-27

### Added

- Command templates discovered under .convertible/commands/*.md, expanded into a Task via `drive --command <name> [args]` ($ARGUMENTS / $1 substitution).
- Lifecycle hooks (.convertible/hooks.json): operator shell commands fired at task_start/pre_tool/post_tool/finish; a pre_tool hook can allow, deny, or rewrite a tool call (Claude-Code-style stdin-JSON + exit-code/structured-stdout I/O contract).
- Interactive foreground palette: `convertible session` over the shared drive path.
- Agent-first CLI: `convertible commands list/overview` and `convertible hooks list/overview`.
- Result artifact now records every hook firing and the originating command.

### Changed

- Hook lifecycle is wired into the engine-agnostic loop, so it binds every engine (all-engines rule); the chassis is no longer purely one-shot.
- Repo-shipped hooks run by default under the trusted-operator-env model (a per-repo trust gate / opt-out is a documented follow-up, not yet built).

### Fixed

- Hook execution and matching failures (subprocess timeout, launch error, invalid matcher regex) now map to a structured fail-closed decision instead of crashing the drive.
- The originating command is persisted in the result artifact on the failure path and for session-run templates (previously recorded as null).
- `convertible session` routes errors/diagnostics to stderr and honors `--json` (one JSON result per drive on stdout, palette chrome to stderr).
- `hooks list` reads entries via the public `HookConfig.all_entries` accessor (removed an unjustified lint suppression).

## [0.2.2] - 2026-05-27

### Added

- README tip (anecdotal, n=1): qwen3_coder handled tool-argument escaping more reliably than hermes for an NVFP4 Qwen3 checkpoint — a hermes run over-escaped docstring triple-quotes into a SyntaxError. Framed as a single observation, not a benchmark.

## [0.2.1] - 2026-05-27

### Changed

- Generalized the vLLM tool-call-parser docs from hermes-specific to model-appropriate (e.g. hermes or qwen3_coder); the engine is parser-agnostic and only needs OpenAI-format tool calls. Touches vllm_openai docstring, the live-proof test docstring, README, and CLAUDE.md.

## [0.2.0] - 2026-05-27

### Added

- convertible drive: run a repo task through a swappable coder engine (bounded agentic tool-loop: read_file/write_file/list_dir/run_command/finish, repo-confined)
- convertible wheels list: discover engine wheels via the convertible.engines entry-point group
- Shared task contract (Task/TaskResult) with lossless JSON round-trip
- Two bundled engines: deterministic networkless mock, and vllm-openai driving any OpenAI-compatible /v1/chat/completions endpoint with tool calling (stdlib urllib, no SDK)
- Git/PR handoff: branch/commit/push + gh pr create, gated by --no-pr/no-remote for offline/CI
- JSON result artifact + step-trace dashboard under .convertible/
- Opt-in live vLLM end-to-end test (CONVERTIBLE_VLLM_E2E=1)

### Changed

- CLAUDE.md expanded from the /init seed into a full runtime prompt for the harness
- README rewritten to document the engine/driver/chassis/wheels architecture and the v0 boundary

### Fixed

- Loop now serializes outbound tool-call `arguments` as a JSON string (OpenAI wire format), so multi-turn vLLM tool loops aren't rejected by strict servers (Qodo #1)
- `drive` attempts handoff whenever the drive succeeds (not only when `write_file` ran), so edits made via `run_command` are committed/pushed; `changed_files` is backfilled from `git status` (Qodo #2)
- Handoff note no longer claims "local commit only" when the push succeeded but `gh pr create` failed (Qodo #4)
- Reduced the "wheel/garage" pun in the running CLI's user-facing output, keeping external messaging engine-centric (Qodo #3)

## [0.1.2] - 2026-05-27

### Changed

- **Renamed the PyPI distribution from `convertible` to `convertible-cli`** — the
  bare `convertible` name was unavailable/ambiguous on PyPI. Only the published
  distribution name changes; the import package (`convertible/`), the `convertible`
  CLI entry point, and the wheel build target are unchanged. Updated the TestPyPI
  install hint in `.github/workflows/publish.yml` to match.

## [0.1.1] - 2026-05-26

### Changed

- **CI gates on the SonarCloud quality gate**
  ([issue #3](https://github.com/agentculture/convertible/issues/3)) —
  added `sonar.qualitygate.wait=true` to `sonar-project.properties` so a failing
  gate fails the `test` job when `SONAR_TOKEN` is set. Token-less repos and fork
  PRs remain green (the scan step is guarded by `if: env.SONAR_TOKEN != ''`).

## [0.1.0] - 2026-05-26

### Added

- **Onboarded into the AgentCulture mesh** ([issue #1](https://github.com/agentculture/convertible/issues/1)).
- **Agent-first CLI** cited from teken's (`afi-cli`) `python-cli` reference
  (`teken cli cite`) — verbs `whoami`, `learn`, `explain`, `overview`, `doctor`,
  and the `cli` noun group. Runtime is self-contained (`dependencies = []`);
  `teken>=0.8` is a dev dependency only. Passes the seven-bundle agent-first
  rubric (`teken cli doctor . --strict`). `doctor` checks the agent-identity
  invariants (prompt-file-present, backend-consistency, skills-present).
- **Mesh identity**: `culture.yaml` (`suffix: convertible`,
  `backend: claude`) and the matching `CLAUDE.md` prompt file.
- **Canonical guildmaster skill kit** (11 skills) vendored under
  `.claude/skills/` (cite-don't-import): `agent-config`, `assign-to-workforce`,
  `cicd`, `communicate`, `doc-test-alignment`, `pypi-maintainer`, `run-tests`,
  `sonarclaude`, `spec-to-plan`, `think`, `version-bump`. Every `SKILL.md`
  carries `type: command` (load-bearing for the culture/claude backend);
  `cicd` / `communicate` consumer-identifying prose adapted, all script bodies
  verbatim. Provenance in `docs/skill-sources.md`. Three skills (`think`,
  `spec-to-plan`, `assign-to-workforce`) originate in `devague`, re-broadcast
  via guildmaster.
- **Build + deploy baseline**: `pyproject.toml` (hatchling), `tests/` (pytest,
  xdist, coverage), `.github/workflows/{tests,publish}.yml` (CI rubric/lint gate,
  PyPI Trusted Publishing), `.flake8`, `.markdownlint-cli2.yaml`,
  `sonar-project.properties`, and `.claude/skills.local.yaml.example`.

### Changed

### Fixed

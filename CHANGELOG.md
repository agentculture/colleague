# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

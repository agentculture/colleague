# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

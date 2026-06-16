# Build Plan — Colleague work hands back lint-clean code by default: before every git handoff it detects the repo's configured linters (black, isort, flake8, ruff) and auto-fixes what it can as a pre-finish gate, so a delegated colleague work no longer needs an integrator lint-fix pass

slug: `colleague-work-hands-back-lint-clean-code-by-defau` · status: `exported` · from frame: `colleague-work-hands-back-lint-clean-code-by-defau`

> Colleague work hands back lint-clean code by default: before every git handoff it detects the repo's configured linters (black, isort, flake8, ruff) and auto-fixes what it can as a pre-finish gate, so a delegated colleague work no longer needs an integrator lint-fix pass

## Tasks

### t1 — contract.py: add LintReport dataclass + TaskResult.lint_report (omit-when-empty)

- covers: c16, h3
- acceptance:
  - A TaskResult with no lint findings serializes byte-identically to today (lint_report key absent from JSON); a populated LintReport (fixed[], residual[], skipped[]) round-trips through to_dict/from_dict

### t2 — config.py: lint opt-out resolution on EngineConfig (lint enabled + lint_fix_retries) wired into resolve() + load_config_file

- covers: h7
- acceptance:
  - EngineConfig.resolve yields lint enabled by default; an explicit flag, COLLEAGUE_LINT=0 env, and .colleague/config.json {lint:false} each disable it with precedence flag>env>config>default-on; COLLEAGUE_LINT_FIX_RETRIES resolves to int (default 1) via the same precedence

### t3 — colleague/lint.py: linter detection + curated pre-finish gate + tests/test_lint.py (TDD)

- depends on: t1
- covers: c2, c6, c7, c8, c15, c16, h2, h7, h11, h12, h13
- acceptance:
  - detect_linters parses [tool.black]/[tool.isort]/[tool.ruff] from pyproject.toml (stdlib tomllib) and [flake8] from setup.cfg/.flake8/tox.ini (stdlib configparser), returning an empty result for an unconfigured repo
  - run_lint_gate shells out ONLY to black/isort/ruff/flake8 (curated allow-list, never an arbitrary program) and operates ONLY on the supplied changed-files list, returning a LintReport of fixed + residual violations
  - a configured-but-missing linter binary is skipped with a recorded note and never raises; lint.py is the only colleague module that imports subprocess

### t4 — loop.py + mock/vllm backends: wire the pre-finish lint gate (bounded model fix-turn, non-blocking, top-level only)

- depends on: t1, t2, t3
- covers: c4, c14, h1, h5, h9
- acceptance:
  - after the work loop and before handoff, when lint is enabled and the work item changed files, the gate runs on the changed files and attaches the LintReport to TaskResult
  - if residual reporter violations remain it injects ONE bounded model fix-turn capped by lint_fix_retries (default 1), then proceeds to handoff regardless of any leftover (never wedges); fires once at the top level, not per-subagent
  - the gate fires identically for mock and vllm-openai (config forwarded via ContextControls); no lint logic lives in any engines/* module beyond config forwarding; lint disabled OR no files changed is a strict no-op

### t5 — work.py CLI: --no-lint flag + residual lint surfaced to stderr

- depends on: t1, t2
- covers: c5, h10
- acceptance:
  - colleague work accepts --no-lint and threads it into EngineConfig resolution; a default run has lint on
  - residual lint violations from TaskResult.lint_report print to stderr (never stdout) as a warning, and --json output carries the lint_report payload

### t6 — tests: boundary + zero-deps + e2e-shape guards for the lint gate

- depends on: t3, t4
- covers: c1, c3, c9, h8, h14
- acceptance:
  - test_boundary.py sanctions exactly colleague/lint.py as a subprocess consumer and still fails if any OTHER module gains a subprocess import
  - test_zero_deps.py imports colleague.lint and asserts no third-party import leak; pyproject.toml dependencies stays []
  - test_e2e_mock.py proves the lint_report behavior is identical for mock and vllm and that a repo with no configured linter yields a byte-identical TaskResult (lint_report absent)

### t7 — docs: CLAUDE.md lint-gate architecture bullet + docs/features/lint-gate.md

- depends on: t3, t4, t5
- covers: c7, c8
- acceptance:
  - CLAUDE.md gains a Lint gate bullet covering the pre-finish gate, default-on/opt-out, curated allow-list, bounded fix-turn, and HONEST limits (python-only, changed-files scope, not a CI replacement, missing-binary degradation)
  - docs/features/lint-gate.md documents detection, the fix-then-surface flow, the opt-out knobs, and a worked example

### t8 — version bump (minor) + CHANGELOG entry

- depends on: t4, t5, t6, t7
- acceptance:
  - pyproject.toml and colleague/__init__.py bump one minor version; CHANGELOG.md prepends a Keep-a-Changelog entry for the lint pre-finish gate; the version-check CI job passes

## Risks

- [unknown_nonblocking] Changed-files source: t4 must reuse the tool executor's write-tracking / git diff vs base_sha to scope the gate; if unavailable it falls back to git status in the isolation worktree (task t4)
- [follow_up] The bounded model fix-turn needs a live backend; on mock it is a no-op (no real fix) — acceptable under all-engines (fires identically, produces no edit), demonstrated by the e2e test (task t4)
- [follow_up] ruff standalone config (ruff.toml/.ruff.toml) and non-pyproject black/isort config are not detected in v1 — pyproject sections + setup.cfg/.flake8/tox.ini [flake8] only; standalone ruff.toml is a documented follow-up (task t3)

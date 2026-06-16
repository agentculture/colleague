# Colleague work hands back lint-clean code by default: before every git handoff it detects the repo's configured linters (black, isort, flake8, ruff) and auto-fixes what it can as a pre-finish gate, so a delegated colleague work no longer needs an integrator lint-fix pass

> Colleague work hands back lint-clean code by default: before every git handoff it detects the repo's configured linters (black, isort, flake8, ruff) and auto-fixes what it can as a pre-finish gate, so a delegated colleague work no longer needs an integrator lint-fix pass

## Audience

- An operator delegating a coding task to colleague (work/drive, and ask-colleague write --apply) in a repo that configures Python linters (black/isort/flake8/ruff)

## Before → After

- Before: colleague returns functionally-correct code (its own pytest passes) that fails the repo lint gate — flake8 F401/E501, black/isort formatting — so every delegated task needs an avoidable integrator lint-fix pass after handoff
- After: Before the git handoff, colleague detects the repo's configured linters and auto-fixes the work item's changed files, so a delegated colleague work lands lint-clean by default with no integrator fix-up

## Why it matters

- The recurring integrator lint-fix pass is the tax that made delegation feel unfinished; removing it is what makes 'delegate to colleague' actually save the requester work

## Requirements

- Runtime-owned: the lint gate fires from the loop/handoff pre-finish path so it behaves identically for mock and vllm-openai (all-engines rule), exactly like hooks/telemetry/stats
  - honesty: There is no lint code in any colleague/engines/* backend module; the gate is invoked once from colleague/loop.py (or the shared execute_work path) and the e2e mock/vllm shape test proves identical lint_report behavior
- Zero new runtime deps: detect linters by parsing config with stdlib (tomllib for pyproject.toml, configparser for setup.cfg/.flake8/tox.ini); shell out only to the curated linter allow-list (black/isort/flake8/ruff), the same permitted-subprocess exception as the culture/devague tools, sanctioned in a new colleague/lint.py and the boundary test
  - honesty: pyproject.toml keeps dependencies = []; the zero-deps guard still passes; lint.py is the only new module that imports subprocess, and test_boundary.py is updated to sanction exactly it (curated allow-list black/isort/flake8/ruff, no arbitrary program)
- Strict no-op when no linters are configured (or all are opted out): TaskResult is byte-identical to today, and TaskResult.lint_report is omitted-when-empty like destination/announcement so the e2e shape test stays green
  - honesty: With no [tool.black]/[tool.isort]/[tool.ruff]/[flake8] section detected, run_lint_gate returns an empty report and TaskResult serializes byte-identically to a pre-feature run; lint_report is absent from the JSON when empty

## Honesty conditions

- After a colleague work item in a linter-configured repo, the handed-off branch passes that repo's own lint gate (black --check / isort --check / flake8) with zero integrator edits
- The feature activates only for an operator whose repo configures at least one of black/isort/flake8/ruff; for every other repo it is invisible (strict no-op)
- Reproducible today: a colleague work item on the colleague repo itself produces black/isort/flake8 violations that need a manual fix-up before the repo lint gate passes
- After the gate, re-running the repo's own lint commands on the changed files reports clean, except for any residual the bounded model fix-turn could not resolve (which is surfaced, not hidden)
- The operator can merge the handed-off branch with zero separate lint-fix edits — measurable as no integrator lint commit on top of the colleague diff
- git diff of the handoff shows edits only to files the work item already touched; a pre-existing violation in an untouched file is never modified by the gate
- In a repo with no Python linter configured (e.g. a JS-only repo) the gate detects nothing and is a strict no-op; non-Python linters are explicitly deferred
- The gate shells out only to the curated allow-list black/isort/flake8/ruff, opens no socket/daemon, runs no arbitrary program, and is best-effort (not a guarantee equal to CI)
- Demonstrated end-to-end: a delegated work item on a linter-configured repo lands a branch passing black --check/isort --check/flake8 with no integrator edit; a no-linter repo yields a byte-identical TaskResult (e2e shape test pins it)
- Default-on bites only in repos that actually configure a linter; with --no-lint / COLLEAGUE_LINT=0 / config lint:false the gate never runs and behavior is byte-identical to today
- The fix-turn reuses the existing bounded-retry precedent (_MAX_TIMEOUT_RETRIES/finish-nudge): COLLEAGUE_LINT_FIX_RETRIES defaults to 1, the loop always proceeds to handoff on exhaustion (never wedges, per c12), and with the knob at 0 only the deterministic fixers run

## Success signals

- A delegated colleague work in a black/isort/flake8-configured repo lands a branch that passes the repo lint gate with no integrator fix-up; a repo with no configured linters yields a byte-identical TaskResult to today

## Scope / boundaries

- Not a whole-repo reformat: the gate operates only on the work item's changed files, never pre-existing violations elsewhere in the repo
- Python-toolchain only in v1 (black, isort, flake8, ruff); other-language linters and a generic lint hook are a documented follow-up
- Not a sandbox or a CI lint replacement: it is a best-effort, bounded, degradable pre-finish convenience that shells out only to a curated linter allow-list

## Assumptions

- The repo's configured linters are installed in colleague's environment; a configured-but-missing linter binary degrades to skip-with-recorded-note, never crashes the handoff (like the vLLM /tokenize graceful degradation)
- Running the deterministic fixers (black/isort) on a changed file in an already-conformant repo only alters the work item's own new code; in a non-conformant repo the fixer may widen the diff on touched files — accepted and documented

## Decisions

- Default-ON with an opt-out (--no-lint flag, COLLEAGUE_LINT=0 env, .colleague/config.json lint:false) per operator intent — not opt-in; precedence flag > env > config > default-on
- The gate is non-blocking: residual reporter violations are surfaced but never wedge the handoff; the auto-fix changes are folded into the work item's commit so they land with the diff
- Lint fires once at the top-level pre-finish step, after any auto-split/subagent merge — not per-subagent child
- v1 runs the deterministic fixers (black, isort, ruff --fix/format) on the work item's changed files, then the reporters (flake8 / ruff check); if residual violations remain it injects ONE bounded model fix-turn (reusing the finish-nudge / forced-synthesis pattern, capped by COLLEAGUE_LINT_FIX_RETRIES, default 1), re-runs fixers+reporters, then proceeds regardless of any leftover

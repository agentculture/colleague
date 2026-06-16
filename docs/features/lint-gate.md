# lint-gate — auto-lint changed files before handoff

> `colleague work` (and `drive`, and `ask-colleague write --apply`) runs the
> repo's configured Python linters on the work item's **changed files** before
> the git handoff, auto-fixing what it can, so delegated work lands lint-clean
> without a separate integrator lint-fix pass. Born from the plan-mode workforce
> build, where colleague's functionally-correct output kept failing the repo lint
> gate (flake8 F401/E501, black/isort).

The lint gate is a **pre-finish convenience** (#200) that runs on every work item
by default. It is **non-blocking**: the handoff always proceeds; any leftover
residual is surfaced (stderr + the `lint_report` in the JSON artifact), never
wedging the work item.

## Detection (`colleague/lint.py` `detect_linters`)

The gate discovers which linters to run from the repo's own configuration:

- **black / isort / ruff** — detected from a `[tool.black]` / `[tool.isort]` /
  `[tool.ruff]` table in `pyproject.toml` (parsed with stdlib `tomllib`).
- **flake8** — detected from a `[flake8]` section in `.flake8`, `setup.cfg`, or
  `tox.ini` (stdlib `configparser`).

**No linter configured → the gate is a strict no-op.** It never runs a linter
that the repo itself does not declare.

## What it runs (`run_lint_gate`)

The gate operates on the **changed `.py` files only**, in two phases:

1. **Fixers** (auto-fix in place): `isort`, `black`, `ruff check --fix`, `ruff format`
2. **Reporters** (residual violations): `flake8`, `ruff check`

### Curated allow-list

The gate shells out **only** to `black`, `isort`, `ruff`, and `flake8` — never
an arbitrary program. It is the one new module that imports `subprocess`.

A configured-but-missing linter binary is recorded as `skipped` and never
crashes the handoff (graceful degradation).

## The bounded model fix-turn

After the deterministic fixers, if reporter violations remain **and** the work
item finished cleanly, the runtime injects **one bounded model fix-turn** per
remaining retry (capped by `COLLEAGUE_LINT_FIX_RETRIES`, default `1`) asking
the model to fix the residual, then re-runs the gate.

With the knob at `0`, only the deterministic fixers run. The model fix-turn
needs a live backend; on the `mock` backend it is a no-op.

## Opt-out (default-ON)

The gate is **ON by default**. Disable it with:

- the `--no-lint` flag,
- `COLLEAGUE_LINT=0`, or
- `.colleague/config.json` `{"lint": false}`.

**Precedence:** flag > env > config > default-on.

## Where the report lands

`TaskResult.lint_report` — a `LintReport` with `fixed` / `residual` / `skipped`
lists. The field is **omitted** from the artifact when the gate did not run.

## Worked example

The gate runs quietly inside the work item — it adds no per-linter chatter to
stdout. The only thing it prints (to **stderr**) is leftover residual it could
not auto-fix; the full record is in the artifact's `lint_report`.

The common case — every violation auto-fixed, nothing to surface:

```text
$ colleague work "add a utility function to utils/helpers.py" --repo .
… (work item runs; the gate auto-fixes the changed .py with isort/black) …
status: ok
task: a1b2c3d4e5f6
```

The branch lands black/isort-clean with no integrator fix-up. When a reporter
violation survives the fixers *and* the (capped) model fix-turn, it is surfaced
on stderr and recorded — but the handoff still proceeds (non-blocking):

```text
lint: 1 issue(s) not auto-fixed:
utils/helpers.py:3:1: F821 undefined name 'helper'
```

Disable the gate for a run with `--no-lint`.

## Honest limits

- **Python-toolchain only.** The allow-list is `black`/`isort`/`ruff`/`flake8`;
  other-language linters and a generic lint hook are a follow-up.
- **Changed-files scope (not changed-lines).** In a non-conformant repo a fixer
  may widen the diff on a touched file.
- **Standalone `ruff.toml` / `.ruff.toml` and non-pyproject black/isort config
  are not detected in v1.** Only `pyproject.toml` sections and
  `.flake8`/`setup.cfg`/`tox.ini` `[flake8]` are recognised.
- **Best-effort convenience, not a sandbox or a CI lint replacement.** The gate
  is a developer convenience; it does not substitute for CI lint checks.
- **The model fix-turn needs a live backend.** On the `mock` backend it is a
  no-op.

## See also

- [`docs/features/ask-colleague.md`](ask-colleague.md) — the `ask-colleague write --apply` path that triggers the gate
- [`docs/features/agent-cli.md`](agent-cli.md) — `colleague work` and `colleague drive` entry points

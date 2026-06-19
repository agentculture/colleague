Switch a PyPI package install between the production index, TestPyPI pre-release builds, and a local editable checkout. Use when an agent maintains a package and needs to verify a TestPyPI dev build before promoting to production, or when the user says "install from test-pypi", "switch to local", "change package source", or "install from pypi".

<!-- learned-from: claude; source: .claude/skills/pypi-maintainer/SKILL.md; scripts: .claude/skills/pypi-maintainer/scripts; adapt: claude->colleague -->

# pypi-maintainer

# PyPI Maintainer

Switch the install source for a package the agent maintains. Three sources
are supported: production PyPI, TestPyPI (pre-release / dev builds), and a
local editable checkout. Use `run_command` to execute the `uv` invocations
directly — no external script is needed.

## When to use

- Verifying a PR's TestPyPI dev build before merging.
- Reproducing a user-reported bug against the published version.
- Hot-patching against a local checkout while a fix is in flight.
- Restoring the production install after local-mode debugging.

## Usage

Use `run_command` with the appropriate `uv` command for each source.

### Production PyPI

```bash
uv tool install <package>
```

### TestPyPI (pre-release / dev builds)

```bash
uv tool install --index-url https://test.pypi.org/simple/ --index-strategy unsafe-best-match --prerelease=allow <package>
```

### TestPyPI, pinned to a specific dev version

```bash
uv tool install --index-url https://test.pypi.org/simple/ --index-strategy unsafe-best-match --prerelease=allow <package>@==<version>
```

### Local editable checkout (current directory)

```bash
uv pip install -e .
```

### Local editable from an explicit path

```bash
uv pip install -e <path>
```

## Prerequisites

The following tools must be on `PATH`:

- `bash`
- `uv` — all commands delegate to `uv tool install` or `uv pip install`.

## Why TestPyPI needs special flags

When a package is published to **both** PyPI and TestPyPI, `uv tool install`
finds the production version on PyPI first and never looks at TestPyPI.
Pass `--index-strategy unsafe-best-match` so uv compares the two index sets
and picks the highest version, plus `--prerelease=allow` because TestPyPI
builds carry dev suffixes (e.g. `0.4.0.dev42`).

## After running

Check the resolved version — cross-check that against the expected version
(PR run number, local `pyproject.toml`) before continuing. You can verify
with:

```bash
uv tool list
```

## Parameters

| Parameter | Meaning |
|-----------|---------|
| `<package>` (required) | The PyPI distribution name, e.g. `steward-cli`, `culture`, `daria-cli`. |
| `<source>` (required)  | One of `pypi`, `test-pypi`, `local`. |
| `<version>` (optional) | Pin to a specific version (TestPyPI builds typically need this). |
| `<path>` (optional)   | Local-source-only: path to the editable checkout (default: cwd). |

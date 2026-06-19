Run pytest with parallel execution and coverage. Use when running tests, verifying changes, or the user says "run tests", "test", or "pytest".

<!-- learned-from: claude; source: .claude/skills/run-tests/SKILL.md; scripts: .claude/skills/run-tests/scripts; adapt: claude->colleague -->

# run-tests

# Run Tests

Run the project's pytest suite with optional parallelism (pytest-xdist) and coverage.
Coverage targets are read from `pyproject.toml`'s `[tool.coverage.run]` section,
so the same approach works in any sibling repo without modification.

## Usage

Use the built-in `run_tests` tool for the common case, or `run_command` when you
need flags the tool does not expose.

```
# Default: parallel + verbose (recommended)
run_tests

# Specific test file or module
run_tests paths=["tests/test_socket_server.py"]

# Full suite (explicit)
run_tests paths=[]
```

For more control (coverage, xdist options, filtering, etc.) fall back to
`run_command`:

```bash
# Parallel + verbose
uv run pytest -n auto -v

# Parallel + coverage report
uv run pytest -n auto --cov --cov-report=term-missing

# Full CI mode: parallel + coverage + XML report + verbose
uv run pytest -n auto --cov --cov-report=xml -v

# Specific test file
uv run pytest tests/test_rooms.py

# Without parallelism (for debugging test ordering issues)
uv run pytest tests/test_flaky.py -v

# Filter by pattern
uv run pytest -k "pattern" -v
```

## Options (via run_command)

| Flag | Description |
|------|-------------|
| `-n auto` | Run with pytest-xdist across all CPU cores |
| `--cov` | Enable coverage reporting |
| `--cov-report=term-missing` | Show uncovered lines in the terminal |
| `--cov-report=xml` | Produce an XML coverage report (CI) |
| `-v` | Verbose output |
| `-x` | Stop on first failure |
| `-k "pattern"` | Select tests by name pattern |

## When to Use Which Mode

- **After code changes:** `run_tests` — fast parallel run via the built-in tool
- **Quick sanity check:** `run_command "uv run pytest -n auto -q"` — minimal output
- **Before PR / release:** `run_command "uv run pytest -n auto --cov --cov-report=xml -v"` — matches CI exactly
- **Debugging flaky test:** `run_command "uv run pytest tests/test_flaky.py -v"` — sequential, single file

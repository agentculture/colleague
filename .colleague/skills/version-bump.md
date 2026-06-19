Bump the semver version in pyproject.toml (major, minor, or patch) and prepend a Keep-a-Changelog entry to CHANGELOG.md. Use when preparing a release, before creating a PR (the version-check CI job blocks merge if you don't), or when the user says "bump version", "release", or "increment version".

<!-- learned-from: claude; source: .claude/skills/version-bump/SKILL.md; scripts: .claude/skills/version-bump/scripts; adapt: claude->colleague -->

# version-bump

# Version Bump

Bump the semver version in `pyproject.toml` and prepend a new entry to
`CHANGELOG.md`. Mirrors the AgentCulture workflow used by `culture`,
`afi-cli`, `cfafi`, and other org repos; vendored here so the repo is
self-contained.

## Usage

Run from the repo root using colleague's tools.

1. **Read the current version** — use `read_file` on `pyproject.toml` to
   locate the `version = "x.y.z"` field under `[project]`.

2. **Compute the new version** — apply the appropriate bump (see Bump Types
   below).

3. **Bump `pyproject.toml`** — use `edit_file` to replace the old
   `version = "x.y.z"` with the new value.

4. **Update `CHANGELOG.md`** — use `read_file` on `CHANGELOG.md`, then
   `edit_file` to prepend a new `## [x.y.z] - YYYY-MM-DD` entry with the
   appropriate `### Added` / `### Changed` / `### Fixed` sections.

5. **Verify** — use `run_command` with `git diff` to review the changes
   before committing.

## Bump Types

| Type    | Example        | When to use                                                       |
|---------|----------------|-------------------------------------------------------------------|
| `major` | 0.1.0 → 1.0.0  | Breaking changes, namespace restructures, CLI surface breaks      |
| `minor` | 0.1.0 → 0.2.0  | New features, new commands, new modules                           |
| `patch` | 0.1.0 → 0.1.1  | Bug fixes, doc updates, dependency bumps, CI-only changes         |

## Changelog Entry Format

Prepend a new section at the top of `CHANGELOG.md`, directly after the
title line. All subsections are optional — only include non-empty ones.

```markdown
## [x.y.z] - YYYY-MM-DD

### Added
- New feature description

### Changed
- Change to existing functionality

### Fixed
- Bug fix description
```

## What it touches

- `pyproject.toml` — the `version = "x.y.z"` field under `[project]` (single
  source of truth; `colleague/__init__.py` reads it via `importlib.metadata`,
  so there is no separate `__version__` literal to keep in sync).
- `CHANGELOG.md` — inserts a new `## [x.y.z] - YYYY-MM-DD` entry at the top.

Pick a bump type from the diff (patch for fixes, minor for new features,
major for breaking changes), summarise the diff into `added` / `changed` /
`fixed` items, and commit the resulting `pyproject.toml` + `CHANGELOG.md`
alongside the code change so the `version-check` CI job sees a consistent
bump.

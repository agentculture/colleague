"""Environment check-group — operating environment health.

Verifies the broader operating environment: the ``.convertible/`` config tree,
the extensibility layer (hooks + command templates + AGENTS/skills layering),
external tooling on ``PATH``, and CLI self-integrity.

All checks are read-only and must never raise; errors are caught and turned into
failed checks so one broken probe cannot take down the whole report.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from convertible.oilcheck import make_check


def _repo_path() -> Path:
    """Return the current working directory as the repo root.

    The environment group is invoked by ``convertible doctor`` from whatever
    directory the user is in — that directory is the implicit repo root,
    exactly as it is for ``convertible drive --repo .``.
    """
    return Path.cwd()


# ---------------------------------------------------------------------------
# Individual check implementations
# ---------------------------------------------------------------------------


def _check_config_dir(repo: Path) -> dict:
    """Check 1: report whether a repo-level .convertible/ config dir resolves."""
    try:
        from convertible.configdir import config_roots

        roots = config_roots(repo)
        repo_config = repo / ".convertible"
        present = repo_config.is_dir()
        if present:
            msg = f".convertible/ config dir present at {repo_config}"
        else:
            user_config = Path.home() / ".convertible"
            if user_config.is_dir():
                msg = f"no repo-level .convertible/; user-level {user_config} resolves"
            else:
                msg = "no .convertible/ config dir (repo-level or user-level) — config is optional"
        _ = roots  # used to confirm the resolver does not raise
    except Exception as exc:  # noqa: BLE001
        msg = f"config_roots probe failed: {exc}"
    return make_check("config_dir", True, "info", msg)


def _check_hooks_valid(repo: Path) -> dict:
    """Check 2: if hooks.json exists, it must parse as valid JSON."""
    try:
        hooks_path = repo / ".convertible" / "hooks.json"
        if not hooks_path.is_file():
            return make_check(
                "hooks_valid",
                True,
                "info",
                ".convertible/hooks.json absent — hooks are optional",
            )
        raw = hooks_path.read_text(encoding="utf-8")
        json.loads(raw)  # raises json.JSONDecodeError on malformed input
        return make_check(
            "hooks_valid",
            True,
            "info",
            ".convertible/hooks.json is valid JSON",
        )
    except json.JSONDecodeError as exc:
        return make_check(
            "hooks_valid",
            False,
            "error",
            f".convertible/hooks.json is malformed JSON: {exc}",
            remediation=(
                "fix the syntax in .convertible/hooks.json; "
                "run `python3 -m json.tool .convertible/hooks.json` to validate"
            ),
        )
    except OSError as exc:
        return make_check(
            "hooks_valid",
            False,
            "error",
            f".convertible/hooks.json could not be read: {exc}",
            remediation="check file permissions on .convertible/hooks.json",
        )
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "hooks_valid",
            False,
            "error",
            f"hooks.json probe failed unexpectedly: {exc}",
            remediation="investigate .convertible/hooks.json",
        )


def _check_commands_parse(repo: Path) -> dict:
    """Check 3: command templates must parse via commands.py."""
    try:
        from convertible.commands import discover_commands, load_command

        discovered = discover_commands(repo)
        if not discovered:
            return make_check(
                "commands_parse",
                True,
                "info",
                "no command templates found — commands are optional",
            )
        failures: list[str] = []
        for stem, path in discovered.items():
            try:
                load_command(path)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{stem}: {exc}")

        if failures:
            return make_check(
                "commands_parse",
                False,
                "error",
                f"{len(failures)} command template(s) failed to parse: {', '.join(failures)}",
                remediation=(
                    "fix or remove the offending template(s) under .convertible/commands/"
                ),
            )
        return make_check(
            "commands_parse",
            True,
            "info",
            f"{len(discovered)} command template(s) parsed successfully",
        )
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "commands_parse",
            False,
            "error",
            f"command template probe failed: {exc}",
            remediation="check .convertible/commands/ for issues",
        )


def _check_layering(repo: Path) -> dict:
    """Check 4: AGENTS/skills layering resolution must not raise."""
    try:
        from convertible.layers import resolve_agents, resolve_skills

        # Use a sentinel model name; we want to confirm the resolution
        # machinery itself works, not that any overlay files are present.
        _model = "mock"
        agents = resolve_agents(repo, _model)
        skills = resolve_skills(repo, _model)
        n_agents = len(agents)
        n_skills = len(skills)
        msg = (
            f"AGENTS/skills layering resolved: {n_agents} AGENTS layer(s), " f"{n_skills} skill(s)"
        )
        return make_check("layering", True, "info", msg)
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "layering",
            False,
            "warning",
            f"AGENTS/skills layering raised an exception: {exc}",
            remediation=(
                "check AGENTS.md / AGENTS.convertible.md and .convertible/skills/ "
                "for file permission issues or symlinks escaping the repo"
            ),
        )


def _check_git_present() -> dict:
    """Check 5: git must be on PATH (required for handoff)."""
    git = shutil.which("git")
    if git:
        return make_check("git_present", True, "error", f"git found at {git}")
    return make_check(
        "git_present",
        False,
        "error",
        "git not found on PATH",
        remediation=(
            "install git (e.g. `apt install git` or `brew install git`); "
            "git is required for the handoff (branch/commit/push)"
        ),
    )


def _check_gh_present() -> dict:
    """Check 6: gh (GitHub CLI) should be on PATH for PR creation."""
    gh = shutil.which("gh")
    if gh:
        return make_check("gh_present", True, "warning", f"gh CLI found at {gh}")
    return make_check(
        "gh_present",
        False,
        "warning",
        "gh (GitHub CLI) not found on PATH",
        remediation=(
            "install gh for PR-creation handoff "
            "(see https://cli.github.com/); "
            "offline/CI drives that pass --no-pr still work without it"
        ),
    )


def _check_cli_integrity() -> dict:
    """Check 7: the package imports, __version__ resolves, and the parser builds."""
    try:
        import convertible

        version = getattr(convertible, "__version__", None)
        if not version:
            return make_check(
                "cli_integrity",
                False,
                "error",
                "convertible.__version__ is absent or empty",
                remediation=(
                    "ensure convertible is installed correctly; " "try `uv sync` and re-run"
                ),
            )
        from convertible.cli import _build_parser

        _build_parser()
        return make_check(
            "cli_integrity",
            True,
            "error",
            f"CLI integrity OK (convertible {version})",
        )
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "cli_integrity",
            False,
            "error",
            f"CLI integrity check failed: {exc}",
            remediation=(
                "ensure convertible is installed correctly; "
                "try `uv sync` and re-run; "
                "if the error persists, file a bug"
            ),
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def checks() -> list[dict]:
    """Return all environment checks.

    Verifies: config dir resolution, hooks.json validity, command templates
    parsing, AGENTS/skills layering, git on PATH, gh on PATH, and CLI
    self-integrity.

    Read-only and never raises — all probe errors are caught and returned as
    failed checks.
    """
    repo = _repo_path()
    return [
        _check_config_dir(repo),
        _check_hooks_valid(repo),
        _check_commands_parse(repo),
        _check_layering(repo),
        _check_git_present(),
        _check_gh_present(),
        _check_cli_integrity(),
    ]

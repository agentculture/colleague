"""Environment check-group — operating environment health.

Verifies the broader operating environment: the ``.colleague/`` config tree,
the extensibility layer (hooks + command templates + AGENTS/skills layering),
external tooling on ``PATH``, and CLI self-integrity.

All checks are read-only and must never raise; errors are caught and turned into
failed checks so one broken probe cannot take down the whole report.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from colleague.configdir import CONFIG_DIR_NAME
from colleague.oilcheck import make_check


def _repo_path() -> Path:
    """Return the current working directory as the repo root.

    The environment group is invoked by ``colleague doctor`` from whatever
    directory the user is in — that directory is the implicit repo root,
    exactly as it is for ``colleague work --repo .``.
    """
    return Path.cwd()


# ---------------------------------------------------------------------------
# Individual check implementations
# ---------------------------------------------------------------------------


def _check_config_dir(repo: Path) -> dict:
    """Check 1: report whether a repo-level .colleague/ config dir resolves."""
    try:
        from colleague.configdir import config_roots

        roots = config_roots(repo)
        repo_config = repo / CONFIG_DIR_NAME
        present = repo_config.is_dir()
        if present:
            msg = f".colleague/ config dir present at {repo_config}"
        else:
            user_config = Path.home() / CONFIG_DIR_NAME
            if user_config.is_dir():
                msg = f"no repo-level .colleague/; user-level {user_config} resolves"
            else:
                msg = "no .colleague/ config dir (repo-level or user-level) — config is optional"
        _ = roots  # used to confirm the resolver does not raise
        return make_check("config_dir", True, "info", msg)
    except Exception as exc:  # noqa: BLE001
        # Contract: an unexpected probe error is surfaced as a failed check, not
        # masked behind a passing info. Config is optional, so this is a warning.
        return make_check(
            "config_dir",
            False,
            "warning",
            f"config_roots probe failed: {exc}",
            remediation=(
                "check filesystem permissions; ensure .colleague/ and "
                "~/.colleague are accessible"
            ),
        )


def _check_hooks_valid(repo: Path) -> dict:
    """Check 2: if hooks.json exists, it must parse as valid JSON."""
    try:
        hooks_path = repo / CONFIG_DIR_NAME / "hooks.json"
        if not hooks_path.is_file():
            return make_check(
                "hooks_valid",
                True,
                "info",
                ".colleague/hooks.json absent — hooks are optional",
            )
        raw = hooks_path.read_text(encoding="utf-8")
        json.loads(raw)  # raises json.JSONDecodeError on malformed input
        return make_check(
            "hooks_valid",
            True,
            "info",
            ".colleague/hooks.json is valid JSON",
        )
    except json.JSONDecodeError as exc:
        return make_check(
            "hooks_valid",
            False,
            "error",
            f".colleague/hooks.json is malformed JSON: {exc}",
            remediation=(
                "fix the syntax in .colleague/hooks.json; "
                "run `python3 -m json.tool .colleague/hooks.json` to validate"
            ),
        )
    except OSError as exc:
        return make_check(
            "hooks_valid",
            False,
            "error",
            f".colleague/hooks.json could not be read: {exc}",
            remediation="check file permissions on .colleague/hooks.json",
        )
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "hooks_valid",
            False,
            "error",
            f"hooks.json probe failed unexpectedly: {exc}",
            remediation="investigate .colleague/hooks.json",
        )


def _check_commands_parse(repo: Path) -> dict:
    """Check 3: command templates must parse via commands.py."""
    try:
        from colleague.commands import discover_commands, load_command

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
                remediation=("fix or remove the offending template(s) under .colleague/commands/"),
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
            remediation="check .colleague/commands/ for issues",
        )


def _check_layering(repo: Path) -> dict:
    """Check 4: AGENTS/skills layering resolution must not raise."""
    try:
        from colleague.layers import resolve_agents, resolve_skills

        # Use a sentinel model name; we want to confirm the resolution
        # machinery itself works, not that any overlay files are present.
        _model = "mock"
        agents = resolve_agents(repo, _model)
        skills = resolve_skills(repo, _model)
        n_agents = len(agents)
        n_skills = len(skills)
        msg = f"AGENTS/skills layering resolved: {n_agents} AGENTS layer(s), {n_skills} skill(s)"
        return make_check("layering", True, "info", msg)
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "layering",
            False,
            "warning",
            f"AGENTS/skills layering raised an exception: {exc}",
            remediation=(
                "check AGENTS.md / AGENTS.colleague.md and .colleague/skills/ "
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
        import colleague

        version = getattr(colleague, "__version__", None)
        if not version:
            return make_check(
                "cli_integrity",
                False,
                "error",
                "colleague.__version__ is absent or empty",
                remediation="ensure colleague is installed correctly; try `uv sync` and re-run",
            )
        from colleague.cli import _build_parser

        _build_parser()
        return make_check(
            "cli_integrity",
            True,
            "error",
            f"CLI integrity OK (colleague {version})",
        )
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "cli_integrity",
            False,
            "error",
            f"CLI integrity check failed: {exc}",
            remediation=(
                "ensure colleague is installed correctly; "
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

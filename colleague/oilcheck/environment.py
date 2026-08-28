"""Environment check-group — operating environment health.

Verifies the broader operating environment: the ``.colleague/`` config tree,
the extensibility layer (hooks + command templates + AGENTS/skills layering),
external tooling on ``PATH``, and CLI self-integrity.

All checks are read-only and must never raise; errors are caught and turned into
failed checks so one broken probe cannot take down the whole report.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from colleague import livecheck
from colleague.configdir import CONFIG_DIR_NAME
from colleague.oilcheck import make_check

#: t6 acceptance: webglass warns above this many concurrent sessions.
_WEBGLASS_SESSION_WARN_THRESHOLD = 10


def _repo_path() -> Path:
    """Return cwd as the repo root (mirrors ``colleague work --repo .``)."""
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
    # Probe error surfaces as a check, not a crash.
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "config_dir",
            False,
            "warning",
            f"config_roots probe failed: {exc}",
            remediation="check filesystem permissions on .colleague/ and ~/.colleague",
        )


def _check_hooks_valid(repo: Path) -> dict:
    """Check 2: if hooks.json exists, it must parse as valid JSON."""
    try:
        hooks_path = repo / CONFIG_DIR_NAME / "hooks.json"
        if not hooks_path.is_file():
            return make_check(
                "hooks_valid", True, "info", ".colleague/hooks.json absent — optional"
            )
        json.loads(hooks_path.read_text(encoding="utf-8"))  # raises on malformed input
        return make_check("hooks_valid", True, "info", ".colleague/hooks.json is valid JSON")
    except json.JSONDecodeError as exc:
        return make_check(
            "hooks_valid",
            False,
            "error",
            f".colleague/hooks.json is malformed JSON: {exc}",
            remediation="fix the syntax; `python3 -m json.tool .colleague/hooks.json` validates",
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
            return make_check("commands_parse", True, "info", "no command templates — optional")
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
                remediation="fix or remove the offending template(s) under .colleague/commands/",
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

        # Sentinel model name: confirms the resolution machinery works, not
        # that any overlay files are present.
        agents = resolve_agents(repo, "mock")
        skills = resolve_skills(repo, "mock")
        msg = f"layering resolved: {len(agents)} AGENTS layer(s), {len(skills)} skill(s)"
        return make_check("layering", True, "info", msg)
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "layering",
            False,
            "warning",
            f"AGENTS/skills layering raised an exception: {exc}",
            remediation="check AGENTS.md / .colleague/skills/ for permission issues",
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
        remediation="install git (e.g. `apt install git`); required for handoff",
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
        remediation="install gh (https://cli.github.com/); --no-pr drives still work without it",
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
        return make_check("cli_integrity", True, "error", f"CLI integrity OK (colleague {version})")
    except Exception as exc:  # noqa: BLE001
        return make_check(
            "cli_integrity",
            False,
            "error",
            f"CLI integrity check failed: {exc}",
            remediation="ensure colleague is installed correctly; try `uv sync` and re-run",
        )


def _check_webglass() -> dict:
    """Check 8: webglass (t6) — WARN-only, never flips report health.

    ``ok`` when ``webglass doctor`` exits 0 within 10s; ``warn`` when
    absent/unhealthy; ``warn`` naming the count when ``session list --json``
    reports more than :data:`_WEBGLASS_SESSION_WARN_THRESHOLD` sessions.
    Shells out via :func:`colleague.livecheck.webglass_status` (the
    sanctioned subprocess consumer) — no new subprocess import here.
    """
    status = livecheck.webglass_status()
    if not status["healthy"]:
        return make_check(
            "webglass",
            False,
            "warning",
            f"webglass unhealthy: {status['detail']}",
            remediation="install/fix webglass (see docs/organs.md)",
        )
    sessions = status["sessions"]
    if isinstance(sessions, int) and sessions > _WEBGLASS_SESSION_WARN_THRESHOLD:
        return make_check(
            "webglass",
            False,
            "warning",
            f"webglass healthy but {sessions} sessions open (> {_WEBGLASS_SESSION_WARN_THRESHOLD})",
            remediation="close excess webglass sessions (`webglass session list`)",
        )
    return make_check("webglass", True, "warning", f"webglass healthy: {status['detail']}")


def _check_web_search_provider() -> dict:
    """Check 9: web_search_provider (t6) — WARN-only; never prints the key value."""
    if os.environ.get("WEBGLASS_BRAVE_API_KEY"):
        return make_check(
            "web_search_provider", True, "warning", "WEBGLASS_BRAVE_API_KEY is set in this process"
        )
    return make_check(
        "web_search_provider",
        False,
        "warning",
        "WEBGLASS_BRAVE_API_KEY unset in this process",
        remediation="export WEBGLASS_BRAVE_API_KEY=<key> to enable web search",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def checks() -> list[dict]:
    """Return all environment checks: config dir, hooks.json, command templates,
    AGENTS/skills layering, git, gh, CLI integrity, webglass, web_search_provider
    (the last two, t6, are WARN-only). Read-only; never raises.
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
        _check_webglass(),
        _check_web_search_provider(),
    ]

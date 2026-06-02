"""Tests for the doc-test-alignment (b) "claude" check.

HERMETIC, stdlib-only, no ``import convertible``. The "claude" check scans the
fenced bash block(s) under the ``## Commands`` heading of CLAUDE.md and reuses
the same ``_cmd`` engine as the "readme" check. We reuse the fake-CLI builder
from the readme test module so the two suites stay consistent.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import stat
import sys

import pytest

# Help dumps for the fake CLI (kept in sync with the readme test's fake CLI).
_FAKE_HELP_TOP = """\
usage: convertible [-h] [--version] {...} ...

positional arguments:
  {whoami,doctor,wheels,feedback,telemetry,drive,commands,hooks}
    whoami     Report identity.
    doctor     Health check.
    wheels     Discover engines.
    feedback   Grade a drive.
    telemetry  Inspect GPS config.
    drive      Drive toward a goal.
    commands   Discover templates.
    hooks      Inspect hooks.

options:
  -h, --help  show this help message and exit
  --version   show version and exit
"""

_FAKE_HELP_DRIVE = """\
usage: convertible drive [-h] [--repo REPO] [--engine ENGINE] [--no-pr]
                         [--base-url BASE_URL] [--model MODEL]

options:
  -h, --help           show this help message and exit
  --repo REPO          Path to the target repository.
  --engine ENGINE      Engine wheel to drive.
  --no-pr              Commit locally; do not push.
  --base-url BASE_URL  Override the engine base URL.
  --model MODEL        Override the engine model name.
"""


def _make_fake_cli(directory: pathlib.Path, marker: pathlib.Path) -> pathlib.Path:
    """Write a fake ``convertible`` executable (mirrors the readme test's CLI)."""
    py = sys.executable
    script = directory / "convertible"
    body = f"""#!{py}
import sys

HELP_TOP = {_FAKE_HELP_TOP!r}
HELP_DRIVE = {_FAKE_HELP_DRIVE!r}
MARKER = {str(marker)!r}

args = sys.argv[1:]

if "--help" in args:
    verb = None
    for a in args:
        if a == "--help":
            break
        if not a.startswith("-"):
            verb = a
            break
    if verb == "drive":
        sys.stdout.write(HELP_DRIVE)
    else:
        sys.stdout.write(HELP_TOP)
    sys.exit(0)

with open(MARKER, "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\\n")
sys.stdout.write("ok: " + " ".join(args) + "\\n")
sys.exit(0)
"""
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _make_fake_uv(directory: pathlib.Path) -> pathlib.Path:
    """Fake ``uv`` that strips a leading ``run`` and execs the rest."""
    py = sys.executable
    script = directory / "uv"
    body = f"""#!{py}
import os
import sys

args = sys.argv[1:]
if args and args[0] == "run":
    args = args[1:]
while args and args[0].startswith("-"):
    args = args[1:]
if not args:
    sys.exit(0)
os.execvp(args[0], args)
"""
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


_SCRIPTS_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "doc-test-alignment"
    / "scripts"
)


def _load(mod_stem: str):
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    checks_dir = str(_SCRIPTS_DIR / "checks")
    if checks_dir not in sys.path:
        sys.path.insert(0, checks_dir)
    mod_name = f"checks.{mod_stem}"
    spec = importlib.util.spec_from_file_location(
        mod_name, _SCRIPTS_DIR / "checks" / f"{mod_stem}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module so @dataclass field resolution can find the
    # module via sys.modules[cls.__module__] (mirrors importlib.import_module).
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


_cmd = _load("_cmd")
claude_commands = _load("claude_commands")


@pytest.fixture()
def fake_cli_on_path(tmp_path: pathlib.Path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "EXECUTED.txt"
    _make_fake_cli(bindir, marker)
    _make_fake_uv(bindir)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return marker, bindir


def _write_claude_repo(tmp_path: pathlib.Path, commands_block: str) -> pathlib.Path:
    """Repo with a CLAUDE.md that has a ## Commands section + a bash block."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    text = (
        "# CLAUDE.md\n\n"
        "## What it is\n\nSome prose.\n\n"
        "```bash\n# decoy block before Commands — must be ignored\n"
        "uv run convertible THISSHOULDNOTBESCANNED list\n```\n\n"
        "## Commands\n\n"
        "```bash\n" + commands_block + "\n```\n\n"
        "## After\n\nmore prose.\n"
    )
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# The "claude" check scopes to the ## Commands block ONLY.
# ---------------------------------------------------------------------------


class TestClaudeScoping:
    def test_only_scans_commands_section(self, tmp_path, fake_cli_on_path) -> None:
        repo = _write_claude_repo(
            tmp_path,
            "uv run convertible wheels list\nuv run convertible telemetry status\n",
        )
        checks = claude_commands.run(repo)
        # The decoy verb before ## Commands must never be scanned.
        assert not any("THISSHOULDNOTBESCANNED" in c["message"] for c in checks)
        # Summary is present and scoped.
        assert any(c["id"].endswith("_summary") for c in checks)

    def test_name_constant(self) -> None:
        assert claude_commands.NAME == "claude"

    def test_summary_id_prefixed_claude(self, tmp_path, fake_cli_on_path) -> None:
        repo = _write_claude_repo(tmp_path, "uv run convertible doctor\n")
        checks = claude_commands.run(repo)
        assert any(c["id"].startswith("claude_") for c in checks)


# ---------------------------------------------------------------------------
# RUN PATH: a SAFE command in the Commands block executes & passes.
# ---------------------------------------------------------------------------


class TestClaudeRunPath:
    def test_safe_command_executes(self, tmp_path, fake_cli_on_path) -> None:
        marker, _ = fake_cli_on_path
        repo = _write_claude_repo(tmp_path, "uv run convertible wheels list\n")
        checks = claude_commands.run(repo)
        assert marker.exists()
        assert "wheels list" in marker.read_text(encoding="utf-8")
        assert not any(c["severity"] == "error" for c in checks)

    def test_lint_lines_are_ignored_or_info(self, tmp_path, fake_cli_on_path) -> None:
        """Non-convertible lint tool lines (black/isort/flake8) produce no
        warning/error checks — only convertible invocations yield checks.
        """
        repo = _write_claude_repo(
            tmp_path,
            "uv run black --check convertible tests\n" "uv run convertible wheels list\n",
        )
        checks = claude_commands.run(repo)
        # No check should be about black.
        assert not any("black" in c["message"] and c["severity"] != "info" for c in checks)


# ---------------------------------------------------------------------------
# NETWORKED SKIP + CATCH unknown verb, scoped to the Commands block.
# ---------------------------------------------------------------------------


class TestClaudeNetworkedAndCatch:
    def test_networked_drive_never_executed(self, tmp_path, fake_cli_on_path) -> None:
        marker, _ = fake_cli_on_path
        repo = _write_claude_repo(
            tmp_path,
            'uv run convertible drive "<task>" --repo . --engine mock --no-pr\n',
        )
        checks = claude_commands.run(repo)
        # A drive is networked/side-effecting: NEVER executed.
        assert not marker.exists()
        # It must still be validated (drive is a real verb -> info SKIPPED).
        assert any("skipped" in c["message"].lower() and c["severity"] == "info" for c in checks)

    def test_catches_unknown_verb_in_commands(self, tmp_path, fake_cli_on_path) -> None:
        marker, _ = fake_cli_on_path
        repo = _write_claude_repo(
            tmp_path,
            "uv run convertible bogusverb --engine vllm-openai\n",
        )
        checks = claude_commands.run(repo)
        warns = [c for c in checks if c["severity"] == "warning" and not c["passed"]]
        assert warns
        assert any("bogusverb" in c["message"] for c in warns)
        # Static validation never executes.
        assert not marker.exists()


# ---------------------------------------------------------------------------
# Robustness: missing CLAUDE.md / no Commands section never raises.
# ---------------------------------------------------------------------------


class TestClaudeRobustness:
    def test_missing_claude_md_no_raise(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        checks = claude_commands.run(tmp_path)
        assert isinstance(checks, list)
        assert not any(c["severity"] == "error" for c in checks)

    def test_no_commands_section_no_raise(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\n\nNo commands here.\n", encoding="utf-8")
        checks = claude_commands.run(tmp_path)
        assert isinstance(checks, list)
        assert any(c["id"].endswith("_summary") for c in checks)

    def test_run_against_real_claude_never_raises(self) -> None:
        real_repo = pathlib.Path(__file__).resolve().parents[1]
        checks = claude_commands.run(real_repo)
        assert isinstance(checks, list)
        assert all("id" in c and "severity" in c for c in checks)

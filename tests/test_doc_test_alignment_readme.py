"""Tests for the doc-test-alignment (a) "readme" check + the shared _cmd engine.

These tests are HERMETIC: they build fixture README files and a fake
``colleague`` CLI in ``tmp_path`` so both execution and static-validation are
deterministic without a live ``colleague`` on PATH. No ``import colleague``
anywhere — the check modules are stdlib-only and portable.

The fake CLI:
  * On ``--help`` it prints an argparse-shaped help with a ``{...}`` verb/subverb
    choice set and an ``options:`` flag section.
  * On a real invocation it writes a marker file (proving it WAS executed) and
    echoes its argv, then exits 0 (or 1 if ``--unhealthy`` is passed) so the
    exit-class assertion has something to bite on.

CATCH test (``test_static_validate_flags_unknown_verb``) is written first.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import stat
import sys

import pytest

# ---------------------------------------------------------------------------
# Load the check modules WITHOUT importing colleague. We add the skill's
# scripts dir (and its checks/ dir) to sys.path exactly like the spine does.
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "doc-test-alignment"
    / "scripts"
)


def _load(mod_stem: str):
    """Import ``checks.<mod_stem>`` from the skill scripts dir, stdlib-only."""
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
readme_commands = _load("readme_commands")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FAKE_HELP_TOP = """\
usage: colleague [-h] [--version] {...} ...

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
usage: colleague drive [-h] [--repo REPO] [--engine ENGINE] [--no-pr]
                         [--base-url BASE_URL] [--model MODEL]

options:
  -h, --help           show this help message and exit
  --repo REPO          Path to the target repository.
  --engine ENGINE      Engine wheel to drive.
  --no-pr              Commit locally; do not push.
  --base-url BASE_URL  Override the engine base URL.
  --model MODEL        Override the engine model name.
"""

_FAKE_HELP_FEEDBACK = """\
usage: colleague feedback [-h] [--json] {record,show,overview} ...

positional arguments:
  {record,show,overview}
    record    Record a rating.
    show      Show feedback.
    overview  Describe surface.

options:
  -h, --help  show this help message and exit
  --json      Emit structured JSON.
"""

_FAKE_HELP_WHEELS = """\
usage: colleague wheels [-h] [--json] {list,overview} ...

positional arguments:
  {list,overview}
    list      List engines.
    overview  Describe surface.

options:
  -h, --help  show this help message and exit
  --json      Emit structured JSON.
"""


def _make_fake_cli(directory: pathlib.Path, marker: pathlib.Path) -> pathlib.Path:
    """Write a fake ``colleague`` executable that:

    * prints argparse-shaped help (top-level or per-verb) on ``--help``;
    * on a real invocation appends its argv to *marker* (proving execution) and
      exits 0, or exits 1 when ``--unhealthy`` is present (exit-class probe).
    """
    py = sys.executable
    script = directory / "colleague"
    body = f"""#!{py}
import sys

HELP_TOP = {_FAKE_HELP_TOP!r}
HELP_DRIVE = {_FAKE_HELP_DRIVE!r}
HELP_FEEDBACK = {_FAKE_HELP_FEEDBACK!r}
HELP_WHEELS = {_FAKE_HELP_WHEELS!r}
MARKER = {str(marker)!r}

args = sys.argv[1:]

if "--help" in args:
    # Decide which help to print based on the leading verb (if any).
    verb = None
    for a in args:
        if a == "--help":
            break
        if not a.startswith("-"):
            verb = a
            break
    if verb == "drive":
        sys.stdout.write(HELP_DRIVE)
    elif verb == "feedback":
        sys.stdout.write(HELP_FEEDBACK)
    elif verb == "wheels":
        sys.stdout.write(HELP_WHEELS)
    else:
        sys.stdout.write(HELP_TOP)
    sys.exit(0)

# Real invocation: record it so tests can prove execution happened.
with open(MARKER, "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\\n")

if "--unhealthy" in args:
    sys.stdout.write("status: unhealthy\\n")
    sys.exit(1)

sys.stdout.write("ok: " + " ".join(args) + "\\n")
sys.exit(0)
"""
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _make_fake_uv(directory: pathlib.Path) -> pathlib.Path:
    """Write a fake ``uv`` that strips a leading ``run`` and execs the rest.

    Lets a doc command written as ``uv run colleague …`` resolve to the fake
    ``colleague`` on PATH, hermetically (no real uv, no network).
    """
    py = sys.executable
    script = directory / "uv"
    body = f"""#!{py}
import os
import sys

args = sys.argv[1:]
if args and args[0] == "run":
    args = args[1:]
# Drop common `uv run` flags that take no colleague meaning here.
while args and args[0].startswith("-"):
    args = args[1:]
if not args:
    sys.exit(0)
os.execvp(args[0], args)
"""
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _write_repo(tmp_path: pathlib.Path, readme_body: str) -> pathlib.Path:
    """Create a minimal repo: pyproject.toml + README.md with one bash block."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Fixture\n\n```bash\n" + readme_body + "\n```\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def fake_cli_on_path(tmp_path: pathlib.Path, monkeypatch):
    """Put a fake ``colleague`` on PATH; return (marker_path, bin_dir)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "EXECUTED.txt"
    _make_fake_cli(bindir, marker)
    _make_fake_uv(bindir)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return marker, bindir


# ---------------------------------------------------------------------------
# CATCH test FIRST: static validation must flag an unknown verb.
# ---------------------------------------------------------------------------


class TestCatchUnknownVerb:
    def test_static_validate_flags_unknown_verb(self, fake_cli_on_path) -> None:
        """A networked/unknown ``colleague bogusverb`` whose verb is NOT in the
        fake CLI's --help choice set yields a ``warning`` 'unknown verb' check.
        """
        marker, _ = fake_cli_on_path
        help_cache: dict = {}
        check = _cmd.static_validate("colleague bogusverb --engine vllm-openai", None, help_cache)
        assert check["severity"] == "warning"
        assert check["passed"] is False
        assert "unknown verb" in check["message"].lower() or "bogusverb" in check["message"]
        # Static validation NEVER executes the CLI.
        assert not marker.exists()


# ---------------------------------------------------------------------------
# Classification unit tests on _cmd.classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_mock_introspection_is_safe(self) -> None:
        assert _cmd.classify("colleague wheels list") == "safe"

    def test_doctor_no_probe_is_safe(self) -> None:
        assert _cmd.classify("colleague doctor") == "safe"

    def test_telemetry_status_is_safe(self) -> None:
        assert _cmd.classify("colleague telemetry status") == "safe"

    def test_help_is_safe(self) -> None:
        assert _cmd.classify("colleague drive --help") == "safe"

    def test_engine_vllm_is_networked(self) -> None:
        cmd = "colleague drive 'fix' --engine vllm-openai --base-url http://x/v1"
        assert _cmd.classify(cmd) == "networked"

    def test_base_url_is_networked(self) -> None:
        assert (
            _cmd.classify("colleague drive 'x' --base-url http://localhost:8001/v1") == "networked"
        )

    def test_doctor_probe_is_networked(self) -> None:
        assert _cmd.classify("colleague doctor --probe") == "networked"

    def test_drive_writes_files_is_networked(self) -> None:
        # Even a mock drive writes files / commits — never executed.
        assert (
            _cmd.classify("colleague drive 'add stub' --repo . --engine mock --no-pr")
            == "networked"
        )

    def test_session_is_networked(self) -> None:
        assert _cmd.classify("colleague session --repo . --engine mock") == "networked"

    def test_repo_dot_introspection_is_safe(self) -> None:
        # `--repo .` targets the repo under check → safe to execute.
        assert _cmd.classify("colleague doctor --repo .") == "safe"

    def test_relative_repo_escape_is_networked(self) -> None:
        # A relative --repo (e.g. an escape) must NOT be safe-executed (fail-closed):
        # only `.`/`./` is executable; everything else is static-validated.
        assert _cmd.classify("colleague doctor --repo ../../..") == "networked"
        assert _cmd.classify("colleague doctor --repo subdir") == "networked"
        assert _cmd.classify("colleague doctor --repo=../etc") == "networked"

    def test_absolute_repo_is_networked(self) -> None:
        assert _cmd.classify("colleague doctor --repo /tmp/x") == "networked"

    def test_vllm_e2e_env_is_networked(self) -> None:
        assert _cmd.classify("CONVERTIBLE_VLLM_E2E=1 colleague drive 'x'") == "networked"

    def test_unknown_invocation_fails_closed_to_unknown(self) -> None:
        # A colleague line we can't positively classify as safe → "unknown".
        # The dispatcher treats "unknown" exactly like "networked" (fail-closed:
        # static-validate, never execute) — verified in TestUnknownFailsClosed.
        assert _cmd.classify("colleague some-weird-thing --frobnicate") == "unknown"


# ---------------------------------------------------------------------------
# iter_colleague_invocations — line splitting / continuation joining
# ---------------------------------------------------------------------------


class TestIterInvocations:
    def test_finds_uv_run_and_bare(self) -> None:
        block = (
            "uv sync\n"
            "uv run colleague wheels list   # comment\n"
            "colleague doctor\n"
            "git status\n"
        )
        invs = list(_cmd.iter_colleague_invocations(block))
        cmds = [i.command for i in invs]
        assert any("colleague wheels list" in c for c in cmds)
        assert any(c.strip().startswith("colleague doctor") for c in cmds)
        # Non-colleague lines are ignored.
        assert not any("git status" in c for c in cmds)
        assert not any(c.strip() == "uv sync" for c in cmds)

    def test_joins_backslash_continuation(self) -> None:
        block = (
            "uv run colleague drive 'x' \\\n"
            "  --engine vllm-openai \\\n"
            "  --base-url http://localhost:8001/v1\n"
        )
        invs = list(_cmd.iter_colleague_invocations(block))
        assert len(invs) == 1
        assert "--engine vllm-openai" in invs[0].command
        assert "--base-url" in invs[0].command

    def test_captures_adjacent_comment(self) -> None:
        block = "uv run colleague doctor   # human-readable rubric; exit 1 if unhealthy\n"
        invs = list(_cmd.iter_colleague_invocations(block))
        assert len(invs) == 1
        assert "exit 1 if unhealthy" in invs[0].comment


# ---------------------------------------------------------------------------
# RUN PATH: a SAFE command executes against the fake CLI and passes.
# ---------------------------------------------------------------------------


class TestRunPath:
    def test_safe_command_executes_and_passes(self, fake_cli_on_path) -> None:
        marker, _ = fake_cli_on_path
        check = _cmd.run_safe(_cmd.Invocation("colleague wheels list", ""), pathlib.Path("."))
        assert check["passed"] is True
        assert check["severity"] in ("info", "warning")
        # Proof of execution: the fake CLI recorded the argv.
        assert marker.exists()
        assert "wheels list" in marker.read_text(encoding="utf-8")

    def test_unconditional_nonzero_comment_sets_expectation(self, fake_cli_on_path) -> None:
        """An adjacent UNCONDITIONAL '# exit 1' comment sets a non-zero
        expectation; the fake CLI is forced to exit 1, satisfying it -> PASS.
        """
        marker, _ = fake_cli_on_path
        inv = _cmd.Invocation("colleague doctor --unhealthy", "always exit 1 here")
        check = _cmd.run_safe(inv, pathlib.Path("."))
        assert check["passed"] is True
        assert marker.exists()

    def test_conditional_exit_comment_keeps_zero_expectation(self, fake_cli_on_path) -> None:
        """A CONDITIONAL '# exit 1 if unhealthy' comment does NOT flip the
        expectation: the success path (exit 0) is what we exercise -> PASS.
        """
        marker, _ = fake_cli_on_path
        # No --unhealthy: the fake CLI exits 0, which is the expected (default) class.
        inv = _cmd.Invocation("colleague doctor", "exit 1 if unhealthy")
        check = _cmd.run_safe(inv, pathlib.Path("."))
        assert check["passed"] is True
        assert marker.exists()
        assert not _cmd._expected_nonzero("exit 1 if unhealthy")
        assert _cmd._expected_nonzero("exit 1")

    def test_cli_not_available_downgrades_to_info(self, tmp_path, monkeypatch) -> None:
        """Point PATH at an empty dir: the CLI can't be launched -> info, no crash."""
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        check = _cmd.run_safe(_cmd.Invocation("colleague wheels list", ""), pathlib.Path("."))
        assert check["severity"] == "info"
        assert check["passed"] is True
        assert (
            "not available" in check["message"].lower()
            or "not executed" in check["message"].lower()
        )


# ---------------------------------------------------------------------------
# NETWORKED SKIP: a vllm command is reported SKIPPED-but-validated, NEVER run.
# ---------------------------------------------------------------------------


class TestNetworkedSkip:
    def test_vllm_command_validated_not_executed(self, fake_cli_on_path) -> None:
        marker, _ = fake_cli_on_path
        # 'drive' IS a valid verb in the fake help, and --engine/--base-url are
        # valid drive flags, so static validation PASSES (info).
        cmd = "colleague drive 'fix' --engine vllm-openai --base-url http://x/v1 --model m"
        help_cache: dict = {}
        check = _cmd.static_validate(cmd, None, help_cache)
        assert check["passed"] is True
        assert check["severity"] == "info"
        assert "skipped" in check["message"].lower()
        # PROOF: the fake CLI was NEVER invoked as a real drive.
        assert not marker.exists()

    def test_static_validate_flags_unknown_flag(self, fake_cli_on_path) -> None:
        marker, _ = fake_cli_on_path
        cmd = "colleague drive 'x' --engine vllm-openai --frobnicate"
        help_cache: dict = {}
        check = _cmd.static_validate(cmd, None, help_cache)
        assert check["severity"] == "warning"
        assert check["passed"] is False
        assert "flag" in check["message"].lower()
        assert not marker.exists()


# ---------------------------------------------------------------------------
# END-TO-END: readme_commands.run over a fixture repo (hermetic).
# ---------------------------------------------------------------------------


class TestReadmeRun:
    def test_run_does_not_raise_and_summarizes(self, tmp_path, fake_cli_on_path) -> None:
        repo = _write_repo(
            tmp_path,
            "uv run colleague wheels list\n"
            "uv run colleague drive 'fix' --engine vllm-openai --base-url http://x/v1\n"
            "git status\n",
        )
        checks = readme_commands.run(repo)
        assert isinstance(checks, list)
        # A per-file summary info check is always present.
        assert any(c["id"].endswith("_summary") and c["severity"] == "info" for c in checks)
        # No error-severity checks for a well-formed run.
        assert not any(c["severity"] == "error" for c in checks)

    def test_run_flags_bogus_verb_as_warning(self, tmp_path, fake_cli_on_path) -> None:
        repo = _write_repo(
            tmp_path,
            "uv run colleague bogusverb --engine vllm-openai\n",
        )
        checks = readme_commands.run(repo)
        warns = [c for c in checks if c["severity"] == "warning" and not c["passed"]]
        assert warns, "an unknown verb must surface as a warning"
        assert any("bogusverb" in c["message"] for c in warns)

    def test_unknown_verb_fails_closed_not_executed(self, tmp_path, fake_cli_on_path) -> None:
        """An UNKNOWN colleague invocation is fail-closed: static-validated
        (never executed). Here the unknown verb isn't in the fake help, so it
        surfaces as a warning — and the fake CLI is never run.
        """
        marker, _ = fake_cli_on_path
        repo = _write_repo(tmp_path, "uv run colleague some-weird-thing --frobnicate\n")
        checks = readme_commands.run(repo)
        warns = [c for c in checks if c["severity"] == "warning" and not c["passed"]]
        assert warns, "an unknown verb must surface as a warning"
        # Fail-closed: never executed.
        assert not marker.exists()

    def test_run_against_real_readme_never_raises(self) -> None:
        """Smoke: running against the REAL repo README must not raise.

        We don't assert content (depends on the live CLI presence); we only
        assert the contract: run() returns a list and never raises.
        """
        real_repo = pathlib.Path(__file__).resolve().parents[1]
        checks = readme_commands.run(real_repo)
        assert isinstance(checks, list)
        assert all("id" in c and "severity" in c for c in checks)

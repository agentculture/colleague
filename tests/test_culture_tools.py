"""Tests for the curated culture loop tools (t3).

Two acceptance criteria:

AC1 — the loop exposes the curated ``culture`` tool BEYOND the five base tools,
      and it is dispatchable through the shared :class:`ToolExecutor` (so every
      engine exposes it identically — the all-engines rule).

AC2 — a culture tool invocation shells out to the installed CLI via subprocess
      with the resolved identity injected (``CONVERTIBLE_IDENTITY`` visible to
      the child), runs with cwd at the repo root, NEVER imports the CLI, and:
        * an ABSENT CLI yields a clean tool-error string (no traceback/crash);
        * the allow-list rejects any CLI name outside {agtag, devex} cleanly.

Tests stub the CLI with a tiny fake executable in ``tmp_path`` so neither agtag
nor devex needs to be installed.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from colleague import culture
from colleague.tools import SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor

_BASE_TOOLS = {"read_file", "write_file", "edit_file", "list_dir", "run_command", "finish"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_cli(directory: Path, name: str) -> Path:
    """Write an executable shell script that echoes its argv and identity env.

    Emits two deterministic markers the tests assert on:
      * ``ARGV: <args>`` — proves argv was forwarded
      * ``IDENTITY: <value>`` — proves CONVERTIBLE_IDENTITY reached the child
    """
    script = directory / name
    script.write_text(
        "#!/bin/sh\n"
        'echo "ARGV: $*"\n'
        'echo "IDENTITY: ${CONVERTIBLE_IDENTITY:-<unset>}"\n'
        'echo "CWD: $(pwd)"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ---------------------------------------------------------------------------
# AC1 — schema exposure & dispatch
# ---------------------------------------------------------------------------


class TestCultureToolExposed:
    def test_culture_tool_in_schemas_beyond_base_six(self) -> None:
        names = {s["function"]["name"] for s in SCHEMAS}
        assert _BASE_TOOLS <= names, "the six base tools must remain"
        assert "culture" in names, "the curated culture tool must be exposed"
        # Curated tools beyond the base six (culture + devague + subagent + subagents
        # + check_test_integrity, the runtime chassis).
        assert names == _BASE_TOOLS | {
            "culture",
            "devague",
            "memory",
            "subagent",
            "subagents",
            "check_test_integrity",
            "run_tests",
        }

    def test_tool_names_includes_culture(self) -> None:
        assert "culture" in TOOL_NAMES

    def test_culture_schema_declares_cli_and_args(self) -> None:
        schema = next(s for s in SCHEMAS if s["function"]["name"] == "culture")
        params = schema["function"]["parameters"]["properties"]
        assert "cli" in params
        assert "args" in params
        # The allow-list is advertised to the model via the enum.
        assert set(params["cli"]["enum"]) == {"agtag", "devex"}

    def test_executor_dispatches_culture(self, tmp_path: Path, monkeypatch) -> None:
        """The executor routes the ``culture`` tool name to the culture module."""
        fake = _make_fake_cli(tmp_path, "agtag")
        monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")

        ex = ToolExecutor(tmp_path)
        outcome = ex.execute("culture", {"cli": "agtag", "args": ["issue", "fetch"]})
        assert "ARGV: issue fetch" in outcome.result
        assert not outcome.finished
        assert outcome.changed_file is None
        # Keep the fake referenced so flake8 doesn't complain.
        assert fake.exists()


# ---------------------------------------------------------------------------
# AC2 — shell-out, identity injection, absent CLI, allow-list
# ---------------------------------------------------------------------------


class TestCultureShellOut:
    def test_identity_injected_into_child(self, tmp_path: Path, monkeypatch) -> None:
        """CONVERTIBLE_IDENTITY resolved from culture.yaml reaches the child."""
        (tmp_path / "culture.yaml").write_text("nick: spark\n", encoding="utf-8")
        _make_fake_cli(tmp_path, "devex")
        monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")

        ex = ToolExecutor(tmp_path)
        outcome = ex.execute("culture", {"cli": "devex", "args": ["overview"]})
        assert "IDENTITY: spark" in outcome.result
        assert "ARGV: overview" in outcome.result

    def test_runs_with_cwd_at_repo_root(self, tmp_path: Path, monkeypatch) -> None:
        _make_fake_cli(tmp_path, "agtag")
        monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")

        ex = ToolExecutor(tmp_path)
        outcome = ex.execute("culture", {"cli": "agtag", "args": []})
        # The resolved repo root (symlinks resolved) appears as the child cwd.
        assert f"CWD: {Path(tmp_path).resolve()}" in outcome.result

    def test_absent_cli_clean_error_not_crash(self, tmp_path: Path, monkeypatch) -> None:
        """An uninstalled CLI yields a clean ToolError, not a traceback."""
        # Point PATH somewhere with no agtag/devex so the lookup fails cleanly.
        empty = tmp_path / "emptybin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))

        ex = ToolExecutor(tmp_path)
        with pytest.raises(ToolError) as exc:
            ex.execute("culture", {"cli": "agtag", "args": ["issue", "fetch"]})
        msg = str(exc.value).lower()
        assert "agtag" in msg
        assert "not found" in msg or "not installed" in msg

    def test_allow_list_rejects_unknown_cli(self, tmp_path: Path) -> None:
        ex = ToolExecutor(tmp_path)
        with pytest.raises(ToolError) as exc:
            ex.execute("culture", {"cli": "rm", "args": ["-rf", "/"]})
        msg = str(exc.value).lower()
        assert "rm" in msg
        assert "allow" in msg or "not permitted" in msg or "unknown" in msg

    def test_missing_cli_argument_is_clean_error(self, tmp_path: Path) -> None:
        ex = ToolExecutor(tmp_path)
        with pytest.raises(ToolError):
            ex.execute("culture", {"args": ["issue"]})


# ---------------------------------------------------------------------------
# Module-level surface (no import of the CLI; allow-list is the gate)
# ---------------------------------------------------------------------------


class TestCultureModule:
    def test_allow_list_constant(self) -> None:
        assert culture.ALLOWED_CLIS == frozenset({"agtag", "devex"})

    def test_run_culture_returns_string(self, tmp_path: Path, monkeypatch) -> None:
        _make_fake_cli(tmp_path, "agtag")
        monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")
        out = culture.run_culture("agtag", ["issue", "post", "hi"], root=tmp_path)
        assert isinstance(out, str)
        assert "ARGV: issue post hi" in out

    def test_run_culture_timeout_maps_to_tool_error(self, tmp_path: Path) -> None:
        """A culture CLI timeout becomes a clean CultureToolError, not an escape.

        Parity with the devague transport: an uncaught subprocess.TimeoutExpired
        would bubble out of ToolExecutor and crash the drive.
        """
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="agtag", timeout=1),
        ):
            with pytest.raises(culture.CultureToolError) as excinfo:
                culture.run_culture("agtag", [], root=tmp_path)

        assert "timed out" in str(excinfo.value)

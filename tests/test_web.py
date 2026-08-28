"""Tests for colleague/web.py — curated webglass CLI shell-out launcher.

Written test-first (TDD): tests define the contract, implementation follows.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colleague.web import (
    ALLOWED_VERBS,
    FORBIDDEN_TOKENS,
    WebToolError,
    run_web,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """A minimal repo root with an identity.json so identity resolves."""
    identity_dir = tmp_path / ".colleague"
    identity_dir.mkdir()
    (identity_dir / "identity.json").write_text(json.dumps({"as": "test-agent"}), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def fake_proc() -> MagicMock:
    """A fake Popen instance returned by a monkeypatched subprocess.Popen."""
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = 0
    proc.communicate.return_value = ("ok\n", "")
    return proc


def _write_script(bin_dir: Path, name: str, body: str) -> Path:
    script = bin_dir / name
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ---------------------------------------------------------------------------
# AC: ALLOWED_VERBS exact set
# ---------------------------------------------------------------------------


def test_allowed_verbs_exact_set() -> None:
    assert ALLOWED_VERBS == frozenset(
        {"search", "page open", "page read", "page inspect", "page extract", "page links"}
    )


def test_forbidden_tokens_exact_set() -> None:
    assert FORBIDDEN_TOKENS == frozenset({"--session-id", "--page-ref", "--policy-profile"})


# ---------------------------------------------------------------------------
# AC: refused verbs never spawn a child
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["action", "session", "page screenshot"])
def test_refused_verb_raises_no_spawn(verb: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web(verb, [], root=repo_root)
    assert mock_popen.call_count == 0


def test_refused_verb_error_lists_allowed(repo_root: Path) -> None:
    with patch("subprocess.Popen"):
        with pytest.raises(WebToolError) as exc_info:
            run_web("action", [], root=repo_root)
    msg = str(exc_info.value)
    assert "action" in msg
    assert "search" in msg


# ---------------------------------------------------------------------------
# AC: forbidden argv tokens never spawn a child
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token", sorted(FORBIDDEN_TOKENS))
def test_forbidden_token_raises_no_spawn(token: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web("page open", ["https://example.com", token, "x"], root=repo_root)
    assert mock_popen.call_count == 0


def test_forbidden_token_in_search_args_raises_no_spawn(repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web("search", ["--policy-profile", "x"], root=repo_root)
    assert mock_popen.call_count == 0


# ---------------------------------------------------------------------------
# AC: url must match ^https?:// for url-taking verbs, checked before spawn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb", ["page open", "page read", "page inspect", "page extract", "page links"]
)
def test_missing_url_raises_no_spawn(verb: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web(verb, [], root=repo_root)
    assert mock_popen.call_count == 0


@pytest.mark.parametrize(
    "bad_url", ["ftp://example.com", "example.com", "javascript:alert(1)", "  http://example.com"]
)
def test_bad_url_scheme_raises_no_spawn(bad_url: str, repo_root: Path) -> None:
    with patch("subprocess.Popen") as mock_popen:
        with pytest.raises(WebToolError):
            run_web("page open", [bad_url], root=repo_root)
    assert mock_popen.call_count == 0


def test_valid_https_url_is_accepted(repo_root: Path, fake_proc: MagicMock) -> None:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        result = run_web("page open", ["https://example.com"], root=repo_root)
    mock_popen.assert_called_once()
    assert result.startswith("exit=0\n")


def test_valid_http_url_is_accepted(repo_root: Path, fake_proc: MagicMock) -> None:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        run_web("page read", ["http://example.com"], root=repo_root)
    mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# AC: --json always appended; free-text query after literal '--' for search
# ---------------------------------------------------------------------------


def test_json_flag_always_appended_for_url_verb(repo_root: Path, fake_proc: MagicMock) -> None:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        run_web("page open", ["https://example.com"], root=repo_root)
    argv = mock_popen.call_args[0][0]
    assert argv[-1] == "--json"
    assert argv[0] == "webglass"
    assert argv[1:3] == ["page", "open"]
    assert "https://example.com" in argv


def test_json_flag_always_appended_for_search(repo_root: Path, fake_proc: MagicMock) -> None:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        run_web("search", ["colleague web scout"], root=repo_root)
    argv = mock_popen.call_args[0][0]
    assert argv[-1] == "--json"
    assert argv[0] == "webglass"
    assert argv[1] == "search"


def test_search_query_passed_after_literal_double_dash(
    repo_root: Path, fake_proc: MagicMock
) -> None:
    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        run_web("search", ["colleague web scout"], root=repo_root)
    argv = mock_popen.call_args[0][0]
    assert "--" in argv
    dash_index = argv.index("--")
    assert argv[dash_index + 1] == "colleague web scout"
    # "--" must come before the query and before the trailing --json
    assert dash_index < argv.index("--json")


# ---------------------------------------------------------------------------
# AC: FileNotFoundError / OSError → WebToolError, one-line message
# ---------------------------------------------------------------------------


def test_missing_binary_raises_web_tool_error(repo_root: Path) -> None:
    with patch("subprocess.Popen", side_effect=FileNotFoundError):
        with pytest.raises(WebToolError) as exc_info:
            run_web("search", ["x"], root=repo_root)
    msg = str(exc_info.value)
    assert "\n" not in msg
    assert "webglass" in msg.lower()
    assert "not found" in msg.lower() or "installed" in msg.lower()


def test_os_error_on_launch_raises_web_tool_error(repo_root: Path) -> None:
    with patch("subprocess.Popen", side_effect=OSError("permission denied")):
        with pytest.raises(WebToolError) as exc_info:
            run_web("search", ["x"], root=repo_root)
    msg = str(exc_info.value)
    assert "\n" not in msg


# ---------------------------------------------------------------------------
# AC: output capped at 20,000 chars
# ---------------------------------------------------------------------------


def test_output_truncated_at_20000_chars(repo_root: Path, fake_proc: MagicMock) -> None:
    fake_proc.communicate.return_value = ("x" * 30_000, "")
    with patch("subprocess.Popen", return_value=fake_proc):
        result = run_web("search", ["q"], root=repo_root)
    assert len(result) < 30_100
    assert "truncated" in result


# ---------------------------------------------------------------------------
# AC: identity + cwd (mirrors devague.py shape)
# ---------------------------------------------------------------------------


def test_cwd_is_resolved_root(repo_root: Path, fake_proc: MagicMock) -> None:
    captured_cwd: list[str] = []

    def fake_popen(argv, *, cwd, stdout, stderr, text, env, start_new_session):
        captured_cwd.append(cwd)
        return fake_proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        run_web("search", ["q"], root=repo_root)
    assert captured_cwd[0] == str(repo_root.resolve())


def test_start_new_session_true(repo_root: Path, fake_proc: MagicMock) -> None:
    captured: dict = {}

    def fake_popen(argv, *, cwd, stdout, stderr, text, env, start_new_session):
        captured["start_new_session"] = start_new_session
        return fake_proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        run_web("search", ["q"], root=repo_root)
    assert captured["start_new_session"] is True


def test_identity_injected_into_env(repo_root: Path, fake_proc: MagicMock) -> None:
    captured_env: dict[str, str] = {}

    def fake_popen(argv, *, cwd, stdout, stderr, text, env, start_new_session):
        captured_env.update(env)
        return fake_proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        run_web("search", ["q"], root=repo_root)
    assert "CONVERTIBLE_IDENTITY" in captured_env


# ---------------------------------------------------------------------------
# AC: no .poll() loop, no socket/threading/asyncio import
# ---------------------------------------------------------------------------


def test_no_forbidden_primitives_in_source() -> None:
    source = Path("colleague/web.py").read_text(encoding="utf-8")
    for forbidden in ("import socket", "import asyncio", "import threading", ".poll("):
        assert forbidden not in source, f"web.py must not use {forbidden!r}"


def test_no_adapted_from_header() -> None:
    source = Path("colleague/web.py").read_text(encoding="utf-8")
    assert "adapted-from" not in source.lower()


# ---------------------------------------------------------------------------
# AC: real subprocess — the whole process group is killed on timeout
# ---------------------------------------------------------------------------


def test_timeout_kills_whole_process_group(tmp_path: Path, repo_root: Path, monkeypatch) -> None:
    """A hung webglass that spawns a sleeping grandchild must have BOTH the
    child and the grandchild reaped when the group is killed on timeout."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "grandchild.pid"

    script_body = f"""#!/bin/sh
sleep 60 &
echo $! > "{pid_file}"
sleep 60
"""
    _write_script(bin_dir, "webglass", script_body)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setattr("colleague.web._TIMEOUT_SECONDS", 2)

    with pytest.raises(WebToolError) as exc_info:
        run_web("search", ["q"], root=repo_root)
    assert "timed out" in str(exc_info.value).lower()

    # Give the OS a brief moment to finish reaping the killed grandchild.
    deadline = time.time() + 5
    grandchild_pid = None
    while time.time() < deadline:
        if pid_file.exists():
            content = pid_file.read_text(encoding="utf-8").strip()
            if content:
                grandchild_pid = int(content)
                break
        time.sleep(0.1)

    assert grandchild_pid is not None, "fake webglass never wrote the grandchild pid"

    dead = False
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            dead = True
            break
        except PermissionError:
            # Reparented to a different owner/zombie edge case: treat as gone.
            dead = True
            break
        time.sleep(0.1)

    assert dead, f"grandchild pid {grandchild_pid} is still alive after group kill"


def test_success_with_real_fake_cli(tmp_path: Path, repo_root: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script_body = """#!/bin/sh
echo "$@"
echo '{"ok": true}'
"""
    _write_script(bin_dir, "webglass", script_body)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    result = run_web("page open", ["https://example.com"], root=repo_root)
    assert result.startswith("exit=0\n")
    assert "page open https://example.com --json" in result
    assert '{"ok": true}' in result

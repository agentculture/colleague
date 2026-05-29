"""Tests for convertible/devague.py — curated devague CLI shell-out launcher.

Written test-first (TDD): tests define the contract, implementation follows.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from convertible.devague import (
    ALLOWED_MOVES,
    DevagueToolError,
    normalize_args,
    run_devague,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """A minimal repo root with an identity.json so identity resolves."""
    identity_dir = tmp_path / ".convertible"
    identity_dir.mkdir()
    (identity_dir / "identity.json").write_text(json.dumps({"as": "test-agent"}), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def fake_proc() -> MagicMock:
    """A fake CompletedProcess returned by monkeypatched subprocess.run."""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "ok\n"
    proc.stderr = ""
    return proc


# ---------------------------------------------------------------------------
# AC: ALLOWED_MOVES set
# ---------------------------------------------------------------------------


def test_allowed_moves_exact_set() -> None:
    """ALLOWED_MOVES must contain exactly the 7 permitted moves."""
    assert ALLOWED_MOVES == frozenset(
        {"new", "capture", "interrogate", "park", "converge", "status", "show"}
    )


def test_allowed_moves_excludes_confirm() -> None:
    assert "confirm" not in ALLOWED_MOVES


def test_allowed_moves_excludes_reject() -> None:
    assert "reject" not in ALLOWED_MOVES


def test_allowed_moves_excludes_export() -> None:
    assert "export" not in ALLOWED_MOVES


# ---------------------------------------------------------------------------
# AC: each of the 7 allowed moves is accepted and subprocess is called
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("move", sorted(ALLOWED_MOVES))
def test_allowed_move_calls_subprocess(move: str, repo_root: Path, fake_proc: MagicMock) -> None:
    """Each allowed move must invoke subprocess.run and return the output format."""
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        result = run_devague(move, [], root=repo_root)

    mock_run.assert_called_once()
    # Verify the output format: starts with "exit=<code>\n"
    assert result.startswith("exit=0\n")
    # Verify argv: first element is "devague", second is the move
    call_args = mock_run.call_args
    argv = call_args[0][0]
    assert argv[0] == "devague"
    assert argv[1] == move


# ---------------------------------------------------------------------------
# AC: confirm / reject / export raise DevagueToolError — NO subprocess spawned
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("move", ["confirm", "reject", "export"])
def test_user_only_moves_raise_error_no_subprocess(move: str, repo_root: Path) -> None:
    """Excluded moves must raise DevagueToolError before any subprocess is spawned."""
    with patch("subprocess.run") as mock_run:
        with pytest.raises(DevagueToolError):
            run_devague(move, [], root=repo_root)

    # Critical: subprocess.run must NEVER have been called
    assert mock_run.call_count == 0


def test_confirm_error_message_lists_allowed(repo_root: Path) -> None:
    """The error message for a disallowed move should mention allowed moves."""
    with patch("subprocess.run"):
        with pytest.raises(DevagueToolError) as exc_info:
            run_devague("confirm", [], root=repo_root)

    msg = str(exc_info.value)
    assert "confirm" in msg
    # Should list allowed moves
    assert "new" in msg or "allowed" in msg.lower()


# ---------------------------------------------------------------------------
# AC: CONVERTIBLE_IDENTITY is injected + cwd equals the resolved root
# ---------------------------------------------------------------------------


def test_identity_injected_into_env(repo_root: Path, fake_proc: MagicMock) -> None:
    """CONVERTIBLE_IDENTITY must be present in the subprocess env."""
    captured_env: dict[str, str] = {}

    def fake_run(argv, *, cwd, capture_output, text, timeout, env):
        captured_env.update(env)
        return fake_proc

    with patch("subprocess.run", side_effect=fake_run):
        run_devague("status", [], root=repo_root)

    assert "CONVERTIBLE_IDENTITY" in captured_env


def test_cwd_is_resolved_root(repo_root: Path, fake_proc: MagicMock) -> None:
    """The subprocess cwd must equal the resolved repo root."""
    captured_cwd: list[str] = []

    def fake_run(argv, *, cwd, capture_output, text, timeout, env):
        captured_cwd.append(cwd)
        return fake_proc

    with patch("subprocess.run", side_effect=fake_run):
        run_devague("status", [], root=repo_root)

    assert captured_cwd[0] == str(repo_root.resolve())


def test_identity_value_propagated(repo_root: Path, fake_proc: MagicMock) -> None:
    """The identity value from identity.json must be injected as CONVERTIBLE_IDENTITY."""
    captured_env: dict[str, str] = {}

    def fake_run(argv, *, cwd, capture_output, text, timeout, env):
        captured_env.update(env)
        return fake_proc

    with patch("subprocess.run", side_effect=fake_run):
        run_devague("new", ["my-frame"], root=repo_root)

    assert captured_env.get("CONVERTIBLE_IDENTITY") == "test-agent"


def test_args_forwarded_to_subprocess(repo_root: Path, fake_proc: MagicMock) -> None:
    """Extra args must be forwarded after the move name."""
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        run_devague("capture", ["--frame", "my-frame", "--text", "hello"], root=repo_root)

    argv = mock_run.call_args[0][0]
    assert argv == ["devague", "capture", "--frame", "my-frame", "--text", "hello"]


# ---------------------------------------------------------------------------
# AC: missing binary → graceful DevagueToolError (no traceback escapes)
# ---------------------------------------------------------------------------


def test_missing_binary_raises_devague_tool_error(repo_root: Path) -> None:
    """FileNotFoundError from subprocess must be mapped to DevagueToolError."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(DevagueToolError) as exc_info:
            run_devague("status", [], root=repo_root)

    msg = str(exc_info.value)
    assert "devague" in msg.lower()
    assert "not found" in msg.lower() or "installed" in msg.lower()


def test_missing_binary_no_file_not_found_propagates(repo_root: Path) -> None:
    """FileNotFoundError must NOT propagate — it is caught and re-raised as DevagueToolError."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(DevagueToolError):
            run_devague("show", [], root=repo_root)


# ---------------------------------------------------------------------------
# AC: output format
# ---------------------------------------------------------------------------


def test_output_format_includes_exit_code(repo_root: Path) -> None:
    """Return value must start with 'exit=<code>\\n'."""
    proc = MagicMock()
    proc.returncode = 42
    proc.stdout = "some output"
    proc.stderr = ""

    with patch("subprocess.run", return_value=proc):
        result = run_devague("status", [], root=repo_root)

    assert result.startswith("exit=42\n")
    assert "some output" in result


def test_output_truncated_at_max_chars(repo_root: Path) -> None:
    """Output exceeding _MAX_OUTPUT_CHARS must be truncated."""
    from convertible.devague import _MAX_OUTPUT_CHARS

    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "x" * (_MAX_OUTPUT_CHARS + 1000)
    proc.stderr = ""

    with patch("subprocess.run", return_value=proc):
        result = run_devague("status", [], root=repo_root)

    assert len(result) < _MAX_OUTPUT_CHARS + 100  # some slack for the truncation suffix
    assert "truncated" in result


def test_stderr_included_in_output(repo_root: Path) -> None:
    """Both stdout and stderr must be concatenated in the return value."""
    proc = MagicMock()
    proc.returncode = 1
    proc.stdout = "out-part"
    proc.stderr = "err-part"

    with patch("subprocess.run", return_value=proc):
        result = run_devague("show", [], root=repo_root)

    assert "out-part" in result
    assert "err-part" in result


# ---------------------------------------------------------------------------
# AC: normalize_args handles list / string / None
# ---------------------------------------------------------------------------


def test_normalize_args_list() -> None:
    assert normalize_args(["a", "b", "c"]) == ["a", "b", "c"]


def test_normalize_args_list_coerces_to_str() -> None:
    assert normalize_args([1, 2, 3]) == ["1", "2", "3"]


def test_normalize_args_string_splits() -> None:
    assert normalize_args("a b c") == ["a", "b", "c"]


def test_normalize_args_none_returns_empty() -> None:
    assert normalize_args(None) == []


def test_normalize_args_empty_list() -> None:
    assert normalize_args([]) == []


def test_normalize_args_tuple() -> None:
    assert normalize_args(("a", "b")) == ["a", "b"]


def test_normalize_args_unknown_type_returns_empty() -> None:
    assert normalize_args(42) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC: no subprocess spawned when move is not in ALLOWED_MOVES (general)
# ---------------------------------------------------------------------------


def test_arbitrary_disallowed_move_no_subprocess(repo_root: Path) -> None:
    """Any move not in ALLOWED_MOVES must raise before spawning a subprocess."""
    with patch("subprocess.run") as mock_run:
        with pytest.raises(DevagueToolError):
            run_devague("delete", [], root=repo_root)

    assert mock_run.call_count == 0


def test_devague_not_imported_as_module() -> None:
    """The devague module must never be imported as Python (shell-out only)."""
    import sys

    assert "devague" not in sys.modules

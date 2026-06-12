"""t7 — self-registration: steward template path + arrival signal.

Acceptance criteria:
  1. register_resident writes culture.yaml + prompt into the steward location; after
     registration resolve_identity(steward_root) == suffix.
  2. Idempotent: calling it twice with the same args leaves a single, uncorrupted
     registration (same file content; no error).
  3. Arrival is signalled via run_steward (assert it was called with the arrival
     subcommand — monkeypatch to record the call); when run_steward raises
     StewardError the result degrades cleanly (signalled=False, a note) and no
     exception escapes.
"""

from __future__ import annotations

from colleague.identity import resolve_identity
from colleague.resident.register import (
    ARRIVAL_SUBCOMMAND,
    RegisterResult,
    register_resident,
)
from colleague.resident.steward import StewardError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_run_steward_ok(cli, args, *, root):
    """Monkeypatch target: simulates a successful steward call."""
    return f"exit=0\nsteward {' '.join(args)} ok"


def _make_run_steward_error(cli, args, *, root):
    """Monkeypatch target: simulates a missing/hung steward CLI."""
    raise StewardError(f"roster CLI '{cli}' not found — is it installed and on PATH?")


def _fake_run_steward_nonzero(cli, args, *, root):
    """Monkeypatch target: the CLI ran but reported a non-zero exit."""
    return f"exit=3\nsteward {' '.join(args)}: not reachable"


class TestNonZeroArrivalExit:
    """A CLI that ran but exited non-zero is NOT a successful arrival (qodo flag)."""

    def test_non_zero_exit_records_not_signalled(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_nonzero)
        result = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert result.signalled is False


# ---------------------------------------------------------------------------
# AC1 — files written; resolve_identity round-trip
# ---------------------------------------------------------------------------


class TestFilesWritten:
    """AC1: register_resident writes the identity files at steward_root."""

    def test_culture_yaml_written(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert (tmp_path / "culture.yaml").exists()

    def test_prompt_file_written(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert (tmp_path / "AGENTS.colleague.md").exists()

    def test_culture_yaml_has_correct_suffix_and_model(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="nova", model="llama3")
        text = (tmp_path / "culture.yaml").read_text()
        assert "suffix: nova" in text
        assert "model: llama3" in text
        assert "backend: colleague" in text

    def test_resolve_identity_returns_suffix(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert resolve_identity(tmp_path) == "spark"

    def test_resolve_identity_at_steward_root(self, tmp_path, monkeypatch) -> None:
        """When steward_root differs from repo_path, identity is at steward_root."""
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        repo = tmp_path / "repo"
        steward = tmp_path / "steward_dir"
        repo.mkdir()
        steward.mkdir()
        register_resident(repo, suffix="peer", model="mixtral", steward_root=steward)
        # culture.yaml at steward_root, not at repo
        assert (steward / "culture.yaml").exists()
        assert not (repo / "culture.yaml").exists()
        assert resolve_identity(steward) == "peer"

    def test_returns_register_result(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        result = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert isinstance(result, RegisterResult)
        assert result.nick == "spark"
        assert result.culture_yaml_path == tmp_path / "culture.yaml"
        assert result.prompt_path == tmp_path / "AGENTS.colleague.md"

    def test_custom_prompt_text_propagated(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b", prompt_text="hello resident")
        assert "hello resident" in (tmp_path / "AGENTS.colleague.md").read_text()


# ---------------------------------------------------------------------------
# AC2 — idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    """AC2: calling register_resident twice with the same args is a clean no-op."""

    def test_second_call_leaves_same_culture_yaml(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        text_first = (tmp_path / "culture.yaml").read_text()
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        text_second = (tmp_path / "culture.yaml").read_text()
        assert text_first == text_second

    def test_second_call_does_not_raise(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        # Must not raise
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")

    def test_second_call_identity_still_resolves(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert resolve_identity(tmp_path) == "spark"

    def test_second_call_returns_same_nick(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        r1 = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        r2 = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert r1.nick == r2.nick == "spark"


# ---------------------------------------------------------------------------
# AC3 — arrival signal + graceful degrade
# ---------------------------------------------------------------------------


class TestArrivalSignal:
    """AC3a: arrival is signalled via run_steward with ARRIVAL_SUBCOMMAND."""

    def test_run_steward_called_on_registration(self, tmp_path, monkeypatch) -> None:
        calls: list[tuple[str, list[str]]] = []

        def _recording_run_steward(cli, args, *, root):
            calls.append((cli, list(args)))
            return "exit=0\nok"

        monkeypatch.setattr("colleague.resident.register.run_steward", _recording_run_steward)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert len(calls) == 1

    def test_run_steward_called_with_arrival_subcommand(self, tmp_path, monkeypatch) -> None:
        calls: list[tuple[str, list[str]]] = []

        def _recording_run_steward(cli, args, *, root):
            calls.append((cli, list(args)))
            return "exit=0\nok"

        monkeypatch.setattr("colleague.resident.register.run_steward", _recording_run_steward)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        _, args_used = calls[0]
        assert args_used == ARRIVAL_SUBCOMMAND

    def test_run_steward_called_with_default_cli(self, tmp_path, monkeypatch) -> None:
        calls: list[tuple[str, list[str]]] = []

        def _recording_run_steward(cli, args, *, root):
            calls.append((cli, list(args)))
            return "exit=0\nok"

        monkeypatch.setattr("colleague.resident.register.run_steward", _recording_run_steward)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        cli_used, _ = calls[0]
        assert cli_used == "steward"

    def test_signalled_true_on_success(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        result = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert result.signalled is True

    def test_signal_output_captured(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        result = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert result.signal_output  # non-empty

    def test_custom_arrival_args_forwarded(self, tmp_path, monkeypatch) -> None:
        calls: list[tuple[str, list[str]]] = []

        def _recording_run_steward(cli, args, *, root):
            calls.append((cli, list(args)))
            return "exit=0\nok"

        monkeypatch.setattr("colleague.resident.register.run_steward", _recording_run_steward)
        custom_args = ["register", "--nick", "spark"]
        register_resident(
            tmp_path,
            suffix="spark",
            model="qwen3-27b",
            arrival_args=custom_args,
        )
        _, args_used = calls[0]
        assert args_used == custom_args

    def test_custom_steward_cli_forwarded(self, tmp_path, monkeypatch) -> None:
        calls: list[tuple[str, list[str]]] = []

        def _recording_run_steward(cli, args, *, root):
            calls.append((cli, list(args)))
            return "exit=0\nok"

        monkeypatch.setattr("colleague.resident.register.run_steward", _recording_run_steward)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b", steward_cli="culture")
        cli_used, _ = calls[0]
        assert cli_used == "culture"

    def test_signal_false_skips_run_steward(self, tmp_path, monkeypatch) -> None:
        calls: list[tuple[str, list[str]]] = []

        def _recording_run_steward(cli, args, *, root):
            calls.append((cli, list(args)))
            return "exit=0\nok"

        monkeypatch.setattr("colleague.resident.register.run_steward", _recording_run_steward)
        result = register_resident(tmp_path, suffix="spark", model="qwen3-27b", signal=False)
        assert calls == []
        assert result.signalled is False
        assert result.signal_output == ""

    def test_files_still_written_when_signal_false(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b", signal=False)
        assert (tmp_path / "culture.yaml").exists()
        assert (tmp_path / "AGENTS.colleague.md").exists()


class TestGracefulDegrade:
    """AC3b: StewardError degrades cleanly; no exception escapes; files are preserved."""

    def test_no_exception_when_steward_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _make_run_steward_error)
        # Must not raise
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")

    def test_signalled_false_on_steward_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _make_run_steward_error)
        result = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert result.signalled is False

    def test_signal_output_contains_note_on_degrade(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _make_run_steward_error)
        result = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert result.signal_output  # non-empty degradation note
        # The note should mention the CLI name or signal failure
        assert "steward" in result.signal_output.lower() or "signal" in result.signal_output.lower()

    def test_files_written_even_on_steward_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _make_run_steward_error)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert (tmp_path / "culture.yaml").exists()
        assert (tmp_path / "AGENTS.colleague.md").exists()

    def test_identity_resolves_even_on_steward_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _make_run_steward_error)
        register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert resolve_identity(tmp_path) == "spark"

    def test_nick_correct_in_result_on_steward_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("colleague.resident.register.run_steward", _make_run_steward_error)
        result = register_resident(tmp_path, suffix="nova", model="llama3")
        assert result.nick == "nova"

    def test_idempotent_degrade_then_success(self, tmp_path, monkeypatch) -> None:
        """A degraded call followed by a successful one works cleanly."""
        monkeypatch.setattr("colleague.resident.register.run_steward", _make_run_steward_error)
        r1 = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert r1.signalled is False

        monkeypatch.setattr("colleague.resident.register.run_steward", _fake_run_steward_ok)
        r2 = register_resident(tmp_path, suffix="spark", model="qwen3-27b")
        assert r2.signalled is True
        assert resolve_identity(tmp_path) == "spark"


# ---------------------------------------------------------------------------
# Boundary: no subprocess import in register.py
# ---------------------------------------------------------------------------


class TestNoBoundaryViolation:
    """register.py must not import subprocess directly."""

    def test_no_subprocess_import(self) -> None:
        import ast
        import pathlib

        src = pathlib.Path(__file__).parent.parent / "colleague" / "resident" / "register.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "subprocess", (
                        "register.py must not import subprocess directly; "
                        "use run_steward from colleague.resident.steward"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert (
                    node.module != "subprocess"
                ), "register.py must not import from subprocess directly"

"""Tests for escalation gating + idempotency (issue #106, task t2).

Covers:
  - should_escalate returns False by default (flag unset).
  - should_escalate returns True when ALL gates are favorable.
  - Linked-worktree detection via .git-is-a-file filesystem check.
  - Policy gate denies agtag when run_command allow-list excludes it.
  - Idempotency: mark_escalated followed by should_escalate returns False.
  - mark_escalated writes the expected JSON marker structure.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import colleague.escalation as escalation_mod
from colleague.escalation import mark_escalated, should_escalate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_main_repo(tmp_path: Path) -> Path:
    """Simulate a main checkout: .git is a DIRECTORY."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _make_worktree_repo(tmp_path: Path) -> Path:
    """Simulate a linked git worktree: .git is a FILE (gitdir pointer)."""
    repo = tmp_path / "worktree"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /some/path/.git/worktrees/sub\n", encoding="utf-8")
    return repo


def _make_colleague_dir(repo: Path) -> Path:
    """Create the .colleague dir so policy resolution has a home."""
    d = repo / ".colleague"
    d.mkdir(exist_ok=True)
    return d


def _write_approvals(colleague_dir: Path, allowed_tokens: list[str]) -> None:
    """Write an approvals.json with a run_command allow-list."""
    (colleague_dir / "approvals.json").write_text(
        json.dumps({"run_command": {"allow": allowed_tokens}}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Gate 1 — opt-in (env flag)
# ---------------------------------------------------------------------------


class TestDefaultOff:
    """Without the env flag, should_escalate is always False."""

    def test_flag_unset_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """Flag unset → False regardless of any other condition."""
        monkeypatch.delenv("COLLEAGUE_ESCALATE", raising=False)
        monkeypatch.delenv("CONVERTIBLE_ESCALATE", raising=False)

        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            assert should_escalate(repo, "task-abc") is False

    def test_flag_set_to_zero_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """Explicit '0' is falsy — still no escalation."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "0")

        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            assert should_escalate(repo, "task-abc") is False

    def test_flag_set_to_false_string_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """Explicit 'false' is falsy."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "false")

        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            assert should_escalate(repo, "task-abc") is False

    def test_legacy_flag_honored_as_truthy(self, tmp_path: Path, monkeypatch) -> None:
        """CONVERTIBLE_ESCALATE=1 activates escalation (legacy fallback)."""
        monkeypatch.delenv("COLLEAGUE_ESCALATE", raising=False)
        monkeypatch.setenv("CONVERTIBLE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            # Policy allows agtag (no run_command section → no-op / all allowed).
            result = should_escalate(repo, "task-legacy")
        assert result is True


# ---------------------------------------------------------------------------
# All gates favorable → True
# ---------------------------------------------------------------------------


class TestAllGatesFavorable:
    """When every gate passes, should_escalate returns True."""

    def test_all_favorable_returns_true(self, tmp_path: Path, monkeypatch) -> None:
        """Flag on + main checkout + remote + gh + policy-allows + no marker → True."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        # No .colleague/approvals.json → run_command section absent → no-op (all allowed).
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            result = should_escalate(repo, "unique-task-123")

        assert result is True

    def test_explicit_agtag_allow_list_passes(self, tmp_path: Path, monkeypatch) -> None:
        """Flag on + agtag in allow-list → True."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        colleague_dir = _make_colleague_dir(repo)
        _write_approvals(colleague_dir, ["agtag", "git", "pytest"])

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            result = should_escalate(repo, "task-with-policy")

        assert result is True


# ---------------------------------------------------------------------------
# Gate 3 — linked worktree detection (filesystem check, no subprocess)
# ---------------------------------------------------------------------------


class TestWorktreeDetection:
    """A linked git worktree (.git is a file) never escalates."""

    def test_git_file_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """When .git is a FILE (linked worktree), should_escalate returns False."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_worktree_repo(tmp_path)
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            result = should_escalate(repo, "task-in-worktree")

        assert result is False

    def test_git_directory_passes_this_gate(self, tmp_path: Path, monkeypatch) -> None:
        """When .git is a DIRECTORY (main checkout), this gate passes."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        # We only care that *this* gate doesn't block; other gates may pass or fail.
        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            result = should_escalate(repo, "task-main-checkout")

        # Policy no-op + no marker → True (all other gates pass with our stubs).
        assert result is True


# ---------------------------------------------------------------------------
# Gate 2 — online / non-CI (remote + gh)
# ---------------------------------------------------------------------------


class TestOnlineGuard:
    """No remote or no gh → False."""

    def test_no_remote_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")
        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=False),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            assert should_escalate(repo, "t") is False

    def test_no_gh_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")
        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=False),
        ):
            assert should_escalate(repo, "t") is False


# ---------------------------------------------------------------------------
# Gate 4 — approval gate (policy)
# ---------------------------------------------------------------------------


class TestPolicyGate:
    """If the policy denies agtag, should_escalate returns False."""

    def test_agtag_not_in_allow_list_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """run_command section present but agtag excluded → policy denies → False."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        colleague_dir = _make_colleague_dir(repo)
        # Allow list present but does NOT include agtag.
        _write_approvals(colleague_dir, ["git", "pytest", "uv"])

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            result = should_escalate(repo, "task-policy-deny")

        assert result is False

    def test_agtag_on_deny_list_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """agtag explicitly on the deny list → policy denies → False."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        colleague_dir = _make_colleague_dir(repo)
        (colleague_dir / "approvals.json").write_text(
            json.dumps({"run_command": {"allow": [], "deny": ["agtag"]}}),
            encoding="utf-8",
        )

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            result = should_escalate(repo, "task-deny-list")

        assert result is False


# ---------------------------------------------------------------------------
# Gate 5 — idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """A second escalation for the same task_id must be rejected."""

    def test_already_marked_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """mark_escalated then should_escalate for same task_id → False."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        # First run: no marker, all gates pass → should be True.
        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            first = should_escalate(repo, "task-idempotent")
        assert first is True

        # Record the escalation.
        mark_escalated(repo, "task-idempotent", "https://example.com/issues/1")

        # Second run: marker exists → False.
        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            second = should_escalate(repo, "task-idempotent")
        assert second is False

    def test_different_task_ids_are_independent(self, tmp_path: Path, monkeypatch) -> None:
        """Marking one task_id does not block a different task_id."""
        monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")

        repo = _make_main_repo(tmp_path)
        _make_colleague_dir(repo)

        mark_escalated(repo, "task-one", "https://example.com/issues/1")

        with (
            patch.object(escalation_mod, "has_remote", return_value=True),
            patch.object(escalation_mod, "gh_available", return_value=True),
        ):
            result = should_escalate(repo, "task-two")

        assert result is True


# ---------------------------------------------------------------------------
# mark_escalated — structure of the marker
# ---------------------------------------------------------------------------


class TestMarkEscalated:
    """mark_escalated writes the expected JSON marker."""

    def test_writes_json_marker(self, tmp_path: Path) -> None:
        """The marker is valid JSON with task_id and issue_url."""
        repo = tmp_path / "repo"
        repo.mkdir()

        mark_escalated(repo, "abc123", "https://example.com/issues/42")

        marker = repo / ".colleague" / "abc123.escalation.json"
        assert marker.is_file(), "Marker file was not written"
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["task_id"] == "abc123"
        assert data["issue_url"] == "https://example.com/issues/42"

    def test_overwrite_is_silent(self, tmp_path: Path) -> None:
        """A second mark_escalated for the same id overwrites without raising."""
        repo = tmp_path / "repo"
        repo.mkdir()

        mark_escalated(repo, "dup-task", "https://example.com/issues/1")
        mark_escalated(repo, "dup-task", "https://example.com/issues/99")

        marker = repo / ".colleague" / "dup-task.escalation.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["issue_url"] == "https://example.com/issues/99"

    def test_creates_colleague_dir(self, tmp_path: Path) -> None:
        """mark_escalated creates .colleague/ if it does not exist."""
        repo = tmp_path / "fresh"
        repo.mkdir()
        assert not (repo / ".colleague").exists()

        mark_escalated(repo, "t1", "https://x.com")

        assert (repo / ".colleague").is_dir()

"""Scoped doc-review command expansion test.

Verifies that the doc-review command template expands correctly when given a
single-surface argument, following the same pattern as tests/test_commands.py.
"""

from __future__ import annotations

from pathlib import Path
from shutil import copy2

from colleague.commands import expand_command


def _make_repo(tmp_path: Path, subpath: str = "repo") -> Path:
    """Create a minimal repo directory under tmp_path."""
    repo = tmp_path / subpath
    repo.mkdir()
    return repo


def _make_commands_dir(base: Path) -> Path:
    """Create .colleague/commands/ directory tree under base."""
    cmds_dir = base / ".colleague" / "commands"
    cmds_dir.mkdir(parents=True)
    return cmds_dir


def _expand_with(tmp_path: Path, args: list[str]):
    """Copy the real doc-review.md into a temp repo and expand it with ``args``."""
    repo = _make_repo(tmp_path)
    cmds_dir = _make_commands_dir(repo)
    copy2(Path(".colleague/commands/doc-review.md"), cmds_dir / "doc-review.md")
    return expand_command(repo, "doc-review", args, user_home=tmp_path / "home")


class TestDocReviewScoped:
    def test_scoped_expansion_names_the_surface(self, tmp_path: Path) -> None:
        """A scoped expansion substitutes the surface name into the task."""
        task = _expand_with(tmp_path, ["README"])
        assert "README" in task.instruction

    def test_scoped_expansion_carries_single_surface_directive(self, tmp_path: Path) -> None:
        """Acceptance #1: a scoped audit instructs single-surface-only coverage
        and an out-of-scope note (the fan-out-ready behavior)."""
        task = _expand_with(tmp_path, ["README"])
        assert "ONLY that one" in task.instruction
        assert "Out of scope for this" in task.instruction

    def test_empty_scope_preserves_audit_all(self, tmp_path: Path) -> None:
        """No scope arg → behavior unchanged: still audits all docs."""
        task = _expand_with(tmp_path, [])
        assert "audit ALL docs" in task.instruction

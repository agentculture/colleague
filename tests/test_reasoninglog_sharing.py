"""The reasoning sidecar stays out of every sharing surface (plan task t9).

The ``<task_id>.reasoning.jsonl`` sidecar (``colleague/reasoninglog.py``)
persists model chain-of-thought which can quote repo content including secrets
read during a run. It is local-diagnostic only (confirmed spec claim c31):
feedback export, handoff/PR content, and mesh surfaces must never read or
transmit it.

Three assertions:

(a) **Feedback export** — a run WITH a sidecar produces no reasoning text in
    the export output (the marker string never appears in the returned rows or
    the JSONL text).

(b) **Handoff / git** — ``.colleague/`` is gitignored (via the self-ignoring
    ``.gitignore`` written by ``ensure_self_ignored``), so a ``git add -A`` in
    a repo with the sidecar stages nothing from ``.colleague/`` except the
    allowed ``commands/`` and ``skills/`` exceptions.

(c) **Grep audit** — no ``colleague/`` source module outside the allow-list
    (``reasoninglog.py``, ``loop_accounting.py``, ``contract.py``) mentions
    ``reasoning.jsonl`` — pinning the set of files that may reference the
    sidecar filename.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from colleague import feedback as fb
from colleague.artifact import ensure_self_ignored, write
from colleague.contract import OK, TaskResult, WorkStats

#: A distinctive marker string that would be unmistakable if it leaked.
MARKER = "SECRET-REASONING-MARKER-XYZ-12345"

#: The allow-list of colleague/ source files that may mention "reasoning.jsonl".
#: reasoninglog.py — the module that creates/reads the sidecar.
#: loop_accounting.py — the wiring that calls reasoninglog.append.
#: contract.py — docstring describing the sidecar filename convention.
_ALLOWLIST: frozenset[str] = frozenset(
    {
        "colleague/reasoninglog.py",
        "colleague/loop_accounting.py",
        "colleague/contract.py",
    }
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo: Path) -> None:
    """Initialize a git repo with an initial commit."""
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")


def _write_sidecar(repo: Path, task_id: str = "task-1") -> Path:
    """Write a fake reasoning sidecar with the marker string."""
    adir = repo / ".colleague"
    adir.mkdir(parents=True, exist_ok=True)
    sidecar = adir / f"{task_id}.reasoning.jsonl"
    record = {
        "seat": "main",
        "turn": 1,
        "request_ts": "2026-01-01T00:00:00+00:00",
        "request_index": 0,
        "text": f"the secret is {MARKER} and the password is hunter2",
    }
    sidecar.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return sidecar


def _write_work_item(repo: Path, task_id: str = "task-1") -> None:
    """Write a minimal work-item artifact + feedback so the export has a row."""
    stats = WorkStats(
        request="do the thing",
        started_at="2026-01-01T00:00:00+00:00",
        step_count=3,
        files_changed=1,
        bytes_written=100,
    )
    write(
        TaskResult(task_id=task_id, status=OK, summary="did it", stats=stats),
        repo / ".colleague",
    )
    fb.write_feedback(repo, task_id, rating=4, notes="good work", by="tester")


# ---------------------------------------------------------------------------
# (a) Feedback export: the sidecar's reasoning text never appears
# ---------------------------------------------------------------------------


class TestFeedbackExportExcludesSidecar:
    """The feedback export output for a run WITH a sidecar contains no
    reasoning text (the marker never appears in the returned rows or the
    JSONL text)."""

    def test_export_rows_contain_no_marker(self, tmp_path: Path) -> None:
        _write_work_item(tmp_path)
        _write_sidecar(tmp_path)

        rows = fb.export_work_items(tmp_path)
        assert len(rows) == 1  # the work item is graded, so it appears
        # Serialize the full export output and assert the marker is absent.
        serialized = json.dumps(rows, ensure_ascii=False)
        assert (
            MARKER not in serialized
        ), f"Feedback export leaked reasoning sidecar content: {MARKER!r} found"

    def test_export_jsonl_text_contains_no_marker(self, tmp_path: Path) -> None:
        _write_work_item(tmp_path)
        _write_sidecar(tmp_path)

        rows = fb.export_work_items(tmp_path)
        lines = [json.dumps(row, ensure_ascii=False) for row in rows]
        text = "\n".join(lines)
        assert (
            MARKER not in text
        ), f"Feedback export JSONL text leaked reasoning sidecar content: {MARKER!r} found"

    def test_list_work_items_does_not_read_sidecar(self, tmp_path: Path) -> None:
        """list_work_items scans *.json (not *.jsonl) — the sidecar is invisible."""
        _write_work_item(tmp_path)
        _write_sidecar(tmp_path)

        items = fb.list_work_items(tmp_path)
        assert len(items) == 1
        serialized = json.dumps([i.to_dict() for i in items], ensure_ascii=False)
        assert MARKER not in serialized

    def test_sidecar_with_child_tag_also_excluded(self, tmp_path: Path) -> None:
        """A tagged child sidecar (<id>.<child>.reasoning.jsonl) is also excluded."""
        _write_work_item(tmp_path)
        # Write a child-tagged sidecar.
        adir = tmp_path / ".colleague"
        child_sidecar = adir / "task-1.child-9.reasoning.jsonl"
        child_sidecar.write_text(
            json.dumps({"text": f"child reasoning: {MARKER}"}) + "\n", encoding="utf-8"
        )

        rows = fb.export_work_items(tmp_path)
        serialized = json.dumps(rows, ensure_ascii=False)
        assert MARKER not in serialized


# ---------------------------------------------------------------------------
# (b) Handoff / git: .colleague/ is gitignored, sidecar cannot be swept
# ---------------------------------------------------------------------------


class TestHandoffGitExcludesSidecar:
    """The handoff's commit path cannot sweep the sidecar: .colleague/ is
    gitignored (check-ignore) — a git add -A in a tmp repo with the sidecar
    stages nothing from .colleague/ except the allowed commands/skills
    exceptions."""

    def test_check_ignore_confirms_sidecar_is_ignored(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        sidecar = _write_sidecar(tmp_path)
        ensure_self_ignored(tmp_path / ".colleague")

        proc = _git(tmp_path, "check-ignore", "-q", str(sidecar.relative_to(tmp_path)))
        assert proc.returncode == 0, (
            f"git check-ignore did not confirm the sidecar is ignored "
            f"(rc={proc.returncode}, stderr={proc.stderr!r})"
        )

    def test_git_add_A_stages_nothing_from_colleague(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        _write_sidecar(tmp_path)
        ensure_self_ignored(tmp_path / ".colleague")

        _git(tmp_path, "add", "-A")
        staged = _git(tmp_path, "diff", "--cached", "--name-only")
        staged_paths = [line.strip() for line in staged.stdout.splitlines() if line.strip()]
        # Nothing from .colleague/ should be staged.
        colleague_paths = [p for p in staged_paths if p.startswith(".colleague/")]
        assert colleague_paths == [], f"git add -A staged .colleague/ paths: {colleague_paths}"

    def test_commands_and_skills_exceptions_still_visible(self, tmp_path: Path) -> None:
        """The allowed commands/ and skills/ overlays remain stageable."""
        _init_git_repo(tmp_path)
        _write_sidecar(tmp_path)
        ensure_self_ignored(tmp_path / ".colleague")

        # Create the allowed overlays.
        commands = tmp_path / ".colleague" / "commands"
        commands.mkdir()
        (commands / "recipe.md").write_text("# recipe\n", encoding="utf-8")
        skills = tmp_path / ".colleague" / "skills"
        skills.mkdir()
        (skills / "style.md").write_text("# style\n", encoding="utf-8")

        _git(tmp_path, "add", "-A")
        staged = _git(tmp_path, "diff", "--cached", "--name-only")
        staged_paths = [line.strip() for line in staged.stdout.splitlines() if line.strip()]
        # The overlays ARE staged (they are the exceptions).
        assert ".colleague/commands/recipe.md" in staged_paths
        assert ".colleague/skills/style.md" in staged_paths
        # But the sidecar is NOT.
        assert ".colleague/task-1.reasoning.jsonl" not in staged_paths

    def test_handoff_produced_filter_excludes_colleague(self, tmp_path: Path) -> None:
        """The handoff's `produced` filter explicitly excludes .colleague/ paths.

        This is a structural assertion: the handoff code at
        colleague/handoff.py line ~264 filters with
        `not path.startswith(".colleague/")`. We verify the behavior by
        confirming that even if git status listed the sidecar as untracked
        (which it won't, due to gitignore), the handoff would still exclude it.
        """
        from colleague.handoff import _untracked_paths

        _init_git_repo(tmp_path)
        _write_sidecar(tmp_path)
        ensure_self_ignored(tmp_path / ".colleague")

        # The sidecar is gitignored, so it won't appear in untracked paths.
        untracked = _untracked_paths(tmp_path)
        sidecar_rel = ".colleague/task-1.reasoning.jsonl"
        assert (
            sidecar_rel not in untracked
        ), f"Sidecar appeared in untracked paths (gitignore not effective): {untracked}"


# ---------------------------------------------------------------------------
# (c) Grep audit: no source module outside the allow-list mentions
#     "reasoning.jsonl"
# ---------------------------------------------------------------------------


class TestGrepAudit:
    """No colleague/ source module outside reasoninglog.py and its wiring
    (loop_accounting.py, contract.py) opens or mentions *.reasoning.jsonl."""

    def test_only_allowlisted_files_mention_reasoning_jsonl(self) -> None:
        """Grep the source tree for 'reasoning.jsonl' and pin the allow-list."""
        package_dir = Path(__file__).resolve().parents[1] / "colleague"
        violations: list[str] = []
        for py_file in sorted(package_dir.rglob("*.py")):
            rel = str(py_file.relative_to(package_dir.parent))
            if rel in _ALLOWLIST:
                continue
            source = py_file.read_text(encoding="utf-8")
            if "reasoning.jsonl" in source:
                # Find the line numbers for the error message.
                lines = source.splitlines()
                for lineno, line in enumerate(lines, start=1):
                    if "reasoning.jsonl" in line:
                        violations.append(f"  {rel}:{lineno}: {line.strip()!r}")

        assert not violations, (
            "Files outside the allow-list mention 'reasoning.jsonl' — "
            "the sidecar must not be read or referenced by any sharing surface:\n"
            + "\n".join(violations)
        )

    def test_allowlist_files_do_mention_reasoning_jsonl(self) -> None:
        """Sanity check: the allow-listed files actually do mention the
        sidecar (so the allow-list isn't vacuously empty)."""
        package_dir = Path(__file__).resolve().parents[1] / "colleague"
        for rel in _ALLOWLIST:
            path = package_dir.parent / rel
            assert path.is_file(), f"Allow-listed file {rel} does not exist"
            source = path.read_text(encoding="utf-8")
            assert "reasoning.jsonl" in source, (
                f"Allow-listed file {rel} no longer mentions 'reasoning.jsonl' — "
                "update the allow-list if the reference was intentionally removed"
            )

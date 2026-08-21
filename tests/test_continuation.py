"""Unit tests for colleague.continuation — resolve + guard + seed (t2).

Test-first: these tests define the contract before the implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.artifact import artifact_dir, write
from colleague.contract import OK, TaskResult, WorkStats
from colleague.feedback import set_last_work

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A temporary repo with an empty .colleague directory."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    return tmp_path


@pytest.fixture()
def sample_stats() -> WorkStats:
    """A minimal WorkStats for test artifacts."""
    return WorkStats(
        request="implement the new feature",
        started_at="2026-01-01T00:00:00Z",
        duration_seconds=30.0,
        model_turns=5,
        step_count=10,
        tool_counts={"read_file": 3, "write_file": 2},
        files_changed=2,
        bytes_written=5000,
    )


@pytest.fixture()
def sample_result(sample_stats: WorkStats) -> TaskResult:
    """A minimal incomplete TaskResult for test artifacts."""
    return TaskResult(
        task_id="task-001",
        status="incomplete",
        summary="Started the feature but ran out of steps",
        changed_files=["src/feature.py", "tests/test_feature.py"],
        error="step budget exhausted",
        stats=sample_stats,
    )


@pytest.fixture()
def ok_result(sample_stats: WorkStats) -> TaskResult:
    """An ok-status TaskResult for guard tests."""
    return TaskResult(
        task_id="task-ok",
        status=OK,
        summary="Done",
        stats=sample_stats,
    )


def _write_artifact(repo: Path, result: TaskResult) -> Path:
    """Write a TaskResult artifact into the repo's .colleague dir."""
    return write(result, artifact_dir(repo))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_corrupt_artifact(repo: Path, task_id: str) -> Path:
    """Write a corrupt (non-JSON) artifact file."""
    adir = artifact_dir(repo)
    path = adir / f"{task_id}.json"
    path.write_text("not-json-{", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Criterion 1: resolve_continuation returns (task_id, seed_text)
# ---------------------------------------------------------------------------


class TestResolveContinuation:
    """resolve_continuation resolves ref and returns (task_id, seed_text)."""

    def test_explicit_task_id(self, repo: Path, sample_result: TaskResult) -> None:
        """Explicit task id resolves and returns the correct tuple."""
        _write_artifact(repo, sample_result)

        from colleague.continuation import resolve_continuation

        task_id, seed_text = resolve_continuation(repo, "task-001")

        assert task_id == "task-001"
        assert isinstance(seed_text, str)
        assert len(seed_text) > 0

    def test_last_ref_resolves_via_feedback(self, repo: Path, sample_result: TaskResult) -> None:
        """ref='last' resolves through feedback.get_last_work."""
        _write_artifact(repo, sample_result)
        set_last_work(repo, "task-001")

        from colleague.continuation import resolve_continuation

        task_id, seed_text = resolve_continuation(repo, "last")

        assert task_id == "task-001"
        assert isinstance(seed_text, str)

    def test_seed_text_contains_preamble(self, repo: Path, sample_result: TaskResult) -> None:
        """seed_text starts with the continuation preamble."""
        _write_artifact(repo, sample_result)

        from colleague.continuation import resolve_continuation

        _, seed_text = resolve_continuation(repo, "task-001")

        assert "CONTINUING" in seed_text
        assert "task-001" in seed_text
        assert "Prior state:" in seed_text

    def test_seed_text_embeds_build_continuation_verbatim(
        self, repo: Path, sample_result: TaskResult
    ) -> None:
        """seed_text contains the build_continuation output verbatim."""
        _write_artifact(repo, sample_result)

        from colleague.continuation import resolve_continuation
        from colleague.escalation import build_continuation

        _, seed_text = resolve_continuation(repo, "task-001")
        expected_record = build_continuation(sample_result, sample_result.stats)

        assert expected_record in seed_text

    def test_seed_text_includes_original_request(
        self, repo: Path, sample_result: TaskResult
    ) -> None:
        """seed_text includes the original request verbatim."""
        _write_artifact(repo, sample_result)

        from colleague.continuation import resolve_continuation

        _, seed_text = resolve_continuation(repo, "task-001")

        assert "implement the new feature" in seed_text


# ---------------------------------------------------------------------------
# Criterion 2: wrong-run guards
# ---------------------------------------------------------------------------


class TestOkGuard:
    """An ok-status artifact raises ContinuationError unless allow_completed."""

    def test_ok_status_raises(self, repo: Path, ok_result: TaskResult) -> None:
        """An ok-status artifact raises ContinuationError."""
        _write_artifact(repo, ok_result)

        from colleague.continuation import ContinuationError, resolve_continuation

        with pytest.raises(ContinuationError, match="nothing to continue: task-ok finished ok"):
            resolve_continuation(repo, "task-ok")

    def test_ok_status_with_allow_completed(self, repo: Path, ok_result: TaskResult) -> None:
        """allow_completed=True bypasses the ok guard."""
        _write_artifact(repo, ok_result)

        from colleague.continuation import resolve_continuation

        task_id, seed_text = resolve_continuation(repo, "task-ok", allow_completed=True)

        assert task_id == "task-ok"
        assert isinstance(seed_text, str)


# ---------------------------------------------------------------------------
# Criterion 2 (cont.): missing / corrupt artifact guards
# ---------------------------------------------------------------------------


class TestMissingArtifact:
    """A missing artifact raises ContinuationError naming the id."""

    def test_missing_artifact_raises(self, repo: Path) -> None:
        """No artifact for the id raises ContinuationError."""
        from colleague.continuation import ContinuationError, resolve_continuation

        with pytest.raises(ContinuationError, match="no artifact for task-missing"):
            resolve_continuation(repo, "task-missing")

    def test_missing_last_work_raises(self, repo: Path) -> None:
        """ref='last' with no last_work pointer raises ContinuationError."""
        from colleague.continuation import ContinuationError, resolve_continuation

        with pytest.raises(ContinuationError):
            resolve_continuation(repo, "last")


class TestCorruptArtifact:
    """A corrupt (non-JSON) artifact raises ContinuationError naming the id."""

    def test_corrupt_json_raises(self, repo: Path) -> None:
        """Corrupt JSON raises ContinuationError naming the task id."""
        _write_corrupt_artifact(repo, "task-corrupt")

        from colleague.continuation import ContinuationError, resolve_continuation

        with pytest.raises(ContinuationError, match="corrupt artifact for task-corrupt"):
            resolve_continuation(repo, "task-corrupt")


# ---------------------------------------------------------------------------
# Criterion 3: pure stdlib / import constraints
# ---------------------------------------------------------------------------


class TestModuleConstraints:
    """The module must only import from
    colleague.{artifact,feedback,escalation,contract,agents.state} (the task
    ledger is the t17 continuation seam)."""

    def test_imports_only_allowed_modules(self) -> None:
        """continuation.py imports only stdlib + allowed colleague modules."""
        import ast

        import colleague.continuation

        source = Path(colleague.continuation.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        allowed_modules = {
            "colleague.artifact",
            "colleague.feedback",
            "colleague.escalation",
            "colleague.contract",
            "colleague.agents.state",
            "json",
            "pathlib",
            "typing",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top == "colleague":
                        assert alias.name in allowed_modules, f"Forbidden import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("colleague"):
                    assert node.module in allowed_modules, f"Forbidden from-import: {node.module}"


class TestWrongShapeArtifacts:
    """Valid JSON with an invalid shape stays inside the ContinuationError
    boundary — never a raw KeyError/TypeError traceback (Qodo #331)."""

    def _write(self, repo, task_id, payload):
        coll = repo / ".colleague"
        coll.mkdir(exist_ok=True)
        (coll / f"{task_id}.json").write_text(payload)

    def test_list_payload(self, tmp_path):
        import pytest

        from colleague.continuation import ContinuationError, resolve_continuation

        self._write(tmp_path, "bad1", "[]")
        with pytest.raises(ContinuationError, match="corrupt artifact for bad1"):
            resolve_continuation(tmp_path, "bad1")

    def test_dict_missing_required_keys(self, tmp_path):
        import pytest

        from colleague.continuation import ContinuationError, resolve_continuation

        self._write(tmp_path, "bad2", "{}")
        with pytest.raises(ContinuationError, match="corrupt artifact for bad2"):
            resolve_continuation(tmp_path, "bad2")

    def test_scalar_payload(self, tmp_path):
        import pytest

        from colleague.continuation import ContinuationError, resolve_continuation

        self._write(tmp_path, "bad3", '"just a string"')
        with pytest.raises(ContinuationError, match="corrupt artifact for bad3"):
            resolve_continuation(tmp_path, "bad3")

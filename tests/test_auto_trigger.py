"""Seamless auto-trigger lane — grade-time + work-start correction capture (plan
task t12, covers c18/h15).

Two triggers, ONE underlying best-effort capture (`colleague.feedback.maybe_capture_correction`),
built on top of t7's `colleague.correction` (resolve merge commit + scoped diff)
and t8's `colleague.memory.build_code_lesson_record` (+ `colleague.memory.remember`):

1. Grade-time (`write_feedback`): when the graded work item's own artifact
   carries BOTH `pr_url` and `tip_sha`, a correction-diff capture fires
   automatically. ANY missing fact, or ANY exception raised by the capture
   machinery, yields an observable non-raising outcome — the grade itself
   must always land (c18's pinned behavior).
2. Work-start (`colleague.cli._commands.work.execute_work`): a best-effort,
   read-only-first check (`find_uncaptured_predecessor`) detects the repo's
   most recent work item when it looks like an uncaptured merged predecessor,
   and `capture_uncaptured_predecessor` fires the same capture for it —
   colleague's own action as the trigger, not just an operator command.

Every outcome — fired / skipped / failed, with a `reason` — is persisted as a
sidecar JSON file beside the work item's artifact
(`<task_id>-correction-capture.json`, read back via
`colleague.feedback.read_correction_capture`) so a test (or operator) can see
what happened without re-running anything. The hyphen (not a dot) right after
the task id is deliberate: `colleague.artifact.find_artifact`'s glob
(`<task_id>.*.json`) must never mistake this sidecar for the work item's own
result artifact.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from colleague import correction as correction_mod
from colleague import feedback
from colleague import memory as memory_mod
from colleague.artifact import write
from colleague.cli._commands.work import execute_work
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult, WorkStats
from colleague.correction import CorrectionRecord, DiffHunk, MissingFact

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _record_work(
    repo: Path,
    task_id: str,
    *,
    request: str = "fix the thing",
    pr_url: str | None = None,
    tip_sha: str | None = None,
    changed_files: list[str] | None = None,
    status: str = OK,
) -> None:
    """Write a work-item artifact under repo/.colleague with the given facts."""
    stats = WorkStats(request=request, started_at="2026-08-01T00:00:00+00:00")
    write(
        TaskResult(
            task_id=task_id,
            status=status,
            summary=f"did {request}",
            stats=stats,
            pr_url=pr_url,
            tip_sha=tip_sha,
            changed_files=changed_files or [],
        ),
        repo / ".colleague",
    )


_OK_HUNKS = {
    "src/foo.py": DiffHunk(file_path="src/foo.py", text="@@ -1,2 +1,2 @@\n-old()\n+new()\n"),
}


def _ok_capture(*_a: Any, **_k: Any) -> CorrectionRecord:
    return CorrectionRecord(ok=True, missing=[], hunks=dict(_OK_HUNKS), note="")


def _no_diff_capture(*_a: Any, **_k: Any) -> CorrectionRecord:
    return CorrectionRecord(
        ok=False,
        missing=[MissingFact.MERGE_SHA],
        hunks={},
        note="correction diff unavailable: missing merge_sha",
    )


def _arm_success(monkeypatch: pytest.MonkeyPatch, *, remember_ok: bool = True) -> dict[str, int]:
    """Patch the correction + memory machinery to a scripted success; return a
    call-count dict the test can assert against."""
    calls = {"resolve": 0, "capture": 0, "remember": 0}

    def fake_resolve(repo: Any, pr_url: Any) -> str:
        calls["resolve"] += 1
        return "merge" + "a" * 10

    def fake_capture(*a: Any, **k: Any) -> CorrectionRecord:
        calls["capture"] += 1
        return _ok_capture()

    def fake_remember(repo: Any, record: dict) -> bool:
        calls["remember"] += 1
        assert record["type"] == "code-lesson"
        return remember_ok

    monkeypatch.setattr(correction_mod, "resolve_merge_commit", fake_resolve)
    monkeypatch.setattr(correction_mod, "capture_correction_diff", fake_capture)
    monkeypatch.setattr(memory_mod, "remember", fake_remember)
    return calls


# ---------------------------------------------------------------------------
# maybe_capture_correction — the shared best-effort capture primitive
# ---------------------------------------------------------------------------


class TestMaybeCaptureCorrection:
    def test_skips_when_no_artifact(self, tmp_path: Path) -> None:
        outcome = feedback.maybe_capture_correction(tmp_path, "ghost")
        assert outcome["outcome"] == feedback.CAPTURE_SKIPPED
        assert "no artifact" in outcome["reason"]

    def test_skips_when_missing_pr_url(self, tmp_path: Path) -> None:
        _record_work(tmp_path, "t1", tip_sha="a" * 40)
        outcome = feedback.maybe_capture_correction(tmp_path, "t1")
        assert outcome["outcome"] == feedback.CAPTURE_SKIPPED
        assert "pr_url" in outcome["reason"]

    def test_skips_when_missing_tip_sha(self, tmp_path: Path) -> None:
        _record_work(tmp_path, "t1", pr_url="https://github.com/org/repo/pull/1")
        outcome = feedback.maybe_capture_correction(tmp_path, "t1")
        assert outcome["outcome"] == feedback.CAPTURE_SKIPPED
        assert "tip_sha" in outcome["reason"]

    def test_skips_when_correction_diff_not_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        monkeypatch.setattr(correction_mod, "resolve_merge_commit", lambda *a, **k: None)
        monkeypatch.setattr(correction_mod, "capture_correction_diff", _no_diff_capture)
        outcome = feedback.maybe_capture_correction(tmp_path, "t1")
        assert outcome["outcome"] == feedback.CAPTURE_SKIPPED
        assert "merge_sha" in outcome["reason"]

    def test_fires_and_stores_lessons_when_all_facts_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        calls = _arm_success(monkeypatch)

        outcome = feedback.maybe_capture_correction(tmp_path, "t1")

        assert outcome["outcome"] == feedback.CAPTURE_FIRED
        assert outcome["hunks_captured"] == 1
        assert outcome["lessons_stored"] == 1
        assert calls == {"resolve": 1, "capture": 1, "remember": 1}

    def test_capture_failure_never_raises_and_records_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )

        def _boom(*_a: Any, **_k: Any) -> str:
            raise RuntimeError("gh exploded")

        monkeypatch.setattr(correction_mod, "resolve_merge_commit", _boom)

        outcome = feedback.maybe_capture_correction(tmp_path, "t1")  # must not raise

        assert outcome["outcome"] == feedback.CAPTURE_FAILED
        assert "gh exploded" in outcome["reason"]

    def test_persists_sidecar_readable_via_read_correction_capture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        _arm_success(monkeypatch)

        feedback.maybe_capture_correction(tmp_path, "t1")

        persisted = feedback.read_correction_capture(tmp_path, "t1")
        assert persisted is not None
        assert persisted["outcome"] == feedback.CAPTURE_FIRED

    def test_read_correction_capture_absent_is_none(self, tmp_path: Path) -> None:
        assert feedback.read_correction_capture(tmp_path, "never-captured") is None

    def test_already_fired_short_circuits_without_recalling_correction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        calls = _arm_success(monkeypatch)
        first = feedback.maybe_capture_correction(tmp_path, "t1")
        assert first["outcome"] == feedback.CAPTURE_FIRED
        assert calls["capture"] == 1

        # A second call must NOT re-invoke the correction machinery.
        second = feedback.maybe_capture_correction(tmp_path, "t1")
        assert second["outcome"] == feedback.CAPTURE_FIRED
        assert calls["capture"] == 1  # unchanged — short-circuited

    def test_sidecar_filename_never_collides_with_find_artifact_glob(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The sidecar must not be mistaken for the work item's own artifact by
        `colleague.artifact.find_artifact`'s ``<task_id>.*.json`` glob."""
        from colleague.artifact import find_artifact

        _record_work(
            tmp_path,
            "t1",
            request="fix the thing",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        _arm_success(monkeypatch)
        feedback.maybe_capture_correction(tmp_path, "t1")

        found = find_artifact(tmp_path, "t1")
        assert found is not None
        assert "correction-capture" not in found.name


# ---------------------------------------------------------------------------
# write_feedback auto-triggers correction capture at grade time
# ---------------------------------------------------------------------------


class TestWriteFeedbackAutoTrigger:
    def test_write_feedback_triggers_capture_when_facts_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        _arm_success(monkeypatch)

        feedback.write_feedback(tmp_path, "t1", rating=4, notes="nice")

        outcome = feedback.read_correction_capture(tmp_path, "t1")
        assert outcome is not None
        assert outcome["outcome"] == feedback.CAPTURE_FIRED

    def test_write_feedback_records_skip_when_facts_absent(self, tmp_path: Path) -> None:
        _record_work(tmp_path, "t1")  # no pr_url, no tip_sha

        feedback.write_feedback(tmp_path, "t1", rating=3)

        outcome = feedback.read_correction_capture(tmp_path, "t1")
        assert outcome is not None
        assert outcome["outcome"] == feedback.CAPTURE_SKIPPED

    def test_capture_failure_never_blocks_the_grade(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC2 (pinned): the grade lands even when the capture machinery blows up."""
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )

        def _boom(*_a: Any, **_k: Any) -> str:
            raise RuntimeError("network exploded")

        monkeypatch.setattr(correction_mod, "resolve_merge_commit", _boom)

        record = feedback.write_feedback(tmp_path, "t1", rating=5, notes="great")  # must not raise

        assert record.rating == 5
        loaded = feedback.read_feedback(tmp_path, "t1")
        assert loaded is not None
        assert loaded.rating == 5

        outcome = feedback.read_correction_capture(tmp_path, "t1")
        assert outcome is not None
        assert outcome["outcome"] == feedback.CAPTURE_FAILED

    def test_sidecar_never_pollutes_list_work_items(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The correction-capture sidecar must be excluded from list_work_items,
        exactly like a `.feedback.json` record (both end in `.json`)."""
        _record_work(
            tmp_path,
            "t1",
            request="do the thing",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        _arm_success(monkeypatch)

        feedback.write_feedback(tmp_path, "t1", rating=4)

        rows = feedback.list_work_items(tmp_path)
        assert len(rows) == 1
        assert rows[0].task_id == "t1"
        assert rows[0].status == OK  # not clobbered by the sidecar's own shape


# ---------------------------------------------------------------------------
# find_uncaptured_predecessor — pure(-ish), read-only detection
# ---------------------------------------------------------------------------


class TestFindUncapturedPredecessor:
    def test_none_when_no_last_work(self, tmp_path: Path) -> None:
        assert feedback.find_uncaptured_predecessor(tmp_path) is None

    def test_none_when_predecessor_missing_pr_url(self, tmp_path: Path) -> None:
        _record_work(tmp_path, "t1", tip_sha="a" * 40)
        feedback.set_last_work(tmp_path, "t1")
        assert feedback.find_uncaptured_predecessor(tmp_path) is None

    def test_none_when_predecessor_missing_tip_sha(self, tmp_path: Path) -> None:
        _record_work(tmp_path, "t1", pr_url="https://github.com/org/repo/pull/1")
        feedback.set_last_work(tmp_path, "t1")
        assert feedback.find_uncaptured_predecessor(tmp_path) is None

    def test_returns_task_id_when_predecessor_has_facts_and_uncaptured(
        self, tmp_path: Path
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        feedback.set_last_work(tmp_path, "t1")
        assert feedback.find_uncaptured_predecessor(tmp_path) == "t1"

    def test_none_when_predecessor_already_captured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        feedback.set_last_work(tmp_path, "t1")
        _arm_success(monkeypatch)
        feedback.maybe_capture_correction(tmp_path, "t1")  # fires, marks captured

        assert feedback.find_uncaptured_predecessor(tmp_path) is None

    def test_still_candidate_when_prior_attempt_was_skipped(self, tmp_path: Path) -> None:
        """A prior SKIPPED (not fired) attempt still counts as uncaptured — worth
        retrying (e.g. the PR may since have merged)."""
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        feedback.set_last_work(tmp_path, "t1")
        # Force a SKIPPED sidecar by capturing before facts existed... simulate
        # by writing a skipped sidecar directly at the read seam.
        feedback._write_correction_capture(  # noqa: SLF001 - testing the seam directly
            tmp_path,
            "t1",
            {"task_id": "t1", "outcome": feedback.CAPTURE_SKIPPED, "reason": "gh unavailable"},
        )
        assert feedback.find_uncaptured_predecessor(tmp_path) == "t1"


# ---------------------------------------------------------------------------
# capture_uncaptured_predecessor — the work-start trigger's capture step
# ---------------------------------------------------------------------------


class TestCaptureUncapturedPredecessor:
    def test_returns_none_when_no_predecessor(self, tmp_path: Path) -> None:
        assert feedback.capture_uncaptured_predecessor(tmp_path) is None

    def test_captures_and_returns_outcome_when_predecessor_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        feedback.set_last_work(tmp_path, "t1")
        calls = _arm_success(monkeypatch)

        outcome = feedback.capture_uncaptured_predecessor(tmp_path)

        assert outcome is not None
        assert outcome["outcome"] == feedback.CAPTURE_FIRED
        assert calls["capture"] == 1
        assert feedback.read_correction_capture(tmp_path, "t1")["outcome"] == feedback.CAPTURE_FIRED

    def test_never_raises_when_capture_blows_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_work(
            tmp_path,
            "t1",
            pr_url="https://github.com/org/repo/pull/1",
            tip_sha="a" * 40,
            changed_files=["src/foo.py"],
        )
        feedback.set_last_work(tmp_path, "t1")

        def _boom(*_a: Any, **_k: Any) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(correction_mod, "resolve_merge_commit", _boom)

        outcome = feedback.capture_uncaptured_predecessor(tmp_path)  # must not raise
        assert outcome is not None
        assert outcome["outcome"] == feedback.CAPTURE_FAILED


# ---------------------------------------------------------------------------
# Sidecar JSON is well-formed and stdlib-only
# ---------------------------------------------------------------------------


def test_sidecar_json_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _record_work(
        tmp_path,
        "t1",
        pr_url="https://github.com/org/repo/pull/1",
        tip_sha="a" * 40,
        changed_files=["src/foo.py"],
    )
    _arm_success(monkeypatch)
    feedback.maybe_capture_correction(tmp_path, "t1")

    path = feedback.correction_capture_path(tmp_path, "t1")
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["task_id"] == "t1"
    assert data["outcome"] == feedback.CAPTURE_FIRED


# ---------------------------------------------------------------------------
# execute_work wiring — the work-start trigger fires for real (t12 AC3)
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised tmp_path with an initial commit (cwd-scoped identity —
    tmp-repo-git-tests-need-cwd-identity lesson)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _run_mock_work(git_repo: Path, instruction: str = "make a small change") -> TaskResult:
    task = Task.new(str(git_repo), instruction, engine="mock")
    result, _artifact_path = execute_work(
        repo=git_repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
        allow_dirty=True,
    )
    return result


class TestExecuteWorkStartWiring:
    def test_execute_work_captures_uncaptured_predecessor_at_start(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A predecessor work item with pr_url+tip_sha, uncaptured, gets captured
        the moment the NEXT work item starts — colleague's own action as
        trigger (AC3), never an operator asking for it."""
        _record_work(
            git_repo,
            "predecessor-1",
            pr_url="https://github.com/org/repo/pull/7",
            tip_sha="b" * 40,
            changed_files=["src/foo.py"],
        )
        feedback.set_last_work(git_repo, "predecessor-1")
        calls = _arm_success(monkeypatch)

        result = _run_mock_work(git_repo)

        assert result.status  # the triggering work item still ran to completion
        outcome = feedback.read_correction_capture(git_repo, "predecessor-1")
        assert outcome is not None
        assert outcome["outcome"] == feedback.CAPTURE_FIRED
        assert calls["capture"] == 1

    def test_execute_work_never_raises_when_predecessor_capture_fails(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blown-up predecessor capture must never keep the NEW work item
        from starting or completing."""
        _record_work(
            git_repo,
            "predecessor-1",
            pr_url="https://github.com/org/repo/pull/7",
            tip_sha="b" * 40,
            changed_files=["src/foo.py"],
        )
        feedback.set_last_work(git_repo, "predecessor-1")

        def _boom(*_a: Any, **_k: Any) -> str:
            raise RuntimeError("gh is on fire")

        monkeypatch.setattr(correction_mod, "resolve_merge_commit", _boom)

        result = _run_mock_work(git_repo)  # must not raise

        assert result.task_id  # the work item completed normally
        outcome = feedback.read_correction_capture(git_repo, "predecessor-1")
        assert outcome is not None
        assert outcome["outcome"] == feedback.CAPTURE_FAILED

    def test_execute_work_is_a_no_op_when_no_predecessor_exists(self, git_repo: Path) -> None:
        """The common case — a repo's first-ever work item — costs nothing
        observable: no sidecar appears anywhere."""
        result = _run_mock_work(git_repo)
        assert result.task_id
        assert list(git_repo.glob(".colleague/*-correction-capture.json")) == []

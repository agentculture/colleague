"""Tests for the distillation alive-counter check-group (plan task t11, c28).

Acceptance criteria:
- doctor reports distillation attempts vs validated from recent artifacts/outcome
  markers and WARNS when attempts>0 with validated=0 — armed-is-not-alive made
  operator-visible.

Scenarios:
* No distill markers at all → info/passed, "no distillation activity"
* Markers with status=done + lesson → counted as validated
* Markers with status=pending → counted as attempts but not validated
* Markers with status=dead → counted as attempts but not validated
* attempts>0 and validated==0 → warning with remediation hint
* attempts>0 and validated>0 → info/passed (distillation is alive)
* The group is read-only: no writes, no network, no subprocess
* Contract compliance: five-key shape, unique ids, never raises
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

import colleague.oilcheck as oilcheck
from colleague.cli import main
from colleague.oilcheck import diagnose
from colleague.oilcheck.distillation import checks

_CHECK_KEYS = {"id", "passed", "severity", "message", "remediation"}


def _write_marker(adir: Path, stem: str, status: str, *, lesson: dict | None = None) -> Path:
    """Write a distill.json outcome marker next to a fake artifact."""
    artifact = adir / f"{stem}.json"
    artifact.write_text(json.dumps({"task_id": stem}), encoding="utf-8")
    marker = adir / f"{stem}.distill.json"
    payload: dict = {"status": status, "written_at": 1.0}
    if lesson:
        payload["lesson"] = lesson
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return marker


# ---------------------------------------------------------------------------
# Scenario 1: no markers → info/passed
# ---------------------------------------------------------------------------


def test_no_markers_is_info_passed(tmp_path: Path) -> None:
    """No distill markers at all → info/passed with 'no distillation activity'."""
    adir = tmp_path / ".colleague"
    adir.mkdir()

    result = checks(repo_path=str(tmp_path))
    assert len(result) == 1
    c = result[0]
    assert c["id"] == "distillation_alive"
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert "no distillation" in c["message"].lower() or "no activity" in c["message"].lower()
    assert c["remediation"] == ""


def test_no_artifact_dir_is_info_passed(tmp_path: Path) -> None:
    """Missing .colleague/ dir → info/passed (nothing to report)."""
    result = checks(repo_path=str(tmp_path))
    assert len(result) == 1
    c = result[0]
    assert c["passed"] is True
    assert c["severity"] == "info"


# ---------------------------------------------------------------------------
# Scenario 2: validated markers (done + lesson)
# ---------------------------------------------------------------------------


def test_done_with_lesson_counts_as_validated(tmp_path: Path) -> None:
    """A marker with status=done and a lesson counts as validated."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "done", lesson={"cause": "x", "lesson": "y", "next_delta": "z"})

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert "1" in c["message"]  # shows count


def test_done_without_lesson_is_attempt_not_validated(tmp_path: Path) -> None:
    """A marker with status=done but no lesson counts as attempt, not validated."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "done")  # no lesson key

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    # attempts=1, validated=0 → warning
    assert c["passed"] is False
    assert c["severity"] == "warning"


# ---------------------------------------------------------------------------
# Scenario 3: pending markers → attempts but not validated
# ---------------------------------------------------------------------------


def test_pending_counts_as_attempt(tmp_path: Path) -> None:
    """A marker with status=pending counts as an attempt but not validated."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "pending")

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert c["remediation"]


def test_dead_counts_as_attempt(tmp_path: Path) -> None:
    """A marker with status=dead counts as an attempt but not validated."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "dead", lesson=None)

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    assert c["passed"] is False
    assert c["severity"] == "warning"


# ---------------------------------------------------------------------------
# Scenario 4: mixed markers — some validated, some not
# ---------------------------------------------------------------------------


def test_mixed_attempts_and_validated_is_passed(tmp_path: Path) -> None:
    """When there are validated lessons, the check passes even with pending attempts."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "done", lesson={"cause": "x", "lesson": "y", "next_delta": "z"})
    _write_marker(adir, "task-2", "pending")
    _write_marker(adir, "task-3", "dead")

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    assert c["passed"] is True
    assert c["severity"] == "info"
    # Message should show both counts
    assert "3" in c["message"]  # 3 attempts
    assert "1" in c["message"]  # 1 validated


def test_all_pending_warns(tmp_path: Path) -> None:
    """All markers pending → warning (armed but not alive)."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "pending")
    _write_marker(adir, "task-2", "pending")

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "2" in c["message"]  # 2 attempts


# ---------------------------------------------------------------------------
# Scenario 5: armed-is-not-alive warning
# ---------------------------------------------------------------------------


def test_armed_is_not_alive_warns(tmp_path: Path) -> None:
    """attempts>0 with validated=0 → warning (armed-is-not-alive)."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "pending")

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert c["remediation"]  # must carry remediation hint


def test_warning_never_flips_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The distillation warning is advisory — never flips doctor unhealthy."""
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [checks])
    monkeypatch.setattr(oilcheck, "_REPO_AWARE_GROUPS", frozenset({checks}))
    report = diagnose()
    assert report["healthy"] is True


# ---------------------------------------------------------------------------
# Scenario 6: read-only — no writes, no network
# ---------------------------------------------------------------------------


def test_checks_opens_no_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The distillation group must not open any socket."""

    def _boom(*_args, **_kwargs):
        raise AssertionError("distillation group opened a socket")

    monkeypatch.setattr(socket, "socket", _boom)
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "pending")

    checks(repo_path=str(tmp_path))  # must not raise


def test_checks_writes_no_files(tmp_path: Path) -> None:
    """The distillation group must not write any files."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "pending")

    before = set(adir.iterdir())
    checks(repo_path=str(tmp_path))
    after = set(adir.iterdir())
    assert before == after, f"checks() created: {after - before}"


# ---------------------------------------------------------------------------
# Scenario 7: corrupt / unreadable markers degrade gracefully
# ---------------------------------------------------------------------------


def test_corrupt_marker_degrades_gracefully(tmp_path: Path) -> None:
    """A corrupt distill.json is silently skipped — no crash."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    # Write a fake artifact
    (adir / "task-1.json").write_text("{}", encoding="utf-8")
    # Write a corrupt marker
    (adir / "task-1.distill.json").write_text("{not valid json", encoding="utf-8")

    result = checks(repo_path=str(tmp_path))  # must not raise
    assert len(result) == 1
    c = result[0]
    # Corrupt marker is skipped → no valid markers → info/passed
    assert c["passed"] is True


def test_zero_byte_marker_degrades_gracefully(tmp_path: Path) -> None:
    """A 0-byte distill.json is silently skipped."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    (adir / "task-1.json").write_text("{}", encoding="utf-8")
    (adir / "task-1.distill.json").write_text("", encoding="utf-8")

    result = checks(repo_path=str(tmp_path))
    assert len(result) == 1
    assert result[0]["passed"] is True


# ---------------------------------------------------------------------------
# Scenario 8: legacy .convertible/ dir is also scanned
# ---------------------------------------------------------------------------


def test_scans_legacy_convertible_dir(tmp_path: Path) -> None:
    """Markers in the legacy .convertible/ dir are also found."""
    legacy_dir = tmp_path / ".convertible"
    legacy_dir.mkdir()
    _write_marker(legacy_dir, "task-1", "pending")

    result = checks(repo_path=str(tmp_path))
    c = result[0]
    assert c["passed"] is False
    assert c["severity"] == "warning"


# ---------------------------------------------------------------------------
# Scenario 9: contract compliance
# ---------------------------------------------------------------------------


class TestCheckShape:
    """Five-key shape, unique ids, valid severities."""

    def test_shape_and_uniqueness(self, tmp_path: Path) -> None:
        adir = tmp_path / ".colleague"
        adir.mkdir()
        _write_marker(adir, "task-1", "pending")

        result = checks(repo_path=str(tmp_path))
        ids = [c["id"] for c in result]
        assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
        for c in result:
            assert set(c) == _CHECK_KEYS, f"bad shape: {c}"
            assert isinstance(c["id"], str)
            assert c["id"]
            assert isinstance(c["passed"], bool)
            assert c["severity"] in {"error", "warning", "info"}
            if c["passed"]:
                assert c["remediation"] == ""

    def test_checks_never_raises(self, tmp_path: Path) -> None:
        """checks() must never raise, even with a broken repo path.

        A raise here fails the test naturally — no wrapper needed.
        """
        result = checks(repo_path="/nonexistent/path/xyz")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Scenario 10: doctor CLI integration
# ---------------------------------------------------------------------------


def test_doctor_json_carries_distillation_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """doctor --json includes the distillation check."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "pending")

    monkeypatch.chdir(tmp_path)
    rc = main(["doctor", "--json", "--repo", str(tmp_path)])
    assert rc == 0  # warning doesn't flip unhealthy
    payload = json.loads(capsys.readouterr().out)
    distill_checks = [c for c in payload["checks"] if c["id"] == "distillation_alive"]
    assert len(distill_checks) == 1
    c = distill_checks[0]
    assert c["passed"] is False
    assert c["severity"] == "warning"


def test_doctor_text_shows_distillation_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """doctor text output shows the distillation warning with [FAIL]."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    _write_marker(adir, "task-1", "pending")

    monkeypatch.chdir(tmp_path)
    rc = main(["doctor", "--repo", str(tmp_path)])
    assert rc == 0  # warning doesn't flip unhealthy
    out = capsys.readouterr().out
    assert "[FAIL] distillation_alive" in out

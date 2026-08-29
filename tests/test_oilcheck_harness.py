"""Plan t20 (c43/h32): the doctor ``harness`` group — four informational rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.oilcheck import diagnose, harness
from tests.test_associate_config import PAYLOAD_WITH_ASSOCIATE, PAYLOAD_WITHOUT_ASSOCIATE, _serving

_IDS = [
    "harness_stream_guards",
    "harness_tool_concurrency",
    "harness_ripgrep",
    "harness_associate",
]


def _by_id(checks: list[dict]) -> dict[str, dict]:
    return {c["id"]: c for c in checks}


def test_group_is_registered_and_informational(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    report = diagnose()
    rows = [c for c in report["checks"] if c["id"].startswith("harness_")]
    assert [c["id"] for c in rows] == _IDS
    assert all(c["severity"] == "info" and c["passed"] and c["remediation"] == "" for c in rows)


def test_snapshot_of_the_four_rows_at_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.delenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", raising=False)
    monkeypatch.delenv("COLLEAGUE_STREAM_MAX_LIFETIME", raising=False)
    monkeypatch.delenv("COLLEAGUE_TOOL_CONCURRENCY", raising=False)
    monkeypatch.setattr(
        harness.shutil, "which", lambda name: "/usr/bin/rg" if name == "rg" else None
    )
    rows = _by_id(harness.checks(repo_path=None))
    assert rows["harness_stream_guards"]["message"] == "stream guards: idle=240s lifetime=1800s"
    assert rows["harness_tool_concurrency"]["message"] == (
        "tool concurrency: 10 (parallel read-only batches up to 10)"
    )
    assert rows["harness_ripgrep"]["message"] == "ripgrep: present (/usr/bin/rg)"
    assert rows["harness_associate"]["message"].startswith("associate: fallback")


def test_stream_guard_sanity_note_and_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "900")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "240")
    row = _by_id(harness.checks())["harness_stream_guards"]
    assert row["passed"]
    assert "idle >= lifetime" in row["message"]
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "0")
    assert _by_id(harness.checks())["harness_stream_guards"]["message"] == (
        "stream guards: off (both bounds 0)"
    )


def test_tool_concurrency_sequential_and_ripgrep_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "1")
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    rows = _by_id(harness.checks())
    assert rows["harness_tool_concurrency"]["message"] == "tool concurrency: 1 (sequential)"
    assert rows["harness_ripgrep"]["message"] == "ripgrep: absent (stdlib grep walker)"


def test_associate_states(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_MODEL", raising=False)
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        opt_in = _by_id(harness.checks(repo_path=tmp_path))["harness_associate"]["message"]
        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "lobes")
        consumed = _by_id(harness.checks(repo_path=tmp_path))["harness_associate"]["message"]
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_MODEL", raising=False)
    with _serving(PAYLOAD_WITHOUT_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        fallback = _by_id(harness.checks(repo_path=tmp_path))["harness_associate"]["message"]
    assert opt_in.startswith("associate: opt-in (advertised nvidia/")
    assert "COLLEAGUE_ASSOCIATE_MODEL=lobes" in opt_in
    assert consumed.startswith("associate: consumed → nvidia/")
    assert "'associate'" in consumed
    assert fallback == "associate: fallback (no associate role advertised) — seats run on cortex"


def test_unreachable_gateway_reports_unknown_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_MODEL", raising=False)
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://127.0.0.1:9")
    row = _by_id(harness.checks(repo_path=tmp_path))["harness_associate"]
    assert row["passed"]
    assert row["message"].startswith("associate: unknown")


def test_doctor_json_carries_the_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    from colleague.cli import main

    assert main(["doctor", "--json", "--repo", str(tmp_path)]) in (0, 1)
    report = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in report["checks"] if c["id"].startswith("harness_")] == _IDS

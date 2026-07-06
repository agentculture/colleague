"""Tests for the coherence pre-finish gate runner (#294, colleague#291 S3).

The consumer seam is pinned by ``_LIVE_PAYLOAD`` — copied VERBATIM from a live
``coherence meaning score --json`` run (coherence-cli 0.5.0 against the lobes
gateway embedder, probed 2026-07-06) — so the coherence-cli#11 domain
restructure cannot silently break the parse. The offline shape is pinned from
the same probe: exit 2, the structured error on stderr, NOTHING on stdout.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from colleague.coherence import diagnostics_lines, run_coherence_gate
from colleague.contract import CoherenceReport

# Copied verbatim from a live `coherence meaning score <file> --json` run.
_LIVE_PAYLOAD = {
    "meaning_score": 0.45873688286180625,
    "subdimensions": {
        "consequence": 0.47376113192464653,
        "agency": 0.5114560374600864,
        "causality": 0.41935020155050307,
        "affordance": 0.4441222551586307,
        "future_constraint": 0.48393761919660033,
    },
    "diagnostics": [
        {
            "code": "missing_consequence",
            "message": "No stated outcome, impact, or risk — say what happens.",
        }
    ],
}

_LIVE_ERROR = {
    "code": 2,
    "message": "Embedding endpoint unreachable at 'http://localhost:8002/v1/embeddings'",
    "remediation": "point COHERENCE_EMBED_URL at a reachable endpoint",
}


def _fake_coherence(tmp_path: Path, monkeypatch, script_body: str) -> None:
    """Install a fake ``coherence`` CLI at the front of PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "coherence"
    script.write_text("#!/bin/sh\n" + script_body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")


def _configured_env(monkeypatch) -> None:
    """Arm the configured-detection: an embedder endpoint colleague knows about."""
    monkeypatch.setenv("COHERENCE_EMBED_URL", "http://localhost:8001/v1")


def _repo_with_md(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docs").mkdir()
    (repo / "docs" / "feature.md").write_text("# Feature\n")
    return repo


class TestRunCoherenceGate:
    def test_no_changed_markdown_is_a_strict_noop(self, tmp_path: Path) -> None:
        repo = _repo_with_md(tmp_path)
        assert run_coherence_gate(repo, ["a.py", "b.txt"]) is None
        assert run_coherence_gate(repo, []) is None

    def test_missing_md_file_is_not_scored(self, tmp_path: Path) -> None:
        repo = _repo_with_md(tmp_path)
        assert run_coherence_gate(repo, ["gone.md"]) is None

    def test_no_embedder_configured_is_a_strict_noop(self, tmp_path: Path, monkeypatch) -> None:
        """No COHERENCE_EMBED_URL anywhere -> None (the no-linter-configured analog)."""
        repo = _repo_with_md(tmp_path)
        _fake_coherence(tmp_path, monkeypatch, "echo '{}'\n")
        monkeypatch.delenv("COHERENCE_EMBED_URL", raising=False)
        assert run_coherence_gate(repo, ["docs/feature.md"]) is None

    def test_missing_cli_degrades_to_skipped(self, tmp_path: Path, monkeypatch) -> None:
        _configured_env(monkeypatch)
        repo = _repo_with_md(tmp_path)
        monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
        report = run_coherence_gate(repo, ["docs/feature.md"])
        assert report is not None
        assert report.status == "skipped"
        assert "not installed" in (report.reason or "")

    def test_scores_changed_md_with_live_pinned_payload(self, tmp_path: Path, monkeypatch) -> None:
        _configured_env(monkeypatch)
        repo = _repo_with_md(tmp_path)
        _fake_coherence(tmp_path, monkeypatch, f"echo '{json.dumps(_LIVE_PAYLOAD)}'\n")
        report = run_coherence_gate(repo, ["docs/feature.md", "code.py"])
        assert report is not None and report.status == "scored"
        assert len(report.files) == 1
        record = report.files[0]
        assert record["path"] == "docs/feature.md"
        assert record["meaning_score"] == _LIVE_PAYLOAD["meaning_score"]
        assert record["subdimensions"] == _LIVE_PAYLOAD["subdimensions"]
        assert record["diagnostics"][0]["code"] == "missing_consequence"

    def test_frame_provenance_recorded_from_env(self, tmp_path: Path, monkeypatch) -> None:
        """The measurement's gauge (coherence-cli#10) rides on the report."""
        repo = _repo_with_md(tmp_path)
        _fake_coherence(tmp_path, monkeypatch, f"echo '{json.dumps(_LIVE_PAYLOAD)}'\n")
        monkeypatch.delenv("COHERENCE_EMBED_URL", raising=False)
        monkeypatch.delenv("COHERENCE_EMBED_MODEL", raising=False)
        report = run_coherence_gate(
            repo,
            ["docs/feature.md"],
            env_overrides={
                "COHERENCE_EMBED_URL": "http://localhost:8001/v1",
                "COHERENCE_EMBED_MODEL": "Qwen/Qwen3-Embedding-0.6B",
            },
        )
        assert report is not None
        assert report.embed_url == "http://localhost:8001/v1"
        assert report.embed_model == "Qwen/Qwen3-Embedding-0.6B"

    def test_operator_env_wins_over_injected(self, tmp_path: Path, monkeypatch) -> None:
        repo = _repo_with_md(tmp_path)
        _fake_coherence(tmp_path, monkeypatch, f"echo '{json.dumps(_LIVE_PAYLOAD)}'\n")
        monkeypatch.setenv("COHERENCE_EMBED_URL", "http://operator:9/v1")
        report = run_coherence_gate(
            repo,
            ["docs/feature.md"],
            env_overrides={"COHERENCE_EMBED_URL": "http://injected:8/v1"},
        )
        assert report is not None
        assert report.embed_url == "http://operator:9/v1"

    def test_exit2_offline_records_structured_error(self, tmp_path: Path, monkeypatch) -> None:
        """Pinned live offline behavior: exit 2, error JSON on stderr, empty stdout."""
        _configured_env(monkeypatch)
        repo = _repo_with_md(tmp_path)
        _fake_coherence(tmp_path, monkeypatch, f"echo '{json.dumps(_LIVE_ERROR)}' >&2\nexit 2\n")
        report = run_coherence_gate(repo, ["docs/feature.md"])
        assert report is not None and report.status == "scored"
        assert "Embedding endpoint unreachable" in report.files[0]["error"]

    def test_unknown_payload_keys_pass_through_verbatim(self, tmp_path: Path, monkeypatch) -> None:
        """A future native frame block (coherence-cli#10) is never dropped."""
        _configured_env(monkeypatch)
        payload = dict(_LIVE_PAYLOAD)
        payload["frame"] = {"model": "Qwen/Qwen3-Embedding-0.6B", "anchors": "meaning-v1"}
        repo = _repo_with_md(tmp_path)
        _fake_coherence(tmp_path, monkeypatch, f"echo '{json.dumps(payload)}'\n")
        report = run_coherence_gate(repo, ["docs/feature.md"])
        assert report is not None
        assert report.files[0]["frame"] == payload["frame"]

    def test_garbage_stdout_records_error_never_raises(self, tmp_path: Path, monkeypatch) -> None:
        _configured_env(monkeypatch)
        repo = _repo_with_md(tmp_path)
        _fake_coherence(tmp_path, monkeypatch, "echo 'not json'\n")
        report = run_coherence_gate(repo, ["docs/feature.md"])
        assert report is not None
        assert "unparseable" in report.files[0]["error"]


class TestReportShape:
    def test_to_dict_omits_absent_fields(self) -> None:
        d = CoherenceReport(status="scored").to_dict()
        assert d == {"status": "scored"}

    def test_round_trip(self) -> None:
        report = CoherenceReport(
            status="scored",
            embed_url="http://x/v1",
            embed_model="m",
            files=[{"path": "a.md", "meaning_score": 0.5}],
        )
        again = CoherenceReport.from_dict(report.to_dict())
        assert again.to_dict() == report.to_dict()

    def test_diagnostics_lines(self) -> None:
        report = CoherenceReport(
            status="scored",
            files=[
                {"path": "a.md", "meaning_score": 0.46, "diagnostics": [{"code": "x"}]},
                {"path": "b.md", "error": "boom"},
                {"path": "c.md", "meaning_score": 0.9, "diagnostics": []},
            ],
        )
        lines = diagnostics_lines(report)
        assert len(lines) == 2
        assert "a.md meaning 0.46" in lines[0] and "x" in lines[0]
        assert "b.md — boom" in lines[1]

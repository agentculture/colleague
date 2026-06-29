"""``colleague tui test`` — JSON scenario runner (t10).

A scenario is a JSON file (NOT YAML — zero-deps, PyYAML is forbidden) describing
an initial state, a list of events to fold, and an ``expect`` block of clauses
to assert against the resulting TAUI mirror. ``tui test`` reports PASS/FAIL with
per-clause detail and exits 1 on FAIL.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main

_REPO = Path(__file__).resolve().parents[1]
_BUNDLED = _REPO / "colleague" / "tui" / "scenarios" / "boost-popup.scenario.json"


def test_bundled_boost_scenario_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert _BUNDLED.exists(), f"bundled scenario missing: {_BUNDLED}"
    rc = main(["tui", "test", "--scenario", str(_BUNDLED), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is True
    # Every clause passed.
    assert all(c["ok"] for c in report["checks"])


def test_bundled_boost_scenario_text_mode(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "test", "--scenario", str(_BUNDLED)])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_failing_scenario_fails_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # No events fired, but we expect a boost popup -> must FAIL.
    scenario = {
        "name": "expect a popup that never appears",
        "initial": {"screen": "main"},
        "events": [],
        "expect": {"popup": {"id": "popup.skill.boost", "visible": True}},
    }
    sf = tmp_path / "fail.scenario.json"
    sf.write_text(json.dumps(scenario), encoding="utf-8")
    rc = main(["tui", "test", "--scenario", str(sf)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_failing_scenario_json_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scenario = {
        "name": "wrong focus",
        "initial": {"screen": "main"},
        "events": [],
        "expect": {"focused": "definitely.not.the.default"},
    }
    sf = tmp_path / "fail2.scenario.json"
    sf.write_text(json.dumps(scenario), encoding="utf-8")
    rc = main(["tui", "test", "--scenario", str(sf), "--json"])
    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert any(not c["ok"] for c in report["checks"])


def test_missing_scenario_file_is_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "test", "--scenario", str(tmp_path / "nope.json")])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


def test_action_available_clause(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scenario = {
        "name": "accept action available after suggestion",
        "initial": {"screen": "main"},
        "events": [{"type": "skill_suggested", "skill": "boost", "reason": "task_complexity_high"}],
        # agentfront uses generic popup.skill-suggested (not per-skill popup ids).
        "expect": {"action_available": "popup.skill-suggested.accept"},
    }
    sf = tmp_path / "ok.scenario.json"
    sf.write_text(json.dumps(scenario), encoding="utf-8")
    rc = main(["tui", "test", "--scenario", str(sf), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is True

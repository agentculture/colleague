"""``convertible tui`` headless CLI verb (t10).

Every verb runs HEADLESS (no real terminal), supports ``--json``, sends results
to stdout / diagnostics + errors to stderr, and raises ``CliError`` (never leaks
a traceback). These tests drive the CLI through ``convertible.cli.main`` exactly
like ``tests/test_feedback_cli.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertible.cli import main
from convertible.tui.events import SkillSuggested, dumps_events
from convertible.tui.state import CockpitState

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_state(path: Path, state: CockpitState) -> Path:
    path.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    return path


def _boost_state() -> CockpitState:
    """A state whose serialized mirror already carries a visible boost popup."""
    from convertible.tui.reducer import reduce

    return reduce(CockpitState(), SkillSuggested(skill="boost", reason="task_complexity_high"))


# ---------------------------------------------------------------------------
# parser still builds (registration didn't break anything)
# ---------------------------------------------------------------------------


def test_help_still_builds(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "tui" in out


# ---------------------------------------------------------------------------
# tui state
# ---------------------------------------------------------------------------


def test_state_default_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "state", "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    assert mirror["taui_version"]  # present and non-empty
    assert mirror["screen"] == "main"
    # The standing prompt action is always available.
    sels = {a["selector"] for a in mirror["available_actions"]}
    assert "input.prompt" in sels


def test_state_from_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", _boost_state())
    rc = main(["tui", "state", "--state", str(sf), "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    popup_ids = {p["id"] for p in mirror["popups"]}
    assert "popup.skill.boost" in popup_ids


# ---------------------------------------------------------------------------
# tui render
# ---------------------------------------------------------------------------


def test_render_emits_frame(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf)])
    assert rc == 0
    frame = capsys.readouterr().out
    assert frame  # a non-empty frame


def test_render_json_wraps_ansi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ansi" in payload and isinstance(payload["ansi"], str)


def test_render_tolerates_taui_mirror(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A TAUI mirror has extra keys (taui_version, available_actions); from_dict tolerates them."""
    from convertible.tui.taui import serialize

    mirror = serialize(_boost_state())
    sf = tmp_path / "mirror.json"
    sf.write_text(json.dumps(mirror), encoding="utf-8")
    rc = main(["tui", "render", "--state", str(sf)])
    assert rc == 0
    assert capsys.readouterr().out


def test_render_missing_file_is_user_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["tui", "render", "--state", str(tmp_path / "nope.json")])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tui inspect
# ---------------------------------------------------------------------------


def test_inspect_returns_node(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", _boost_state())
    rc = main(["tui", "inspect", "--select", "popup.skill.boost", "--state", str(sf), "--json"])
    assert rc == 0
    node = json.loads(capsys.readouterr().out)
    assert node["id"] == "popup.skill.boost" and node["visible"] is True


def test_inspect_bad_selector_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "inspect", "--select", "no.such.node", "--state", str(sf)])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tui action — operate the UI by selector
# ---------------------------------------------------------------------------


def test_action_accept_after_boost_popup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sf = _write_state(tmp_path / "s.json", _boost_state())
    rc = main(
        ["tui", "action", "--select", "popup.skill.boost.accept", "--state", str(sf), "--json"]
    )
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    assert mirror["taui_version"]  # a fresh, valid mirror


def test_action_bad_selector_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "action", "--select", "no.such.action", "--state", str(sf)])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tui replay
# ---------------------------------------------------------------------------


def test_replay_folds_events(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ev = tmp_path / "e.jsonl"
    ev.write_text(
        dumps_events([SkillSuggested(skill="boost", reason="task_complexity_high")]),
        encoding="utf-8",
    )
    rc = main(["tui", "replay", str(ev), "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    popup_ids = {p["id"] for p in mirror["popups"]}
    assert "popup.skill.boost" in popup_ids


# ---------------------------------------------------------------------------
# tui snapshot
# ---------------------------------------------------------------------------


def test_snapshot_writes_three_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "snapshot", "--name", "cap", "--dir", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for key in ("taui", "ansi", "events"):
        assert key in payload
        assert Path(payload[key]).exists()


# ---------------------------------------------------------------------------
# tui diagnose
# ---------------------------------------------------------------------------


def test_diagnose_snapshot_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Write a clean snapshot, then diagnose it: no findings.
    rc = main(["tui", "snapshot", "--name", "cap", "--dir", str(tmp_path)])
    assert rc == 0
    capsys.readouterr()  # drain
    rc = main(["tui", "diagnose", "--dir", str(tmp_path), "--name", "cap", "--json"])
    assert rc == 0
    diag = json.loads(capsys.readouterr().out)
    assert "findings" in diag and "classes" in diag


# ---------------------------------------------------------------------------
# tui overview
# ---------------------------------------------------------------------------


def test_overview_runs(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "overview"])
    assert rc == 0
    assert "tui" in capsys.readouterr().out.lower()


def test_overview_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "convertible tui"


def test_no_verb_defaults_to_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui"])
    assert rc == 0
    assert "tui" in capsys.readouterr().out.lower()

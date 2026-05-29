"""Tests for the devague loop tool and finish destination/announcement extensions.

Written TDD — run these before implementing to see them fail, then implement to
make them green.  Scope: convertible/tools.py additions only; loop wiring is
task t4.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

import convertible.devague as devague_mod
from convertible.tools import FINISH, SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor

# ---------------------------------------------------------------------------
# 1. Schema surface — devague must appear in the shared chassis tool table
# ---------------------------------------------------------------------------


def test_devague_in_tool_names() -> None:
    """``devague`` lives in the shared TOOL_NAMES surface (chassis, not engine)."""
    assert "devague" in TOOL_NAMES


def test_devague_schema_present() -> None:
    """SCHEMAS contains exactly one entry named ``devague``."""
    devague_schemas = [s for s in SCHEMAS if s["function"]["name"] == "devague"]
    assert len(devague_schemas) == 1


def test_devague_move_enum_matches_allowed_moves() -> None:
    """The ``move`` parameter enum equals ``sorted(devague.ALLOWED_MOVES)``."""
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "devague")
    params = schema["function"]["parameters"]
    move_enum = params["properties"]["move"]["enum"]
    assert move_enum == sorted(devague_mod.ALLOWED_MOVES)


def test_devague_move_required() -> None:
    """``move`` must be listed as a required parameter."""
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "devague")
    assert "move" in schema["function"]["parameters"].get("required", [])


def test_devague_has_args_param() -> None:
    """Schema declares an ``args`` parameter (array of strings)."""
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "devague")
    props = schema["function"]["parameters"]["properties"]
    assert "args" in props
    assert props["args"]["type"] == "array"


def test_confirm_not_in_devague_move_enum() -> None:
    """``confirm`` is intentionally excluded — user-only decision."""
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "devague")
    move_enum = schema["function"]["parameters"]["properties"]["move"]["enum"]
    assert "confirm" not in move_enum


def test_reject_not_in_devague_move_enum() -> None:
    """``reject`` is intentionally excluded — user-only decision."""
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "devague")
    move_enum = schema["function"]["parameters"]["properties"]["move"]["enum"]
    assert "reject" not in move_enum


def test_export_not_in_devague_move_enum() -> None:
    """``export`` is intentionally excluded — operator-only move."""
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "devague")
    move_enum = schema["function"]["parameters"]["properties"]["move"]["enum"]
    assert "export" not in move_enum


# ---------------------------------------------------------------------------
# 2. _devague dispatch — happy path (monkeypatched run_devague)
# ---------------------------------------------------------------------------


def test_devague_dispatch_calls_run_devague(tmp_path: Path) -> None:
    """ToolExecutor._devague delegates to devague.run_devague with the right args."""
    ex = ToolExecutor(tmp_path)
    fake_output = "exit=0\nok"
    with patch.object(devague_mod, "run_devague", return_value=fake_output) as mock_run:
        outcome = ex.execute("devague", {"move": "status", "args": ["--verbose"]})
    mock_run.assert_called_once_with(
        "status",
        ["--verbose"],
        root=ex.root,
    )
    assert outcome.result == fake_output
    assert not outcome.finished


def test_devague_dispatch_without_args(tmp_path: Path) -> None:
    """``args`` is optional; omitting it passes an empty list to run_devague."""
    ex = ToolExecutor(tmp_path)
    with patch.object(devague_mod, "run_devague", return_value="exit=0\n") as mock_run:
        ex.execute("devague", {"move": "new"})
    # normalize_args(None) → []
    mock_run.assert_called_once_with("new", [], root=ex.root)


# ---------------------------------------------------------------------------
# 3. Error mapping — DevagueToolError → ToolError (never a crash)
# ---------------------------------------------------------------------------


def test_disallowed_move_becomes_tool_error(tmp_path: Path) -> None:
    """``confirm`` (user-only) surfaces as ToolError, not a crash."""
    ex = ToolExecutor(tmp_path)
    # Let the REAL run_devague raise DevagueToolError for "confirm"
    with pytest.raises(ToolError, match="confirm"):
        ex.execute("devague", {"move": "confirm"})


def test_missing_cli_becomes_tool_error(tmp_path: Path) -> None:
    """A missing devague binary maps to ToolError, not FileNotFoundError."""
    ex = ToolExecutor(tmp_path)
    with patch.object(
        devague_mod,
        "run_devague",
        side_effect=devague_mod.DevagueToolError("devague CLI not found"),
    ):
        with pytest.raises(ToolError, match="devague CLI not found"):
            ex.execute("devague", {"move": "status"})


# ---------------------------------------------------------------------------
# 4. finish schema — destination + announcement are optional
# ---------------------------------------------------------------------------


def test_finish_schema_has_destination_and_announcement() -> None:
    """The ``finish`` schema declares ``destination`` and ``announcement`` params."""
    finish_schema = next(s for s in SCHEMAS if s["function"]["name"] == FINISH)
    props = finish_schema["function"]["parameters"]["properties"]
    assert "destination" in props
    assert "announcement" in props


def test_finish_destination_and_announcement_are_optional() -> None:
    """``destination`` and ``announcement`` must NOT appear in the required list."""
    finish_schema = next(s for s in SCHEMAS if s["function"]["name"] == FINISH)
    required = finish_schema["function"]["parameters"].get("required", [])
    assert "destination" not in required
    assert "announcement" not in required


# ---------------------------------------------------------------------------
# 5. ToolOutcome — destination + announcement fields
# ---------------------------------------------------------------------------


def test_tool_outcome_has_destination_and_announcement_fields() -> None:
    """ToolOutcome.destination and .announcement default to None."""
    from convertible.tools import ToolOutcome

    outcome = ToolOutcome(result="x")
    assert outcome.destination is None
    assert outcome.announcement is None


# ---------------------------------------------------------------------------
# 6. finish execution — with and without destination/announcement
# ---------------------------------------------------------------------------


def test_finish_with_destination_and_announcement(tmp_path: Path) -> None:
    """finish WITH destination+announcement → ToolOutcome carries both fields."""
    ex = ToolExecutor(tmp_path)
    outcome = ex.execute(
        FINISH,
        {
            "summary": "task done",
            "destination": "converge",
            "announcement": "spec converged at v1",
        },
    )
    assert outcome.finished is True
    assert outcome.finish_summary == "task done"
    assert outcome.destination == "converge"
    assert outcome.announcement == "spec converged at v1"


def test_finish_without_destination_unchanged(tmp_path: Path) -> None:
    """finish WITHOUT destination+announcement → both fields remain None (unchanged path)."""
    ex = ToolExecutor(tmp_path)
    outcome = ex.execute(FINISH, {"summary": "plain finish"})
    assert outcome.finished is True
    assert outcome.finish_summary == "plain finish"
    assert outcome.destination is None
    assert outcome.announcement is None


def test_finish_with_only_destination(tmp_path: Path) -> None:
    """finish with destination but no announcement → announcement stays None."""
    ex = ToolExecutor(tmp_path)
    outcome = ex.execute(FINISH, {"summary": "partial", "destination": "park"})
    assert outcome.destination == "park"
    assert outcome.announcement is None


# ---------------------------------------------------------------------------
# 7. All-engines guard — devague tool lives in the chassis, not in engines
# ---------------------------------------------------------------------------


def test_devague_in_shared_schemas_surface() -> None:
    """The devague tool is registered in the single shared SCHEMAS list (chassis)."""
    names = [s["function"]["name"] for s in SCHEMAS]
    assert "devague" in names


def test_no_engine_imports_devague() -> None:
    """No module under convertible/engines/ imports convertible.devague.

    The devague tool belongs to the chassis (tools.py); engines must not
    import it directly — they inherit it through the loop (all-engines rule).
    """
    engines_dir = Path(__file__).parent.parent / "convertible" / "engines"
    pattern = re.compile(r"\bconvertible\.devague\b|from convertible import.*devague")
    violations: list[str] = []
    for py_file in engines_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        source = py_file.read_text(encoding="utf-8")
        if pattern.search(source):
            violations.append(py_file.name)
    assert violations == [], (
        f"Engine(s) {violations} import convertible.devague directly — "
        "the devague tool belongs to the chassis (tools.py), not to engines."
    )

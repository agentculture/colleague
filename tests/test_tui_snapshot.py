"""Tests for convertible.tui.snapshot — snapshot triple write/read."""

from pathlib import Path

from convertible.tui.events import DriveStep, UserInput
from convertible.tui.render.ansi import render
from convertible.tui.snapshot import Snapshot, read_snapshot, write_snapshot
from convertible.tui.state import Action, CockpitState, Drive, Popup, Status
from convertible.tui.taui import serialize


def _make_state() -> CockpitState:
    """Build a CockpitState with a visible popup so serialize() is non-trivial."""
    state = CockpitState(
        screen="main",
        mode="driving",
        status=Status(severity="info", message="Running drive"),
        drive=Drive(task_id="abc-123", engine="mock", step_count=3, running=True),
        popups=[
            Popup(
                id="confirm-popup",
                kind="confirmation",
                visible=True,
                blocking=True,
                message="Approve this change?",
                actions=[
                    Action(selector="button.yes", input="enter", description="Yes"),
                    Action(selector="button.no", input="enter", description="No"),
                ],
            )
        ],
    )
    return state


def _make_events() -> list:
    return [
        UserInput(text="run tests"),
        DriveStep(tool="read_file", summary="read loop.py", ok=True),
        DriveStep(tool="finish", summary="done", ok=True),
    ]


class TestWriteSnapshot:
    def test_produces_three_files(self, tmp_path):
        state = _make_state()
        events = _make_events()
        paths = write_snapshot(tmp_path, "bug-x", state, events)

        assert set(paths.keys()) == {"taui", "ansi", "events"}
        assert paths["taui"] == tmp_path / "bug-x.taui.json"
        assert paths["ansi"] == tmp_path / "bug-x.ansi"
        assert paths["events"] == tmp_path / "bug-x.events.jsonl"

        for p in paths.values():
            assert p.exists(), f"Expected {p} to exist"

    def test_file_names_use_name_argument(self, tmp_path):
        state = CockpitState()
        write_snapshot(tmp_path, "frame-007", state, [])
        assert (tmp_path / "frame-007.taui.json").exists()
        assert (tmp_path / "frame-007.ansi").exists()
        assert (tmp_path / "frame-007.events.jsonl").exists()

    def test_taui_json_content_matches_serialize(self, tmp_path):
        import json

        state = _make_state()
        paths = write_snapshot(tmp_path, "s1", state, [])
        raw = paths["taui"].read_text(encoding="utf-8")
        # Must end with a newline (artifact.py style)
        assert raw.endswith("\n")
        loaded = json.loads(raw)
        assert loaded == serialize(state)

    def test_taui_json_is_pretty_printed(self, tmp_path):
        state = _make_state()
        paths = write_snapshot(tmp_path, "s2", state, [])
        raw = paths["taui"].read_text(encoding="utf-8")
        # indent=2 means lines should not all be on a single line
        assert "\n" in raw
        # First line should be "{"
        assert raw.lstrip().startswith("{")

    def test_ansi_content_matches_render(self, tmp_path):
        state = _make_state()
        paths = write_snapshot(tmp_path, "s3", state, [])
        written = paths["ansi"].read_text(encoding="utf-8")
        assert written == render(state)

    def test_events_jsonl_content_matches_dumps_events(self, tmp_path):
        from convertible.tui.events import dumps_events

        state = CockpitState()
        events = _make_events()
        paths = write_snapshot(tmp_path, "s4", state, events)
        written = paths["events"].read_text(encoding="utf-8")
        assert written == dumps_events(events)

    def test_creates_missing_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "dir"
        assert not nested.exists()
        state = CockpitState()
        paths = write_snapshot(nested, "snap", state, [])
        assert nested.exists()
        for p in paths.values():
            assert p.exists()

    def test_returns_path_objects(self, tmp_path):
        state = CockpitState()
        paths = write_snapshot(tmp_path, "p-test", state, [])
        for v in paths.values():
            assert isinstance(v, Path)

    def test_accepts_string_directory(self, tmp_path):
        state = CockpitState()
        paths = write_snapshot(str(tmp_path), "str-dir", state, [])
        for p in paths.values():
            assert p.exists()

    def test_empty_events_produces_empty_jsonl(self, tmp_path):
        state = CockpitState()
        paths = write_snapshot(tmp_path, "empty-ev", state, [])
        content = paths["events"].read_text(encoding="utf-8")
        assert content == ""


class TestReadSnapshot:
    def test_round_trip_taui(self, tmp_path):
        state = _make_state()
        write_snapshot(tmp_path, "rt", state, [])
        snap = read_snapshot(tmp_path, "rt")
        assert snap.taui == serialize(state)

    def test_round_trip_ansi(self, tmp_path):
        state = _make_state()
        write_snapshot(tmp_path, "rt", state, [])
        snap = read_snapshot(tmp_path, "rt")
        assert snap.ansi == render(state)

    def test_round_trip_events(self, tmp_path):
        state = _make_state()
        events = _make_events()
        write_snapshot(tmp_path, "rt", state, events)
        snap = read_snapshot(tmp_path, "rt")
        # Compare by dict representation (dataclass equality)
        assert [e.to_dict() for e in snap.events] == [e.to_dict() for e in events]

    def test_snapshot_is_dataclass(self, tmp_path):
        state = CockpitState()
        write_snapshot(tmp_path, "dc", state, [])
        snap = read_snapshot(tmp_path, "dc")
        assert isinstance(snap, Snapshot)
        assert isinstance(snap.taui, dict)
        assert isinstance(snap.ansi, str)
        assert isinstance(snap.events, list)

    def test_snapshot_accepts_string_directory(self, tmp_path):
        state = CockpitState()
        write_snapshot(str(tmp_path), "str-rd", state, [])
        snap = read_snapshot(str(tmp_path), "str-rd")
        assert snap.taui == serialize(state)

    def test_triple_is_self_sufficient(self, tmp_path):
        """The triple alone is sufficient input — no live state needed for read."""
        state = _make_state()
        events = _make_events()
        write_snapshot(tmp_path, "self", state, events)

        # Reconstruct without any reference to the original state object
        snap = read_snapshot(tmp_path, "self")
        assert "taui_version" in snap.taui
        assert snap.ansi  # non-empty ANSI frame
        assert len(snap.events) == len(events)

    def test_taui_version_present(self, tmp_path):
        from convertible.tui.taui import SCHEMA_VERSION

        state = CockpitState()
        write_snapshot(tmp_path, "ver", state, [])
        snap = read_snapshot(tmp_path, "ver")
        assert snap.taui.get("taui_version") == SCHEMA_VERSION

    def test_popup_actions_in_available_actions(self, tmp_path):
        state = _make_state()
        write_snapshot(tmp_path, "aa", state, [])
        snap = read_snapshot(tmp_path, "aa")
        selectors = [a["selector"] for a in snap.taui.get("available_actions", [])]
        assert "button.yes" in selectors
        assert "button.no" in selectors
        # standing action always present
        assert "input.prompt" in selectors

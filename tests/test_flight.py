"""Tests for the file-based flight-control-plane primitives (colleague/flight.py)."""

import json

import pytest

from colleague import flight

# --- acceptance 1: incremental, mid-run-readable JSONL feed ----------------


def test_append_feed_writes_one_parseable_record_per_call(tmp_path):
    sess = flight.arm(tmp_path, "t-abc")
    fp = flight.feed_path(tmp_path, "t-abc")

    sess.append_feed(step_index=0, tool="read_file", intent="read x", stats={"steps": 1})
    # readable MID-RUN: parse what is on disk before the next append
    mid = [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]
    assert len(mid) == 1
    assert mid[0] == {
        "step_index": 0,
        "tool": "read_file",
        "intent": "read x",
        "stats": {"steps": 1},
    }

    sess.append_feed(step_index=1, tool="edit_file", intent="edit y", stats={"steps": 2})
    sess.append_feed(step_index=2, tool=None, intent=None, stats={})

    records = [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]
    assert len(records) == 3
    assert [r["step_index"] for r in records] == [0, 1, 2]


# --- acceptance 2: control read with stop + consumed-guidance cursor --------


def test_read_control_returns_unconsumed_guidance_then_empty(tmp_path):
    sess = flight.arm(tmp_path, "t-g")
    flight.control_path(tmp_path, "t-g").write_text(json.dumps({"stop": False, "guidance": ["g1"]}))

    first = sess.read_control()
    assert first.stop is False
    assert first.guidance == ["g1"]

    # same guidance is never returned twice (cursor advanced)
    second = sess.read_control()
    assert second.guidance == []

    # a newly appended guidance is picked up beyond the cursor
    flight.append_guidance(tmp_path, "t-g", "g2")
    third = sess.read_control()
    assert third.guidance == ["g2"]


def test_read_control_stop_true(tmp_path):
    sess = flight.arm(tmp_path, "t-s")
    flight.write_stop(tmp_path, "t-s")
    assert sess.read_control().stop is True


def test_read_control_absent_or_malformed_is_safe(tmp_path):
    sess = flight.arm(tmp_path, "t-none")
    # absent control file
    assert sess.read_control() == flight.Control(stop=False, guidance=[])
    # malformed JSON
    flight.control_path(tmp_path, "t-none").write_text("{not json")
    assert sess.read_control() == flight.Control(stop=False, guidance=[])


# --- acceptance 3: strict scoping under .colleague/flight/ ------------------


def test_reap_orphans_never_touches_paths_outside_flight_dir(tmp_path):
    flight.arm(tmp_path, "t-1")
    # a sibling file under .colleague/ but OUTSIDE flight/
    sibling = tmp_path / ".colleague" / "last_work"
    sibling.write_text("keep me")

    deleted = flight.reap_orphans(tmp_path, active_task_ids=None)

    assert sibling.exists(), "reap must never touch a path outside .colleague/flight/"
    # the armed feed file was an orphan (no active ids) and got reaped
    assert flight.feed_path(tmp_path, "t-1") not in flight.list_flight_files(tmp_path)
    assert all(p.parent == flight.flight_dir(tmp_path) for p in deleted)


def test_reap_orphans_preserves_active_task_files(tmp_path):
    # active + orphan flights, each with feed + control
    flight.arm(tmp_path, "live")
    flight.write_stop(tmp_path, "live")
    flight.arm(tmp_path, "dead")
    flight.write_stop(tmp_path, "dead")

    deleted = flight.reap_orphans(tmp_path, active_task_ids={"live"})

    remaining = {p.name for p in flight.list_flight_files(tmp_path)}
    assert "live.feed.jsonl" in remaining and "live.control.json" in remaining
    assert "dead.feed.jsonl" not in remaining and "dead.control.json" not in remaining
    assert {p.name for p in deleted} == {"dead.feed.jsonl", "dead.control.json"}


# --- acceptance 4: depth cap (fork-bomb guard) -----------------------------


@pytest.mark.parametrize("depth,expected", [("0", False), ("1", False), ("2", True), ("3", True)])
def test_depth_exceeded(monkeypatch, depth, expected):
    monkeypatch.setenv(flight.DEPTH_ENV, depth)
    assert flight.depth_exceeded() is expected


def test_current_depth_defaults_and_tolerates_garbage(monkeypatch):
    monkeypatch.delenv(flight.DEPTH_ENV, raising=False)
    assert flight.current_depth() == 0
    monkeypatch.setenv(flight.DEPTH_ENV, "not-an-int")
    assert flight.current_depth() == 0


def test_child_depth_env_increments(monkeypatch):
    monkeypatch.setenv(flight.DEPTH_ENV, "0")
    assert flight.child_depth_env() == {flight.DEPTH_ENV: "1"}
    monkeypatch.setenv(flight.DEPTH_ENV, "1")
    assert flight.child_depth_env() == {flight.DEPTH_ENV: "2"}


# --- acceptance 5: stdlib-only (no third-party leak) -----------------------


def test_flight_module_is_stdlib_only():
    import inspect

    src = inspect.getsource(flight)
    # the module's import lines reference only stdlib
    import_lines = [ln.strip() for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    allowed_roots = {"json", "os", "dataclasses", "pathlib"}
    for ln in import_lines:
        root = ln.split()[1].split(".")[0]
        assert root in allowed_roots, f"non-stdlib import in flight.py: {ln}"


# --- session reap removes its own files ------------------------------------


def test_session_reap_removes_feed_and_control(tmp_path):
    sess = flight.arm(tmp_path, "t-reap")
    flight.append_guidance(tmp_path, "t-reap", "g")
    assert flight.feed_path(tmp_path, "t-reap").exists()
    assert flight.control_path(tmp_path, "t-reap").exists()

    sess.reap()

    assert not flight.feed_path(tmp_path, "t-reap").exists()
    assert not flight.control_path(tmp_path, "t-reap").exists()

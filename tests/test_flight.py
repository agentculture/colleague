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
    allowed_roots = {"json", "os", "time", "dataclasses", "pathlib"}
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


# --- Bug 2: task-id path-traversal guard -----------------------------------


@pytest.mark.parametrize("tid", ["abc123", "t-reap", "6633119e1c61"])
def test_is_safe_task_id_accepts_normal_ids(tid):
    assert flight.is_safe_task_id(tid) is True


@pytest.mark.parametrize("tid", ["../escape", "/etc/passwd", "a/b", "..", ".", ""])
def test_is_safe_task_id_rejects_traversal(tid):
    assert flight.is_safe_task_id(tid) is False


@pytest.mark.parametrize("tid", ["../escape", "/etc/passwd", "a/b"])
def test_path_helpers_reject_unsafe_task_id(tmp_path, tid):
    with pytest.raises(ValueError):
        flight.feed_path(tmp_path, tid)
    with pytest.raises(ValueError):
        flight.control_path(tmp_path, tid)


# --- Bug 3: write_stop/append_guidance create the flight dir ----------------


def test_control_writers_create_dir_when_absent(tmp_path):
    # no flight has ever been armed -> .colleague/flight/ does not exist
    assert not flight.flight_dir(tmp_path).exists()
    flight.write_stop(tmp_path, "fresh")  # must NOT raise FileNotFoundError
    assert flight.control_path(tmp_path, "fresh").exists()

    flight.append_guidance(tmp_path, "fresh2", "hello")  # also creates the dir
    assert "hello" in flight.FlightSession(tmp_path, "fresh2").read_control().guidance


# --- Bug 5: active-flight detection (mtime heuristic) -----------------------


def test_recent_flight_task_ids_marks_recent_active(tmp_path):
    import os
    import time

    flight.arm(tmp_path, "live")
    flight.arm(tmp_path, "old")
    old = time.time() - (flight.ACTIVE_WINDOW_SECONDS + 60)
    os.utime(flight.feed_path(tmp_path, "old"), (old, old))

    active = flight.recent_flight_task_ids(tmp_path)
    assert "live" in active
    assert "old" not in active


def test_reap_orphans_dry_run_lists_without_deleting(tmp_path):
    flight.arm(tmp_path, "d")
    would = flight.reap_orphans(tmp_path, dry_run=True)
    assert flight.feed_path(tmp_path, "d") in would
    assert flight.feed_path(tmp_path, "d").exists()  # not deleted in dry-run


# --- t6: episode-transition marker + between-episode stop read ---------------
# (indefinite-run t6: chain continuity + episode-transition observability)


def test_transition_announcement_exact_form():
    txt = flight.transition_announcement("abc123", 2, 5)
    assert txt == "episode 2 of 5: continuing abc123"


def test_transition_announcement_unlimited_cap():
    # cap 0 (and any non-positive cap) reads "unlimited" — the c21 convention.
    assert flight.transition_announcement("abc123", 4, 0) == (
        "episode 4 of unlimited: continuing abc123"
    )
    assert flight.transition_announcement("abc123", 4, -1) == (
        "episode 4 of unlimited: continuing abc123"
    )


def test_append_episode_transition_marker_shape(tmp_path):
    flight.append_episode_transition(
        tmp_path, "prior-id", next_task_id="next-id", episode_index=2, cap=5
    )
    lines = flight.feed_path(tmp_path, "prior-id").read_text().splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    assert len(records) == 1
    marker = records[0]
    assert marker["type"] == "episode-transition"
    assert marker["next_task_id"] == "next-id"
    assert marker["episode_index"] == 2
    assert marker["cap"] == 5
    # The common marker keys (the #308 convention) so an existing feed reader
    # (`colleague talk` grounding, `flight status`) never KeyErrors on it.
    assert marker["step_index"] == 0
    assert marker["tool"] is None
    assert marker["stats"] == {}
    assert "at" in marker
    # The intent IS the pilot-facing announcement — hop-by-hop followable.
    assert marker["intent"] == "episode 2 of 5: continuing prior-id"


def test_append_episode_transition_recreates_a_reaped_feed(tmp_path):
    # The loop reaps an episode's feed at finish; the boundary marker append
    # must recreate it best-effort so a pilot can still find the next hop.
    sess = flight.arm(tmp_path, "t-prior")
    sess.reap()
    assert not flight.feed_path(tmp_path, "t-prior").exists()
    flight.append_episode_transition(tmp_path, "t-prior", next_task_id="n1", episode_index=2, cap=0)
    records = [
        json.loads(line) for line in flight.feed_path(tmp_path, "t-prior").read_text().splitlines()
    ]
    assert records[0]["next_task_id"] == "n1"
    assert records[0]["cap"] == 0


def test_append_episode_transition_unwritable_dir_never_raises(tmp_path):
    import os

    fd = flight.flight_dir(tmp_path)
    fd.mkdir(parents=True)
    os.chmod(fd, 0o500)  # read+exec only: the append cannot create the feed file
    try:
        # Best-effort: an unwritable flight dir must never crash the chain.
        flight.append_episode_transition(
            tmp_path, "prior", next_task_id="next", episode_index=2, cap=5
        )
    finally:
        os.chmod(fd, 0o700)
    assert not flight.feed_path(tmp_path, "prior").exists()


def test_read_stop_absent_and_malformed_are_false(tmp_path):
    # absent control file (and even an absent flight dir) reads as no-stop
    assert flight.read_stop(tmp_path, "t-x") is False
    flight.arm(tmp_path, "t-x")
    assert flight.read_stop(tmp_path, "t-x") is False
    flight.control_path(tmp_path, "t-x").write_text("{not json")
    assert flight.read_stop(tmp_path, "t-x") is False


def test_read_stop_true_after_write_stop(tmp_path):
    flight.write_stop(tmp_path, "t-y")
    assert flight.read_stop(tmp_path, "t-y") is True


def test_read_stop_is_a_pure_peek_never_consumes_guidance(tmp_path):
    # read_stop must not advance any guidance cursor — a later FlightSession
    # reader still sees every guidance message.
    flight.append_guidance(tmp_path, "t-z", "g1")
    flight.write_stop(tmp_path, "t-z")
    assert flight.read_stop(tmp_path, "t-z") is True
    sess = flight.FlightSession(repo_path=tmp_path, task_id="t-z")
    control = sess.read_control()
    assert control.stop is True
    assert control.guidance == ["g1"]

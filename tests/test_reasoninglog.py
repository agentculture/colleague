"""Tests for colleague.reasoninglog — the per-request reasoning sidecar (plan task t3).

Arc: a work item's model requests are journaled as a ``.reasoning.jsonl``
sidecar beside the parent artifact, with an off-knob, a size cap (truncated
with a marker record), and tagged child naming. Pure stdlib; the module
imports ``artifact_dir`` from ``colleague.artifact`` (never the reverse).
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague import reasoninglog
from colleague.artifact import artifact_dir

RECORD_KEYS = {"seat", "turn", "request_ts", "request_index", "text"}


def _record(**overrides) -> dict:
    base = {
        "seat": "main",
        "turn": 1,
        "request_ts": "2026-01-01T00:00:00+00:00",
        "request_index": 0,
        "text": "think about the thing",
    }
    base.update(overrides)
    return base


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ── enabled() off-knob ─────────────────────────────────────────────


class TestEnabled:
    """COLLEAGUE_REASONING_LOG=0 disables; default is enabled."""

    def test_default_enabled(self, monkeypatch):
        monkeypatch.delenv("COLLEAGUE_REASONING_LOG", raising=False)
        assert reasoninglog.enabled() is True

    def test_zero_disables(self, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_REASONING_LOG", "0")
        assert reasoninglog.enabled() is False

    def test_anything_else_enables(self, monkeypatch):
        for value in ("1", "true", "yes", ""):
            monkeypatch.setenv("COLLEAGUE_REASONING_LOG", value)
            assert reasoninglog.enabled() is True


# ── record shape ───────────────────────────────────────────────────


class TestRecordShape:
    """append writes one JSON line with the five record fields."""

    def test_single_record_shape(self, tmp_path):
        path = reasoninglog.append(tmp_path, "task-1", _record())
        assert path is not None
        assert path == artifact_dir(tmp_path) / "task-1.reasoning.jsonl"
        lines = _read_lines(path)
        assert len(lines) == 1
        assert set(lines[0].keys()) == RECORD_KEYS
        assert lines[0]["seat"] == "main"
        assert lines[0]["turn"] == 1
        assert lines[0]["request_ts"] == "2026-01-01T00:00:00+00:00"
        assert lines[0]["request_index"] == 0
        assert lines[0]["text"] == "think about the thing"

    def test_records_append_in_order(self, tmp_path):
        reasoninglog.append(tmp_path, "task-1", _record(turn=1, request_index=0))
        reasoninglog.append(tmp_path, "task-1", _record(turn=2, request_index=1))
        reasoninglog.append(tmp_path, "task-1", _record(turn=3, request_index=2))
        lines = _read_lines(artifact_dir(tmp_path) / "task-1.reasoning.jsonl")
        assert [line["turn"] for line in lines] == [1, 2, 3]
        assert [line["request_index"] for line in lines] == [0, 1, 2]

    def test_creates_artifact_dir(self, tmp_path):
        assert not artifact_dir(tmp_path).exists()
        reasoninglog.append(tmp_path, "task-1", _record())
        assert artifact_dir(tmp_path).is_dir()


# ── off-knob: no file, byte-identical run ─────────────────────────


class TestOffKnob:
    """With COLLEAGUE_REASONING_LOG=0, append writes nothing and returns None."""

    def test_no_file_written(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_REASONING_LOG", "0")
        path = reasoninglog.append(tmp_path, "task-1", _record())
        assert path is None
        assert not artifact_dir(tmp_path).exists()

    def test_no_file_even_with_child(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_REASONING_LOG", "0")
        path = reasoninglog.append(tmp_path, "task-1", _record(), child_id="child-9")
        assert path is None
        assert not artifact_dir(tmp_path).exists()


# ── size cap + marker record ───────────────────────────────────────


class TestSizeCap:
    """When the file would exceed max_bytes, a marker record is written and
    appending stops."""

    def test_cap_truncates_with_marker(self, tmp_path):
        cap = 400
        reasoninglog.append(tmp_path, "task-1", _record(text="x" * 50), max_bytes=cap)
        reasoninglog.append(tmp_path, "task-1", _record(text="x" * 50), max_bytes=cap)
        # This one would push the file past the cap.
        reasoninglog.append(tmp_path, "task-1", _record(text="x" * 50), max_bytes=cap)
        path = artifact_dir(tmp_path) / "task-1.reasoning.jsonl"
        lines = _read_lines(path)
        assert lines[-1] == {"truncated": True}
        # The over-cap record itself was NOT written.
        assert len(lines) == 3
        assert all("text" in line for line in lines[:-1])

    def test_nothing_appended_after_marker(self, tmp_path):
        cap = 400
        reasoninglog.append(tmp_path, "task-1", _record(text="x" * 50), max_bytes=cap)
        reasoninglog.append(tmp_path, "task-1", _record(text="x" * 50), max_bytes=cap)
        reasoninglog.append(tmp_path, "task-1", _record(text="x" * 50), max_bytes=cap)
        before = (artifact_dir(tmp_path) / "task-1.reasoning.jsonl").read_bytes()
        reasoninglog.append(tmp_path, "task-1", _record(text="y" * 50), max_bytes=cap)
        after = (artifact_dir(tmp_path) / "task-1.reasoning.jsonl").read_bytes()
        assert before == after

    def test_marker_written_only_once(self, tmp_path):
        cap = 400
        for i in range(5):
            reasoninglog.append(
                tmp_path, "task-1", _record(text="x" * 50, request_index=i), max_bytes=cap
            )
        lines = _read_lines(artifact_dir(tmp_path) / "task-1.reasoning.jsonl")
        assert sum(1 for line in lines if line == {"truncated": True}) == 1

    def test_oversized_single_record_still_gets_marker(self, tmp_path):
        # A record larger than the cap on an empty file: the marker is still
        # written so the truncation is discoverable.
        reasoninglog.append(tmp_path, "task-1", _record(text="x" * 500), max_bytes=100)
        lines = _read_lines(artifact_dir(tmp_path) / "task-1.reasoning.jsonl")
        assert lines == [{"truncated": True}]

    def test_default_cap_is_one_mib(self):
        assert reasoninglog.DEFAULT_MAX_BYTES == 1_000_000


# ── child naming ───────────────────────────────────────────────────


class TestChildNaming:
    """child_id tags the filename: <task_id>.<child_id>.reasoning.jsonl,
    resolving to the OPERATOR repo's .colleague/ dir."""

    def test_child_filename(self, tmp_path):
        path = reasoninglog.append(tmp_path, "task-1", _record(), child_id="child-9")
        assert path == artifact_dir(tmp_path) / "task-1.child-9.reasoning.jsonl"
        assert path.is_file()

    def test_child_and_parent_files_are_distinct(self, tmp_path):
        reasoninglog.append(tmp_path, "task-1", _record())
        reasoninglog.append(tmp_path, "task-1", _record(), child_id="child-9")
        adir = artifact_dir(tmp_path)
        assert (adir / "task-1.reasoning.jsonl").is_file()
        assert (adir / "task-1.child-9.reasoning.jsonl").is_file()

    def test_child_records_land_in_operator_repo_dir(self, tmp_path):
        # The child's sidecar resolves to the SAME .colleague/ dir as the
        # parent artifact — the operator repo's bookkeeping dir.
        path = reasoninglog.append(tmp_path, "task-1", _record(), child_id="child-9")
        assert path.parent == artifact_dir(tmp_path)
        assert path.parent == tmp_path / ".colleague"

    def test_child_id_also_capped(self, tmp_path):
        cap = 400
        reasoninglog.append(
            tmp_path, "task-1", _record(text="x" * 50), child_id="c1", max_bytes=cap
        )
        reasoninglog.append(
            tmp_path, "task-1", _record(text="x" * 50), child_id="c1", max_bytes=cap
        )
        reasoninglog.append(
            tmp_path, "task-1", _record(text="x" * 50), child_id="c1", max_bytes=cap
        )
        lines = _read_lines(artifact_dir(tmp_path) / "task-1.c1.reasoning.jsonl")
        assert lines[-1] == {"truncated": True}


# ── unsafe ids are refused, not written ────────────────────────────


class TestUnsafeIds:
    """Traversal ids (task_id / child_id) are refused: no file, None returned."""

    def test_unsafe_task_id(self, tmp_path):
        path = reasoninglog.append(tmp_path, "../evil", _record())
        assert path is None
        assert not (tmp_path / ".." / "evil.reasoning.jsonl").exists()

    def test_unsafe_child_id(self, tmp_path):
        path = reasoninglog.append(tmp_path, "task-1", _record(), child_id="a/b")
        assert path is None
        assert not (artifact_dir(tmp_path) / "task-1.a").is_dir()

    def test_empty_task_id(self, tmp_path):
        assert reasoninglog.append(tmp_path, "", _record()) is None


# ── module boundary: stdlib + artifact only ────────────────────────


class TestModuleBoundary:
    """reasoninglog imports only stdlib + colleague.artifact (never loop)."""

    def test_imports_are_stdlib_plus_artifact(self):
        import ast

        source = (Path(reasoninglog.__file__)).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        allowed = {"__future__", "json", "os", "pathlib", "time", "colleague", "datetime", "typing"}
        assert imported <= allowed, f"unexpected imports: {imported - allowed}"
        assert "colleague.loop" not in source
        assert "colleague.artifact" in source

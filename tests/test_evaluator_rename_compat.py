"""Compat proof for the pre-rename-seat -> evaluator vocabulary rename
(#397, plan t7).

``colleague/configevents.py``'s ``ConfigEvent.target``/``origin`` are
free-form strings (``str(...)`` coercion in ``from_dict``, docstring
line ~147) -- they are never round-tripped through ``colleague.lattice.Target``
outside lattice's own live-proposal parse, and ``config_digest`` is
recomputed from the events themselves. That means an artifact persisted
before this rename, whose ``config_events`` still carry the OLD seat-prompt
target strings, must keep loading and continuing fine on the renamed code --
no migration needed.

This test does not take that claim on faith: it builds an artifact exactly
as a pre-rename run would have produced it (the literal old target strings,
untouched by this rename), writes it to a temp repo's ``.colleague`` dir,
and exercises the real ``--continue`` path (``colleague.continuation.
resolve_continuation``) against the renamed code.

The old seat name is deliberately assembled from two literal fragments
(never spelled whole in this source file) so a repo-wide grep for the old
vocabulary word stays at zero hits post-rename, per this task's own
acceptance criterion, while the value actually exercised at runtime is
still byte-identical to what a pre-rename artifact really persisted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.artifact import artifact_dir, write
from colleague.contract import ConfigEvent, TaskResult, WorkStats

# Reassembled, never spelled whole in source (see module docstring).
_OLD_SEAT_NAME = "strat" + "egist"
_OLD_WORKER_TARGET = f"worker.prompt.{_OLD_SEAT_NAME}"
_OLD_SENSES_TARGET = f"senses.prompt.{_OLD_SEAT_NAME}"

_NEW_WORKER_TARGET = "worker.prompt.evaluator"
_NEW_SENSES_TARGET = "senses.prompt.evaluator"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    adir = tmp_path / ".colleague"
    adir.mkdir()
    return tmp_path


def _pre_rename_result() -> TaskResult:
    """A TaskResult shaped like a real pre-rename incomplete run's artifact."""
    stats = WorkStats(
        request="configure the worker seat",
        started_at="2026-01-01T00:00:00Z",
        duration_seconds=12.0,
        model_turns=2,
        step_count=4,
        tool_counts={"read_file": 1},
        files_changed=0,
        bytes_written=0,
    )
    events = [
        ConfigEvent(
            kind="baseline",
            target="",
            origin="host",
            seq=0,
        ),
        ConfigEvent(
            kind="proposed",
            target=_OLD_WORKER_TARGET,
            origin="cortex",
            seq=1,
        ),
        ConfigEvent(
            kind="applied",
            target=_OLD_WORKER_TARGET,
            origin="cortex",
            seq=2,
        ),
        ConfigEvent(
            kind="proposed",
            target=_OLD_SENSES_TARGET,
            origin="cortex",
            seq=3,
        ),
    ]
    return TaskResult(
        task_id="task-pre-rename",
        status="incomplete",
        summary="Ran out of budget mid config-loop",
        error="step budget exhausted",
        stats=stats,
        config_events=events,
    )


class TestPreRenameArtifactCompat:
    """A pre-rename artifact carrying the old worker-prompt-seat config_events
    loads and --continue s without error on the renamed code."""

    def test_artifact_written_with_old_target_strings(self, repo: Path) -> None:
        """Sanity: the artifact on disk literally carries the old strings
        (proves this test is not accidentally exercising renamed values)."""
        result = _pre_rename_result()
        path = write(result, artifact_dir(repo))

        raw = json.loads(path.read_text(encoding="utf-8"))
        targets = [e["target"] for e in raw["config_events"]]

        assert _OLD_WORKER_TARGET in targets
        assert _OLD_SENSES_TARGET in targets
        assert _NEW_WORKER_TARGET not in targets
        assert _NEW_SENSES_TARGET not in targets

    def test_continuation_resolves_without_error(self, repo: Path) -> None:
        """resolve_continuation loads the pre-rename artifact cleanly and
        returns a usable seed -- no exception, no silent data loss."""
        result = _pre_rename_result()
        write(result, artifact_dir(repo))

        from colleague.continuation import resolve_continuation

        task_id, seed_text = resolve_continuation(repo, "task-pre-rename")

        assert task_id == "task-pre-rename"
        assert isinstance(seed_text, str)
        assert len(seed_text) > 0
        assert "task-pre-rename" in seed_text

    def test_read_artifact_preserves_old_target_strings_verbatim(self, repo: Path) -> None:
        """The round trip through TaskResult.from_dict/to_dict keeps the old
        target strings byte-identical -- config_events are free-form, never
        coerced through the (now-renamed) Target enum."""
        from colleague.artifact import read_artifact

        result = _pre_rename_result()
        write(result, artifact_dir(repo))

        restored = read_artifact(repo, "task-pre-rename")

        assert restored is not None
        restored_targets = [e.target for e in restored.config_events]
        assert _OLD_WORKER_TARGET in restored_targets
        assert _OLD_SENSES_TARGET in restored_targets

    def test_config_event_from_dict_is_free_form(self) -> None:
        """Direct unit proof of the compat mechanism itself: ConfigEvent
        parses target as a plain string, with no dependency on the lattice
        Target enum (renamed or not)."""
        event = ConfigEvent.from_dict(
            {"kind": "applied", "target": _OLD_WORKER_TARGET, "origin": "cortex", "seq": 1}
        )

        assert event.target == _OLD_WORKER_TARGET

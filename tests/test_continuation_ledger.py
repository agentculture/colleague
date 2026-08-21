"""t17 — continuation rehydrates from the task ledger when ``agents`` is armed.

The artifact stays the wrong-run guard's source (missing/corrupt/ok guards are
untouched); the ledger replaces only the PROSE body of the seed, and only when
the caller says the agents mode is armed AND the ledger reads cleanly. Every
defect fails closed to the existing prose recap with a recorded warning
(``warnings`` out-param); unarmed with a ledger present records an "ignored"
warning; no ledger at all is byte-identical to today.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.agents.state import (
    LEDGER_SCHEMA_VERSION,
    TaskLedger,
    TaskSnapshot,
    ledger_path,
    read_ledger,
)
from colleague.artifact import artifact_dir, write
from colleague.continuation import (
    ContinuationError,
    build_ledger_seed,
    rehydrate_snapshot,
    resolve_continuation,
)
from colleague.contract import OK, TaskResult, WorkStats

TASK = "task-001"
REQUEST = "implement the new feature"
LATEST_INPUT = "actually: skip the docs, just land the tests"
EARLIER_INPUT = "please also write docs"

# The five ``##`` headings escalation.build_continuation renders — the prose
# recap the ledger seed must NOT contain.
PROSE_HEADINGS = (
    "## Continuation State",
    "## Remaining Work",
    "## What's Needed",
    "## Suggested Split",
    "## Why It Hit the Wall",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".colleague").mkdir()
    return tmp_path


def _stats() -> WorkStats:
    return WorkStats(
        request=REQUEST,
        started_at="2026-01-01T00:00:00Z",
        duration_seconds=30.0,
        model_turns=5,
        step_count=10,
        tool_counts={"read_file": 3, "write_file": 2},
        files_changed=2,
        bytes_written=5000,
    )


def _write_artifact(repo: Path, *, status: str = "incomplete", task_id: str = TASK) -> Path:
    result = TaskResult(
        task_id=task_id,
        status=status,
        summary="Started the feature but ran out of steps",
        changed_files=["src/feature.py", "tests/test_feature.py"],
        error="step budget exhausted" if status != OK else "",
        stats=_stats(),
    )
    return write(result, artifact_dir(repo))


def _build_ledger(repo: Path, task_id: str = TASK) -> TaskLedger:
    """A realistic pre-cut ledger: authority facts, constraints, acceptance,
    decisions (one tagged follow-up), loops, changed paths, verification (one
    failed), an unreturned delegation, two operator inputs, a snapshot."""
    led = TaskLedger(ledger_path(repo, task_id), task_id)
    led.append(
        "operator_request",
        {"ref": "message:m-0", "text": REQUEST, "no_pr": True, "mode": "build", "role": "worker"},
    )
    led.append("constraint", {"ref": "c-1", "text": "stdlib only, no new base deps"})
    led.append("acceptance", {"id": "a-1", "text": "tests/test_feature.py passes"})
    led.append("acceptance", {"id": "a-2", "text": "no prose recap headings in seed"})
    led.append("plan_node", {"id": "p-1", "text": "write tests", "status": "done"})
    led.append("decision", {"ref": "d-1", "text": "rehydrate from the ledger, not prose"})
    led.append("decision", {"ref": "d-2", "text": "open an issue for the docs", "follow_up": True})
    led.append("open_loop", {"id": "l-1", "text": "wire the session /continue caller"})
    led.append("open_loop", {"id": "l-2", "text": "temporary loop"})
    led.append("open_loop", {"id": "l-2", "status": "closed"})
    led.append("changed_path", {"path": "src/feature.py"})
    led.append("changed_path", {"path": "tests/test_feature.py"})
    led.append("verification", {"id": "v-1", "command": "pytest -q", "status": "failed"})
    led.append("verification", {"id": "v-2", "command": "black --check", "status": "passed"})
    led.append("delegate", {"id": "sub-1", "child_ref": "task-child-1"})
    led.append("delegate", {"id": "sub-2", "child_ref": "task-child-2"})
    led.append("return", {"id": "sub-2", "ref": "artifact:task-child-2"})
    led.append("operator_input", {"text": EARLIER_INPUT})
    led.append("operator_input", {"text": LATEST_INPUT})
    led.append("invocation", {"episode": 1})
    led.snapshot(referenced_digests={"evaluation_ledger": "abc"})
    return led


def _section(seed: str, heading: str) -> str:
    """The body of the ``## <heading>`` section (up to the next ``## ``)."""
    marker = f"## {heading}"
    assert seed.count(marker) == 1, heading
    body = seed.split(marker, 1)[1]
    return body.split("\n## ", 1)[0]


def _prose_seed(repo: Path) -> str:
    """Today's prose seed for TASK (no ledger involvement at all)."""
    _, seed = resolve_continuation(repo, TASK)
    return seed


# ---------------------------------------------------------------------------
# Armed + clean ledger → the seed is built from the snapshot
# ---------------------------------------------------------------------------


class TestArmedRehydrates:
    def test_seed_from_ledger_not_prose(self, repo: Path) -> None:
        _write_artifact(repo)
        _build_ledger(repo)
        warnings: list[dict] = []
        task_id, seed = resolve_continuation(repo, TASK, agents_armed=True, warnings=warnings)
        assert task_id == TASK
        assert warnings == []
        for heading in PROSE_HEADINGS:
            assert heading not in seed
        # Ledger facts are all present.
        assert REQUEST in seed
        assert LATEST_INPUT in seed
        assert "stdlib only, no new base deps" in seed
        assert "tests/test_feature.py passes" in seed
        assert "no prose recap headings in seed" in seed
        assert "src/feature.py" in seed and "tests/test_feature.py" in seed
        assert "wire the session /continue caller" in seed
        assert "temporary loop" not in seed  # closed loop dropped by replay
        assert "sub-1" in seed and "task-child-1" in seed
        delegations = _section(seed, "Open delegations")
        assert "sub-1" in delegations and "sub-2" not in delegations  # returned → not open
        assert "pytest -q" in seed and "failed" in seed
        assert "open an issue for the docs" in seed
        assert "rehydrate from the ledger, not prose" in seed

    def test_authority_flags_and_digest_rendered(self, repo: Path) -> None:
        _write_artifact(repo)
        led = _build_ledger(repo)
        snap = led.derive()
        _, seed = resolve_continuation(repo, TASK, agents_armed=True)
        assert snap.authority_digest in seed
        assert "no_pr: true" in seed
        assert "mode: build" in seed
        assert "role: worker" in seed

    def test_latest_operator_input_outranks_summaries(self, repo: Path) -> None:
        _write_artifact(repo)
        _build_ledger(repo)
        _, seed = resolve_continuation(repo, TASK, agents_armed=True)
        assert EARLIER_INPUT not in seed  # only the LATEST operator input is carried
        pos_input = seed.index(LATEST_INPUT)
        for section in (
            "Authority",
            "Constraints",
            "Acceptance",
            "Changed paths",
            "Verification",
            "Open loops",
            "Open delegations",
            "Promised follow-ups",
        ):
            assert section in seed, section
            assert pos_input < seed.index(section), section

    def test_request_verbatim_from_ledger_text(self, repo: Path) -> None:
        """The operator_request event's verbatim ``text`` outranks the artifact's copy."""
        _write_artifact(repo)
        led = TaskLedger(ledger_path(repo, TASK), TASK)
        led.append("operator_request", {"ref": "message:m-0", "text": "  exact  spacing\n\nkept  "})
        _, seed = resolve_continuation(repo, TASK, agents_armed=True)
        assert "  exact  spacing\n\nkept  " in seed

    def test_request_falls_back_to_artifact_when_ledger_carries_only_a_ref(
        self, repo: Path
    ) -> None:
        _write_artifact(repo)
        led = TaskLedger(ledger_path(repo, TASK), TASK)
        led.append("operator_request", {"ref": "message:m-0"})
        _, seed = resolve_continuation(repo, TASK, agents_armed=True)
        assert REQUEST in seed
        assert "message:m-0" in seed

    def test_rehydrated_snapshot_equals_pre_cut(self, repo: Path) -> None:
        """0 lost items: the replay after the cut equals the snapshot before it."""
        _write_artifact(repo)
        led = _build_ledger(repo)
        pre_cut: TaskSnapshot = led.derive()
        # "The cut": the writer is gone; a fresh reader rehydrates from disk.
        rehydrated = rehydrate_snapshot(repo, TASK)
        assert rehydrated.changed_paths == pre_cut.changed_paths
        assert rehydrated.open_loops == pre_cut.open_loops
        assert rehydrated.acceptance == pre_cut.acceptance
        assert rehydrated.authority_digest == pre_cut.authority_digest
        assert rehydrated.state_digest == pre_cut.state_digest
        assert len(rehydrated.changed_paths) == 2
        assert {loop["id"] for loop in rehydrated.open_loops} == {"l-1", "sub-1"}
        assert len(rehydrated.acceptance) == 2

    def test_every_pre_cut_item_is_in_the_seed(self, repo: Path) -> None:
        _write_artifact(repo)
        led = _build_ledger(repo)
        pre_cut = led.derive()
        _, seed = resolve_continuation(repo, TASK, agents_armed=True)
        for path in pre_cut.changed_paths:
            assert path in seed
        for loop in pre_cut.open_loops:
            assert str(loop.get("text") or loop.get("child_ref")) in seed
        for acc in pre_cut.acceptance:
            assert acc["text"] in seed
        for con in pre_cut.constraints:
            assert con["text"] in seed

    def test_build_ledger_seed_is_deterministic(self, repo: Path) -> None:
        _build_ledger(repo)
        snap = read_ledger(ledger_path(repo, TASK)).snapshot
        a = build_ledger_seed(snap, request=REQUEST, latest_input=LATEST_INPUT)
        b = build_ledger_seed(snap, request=REQUEST, latest_input=LATEST_INPUT)
        assert a == b
        assert a.startswith("## Original request")

    def test_no_pr_false_and_absent_sections_are_honest(self, repo: Path) -> None:
        _write_artifact(repo)
        led = TaskLedger(ledger_path(repo, TASK), TASK)
        led.append("operator_request", {"ref": "message:m-0", "no_pr": False})
        _, seed = resolve_continuation(repo, TASK, agents_armed=True)
        assert "no_pr: false" in seed
        assert "Promised follow-ups" not in seed  # nothing tagged → section omitted
        assert "_none_" in seed  # empty collections say so, never invent


# ---------------------------------------------------------------------------
# Fail closed: every defect → warning + the prose recap, never an exception
# ---------------------------------------------------------------------------


def _corrupt_truncated_tail(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(text[:-7], encoding="utf-8")  # drops the trailing newline + some bytes


def _corrupt_bumped_schema(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").split("\n")
    header = json.loads(lines[0])
    header["version"] = LEDGER_SCHEMA_VERSION + 1
    lines[0] = json.dumps(header, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines), encoding="utf-8")


def _corrupt_digest_mismatch(path: Path) -> None:
    """Edit an event BEFORE the snapshot in place: seq/task_id intact, replay
    digest no longer matches what the snapshot event recorded."""
    lines = path.read_text(encoding="utf-8").split("\n")
    for i, line in enumerate(lines):
        if '"kind":"changed_path"' in line and "src/feature.py" in line:
            lines[i] = line.replace("src/feature.py", "src/tampered.py")
            break
    else:  # pragma: no cover - fixture guard
        raise AssertionError("fixture has no changed_path line to tamper")
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.mark.parametrize(
    ("corrupt", "reason_fragment"),
    [
        (_corrupt_truncated_tail, "torn tail"),
        (_corrupt_bumped_schema, "schema version"),
        (_corrupt_digest_mismatch, "digest mismatch"),
    ],
)
class TestUnreadableFallsClosed:
    def test_warning_plus_prose(self, repo: Path, corrupt, reason_fragment: str) -> None:
        _write_artifact(repo)
        prose = _prose_seed(repo)
        _build_ledger(repo)
        path = ledger_path(repo, TASK)
        corrupt(path)
        warnings: list[dict] = []
        task_id, seed = resolve_continuation(repo, TASK, agents_armed=True, warnings=warnings)
        assert task_id == TASK
        assert seed == prose
        assert len(warnings) == 1
        w = warnings[0]
        assert w["kind"] == "continuation-ledger"
        assert reason_fragment in w["detail"]
        assert "prose" in w["detail"]
        assert w["ledger"] == str(path)

    def test_no_warnings_list_means_nothing_recorded(
        self, repo: Path, corrupt, reason_fragment: str
    ) -> None:
        _write_artifact(repo)
        prose = _prose_seed(repo)
        _build_ledger(repo)
        corrupt(ledger_path(repo, TASK))
        _, seed = resolve_continuation(repo, TASK, agents_armed=True)
        assert seed == prose


# ---------------------------------------------------------------------------
# Unarmed / absent
# ---------------------------------------------------------------------------


class TestUnarmedAndAbsent:
    def test_unarmed_with_ledger_present_ignores_and_warns(self, repo: Path) -> None:
        _write_artifact(repo)
        prose = _prose_seed(repo)
        _build_ledger(repo)
        warnings: list[dict] = []
        _, seed = resolve_continuation(repo, TASK, warnings=warnings)
        assert seed == prose
        assert len(warnings) == 1
        assert warnings[0]["kind"] == "continuation-ledger"
        assert "ignored" in warnings[0]["detail"]
        assert "not armed" in warnings[0]["detail"]
        assert warnings[0]["ledger"] == str(ledger_path(repo, TASK))

    def test_unarmed_default_signature_is_byte_identical(self, repo: Path) -> None:
        _write_artifact(repo)
        prose = _prose_seed(repo)
        _build_ledger(repo)
        assert resolve_continuation(repo, TASK) == (TASK, prose)

    def test_no_ledger_armed_is_prose_with_no_warning(self, repo: Path) -> None:
        _write_artifact(repo)
        prose = _prose_seed(repo)
        warnings: list[dict] = []
        _, seed = resolve_continuation(repo, TASK, agents_armed=True, warnings=warnings)
        assert seed == prose
        assert warnings == []

    def test_no_ledger_unarmed_is_prose_with_no_warning(self, repo: Path) -> None:
        _write_artifact(repo)
        warnings: list[dict] = []
        _, seed = resolve_continuation(repo, TASK, warnings=warnings)
        assert "## Continuation State" in seed
        assert warnings == []


# ---------------------------------------------------------------------------
# The artifact stays the wrong-run guard's source
# ---------------------------------------------------------------------------


class TestArtifactStaysTheGuard:
    def test_ok_artifact_refused_even_with_ledger(self, repo: Path) -> None:
        _write_artifact(repo, status=OK)
        _build_ledger(repo)
        with pytest.raises(ContinuationError, match="finished ok"):
            resolve_continuation(repo, TASK, agents_armed=True)

    def test_missing_artifact_refused_even_with_ledger(self, repo: Path) -> None:
        _build_ledger(repo)
        with pytest.raises(ContinuationError, match="no artifact"):
            resolve_continuation(repo, TASK, agents_armed=True)

    def test_ledger_for_a_different_task_is_not_used(self, repo: Path) -> None:
        _write_artifact(repo)
        _build_ledger(repo, task_id="task-other")
        warnings: list[dict] = []
        _, seed = resolve_continuation(repo, TASK, agents_armed=True, warnings=warnings)
        assert "## Continuation State" in seed
        assert warnings == []

    def test_ok_with_allow_completed_rehydrates(self, repo: Path) -> None:
        _write_artifact(repo, status=OK)
        _build_ledger(repo)
        _, seed = resolve_continuation(repo, TASK, allow_completed=True, agents_armed=True)
        assert "## Continuation State" not in seed
        assert LATEST_INPUT in seed

    def test_rehydrate_snapshot_missing_ledger_returns_none(self, repo: Path) -> None:
        assert rehydrate_snapshot(repo, TASK) is None

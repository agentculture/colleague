"""``work --continue`` re-applies the recorded rung, loudly on mismatch (t8, c32/h19).

Pins the v4-cutover trap closure: continuing a run whose artifact recorded an
acting-seat rung re-applies THAT rung to the acting seat of the new episode —
an explicit ``--effort`` on the continue invocation wins over it — and when
the recorded rung differs from what env/config would currently resolve, a
``TaskResult.warnings`` entry names both values and the source artifact.
Equal -> no warning. A pre-#476 artifact (no ``effort`` block, no
``finish_states[].reasoning_effort``) -> nothing to re-apply, no warning.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from colleague.cli._commands._listing import reapply_recorded_effort
from colleague.cli._commands._work_support import _stamp_run_metadata
from colleague.cli._commands._work_task import _build_task
from colleague.cli._commands.session import SessionIO, _Session
from colleague.config import EngineConfig
from colleague.continuation import (
    EFFORT_WARNING_KIND,
    recorded_acting_effort,
)
from colleague.contract import OK, TaskResult


def _write_artifact(
    repo: Path,
    task_id: str,
    *,
    effort_block: str | None = None,
    finish_effort: str | None = None,
    status: str = "incomplete",
) -> Path:
    coll = repo / ".colleague"
    coll.mkdir(exist_ok=True)
    data: dict = {
        "task_id": task_id,
        "status": status,
        "summary": "stopped early",
        "changed_files": [],
        "steps": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "stats": {"request": "the original request"},
    }
    if effort_block is not None:
        data["effort"] = {"main": effort_block}
    if finish_effort is not None:
        data["finish_states"] = [
            {
                "seat": "main",
                "kind": "substantive",
                "content": "x",
                "reasoning_effort": finish_effort,
            }
        ]
    path = coll / f"{task_id}.json"
    path.write_text(json.dumps(data))
    (coll / "last_work").write_text(f"{task_id}\n")
    return path


# ── recorded_acting_effort: where the rung is read from ─────────────────────


class TestRecordedActingEffort:
    def test_effort_block_wins_over_finish_record(self, tmp_path: Path) -> None:
        path = _write_artifact(tmp_path, "t1", effort_block="medium", finish_effort="high")
        assert recorded_acting_effort(tmp_path, "t1") == ("medium", path)

    def test_finish_record_fallback(self, tmp_path: Path) -> None:
        path = _write_artifact(tmp_path, "t2", finish_effort="high")
        assert recorded_acting_effort(tmp_path, "t2") == ("high", path)

    def test_pre_476_artifact_has_nothing_to_reapply(self, tmp_path: Path) -> None:
        path = _write_artifact(tmp_path, "t3")
        assert recorded_acting_effort(tmp_path, "t3") == (None, path)

    def test_missing_artifact(self, tmp_path: Path) -> None:
        (tmp_path / ".colleague").mkdir()
        assert recorded_acting_effort(tmp_path, "nope") == (None, None)

    def test_unknown_rung_reads_as_absent(self, tmp_path: Path) -> None:
        path = _write_artifact(tmp_path, "t4", effort_block="turbo")
        assert recorded_acting_effort(tmp_path, "t4") == (None, path)

    def test_corrupt_artifact_never_raises(self, tmp_path: Path) -> None:
        coll = tmp_path / ".colleague"
        coll.mkdir()
        (coll / "bad.json").write_text("{not json")
        rung, path = recorded_acting_effort(tmp_path, "bad")
        assert rung is None
        assert path is not None


# ── reapply_recorded_effort: applied + loud only on mismatch ────────────────


class TestReapplyRecordedEffort:
    def test_mismatch_reapplies_and_warns_with_both_values(self, tmp_path: Path) -> None:
        path = _write_artifact(tmp_path, "m1", effort_block="medium")
        config = EngineConfig.resolve(model="m")  # default resolves cortex -> "off" (row 77, d1)
        warnings: list[dict] = []
        warning = reapply_recorded_effort(config, tmp_path, "m1", warnings=warnings)
        assert config.reasoning_effort_seats["cortex"] == "medium"
        assert warning is not None
        assert warnings == [warning]
        assert warning["kind"] == EFFORT_WARNING_KIND
        assert warning["recorded"] == "medium"
        assert warning["resolved"] == "off"
        assert warning["artifact"] == str(path)
        assert "medium" in warning["detail"]
        assert "off" in warning["detail"]
        assert str(path) in warning["detail"]
        # The warning is staged for the run's TaskResult (drained by
        # _stamp_run_metadata).
        assert config.continuation_warnings == [warning]

    def test_equal_reapplies_silently(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "m2", effort_block="off")
        config = EngineConfig.resolve(model="m")
        warnings: list[dict] = []
        assert reapply_recorded_effort(config, tmp_path, "m2", warnings=warnings) is None
        assert warnings == []
        assert getattr(config, "continuation_warnings", []) == []
        assert config.reasoning_effort_seats["cortex"] == "off"

    def test_pre_476_artifact_is_a_no_op(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "m3")
        config = EngineConfig.resolve(model="m")
        warnings: list[dict] = []
        assert reapply_recorded_effort(config, tmp_path, "m3", warnings=warnings) is None
        assert warnings == []
        assert config.reasoning_effort_seats == {}

    def test_none_config_is_tolerated(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "m4", effort_block="medium")
        assert reapply_recorded_effort(None, tmp_path, "m4") is None

    def test_worker_armed_applies_to_worker_seat(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "m5", effort_block="medium")
        config = EngineConfig.resolve(model="m")
        config.worker = object()  # the acting seat becomes "worker"
        reapply_recorded_effort(config, tmp_path, "m5")
        assert config.reasoning_effort_seats["worker"] == "medium"


# ── the CLI continue path: call order makes the precedence explicit ─────────


def _make_ns(repo: Path, *, continue_ref: str, effort: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        instruction=[],
        repo=str(repo),
        engine="mock",
        command_name=None,
        attach=[],
        continue_ref=continue_ref,
        effort=effort,
        model=None,
    )


class TestCliContinuePrecedence:
    def test_no_flag_reapplies_recorded_rung(self, tmp_path: Path) -> None:
        path = _write_artifact(tmp_path, "c1", effort_block="medium")
        config = EngineConfig.resolve(model="m")
        args = _make_ns(tmp_path, continue_ref="c1")
        task = _build_task(args, tmp_path, "mock", config)
        assert "CONTINUING work item c1" in task.instruction
        assert config.reasoning_effort_seats["cortex"] == "medium"
        assert config.continuation_warnings[0]["artifact"] == str(path)

    def test_explicit_effort_flag_wins(self, tmp_path: Path) -> None:
        """maybe_list_and_apply applies --effort first; the continue re-apply
        then stands down entirely (explicit wins, c25) — no clobber, no warning."""
        from colleague.cli._commands._listing import maybe_list_and_apply

        _write_artifact(tmp_path, "c2", effort_block="medium")
        config = EngineConfig.resolve(model="m")
        args = _make_ns(tmp_path, continue_ref="c2", effort="high")
        assert maybe_list_and_apply(args, config, tmp_path, json_mode=False) is None
        _build_task(args, tmp_path, "mock", config)
        assert config.reasoning_effort_seats["cortex"] == "high"
        assert getattr(config, "continuation_warnings", []) == []

    def test_recorded_equal_no_warning(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "c3", effort_block="off")
        config = EngineConfig.resolve(model="m")
        args = _make_ns(tmp_path, continue_ref="c3")
        _build_task(args, tmp_path, "mock", config)
        assert getattr(config, "continuation_warnings", []) == []

    def test_pre_476_artifact_unchanged(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "c4")
        config = EngineConfig.resolve(model="m")
        args = _make_ns(tmp_path, continue_ref="c4")
        _build_task(args, tmp_path, "mock", config)
        assert config.reasoning_effort_seats == {}
        assert getattr(config, "continuation_warnings", []) == []


# ── the warning lands on TaskResult.warnings ────────────────────────────────


def test_stamp_run_metadata_drains_continuation_warnings() -> None:
    config = EngineConfig.resolve(model="m")
    warning = {"kind": EFFORT_WARNING_KIND, "detail": "d", "recorded": "medium"}
    config.continuation_warnings = [warning]
    result = TaskResult(task_id="x", status=OK, summary="s")
    _stamp_run_metadata(
        result, config=config, command_name=None, mode=None, continued_from="old", chain=None
    )
    assert warning in result.warnings
    # Drained: a second run on the same (session) config never re-stamps it.
    result2 = TaskResult(task_id="y", status=OK, summary="s")
    _stamp_run_metadata(
        result2, config=config, command_name=None, mode=None, continued_from=None, chain=None
    )
    assert warning not in result2.warnings


# ── the session /continue leg shares the path ───────────────────────────────


class _Harness:
    def __init__(self, repo: Path) -> None:
        self.calls: list[dict] = []
        self.errors: list[str] = []

        def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
            self.calls.append(dict(kwargs))
            return (TaskResult(task_id="new", status=OK, summary="done"), repo / "a.json")

        self.session = _Session(
            repo=repo,
            engine_name="mock",
            open_pr=False,
            base="main",
            config=EngineConfig.resolve(model="m"),
            json_mode=False,
            view="markdown",
            io=SessionIO(out=lambda *a, **k: None, err=self.errors.append),
            work_fn=_work_fn,
        )


class TestSessionContinue:
    def test_slash_continue_reapplies_and_warns(self, tmp_path: Path) -> None:
        path = _write_artifact(tmp_path, "s1", effort_block="medium")
        h = _Harness(tmp_path)
        assert h.session._slash("/continue") is True
        assert h.session.config.reasoning_effort_seats["cortex"] == "medium"
        assert any(str(path) in e for e in h.errors)
        assert len(h.calls) == 1

    def test_explicit_session_effort_wins(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "s2", effort_block="medium")
        h = _Harness(tmp_path)
        assert h.session._slash("/effort high") is True
        assert h.session._slash("/continue") is True
        assert h.session.config.reasoning_effort_seats["cortex"] == "high"
        assert getattr(h.session.config, "continuation_warnings", []) == []

    def test_equal_recorded_rung_is_silent(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "s3", effort_block="off")
        h = _Harness(tmp_path)
        assert h.session._slash("/continue") is True
        assert not any("recorded" in e for e in h.errors)


# ---------------------------------------------------------------------------
# review-2 finding: a staged warning is cleared even when the engine raises
# ---------------------------------------------------------------------------


def test_staged_warning_cleared_when_engine_raises(tmp_path, monkeypatch) -> None:
    """If _drive_engine raises, the finally block clears the staged warning so a
    long-lived session config never stamps it onto an unrelated later run."""
    import subprocess

    from colleague.cli._commands import work as work_mod
    from colleague.contract import Task

    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    # cwd-scoped identity: CI runners have no global git user (exit-128 otherwise).
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "x"], check=True)

    config = EngineConfig.resolve()
    config.continuation_warnings = [{"kind": "continuation-effort", "detail": "stale"}]

    def _boom(**kwargs):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(work_mod, "_drive_engine", _boom)
    try:
        work_mod.execute_work(
            repo=repo,
            engine_name="mock",
            task=Task.new(str(repo), "t"),
            open_pr=False,
            base="main",
            config=config,
        )
    except RuntimeError:
        pass
    assert getattr(config, "continuation_warnings", None) in (None, [])

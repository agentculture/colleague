"""Continuation propagates the original brief (c22/h15/h3 of
``docs/specs/2026-09-01-small-fixes-then-effort-balance.md``).

``work --continue`` builds the resumed run's ``Task.instruction`` from a
SYNTHESIZED SEED (preamble + continuation record + original request). Left
alone, the loop's own task-text stamp would record that seed as the resumed
artifact's ``TaskResult.task_text`` — never the brief a human actually wrote,
breaking reproducibility (challenge finding c22). This module pins the fix:

* :func:`colleague.continuation.prior_task_text` reads the prior artifact's
  own ``task_text`` field (the propagated original, however many times the
  chain of continuations runs);
* :func:`colleague.tasktext.apply_continuation_task_text` overrides the
  resumed result's ``task_text`` with it, at the same seam
  ``TaskResult.continued_from`` is stamped;
* the acceptance test drives the real CLI seam end to end (``_build_task`` +
  ``execute_work`` on the ``mock`` engine) and asserts the resumed artifact's
  ``task_text`` equals the ORIGINAL brief verbatim — never the synthesized seed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from colleague import tasktext
from colleague.cli._commands import work as work_mod
from colleague.cli._commands._work_task import _build_task
from colleague.config import EngineConfig
from colleague.continuation import prior_task_text
from colleague.contract import OK, TaskResult

_ORIGINAL_BRIEF = "implement the widget exporter exactly as described in issue #999"


def _write_artifact(
    repo: Path,
    task_id: str,
    *,
    task_text: str | None = "OMIT",
    status: str = "incomplete",
) -> Path:
    """A minimal hand-written artifact — ``task_text`` present/omitted/absent
    per *task_text* (``"OMIT"`` sentinel skips the key entirely, mirroring a
    pre-#481 artifact; ``None`` writes the field as JSON null)."""
    coll = repo / ".colleague"
    coll.mkdir(exist_ok=True)
    data: dict = {
        "task_id": task_id,
        "status": status,
        "summary": "stopped early",
        "changed_files": [],
        "steps": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "stats": {"request": _ORIGINAL_BRIEF},
    }
    if task_text != "OMIT":
        data["task_text"] = task_text
    path = coll / f"{task_id}.json"
    path.write_text(json.dumps(data))
    (coll / "last_work").write_text(f"{task_id}\n")
    return path


def _make_ns(repo: Path, *, continue_ref: str) -> argparse.Namespace:
    return argparse.Namespace(
        instruction=[],
        repo=str(repo),
        engine="mock",
        command_name=None,
        attach=[],
        continue_ref=continue_ref,
        effort=None,
        model=None,
    )


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    # cwd-scoped identity: CI runners have no global git user (exit-128 otherwise).
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "x"], check=True)
    return repo


# ---------------------------------------------------------------------------
# colleague.continuation.prior_task_text — the read half
# ---------------------------------------------------------------------------


def test_prior_task_text_reads_the_prior_artifacts_field(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "p1", task_text=_ORIGINAL_BRIEF)
    assert prior_task_text(tmp_path, "p1") == _ORIGINAL_BRIEF


def test_prior_task_text_none_when_prior_artifact_carries_none(tmp_path: Path) -> None:
    """A pre-#481 artifact (or one recorded with the knob off) carries no
    ``task_text`` — propagation yields ``None``, never the artifact's request."""
    _write_artifact(tmp_path, "p2", task_text="OMIT")
    assert prior_task_text(tmp_path, "p2") is None


def test_prior_task_text_none_when_field_is_json_null(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "p3", task_text=None)
    assert prior_task_text(tmp_path, "p3") is None


def test_prior_task_text_none_for_missing_artifact(tmp_path: Path) -> None:
    (tmp_path / ".colleague").mkdir()
    assert prior_task_text(tmp_path, "nope") is None


def test_prior_task_text_none_for_corrupt_artifact(tmp_path: Path) -> None:
    coll = tmp_path / ".colleague"
    coll.mkdir()
    (coll / "p4.json").write_text("{not json")
    assert prior_task_text(tmp_path, "p4") is None


# ---------------------------------------------------------------------------
# colleague.tasktext.apply_continuation_task_text — the stamp half
# ---------------------------------------------------------------------------


def test_apply_is_a_no_op_when_not_a_continuation() -> None:
    result = TaskResult(task_id="x", status=OK, summary="s", task_text="whatever the loop set")
    tasktext.apply_continuation_task_text(
        result, continued_from=None, continuation_task_text=_ORIGINAL_BRIEF
    )
    assert result.task_text == "whatever the loop set"


def test_apply_overrides_the_seed_with_the_propagated_original() -> None:
    result = TaskResult(task_id="x", status=OK, summary="s", task_text="preamble + seed text")
    tasktext.apply_continuation_task_text(
        result, continued_from="prior-id", continuation_task_text=_ORIGINAL_BRIEF
    )
    assert result.task_text == _ORIGINAL_BRIEF
    assert result.task_text != "preamble + seed text"


def test_apply_clears_task_text_when_prior_had_none() -> None:
    """A seed is never a brief: with nothing honest to propagate, task_text is
    cleared rather than left at the synthesized seed the loop stamped."""
    result = TaskResult(task_id="x", status=OK, summary="s", task_text="preamble + seed text")
    tasktext.apply_continuation_task_text(
        result, continued_from="prior-id", continuation_task_text=None
    )
    assert result.task_text is None


def test_apply_respects_the_off_knob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_RECORD_TASK_TEXT", "0")
    result = TaskResult(task_id="x", status=OK, summary="s", task_text=None)
    tasktext.apply_continuation_task_text(
        result, continued_from="prior-id", continuation_task_text=_ORIGINAL_BRIEF
    )
    assert result.task_text is None


# ---------------------------------------------------------------------------
# Acceptance 1: end-to-end via the CLI seam (mock engine) — the resumed
# artifact's task_text equals the ORIGINAL brief verbatim, never the seed.
# ---------------------------------------------------------------------------


def test_work_continue_records_the_original_brief_not_the_seed(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _write_artifact(repo, "prior-1", task_text=_ORIGINAL_BRIEF, status="incomplete")

    config = EngineConfig.resolve(model="m")
    args = _make_ns(repo, continue_ref="prior-1")
    task = _build_task(args, repo, "mock", config)

    # Sanity: the dispatched instruction IS the synthesized seed, not the brief.
    assert task.instruction != _ORIGINAL_BRIEF
    assert "CONTINUING" in task.instruction or "Original request" in task.instruction

    result, _artifact_path = work_mod.execute_work(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
        continued_from=getattr(args, "_continued_from_resolved", None),
        continuation_task_text=getattr(args, "_continuation_task_text_resolved", None),
    )

    assert result.continued_from == "prior-1"
    assert result.task_text == _ORIGINAL_BRIEF
    assert result.task_text != task.instruction


def test_work_continue_records_nothing_when_prior_artifact_has_no_task_text(
    tmp_path: Path,
) -> None:
    """A pre-#481 artifact (or one recorded with the knob off) has no
    task_text to propagate — the resumed run records nothing, never the seed."""
    repo = _git_repo(tmp_path)
    _write_artifact(repo, "prior-2", task_text="OMIT", status="incomplete")

    config = EngineConfig.resolve(model="m")
    args = _make_ns(repo, continue_ref="prior-2")
    task = _build_task(args, repo, "mock", config)

    result, _artifact_path = work_mod.execute_work(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
        continued_from=getattr(args, "_continued_from_resolved", None),
        continuation_task_text=getattr(args, "_continuation_task_text_resolved", None),
    )

    assert result.continued_from == "prior-2"
    assert result.task_text is None
    assert "task_text" not in result.to_dict()


def test_work_continue_knob_off_records_no_task_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_RECORD_TASK_TEXT", "0")
    repo = _git_repo(tmp_path)
    _write_artifact(repo, "prior-3", task_text=_ORIGINAL_BRIEF, status="incomplete")

    config = EngineConfig.resolve(model="m")
    args = _make_ns(repo, continue_ref="prior-3")
    task = _build_task(args, repo, "mock", config)

    result, _artifact_path = work_mod.execute_work(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
        continued_from=getattr(args, "_continued_from_resolved", None),
        continuation_task_text=getattr(args, "_continuation_task_text_resolved", None),
    )

    assert result.task_text is None
    assert "task_text" not in result.to_dict()


def test_ordinary_run_is_unaffected(tmp_path: Path) -> None:
    """A non-continuation run keeps recording task.instruction verbatim —
    byte-identical to the pre-fix behaviour."""
    repo = _git_repo(tmp_path)
    config = EngineConfig.resolve(model="m")
    args = argparse.Namespace(
        instruction=["do", "a", "thing"],
        repo=str(repo),
        engine="mock",
        command_name=None,
        attach=[],
        continue_ref=None,
        effort=None,
        model=None,
    )
    task = _build_task(args, repo, "mock", config)
    result, _artifact_path = work_mod.execute_work(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
    )
    assert result.continued_from is None
    assert result.task_text == "do a thing"


# ---------------------------------------------------------------------------
# Chain path (--until-done): the original brief rides every episode.
# ---------------------------------------------------------------------------


def test_chain_episode_dispatch_threads_continuation_task_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``execute_work_chain``'s initial episode call carries the SAME
    continuation_task_text the CLI seam resolved for it."""
    from colleague.cli._commands import _work_chain
    from colleague.contract import Task

    repo = _git_repo(tmp_path)
    _write_artifact(repo, "prior-c1", task_text=_ORIGINAL_BRIEF, status="incomplete")

    captured: list[dict] = []
    real_execute_work = work_mod.execute_work

    def _spy(**kwargs):
        captured.append(kwargs)
        kwargs = dict(kwargs)
        kwargs["chain"] = None
        return real_execute_work(**kwargs)

    monkeypatch.setattr(work_mod, "execute_work", _spy)

    config = EngineConfig.resolve(model="m")
    task = Task.new(str(repo), "seed text for the chain")

    result, _path = _work_chain.execute_work_chain(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
        cap=1,
        continued_from="prior-c1",
        continuation_task_text=prior_task_text(repo, "prior-c1"),
    )

    assert captured, "execute_work was never dispatched"
    assert captured[0]["continuation_task_text"] == _ORIGINAL_BRIEF
    assert result.task_text == _ORIGINAL_BRIEF

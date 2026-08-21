"""#411 t19 — ledger location on isolated runs + the finished-ledger reap.

Criterion 1: an ARMED run whose ``Task.repo_path`` is a throwaway worktree
writes ``.colleague/ledger/<id>.jsonl`` under the OPERATOR repo
(``task.flight_repo_path``), never inside the worktree, and the operator repo's
``git status`` stays clean (the repo's own ``/.colleague/*`` ignore rule).

Criterion 2: ``handoff.reap_finished_ledgers`` + ``colleague clean`` remove a
ledger ONLY when its task's artifact is final (ok / incomplete / error) or the
task is orphaned (dead liveness marker / an iso worktree the clean just reaped);
a live task's ledger (``active_task_ids`` or an alive marker) is never removed;
``--dry-run`` reports without removing; unrelated files are untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest

from colleague import artifact, handoff, loop, worktrees
from colleague.agents.state.ledger import ledger_path
from colleague.cli._commands.clean import cmd_clean
from colleague.config import EngineConfig
from colleague.contract import ERROR, INCOMPLETE, OK, Task, TaskResult
from colleague.loop import ContextControls, ModelResponse, ToolCall

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=check
    )


#: The repo's own ignore rule for colleague bookkeeping (``.gitignore``: everything
#: under ``.colleague/`` except the shareable commands/skills dirs).
_IGNORE_RULES = "/.colleague/*\n!/.colleague/commands/\n!/.colleague/skills/\n"


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (repo / ".gitignore").write_text(_IGNORE_RULES, encoding="utf-8")
    _git(repo, "add", "README.md", ".gitignore")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def _dead_pid() -> int:
    proc = subprocess.Popen(["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait()
    return proc.pid


def _write_marker(repo: Path, task_id: str, pid: int) -> None:
    marker = worktrees.iso_liveness_path(str(repo), task_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(pid), encoding="utf-8")


def _write_ledger(repo: Path, task_id: str) -> Path:
    path = ledger_path(repo, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema":"colleague.task-ledger","version":1,"task_id":"x"}\n')
    return path


def _write_artifact(repo: Path, task_id: str, status: str = OK) -> Path:
    result = TaskResult(task_id=task_id, status=status, summary="done")
    return artifact.write(result, artifact.artifact_dir(repo))


def _clean_args(repo: Path, *, dry_run: bool, json_mode: bool = True) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo), dry_run=dry_run, merged=False, older_than=None, base="main", json=json_mode
    )


# ---------------------------------------------------------------------------
# criterion 1 — an isolated armed run ledgers at the OPERATOR repo
# ---------------------------------------------------------------------------


def test_isolated_armed_run_ledgers_at_operator_repo_and_git_status_stays_clean(
    git_repo: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    operator = git_repo
    (operator / ".colleague").mkdir()
    (operator / ".colleague" / "config.json").write_text(
        json.dumps({"agents": True}), encoding="utf-8"
    )
    cfg = EngineConfig.resolve(repo_path=operator, discover_lobes=False)
    assert cfg.agents is True
    # the throwaway worktree stand-in: a DIFFERENT directory than the operator repo
    worktree = tmp_path / "iso-worktree"
    worktree.mkdir()
    (worktree / "README.md").write_text("# wt\n", encoding="utf-8")
    task = Task.new(str(worktree), "list the tree", flight_repo_path=str(operator))

    script = iter(
        [
            ModelResponse(tool_calls=[ToolCall("l", "list_dir", {"path": "."})]),
            ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "done"})]),
        ]
    )
    result = loop.run(
        lambda _m: next(script), task, max_steps=4, context=ContextControls.from_config(cfg)
    )
    assert result.status == OK

    expected = ledger_path(operator, task.id)
    assert result.agents["ledger_path"] == str(expected)
    assert expected.is_file()  # under the OPERATOR repo …
    assert not (worktree / ".colleague").exists()  # … never inside the worktree
    # the operator tree is untouched: the repo's own ignore rule swallows the ledger
    assert _git(operator, "status", "--porcelain").stdout == ""
    assert _git(operator, "check-ignore", "-q", str(expected), check=False).returncode == 0


def test_ledger_dir_matches_the_ledger_path_helper(tmp_path: Path) -> None:
    assert handoff.ledger_dir(tmp_path) == ledger_path(tmp_path, "any").parent


# ---------------------------------------------------------------------------
# criterion 2 — reap_finished_ledgers
# ---------------------------------------------------------------------------


def test_finished_ok_task_ledger_is_reaped(git_repo: Path) -> None:
    led = _write_ledger(git_repo, "fin1")
    _write_artifact(git_repo, "fin1", status=OK)
    reaped = handoff.reap_finished_ledgers(git_repo)
    assert reaped == [str(led)]
    assert not led.exists()


@pytest.mark.parametrize("status", [INCOMPLETE, ERROR])
def test_resumable_task_ledger_is_kept_even_when_orphaned(git_repo: Path, status: str) -> None:
    """An incomplete/error artifact is a `work --continue` seed (#411 c35): its
    ledger survives clean — even with a dead marker or an explicit orphaned id."""
    led = _write_ledger(git_repo, "res1")
    _write_artifact(git_repo, "res1", status=status)
    _write_marker(git_repo, "res1", _dead_pid())
    assert handoff.reap_finished_ledgers(git_repo, orphaned_task_ids={"res1"}) == []
    assert led.exists()


def test_ledger_without_artifact_or_marker_is_kept(git_repo: Path) -> None:
    """No artifact yet + no liveness opinion = a run that may still be going
    (an in-place / non-isolated run never stamps a marker) — keep it."""
    led = _write_ledger(git_repo, "run1")
    assert handoff.reap_finished_ledgers(git_repo) == []
    assert led.exists()


def test_active_task_id_spares_a_finished_looking_ledger(git_repo: Path) -> None:
    led = _write_ledger(git_repo, "act1")
    _write_artifact(git_repo, "act1")  # e.g. a prior episode's artifact of a chained run
    assert handoff.reap_finished_ledgers(git_repo, active_task_ids={"act1"}) == []
    assert led.exists()


def test_alive_liveness_marker_spares_the_ledger(git_repo: Path) -> None:
    """The running-marker double: a marker naming THIS (alive) process wins over
    a terminal artifact — a live task's ledger is never removed."""
    led = _write_ledger(git_repo, "live1")
    _write_artifact(git_repo, "live1")
    _write_marker(git_repo, "live1", os.getpid())
    assert handoff.reap_finished_ledgers(git_repo) == []
    assert led.exists()


def test_dead_liveness_marker_marks_the_task_orphaned(git_repo: Path) -> None:
    led = _write_ledger(git_repo, "dead1")  # no artifact: the run crashed before writing one
    _write_marker(git_repo, "dead1", _dead_pid())
    assert handoff.reap_finished_ledgers(git_repo) == [str(led)]
    assert not led.exists()


def test_unparseable_marker_is_no_opinion_and_keeps_the_ledger(git_repo: Path) -> None:
    led = _write_ledger(git_repo, "odd1")
    marker = worktrees.iso_liveness_path(str(git_repo), "odd1")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("not-a-pid", encoding="utf-8")
    assert handoff.reap_finished_ledgers(git_repo) == []
    assert led.exists()


def test_orphaned_task_ids_reap_the_ledger(git_repo: Path) -> None:
    """The bridge from the iso-worktree reap (which clears the dead marker as it
    goes): the caller names the task ids it just found orphaned."""
    led = _write_ledger(git_repo, "orph1")
    assert handoff.reap_finished_ledgers(git_repo, orphaned_task_ids={"orph1"}) == [str(led)]
    assert not led.exists()


def test_orphaned_task_ids_never_beat_a_live_signal(git_repo: Path) -> None:
    led = _write_ledger(git_repo, "orph2")
    assert (
        handoff.reap_finished_ledgers(
            git_repo, active_task_ids={"orph2"}, orphaned_task_ids={"orph2"}
        )
        == []
    )
    assert led.exists()


def test_dry_run_reports_without_removing(git_repo: Path) -> None:
    led = _write_ledger(git_repo, "dry1")
    _write_artifact(git_repo, "dry1")
    assert handoff.reap_finished_ledgers(git_repo, dry_run=True) == [str(led)]
    assert led.exists()


def test_unreadable_or_empty_artifact_is_not_final(git_repo: Path) -> None:
    led_a = _write_ledger(git_repo, "bad1")
    (artifact.artifact_dir(git_repo) / "bad1.json").write_text("{not json", encoding="utf-8")
    led_b = _write_ledger(git_repo, "bad2")
    (artifact.artifact_dir(git_repo) / "bad2.json").write_text("", encoding="utf-8")
    assert handoff.reap_finished_ledgers(git_repo) == []
    assert led_a.exists()
    assert led_b.exists()


def test_unrelated_files_are_untouched(git_repo: Path) -> None:
    ldir = handoff.ledger_dir(git_repo)
    ldir.mkdir(parents=True)
    note = ldir / "notes.txt"
    note.write_text("keep me", encoding="utf-8")
    nested = ldir / "sub" / "fin9.jsonl"
    nested.parent.mkdir()
    nested.write_text("nested", encoding="utf-8")
    other = git_repo / ".colleague" / "fin9.jsonl"
    other.write_text("sibling", encoding="utf-8")
    _write_artifact(git_repo, "fin9")
    led = _write_ledger(git_repo, "fin9")
    assert handoff.reap_finished_ledgers(git_repo) == [str(led)]
    assert note.exists()
    assert nested.exists()
    assert other.exists()
    assert not led.exists()


def test_missing_ledger_dir_is_a_noop(git_repo: Path) -> None:
    assert handoff.reap_finished_ledgers(git_repo) == []
    assert handoff.reap_finished_ledgers(git_repo, dry_run=True) == []


def test_unlink_failure_is_reported_not_raised(git_repo: Path, monkeypatch) -> None:
    led = _write_ledger(git_repo, "fail1")
    _write_artifact(git_repo, "fail1")

    def boom(self, *a, **k):
        raise OSError("busy")

    monkeypatch.setattr(Path, "unlink", boom)
    assert handoff.reap_finished_ledgers(git_repo) == []
    assert led.exists()


# ---------------------------------------------------------------------------
# criterion 2 — the `colleague clean` verb
# ---------------------------------------------------------------------------


def test_clean_reaps_finished_ledger_and_spares_live_one(
    git_repo: Path, capsys: pytest.CaptureFixture
) -> None:
    done = _write_ledger(git_repo, "done1")
    _write_artifact(git_repo, "done1")
    live = _write_ledger(git_repo, "live2")
    _write_artifact(git_repo, "live2")
    _write_marker(git_repo, "live2", os.getpid())  # running-marker double
    pending = _write_ledger(git_repo, "pend1")  # no artifact, no marker

    assert cmd_clean(_clean_args(git_repo, dry_run=False)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ledgers"] == [str(done)]
    assert not done.exists()
    assert live.exists()
    assert pending.exists()


def test_clean_dry_run_reports_ledger_without_removing(
    git_repo: Path, capsys: pytest.CaptureFixture
) -> None:
    done = _write_ledger(git_repo, "done2")
    _write_artifact(git_repo, "done2")
    assert cmd_clean(_clean_args(git_repo, dry_run=True)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["ledgers"] == [str(done)]
    assert done.exists()


def test_clean_reaps_the_ledger_of_an_orphaned_iso_worktree(
    git_repo: Path, capsys: pytest.CaptureFixture
) -> None:
    """The realistic crash: the iso worktree + its ledger survive a SIGKILL, the
    marker names a dead pid, no artifact was ever written. One `clean` reaps the
    worktree AND the ledger (the iso reap clears the marker; the orphaned ids it
    found bridge to the ledger reap)."""
    iso = worktrees.isolation_worktree_add(str(git_repo), "crash1", "colleague/crash1")
    _write_marker(git_repo, "crash1", _dead_pid())
    led = _write_ledger(git_repo, "crash1")
    assert cmd_clean(_clean_args(git_repo, dry_run=False)) == 0
    report = json.loads(capsys.readouterr().out)
    assert not Path(iso).exists()
    assert report["ledgers"] == [str(led)]
    assert not led.exists()


def test_clean_text_render_lists_ledgers(git_repo: Path, capsys: pytest.CaptureFixture) -> None:
    _write_ledger(git_repo, "done3")
    _write_artifact(git_repo, "done3")
    assert cmd_clean(_clean_args(git_repo, dry_run=False, json_mode=False)) == 0
    out = capsys.readouterr().out
    assert "ledgers (reaped):" in out
    assert "done3.jsonl" in out


def test_clean_text_render_nothing_to_reap_mentions_ledgers(
    git_repo: Path, capsys: pytest.CaptureFixture
) -> None:
    _write_ledger(git_repo, "pend2")  # live-or-unknown: kept, so nothing to reap
    assert cmd_clean(_clean_args(git_repo, dry_run=False, json_mode=False)) == 0
    out = capsys.readouterr().out
    assert "nothing to reap" in out
    assert "ledgers" in out

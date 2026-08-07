"""Behavior-level e2e for the self-learning arc (plan t16 — spec c1/h1, c22/h17, c24/h19).

The #380 lesson made this task exist: module-green is not composition-green.
These tests drive the REAL loop with the mock-style scripted completion, a
ROUND-TRIP fake eidetic CLI (remember persists, recall serves what was
remembered), and the rung-2 distillation seam — and assert record CONTENT
verbatim, never mere existence:

1. a deliberately failed run's store record carries the incompletion reason
   and evidence verbatim (rung 1);
2. with a validating distillation seam the same record carries the lesson
   (rung 2);
3. a SECOND run in the same repo recalls that record into its first turn —
   a failed run teaches the next one;
4. a detached (background-child) seam is recorded as ``detached``, never
   conflated with ``no-lesson-extracted``.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from colleague.contract import Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Harness — scripted completion + a ROUND-TRIP fake eidetic CLI
# ---------------------------------------------------------------------------

_READ_STEP = ModelResponse(tool_calls=[ToolCall("r", "read_file", {"path": "alpha.py"})])


def _scripted(responses):
    state = {"i": 0}

    def complete(messages):
        _scripted.last_first_turn = (
            [dict(m) for m in messages]
            if state["i"] == 0
            else getattr(_scripted, "last_first_turn", None)
        )
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _roundtrip_eidetic(bin_dir: Path, store: Path) -> None:
    """A fake eidetic CLI whose remember PERSISTS and whose recall SERVES.

    Unlike the static fake in test_loop_memory.py, this one round-trips: a
    record remembered by run 1 is exactly what run 2's recall receives — the
    teaching loop under test, with zero LLM and zero network.
    """
    script = bin_dir / "eidetic"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"STORE = {str(store)!r}\n"
        "def load():\n"
        "    try:\n"
        "        return json.load(open(STORE))\n"
        "    except Exception:\n"
        "        return {}\n"
        "if sys.argv[1] == 'remember':\n"
        "    rec = json.loads(sys.argv[2])\n"
        "    data = load(); data[rec['id']] = rec\n"
        "    json.dump(data, open(STORE, 'w'))\n"
        "elif sys.argv[1] == 'recall':\n"
        "    print(json.dumps([{'text': r['text']} for r in load().values()]))\n"
        "sys.exit(0)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


@pytest.fixture()
def learn_repo(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    (repo / ".eidetic" / "memory").mkdir(parents=True)
    (repo / "alpha.py").write_text("x = 1\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    store = tmp_path / "store.json"
    _roundtrip_eidetic(bin_dir, store)
    import os

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return repo, store


def _failed_run(repo: Path, *, distill_fn=None, max_steps: int = 3):
    """Drive a run to budget exhaustion (the deliberate failure)."""
    task = Task.new(str(repo), "harden the retry loop against jitter")
    controls = ContextControls(memory=True, distill_fn=distill_fn)
    complete = _scripted([_READ_STEP])
    result = run(complete, task, max_steps=max_steps, context=controls)
    return task, result, complete


def _store_record(store: Path, task_id: str) -> dict:
    data = json.loads(store.read_text())
    rec = data.get(f"work-lesson-{task_id}")
    assert rec is not None, f"no work-lesson record for {task_id} in the store"
    return rec


# ---------------------------------------------------------------------------
# 1. rung 1 — the failed run's record carries the failure substance VERBATIM
# ---------------------------------------------------------------------------


def test_failed_run_record_carries_incompletion_verbatim(learn_repo) -> None:
    repo, store = learn_repo
    task, result, _ = _failed_run(repo)

    assert result.status != "ok"
    assert result.incompletion is not None
    rec = _store_record(store, task.id)
    # Content, not existence: the reason and evidence ride the record text.
    assert str(result.incompletion.reason)[:80] in rec["text"]
    assert str(result.incompletion.evidence)[:80] in rec["text"]


# ---------------------------------------------------------------------------
# 2. rung 2 — a validating seam folds the lesson into the SAME record
# ---------------------------------------------------------------------------


def test_failed_run_with_validating_seam_carries_lesson(learn_repo) -> None:
    repo, store = learn_repo
    raw = json.dumps(
        {
            "cause": "budget spent re-reading alpha.py",
            "lesson": "map the module once, then edit",
            "next_delta": "grep the symbol before opening files",
        }
    )
    task, result, _ = _failed_run(repo, distill_fn=lambda res, head: raw)

    rec = _store_record(store, task.id)
    assert "Lesson (origin=model)" in rec["text"]
    assert "map the module once, then edit" in rec["text"]
    assert rec["metadata"]["distill"] == "validated"
    assert result.memory["distill_attempts"] == 1
    assert result.memory["distill_validated"] == 1


# ---------------------------------------------------------------------------
# 3. the loop closes — run 2 recalls run 1's record into its first turn
# ---------------------------------------------------------------------------


def test_second_run_recalls_first_runs_lesson_verbatim(learn_repo) -> None:
    repo, store = learn_repo
    raw = json.dumps(
        {
            "cause": "budget spent re-reading alpha.py",
            "lesson": "map the module once, then edit",
            "next_delta": "grep the symbol before opening files",
        }
    )
    task1, result1, _ = _failed_run(repo, distill_fn=lambda res, head: raw)
    rec1 = _store_record(store, task1.id)

    # Run 2: same repo, fresh task. Its FIRST TURN must carry run 1's record.
    task2 = Task.new(str(repo), "harden the retry loop against jitter, take two")
    seen: list[list[dict]] = []

    def complete2(messages):
        if not seen:
            seen.append([dict(m) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "verified the fix"})])

    run(complete2, task2, max_steps=4, context=ContextControls(memory=True))
    first_turn = json.dumps(seen[0])
    # The failure reason AND the distilled lesson reach the next mind verbatim.
    assert str(result1.incompletion.reason)[:60] in first_turn
    assert "map the module once, then edit" in first_turn
    # And the record they came from is the one run 1 wrote.
    assert rec1["id"] == f"work-lesson-{task1.id}"


# ---------------------------------------------------------------------------
# 4. detached child semantics — never conflated with no-lesson-extracted
# ---------------------------------------------------------------------------


def test_detached_seam_records_detached_not_no_lesson(learn_repo) -> None:
    repo, store = learn_repo

    def child_fn(res, head):
        return None  # the child owns the outcome

    child_fn.detached = True  # the marker make_distill_fn sets

    task, result, _ = _failed_run(repo, distill_fn=child_fn)
    rec = _store_record(store, task.id)
    assert rec["metadata"]["distill"] == "detached"
    assert "no-lesson-extracted" not in json.dumps(rec["metadata"])
    assert result.memory["distill_attempts"] == 1
    assert result.memory["distill_validated"] == 0


# ---------------------------------------------------------------------------
# 5. author-injection — from_config resolves the distill author by precedence
# ---------------------------------------------------------------------------


def test_resolve_distill_author_from_config_precedence() -> None:
    from colleague.distill import resolve_distill_author_from_config

    class _DT:
        model = "muse-model"
        base_url = "http://dt:1/v1"
        api_key = "k1"

    class _CfgDeepthink:
        deepthink = _DT()
        model = "main-model"
        base_url = "http://main:1/v1"
        api_key = "k0"
        lobes_gateway_url = "http://gw:1"

    author = resolve_distill_author_from_config(_CfgDeepthink())
    assert author is not None and author.model == "muse-model"

    class _CfgLobes:
        deepthink = None
        model = "cortex-model"
        base_url = "http://gw:1/v1"
        api_key = "k2"
        lobes_gateway_url = "http://gw:1"

    author = resolve_distill_author_from_config(_CfgLobes())
    assert author is not None and author.model == "cortex-model"

    class _CfgBare:
        deepthink = None
        model = "plain"
        base_url = "http://x/v1"
        api_key = ""
        lobes_gateway_url = None

    assert resolve_distill_author_from_config(_CfgBare()) is None


# ---------------------------------------------------------------------------
# 6. strive's acting leg is REAL — an attempt runs a work episode in the
#    episode worktree, and the measure scores THAT tree (t16)
# ---------------------------------------------------------------------------


def _git_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "striverepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo


def test_strive_cli_dispatch_runs_real_episode_in_worktree(tmp_path: Path) -> None:
    import subprocess

    from colleague.cli._commands.strive import _strive_run

    repo = _git_repo(tmp_path)
    # The measure proves its own cwd: it writes a marker file where it runs.
    result = _strive_run(
        goal="make the seed grow",
        attempts=1,
        measure_cmd="pwd > measured-here.txt && echo 1",
        engine="mock",
        repo=str(repo),
    )

    assert result["attempts_run"] == 1
    assert len(result["ledger_entries"]) == 1
    # The measure ran in the episode worktree, NEVER the operator tree.
    assert not (repo / "measured-here.txt").exists()
    # The episode branch survives the worktree reap, carrying the measure marker.
    branches = subprocess.run(
        ["git", "branch", "--list", "sub/strive-*"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "sub/strive-make-the-seed-grow" in branches
    show = subprocess.run(
        ["git", "show", "sub/strive-make-the-seed-grow:measured-here.txt"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert show.returncode == 0 and ".colleague/worktrees" in show.stdout
    # And the operator tree is untouched (no worktree residue).
    assert not (repo / ".colleague" / "worktrees" / "strive-make-the-seed-grow").exists()

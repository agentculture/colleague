"""Runtime memory wiring (plan t2, spec R1/c9/h7): recall-before + remember-after.

The loop consults the repo's eidetic memory store around every work item —
recall at task start (a token-capped "prior lessons" block injected as advisory
context) and remember at exit (a deterministic lesson record) — via the
:mod:`colleague.memory` adapter (plan t1).

Arming is deliberately conservative (h7 + test hygiene):

- the repo must contain a ``.eidetic/`` store (a repo opts into memory by
  having one; a tmp test repo without it is a strict no-op — zero subprocess);
- ``ContextControls.memory`` must be truthy (forwarded from
  ``EngineConfig.memory``, default-on, opt-out via ``COLLEAGUE_MEMORY=0`` /
  config.json ``{"memory": false}`` — the lint-gate pattern);
- the eidetic CLI must be on PATH (absent = strict no-op, from t1).

Everything recorded lands on ``TaskResult.memory`` (omit-when-None), so a
memory-less run serializes byte-identically.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from colleague.contract import OK, Task, TaskResult
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_FINISH = ModelResponse(
    tool_calls=[
        ToolCall(
            "f",
            "finish",
            {
                "summary": (
                    "The survey found the adapter seam in alpha.py and the retry loop "
                    "in beta.py; the timeout classification is swallowed in beta.py's "
                    "except clause, which is where the fix belongs."
                )
            },
        )
    ]
)


def scripted(responses: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _fake_eidetic(bin_dir: Path, log: Path, recall_payload: list[dict]) -> None:
    """Install a fake ``eidetic`` executable that logs argv and answers recall."""
    script = bin_dir / "eidetic"
    payload = json.dumps(recall_payload)
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1] == 'recall':\n"
        f"    print({payload!r})\n"
        "sys.exit(0)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".eidetic" / "memory").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def eidetic_log(repo: Path, tmp_path: Path, monkeypatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "eidetic.log"
    _fake_eidetic(
        bin_dir,
        log,
        [
            {"text": "GOTCHA: loop.py is the hot file - merge sequentially."},
            {"text": "DECISION: the all-engines rule is settled."},
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_armed_run_recalls_injects_and_remembers(repo: Path, eidetic_log: Path) -> None:
    seen_messages: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen_messages.append([dict(m) for m in messages])
        return _FINISH

    task = Task.new(str(repo), "map the retry architecture")
    result = run(complete, task, max_steps=5, context=ContextControls(memory=True))

    assert result.status == OK
    calls = _calls(eidetic_log)
    recall_calls = [c for c in calls if c[0] == "recall"]
    remember_calls = [c for c in calls if c[0] == "remember"]
    assert len(recall_calls) == 1
    assert "--scope" in recall_calls[0] and "colleague" in recall_calls[0]
    assert len(remember_calls) == 1
    lesson = json.loads(remember_calls[0][1])
    assert lesson["id"] == f"work-lesson-{task.id}"
    assert task.id in lesson["text"] or "map the retry" in lesson["text"]
    # The recalled lessons were injected as advisory context before the first turn.
    first_turn = seen_messages[0]
    joined = json.dumps(first_turn)
    assert "GOTCHA: loop.py is the hot file" in joined
    # And the artifact records the whole exchange (h7: diagnosable, never silent).
    assert result.memory is not None
    assert result.memory["recalled"] == 2
    assert result.memory["injected_chars"] > 0
    assert result.memory["lesson_recorded"] is True
    assert result.to_dict()["memory"]["recalled"] == 2


def test_no_eidetic_dir_is_strict_noop(tmp_path: Path, monkeypatch) -> None:
    """A repo without .eidetic/ never spawns the CLI — byte-identical artifact."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "eidetic.log"
    _fake_eidetic(bin_dir, log, [{"text": "should never be read"}])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = run(
        scripted([_FINISH]),
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    assert result.status == OK
    assert _calls(log) == []
    assert result.memory is None
    assert "memory" not in result.to_dict()


def test_memory_disabled_is_strict_noop(repo: Path, eidetic_log: Path) -> None:
    """ContextControls.memory falsy → no subprocess even with a store present."""
    result = run(scripted([_FINISH]), Task.new(str(repo), "task"), max_steps=5)

    assert result.status == OK
    assert _calls(eidetic_log) == []
    assert result.memory is None


def test_recall_block_is_capped(repo: Path, tmp_path: Path, monkeypatch) -> None:
    """A huge recall result set injects at most the cap, never the firehose."""
    bin_dir = tmp_path / "bin2"
    bin_dir.mkdir()
    log = tmp_path / "eidetic2.log"
    _fake_eidetic(bin_dir, log, [{"text": "X" * 5000} for _ in range(10)])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    seen: list[int] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append(sum(len(str(m.get("content", ""))) for m in messages))
        return _FINISH

    result = run(
        complete,
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    assert result.memory is not None
    assert result.memory["recalled"] == 10
    assert result.memory["injected_chars"] <= 4000


def test_lesson_recorded_even_on_incomplete_run(repo: Path, eidetic_log: Path) -> None:
    """A failed/partial run is the most valuable lesson — still remembered."""
    never_finish = ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])
    result = run(
        scripted([never_finish]),
        Task.new(str(repo), "task"),
        max_steps=2,
        context=ContextControls(memory=True),
    )

    remember_calls = [c for c in _calls(eidetic_log) if c[0] == "remember"]
    assert len(remember_calls) == 1
    lesson = json.loads(remember_calls[0][1])
    assert "incomplete" in lesson["text"].lower()
    assert result.memory is not None and result.memory["lesson_recorded"] is True


def test_memory_root_targets_durable_store(repo: Path, eidetic_log: Path, tmp_path: Path) -> None:
    """An isolated run's lessons land in the OPERATOR repo, not the worktree.

    ``repo`` (with .eidetic) plays the operator root via ``memory_root``; the
    task's own repo_path is a store-less stand-in for the throwaway worktree —
    without the root override memory would not even arm, and a lesson written
    to the worktree would be reaped with it (caught live on the first smoke run).
    """
    worktree = tmp_path / "iso-worktree"
    worktree.mkdir()
    task = Task.new(str(worktree), "isolated work")
    result = run(
        scripted([_FINISH]),
        task,
        max_steps=5,
        context=ContextControls(memory=True, memory_root=str(repo)),
    )

    calls = _calls(eidetic_log)
    assert [c[0] for c in calls] == ["recall", "remember"]
    assert result.memory is not None and result.memory["lesson_recorded"] is True


def test_memory_field_round_trips() -> None:
    r = TaskResult(task_id="x", status=OK, memory={"recalled": 2, "lesson_recorded": True})
    assert TaskResult.from_dict(r.to_dict()).memory == {"recalled": 2, "lesson_recorded": True}
    bare = TaskResult(task_id="x", status=OK)
    assert "memory" not in bare.to_dict()

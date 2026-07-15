"""Session ``/continue`` (#167): one move resumes a cut work item.

The session leg of the continue affordance: ``/continue [id|last]`` rides the
SAME ``resolve_continuation`` path the ``work --continue`` CLI flag uses, then
dispatches through the ordinary work path (cockpit, heal guard, artifact) —
and stamps the lineage on the dispatched run. Errors are the CLI's own
``ContinuationError`` text, so an off-TTY agent parses one shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague.cli._commands.session import _SLASH_COMMANDS, SessionIO, _Session
from colleague.config import EngineConfig
from colleague.contract import OK, TaskResult


def _write_artifact(repo: Path, task_id: str, *, status: str = "incomplete") -> None:
    coll = repo / ".colleague"
    coll.mkdir(exist_ok=True)
    (coll / f"{task_id}.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "status": status,
                "summary": "stopped early",
                "changed_files": [],
                "steps": [],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "stats": {"request": "the original request"},
            }
        )
    )
    (coll / "last_work").write_text(f"{task_id}\n")


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


def test_bare_continue_defaults_to_last(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "cut1")
    h = _Harness(tmp_path)
    assert h.session._slash("/continue") is True
    assert len(h.calls) == 1
    task = h.calls[0]["task"]
    assert "CONTINUING work item cut1" in task.instruction
    assert "the original request" in task.instruction
    assert h.calls[0]["continued_from"] == "cut1"


def test_continue_explicit_id(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "cut2")
    h = _Harness(tmp_path)
    assert h.session._slash("/continue cut2") is True
    assert len(h.calls) == 1
    assert h.calls[0]["continued_from"] == "cut2"


def test_continue_with_no_history_is_a_clean_error(tmp_path: Path) -> None:
    (tmp_path / ".colleague").mkdir()
    h = _Harness(tmp_path)
    assert h.session._slash("/continue") is True
    assert h.calls == []
    assert any("no 'last' work item" in e for e in h.errors)


def test_continue_ok_run_is_refused_with_the_cli_error_shape(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "done3", status=OK)
    h = _Harness(tmp_path)
    assert h.session._slash("/continue done3") is True
    assert h.calls == []
    assert any("nothing to continue: done3 finished ok" in e for e in h.errors)


def test_lineage_cell_is_consumed_per_dispatch(tmp_path: Path) -> None:
    """An ordinary dispatch after /continue carries no stale lineage."""
    _write_artifact(tmp_path, "cut4")
    h = _Harness(tmp_path)
    h.session._slash("/continue")
    h.session._work_line("a fresh unrelated goal")
    assert len(h.calls) == 2
    assert h.calls[0]["continued_from"] == "cut4"
    # An ordinary dispatch passes NO lineage kwarg at all (stable stub shape).
    assert "continued_from" not in h.calls[1]


def test_continue_is_in_the_slash_catalog() -> None:
    spec = next(s for s in _SLASH_COMMANDS if s.name == "continue")
    assert "resume" in spec.description
    assert spec.arg_hint == "[id|last]"

"""Tests for the ``colleague session`` ``/attach`` slash command (task t11).

``/attach <path>`` validates via :func:`colleague.media.validate_attachment`
and STAGES the attachment for the NEXT work line; repeatable (multiple staged
attachments accumulate, in order). ``/attach`` with no argument lists what is
currently staged (or says none staged). When the next work item is built from
a session line, staged attachments land on ``Task.attachments`` in staged
order and the staging list CLEARS (one-shot semantics) — the following work
line carries none. A validation failure prints a clean error (the session's
normal ``_error`` style) and stages nothing.

Written test-first (TDD), driven the same way as the existing session tests:
scripted ``input_fn`` through :func:`run_session` with a recording fake
``_work_fn`` (mirrors ``_ok_drive`` in ``tests/test_session.py``), plus direct
``_Session``/``_slash`` calls (mirrors ``_make_session`` in
``tests/test_session_cockpit.py``) for the narrower unit checks.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from colleague.cli._commands.session import (
    _HELP_TEXT,
    _SLASH_COMMANDS,
    SessionIO,
    _Session,
    run_session,
)
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.media import validate_attachment

# ---------------------------------------------------------------------------
# Helpers (mirrors the established session test fixtures)
# ---------------------------------------------------------------------------


class _CollectingOut:
    """Fake output sink that collects all emitted lines."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _make_args(tmp_path: Path, **over: object) -> argparse.Namespace:
    base: dict[str, Any] = dict(
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _make_session(repo: Path) -> _Session:
    return _Session(
        repo=repo,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(model="m"),
        json_mode=False,
        view="markdown",
        io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
        work_fn=lambda **k: None,
    )


def _recording_work(recorder: list[dict[str, Any]]):
    """A fake ``_work_fn`` that records every dispatch's kwargs (mirrors the
    established ``_ok_drive`` pattern in ``tests/test_session.py``)."""

    def _fake(**kwargs: object) -> tuple[TaskResult, Path]:
        recorder.append(kwargs)
        return TaskResult(task_id="x", status=OK, summary="done"), Path("art.json")

    return _fake


def _make_media(tmp_path: Path, name: str = "pic.png") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n")
    return p


# ---------------------------------------------------------------------------
# 1. Same-shape: a staged attachment lands on Task.attachments
# ---------------------------------------------------------------------------


def test_attach_stages_and_lands_on_task_attachments(tmp_path: Path) -> None:
    img = _make_media(tmp_path)
    calls: list[dict[str, Any]] = []
    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter([f"/attach {img}", "look at this", "q"]),
        out=out,
        _work_fn=_recording_work(calls),
        _color=False,
    )
    assert rc == 0
    assert len(calls) == 1
    task = calls[0]["task"]
    assert isinstance(task, Task)
    assert task.attachments == [validate_attachment(str(img))]


def test_attach_repeatable_accumulates_in_order(tmp_path: Path) -> None:
    img1 = _make_media(tmp_path, "one.png")
    img2 = _make_media(tmp_path, "two.jpg")
    calls: list[dict[str, Any]] = []
    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter([f"/attach {img1}", f"/attach {img2}", "look at this", "q"]),
        out=out,
        _work_fn=_recording_work(calls),
        _color=False,
    )
    assert rc == 0
    assert len(calls) == 1
    task = calls[0]["task"]
    assert task.attachments == [
        validate_attachment(str(img1)),
        validate_attachment(str(img2)),
    ]


# ---------------------------------------------------------------------------
# 2. One-shot: staging clears after the work line consumes it
# ---------------------------------------------------------------------------


def test_attach_is_one_shot_second_work_line_carries_none(tmp_path: Path) -> None:
    img = _make_media(tmp_path)
    calls: list[dict[str, Any]] = []
    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter([f"/attach {img}", "first request", "second request", "q"]),
        out=out,
        _work_fn=_recording_work(calls),
        _color=False,
    )
    assert rc == 0
    assert len(calls) == 2
    assert calls[0]["task"].attachments == [validate_attachment(str(img))]
    assert calls[1]["task"].attachments is None


def test_consume_staged_attachments_clears_the_staging_list(tmp_path: Path) -> None:
    img = _make_media(tmp_path)
    s = _make_session(tmp_path)
    s._slash(f"/attach {img}")
    assert s._staged_attachments  # staged

    task = Task.new(str(tmp_path), "do it", engine="mock")
    s._consume_staged_attachments(task)
    assert task.attachments == [validate_attachment(str(img))]
    assert s._staged_attachments == []

    # A second consume on a fresh task (nothing staged) is a no-op — the task
    # keeps its constructed default (None), never re-applies the old staging.
    task2 = Task.new(str(tmp_path), "do it again", engine="mock")
    s._consume_staged_attachments(task2)
    assert task2.attachments is None


# ---------------------------------------------------------------------------
# 3. Missing file / bad extension: clean error, nothing staged
# ---------------------------------------------------------------------------


def test_attach_missing_file_reports_clean_error_and_stages_nothing(tmp_path: Path) -> None:
    errors: list[str] = []
    s = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(model="m"),
        json_mode=False,
        view="markdown",
        io=SessionIO(
            out=lambda *a, **k: None,
            err=lambda *a, **k: errors.append(" ".join(str(x) for x in a)),
        ),
        work_fn=lambda **k: None,
    )
    still_running = s._slash("/attach /nonexistent/path/nope.png")
    assert still_running is True  # a bad attach never tears down the session
    assert s._staged_attachments == []
    assert errors  # a diagnostic was reported, the session's normal error style
    assert "not found" in errors[0].lower()


def test_attach_unknown_extension_is_a_clean_error_and_stages_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    s = _make_session(tmp_path)
    errors: list[str] = []
    s.err = lambda *a, **k: errors.append(" ".join(str(x) for x in a))
    s._slash(f"/attach {bad}")
    assert s._staged_attachments == []
    assert errors
    assert "unknown" in errors[0].lower() or "extension" in errors[0].lower()


def test_attach_error_via_run_session_end_to_end(tmp_path: Path) -> None:
    """The same missing-file error, driven through the full run_session loop —
    proves a bad /attach never crashes the session and stages nothing that would
    later leak onto a work item."""
    calls: list[dict[str, Any]] = []
    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["/attach /nope/nope.png", "do a thing", "q"]),
        out=out,
        _work_fn=_recording_work(calls),
        _color=False,
    )
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["task"].attachments is None


# ---------------------------------------------------------------------------
# 4. No attachment staged: work line routes byte-identically to today
# ---------------------------------------------------------------------------


def test_no_attachment_staged_task_attachments_is_none(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["do a thing", "q"]),
        out=out,
        _work_fn=_recording_work(calls),
        _color=False,
    )
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["task"].attachments is None


# ---------------------------------------------------------------------------
# /attach with no argument: list staged attachments
# ---------------------------------------------------------------------------


def test_attach_no_arg_lists_none_staged(tmp_path: Path) -> None:
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["/attach", "q"]), out=out, _color=False)
    assert rc == 0
    assert "no attachment" in out.text().lower()


def test_attach_no_arg_lists_staged_attachments(tmp_path: Path) -> None:
    img = _make_media(tmp_path)
    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter([f"/attach {img}", "/attach", "q"]),
        out=out,
        _color=False,
    )
    assert rc == 0
    assert str(img) in out.text()


# ---------------------------------------------------------------------------
# Slash catalog registration (the single source of truth /help + popup derive
# from — the drift pattern used throughout tests/test_session_cockpit.py)
# ---------------------------------------------------------------------------


def test_attach_is_registered_in_slash_catalog() -> None:
    names = {spec.name for spec in _SLASH_COMMANDS}
    assert "attach" in names
    assert "/attach" in _HELP_TEXT

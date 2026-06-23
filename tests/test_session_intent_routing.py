"""Headless-TUI scenario tests for agent-native intent routing in ``colleague session``.

Task t1 of the agent-native-default feature.  Verifies that a free-text goal typed
into the interactive session is classified and routed to the correct verb (``plan``
or ``work``) without any explicit subcommand, and that the session backend defaults
to colleague's own served backend (``vllm-openai``) rather than the old ``mock``.

Tests are driven entirely through the injectable seams on :func:`run_session`
(``input_fn``, ``out``, ``err``, ``_work_fn``, ``_plan_fn``); no real backend or
network is touched.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pytest

from colleague.cli._commands.session import run_session
from colleague.contract import OK, TaskResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CollectingOut:
    """Fake output sink that collects every emitted string."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _silent(*args: object, **kwargs: object) -> None:
    """Discard all output (err sink)."""


def _make_args(
    tmp_path: Path,
    engine: Optional[str] = "mock",
    base: str = "main",
    allow_dirty: bool = False,
) -> argparse.Namespace:
    """Build a minimal Namespace for ``run_session``; matches the CLI parser shape."""
    return argparse.Namespace(
        repo=str(tmp_path),
        engine=engine,
        no_pr=True,
        base=base,
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=allow_dirty,
    )


def _minimal_task_result(task_id: str = "test000") -> TaskResult:
    """Build the smallest valid TaskResult that satisfies the session's _run_work path."""
    return TaskResult(task_id=task_id, status=OK, summary="done")


def _make_work_fn(capture: dict) -> object:
    """Return a fake _work_fn that records calls and returns a stub TaskResult."""

    def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
        capture["fired"] = True
        capture["engine_name"] = kwargs.get("engine_name")
        capture["task"] = kwargs.get("task")
        task = kwargs.get("task")
        tid = task.id if task is not None else "stub"
        return _minimal_task_result(tid), Path("/dev/null")

    return _work_fn


def _make_plan_fn(capture: dict) -> object:
    """Return a fake _plan_fn that records calls and returns a stub summary."""

    def _plan_fn(**kwargs: object) -> str:
        capture["fired"] = True
        capture["engine_name"] = kwargs.get("engine_name")
        capture["request"] = kwargs.get("request")
        return "plan summary: done"

    return _plan_fn


def _run_one(
    tmp_path: Path,
    goal: str,
    *,
    engine: Optional[str] = "mock",
    work_capture: Optional[dict] = None,
    plan_capture: Optional[dict] = None,
    out: Optional[_CollectingOut] = None,
    monkeypatch: Optional[pytest.MonkeyPatch] = None,
    env_overrides: Optional[dict] = None,
) -> None:
    """Drive one session iteration with the given goal line, then quit."""
    if work_capture is None:
        work_capture = {}
    if plan_capture is None:
        plan_capture = {}
    if out is None:
        out = _CollectingOut()

    if monkeypatch is not None and env_overrides:
        for key, val in env_overrides.items():
            if val is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, val)

    args = _make_args(tmp_path, engine=engine)
    run_session(
        args,
        input_fn=iter([goal, "q"]),
        out=out,
        err=_silent,
        _work_fn=_make_work_fn(work_capture),
        _plan_fn=_make_plan_fn(plan_capture),
        _color=False,
    )


# ---------------------------------------------------------------------------
# Test 1: PLAN intent routes to _plan_fn, NOT _work_fn
# ---------------------------------------------------------------------------


def test_plan_intent_routes_to_plan_fn(tmp_path: Path) -> None:
    """A free-text line with a planning signal calls _plan_fn and skips _work_fn."""
    work_capture: dict = {}
    plan_capture: dict = {}

    _run_one(
        tmp_path,
        "plan this feature end to end",
        work_capture=work_capture,
        plan_capture=plan_capture,
    )

    assert plan_capture.get("fired"), "_plan_fn was not called for a PLAN-intent goal"
    assert not work_capture.get("fired"), "_work_fn must NOT be called for a PLAN-intent goal"


# ---------------------------------------------------------------------------
# Test 2: WORK intent routes to _work_fn, NOT _plan_fn
# ---------------------------------------------------------------------------


def test_work_intent_routes_to_work_fn(tmp_path: Path) -> None:
    """A concrete work goal calls _work_fn and skips _plan_fn."""
    work_capture: dict = {}
    plan_capture: dict = {}

    _run_one(
        tmp_path,
        "fix the typo in README",
        work_capture=work_capture,
        plan_capture=plan_capture,
    )

    assert work_capture.get("fired"), "_work_fn was not called for a WORK-intent goal"
    assert not plan_capture.get("fired"), "_plan_fn must NOT be called for a WORK-intent goal"


# ---------------------------------------------------------------------------
# Test 3: default backend is vllm-openai (colleague's own served backend)
# ---------------------------------------------------------------------------


def test_session_defaults_to_own_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no explicit --engine and no env overrides, the session uses vllm-openai."""
    monkeypatch.delenv("COLLEAGUE_SESSION_ENGINE", raising=False)
    monkeypatch.delenv("COLLEAGUE_ENGINE", raising=False)

    work_capture: dict = {}
    plan_capture: dict = {}

    _run_one(
        tmp_path,
        "fix the typo in README",
        engine=None,  # no explicit --engine flag
        work_capture=work_capture,
        plan_capture=plan_capture,
        monkeypatch=monkeypatch,
    )

    assert work_capture.get("fired"), "_work_fn was not called"
    assert (
        work_capture.get("engine_name") == "vllm-openai"
    ), f"Expected 'vllm-openai' as default backend, got {work_capture.get('engine_name')!r}"


# ---------------------------------------------------------------------------
# Test 4: COLLEAGUE_SESSION_ENGINE env var overrides the default
# ---------------------------------------------------------------------------


def test_session_engine_override_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting COLLEAGUE_SESSION_ENGINE=mock routes the session through mock."""
    monkeypatch.setenv("COLLEAGUE_SESSION_ENGINE", "mock")

    work_capture: dict = {}
    plan_capture: dict = {}

    _run_one(
        tmp_path,
        "fix the typo in README",
        engine=None,  # no explicit flag — env var should win
        work_capture=work_capture,
        plan_capture=plan_capture,
        monkeypatch=monkeypatch,
    )

    assert work_capture.get("fired"), "_work_fn was not called"
    assert (
        work_capture.get("engine_name") == "mock"
    ), f"Expected 'mock' via env override, got {work_capture.get('engine_name')!r}"


# ---------------------------------------------------------------------------
# Test 5: explicit --engine flag wins over COLLEAGUE_SESSION_ENGINE env var
# ---------------------------------------------------------------------------


def test_explicit_engine_flag_wins_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit --engine flag wins over COLLEAGUE_SESSION_ENGINE."""
    monkeypatch.setenv("COLLEAGUE_SESSION_ENGINE", "mock")

    work_capture: dict = {}
    plan_capture: dict = {}

    # engine="vllm-openai" is passed explicitly despite env saying "mock"
    _run_one(
        tmp_path,
        "fix the typo in README",
        engine="vllm-openai",
        work_capture=work_capture,
        plan_capture=plan_capture,
        monkeypatch=monkeypatch,
    )

    assert work_capture.get("fired"), "_work_fn was not called"
    assert (
        work_capture.get("engine_name") == "vllm-openai"
    ), f"Expected explicit 'vllm-openai' to win, got {work_capture.get('engine_name')!r}"


# ---------------------------------------------------------------------------
# Test 6: the routed-verb marker appears in the session feed
# ---------------------------------------------------------------------------


def test_feed_shows_routed_verb(tmp_path: Path) -> None:
    """For a PLAN-intent goal the feed contains a '→ plan:' routing line."""
    out = _CollectingOut()
    work_capture: dict = {}
    plan_capture: dict = {}

    _run_one(
        tmp_path,
        "plan this feature end to end",
        out=out,
        work_capture=work_capture,
        plan_capture=plan_capture,
    )

    rendered = out.text()
    assert (
        "→ plan:" in rendered
    ), f"Expected '→ plan:' routing marker in feed output, got:\n{rendered}"

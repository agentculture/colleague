"""Tests for colleague/webbudget.py — the web-call budget (plan t9).

Written test-first: these tests define the contract before/alongside the
implementation. Covers: the cap refuses call N+1 without spawning
(patching ``colleague.web.run_web``), the cap warning names both
continuation commands and the knob, ``WorkStats.web_calls``/``web_failed``
round-trip through the artifact JSON (old artifacts default to 0), a
continuation resumes the counter and a doubled cap allows N more calls, and
``chain.CONTINUABLE_REASONS`` is pinned unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import colleague.web_schemas as web_schemas
from colleague import webbudget
from colleague.artifact import write
from colleague.chain import CONTINUABLE_REASONS
from colleague.continuation import resolve_continuation
from colleague.contract import OK, TaskResult, WorkStats
from colleague.tools import ToolError, ToolExecutor

# ---------------------------------------------------------------------------
# AC: call N+1 refuses without spawning
# ---------------------------------------------------------------------------


def test_cap_refuses_call_n_plus_1_without_spawning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/webglass")
    monkeypatch.delenv(web_schemas.WEB_ENV, raising=False)
    monkeypatch.setenv(webbudget.ENV_MAX_CALLS, "2")

    executor = ToolExecutor(tmp_path)
    handler = web_schemas.dispatch(executor)["web"]
    run_web = MagicMock(
        return_value="exit=0\n"
        + json.dumps({"operation_id": "op-1", "lifecycle_state": "succeeded"})
    )
    monkeypatch.setattr(web_schemas.web, "run_web", run_web)

    handler({"verb": "search", "query": "a"})
    handler({"verb": "search", "query": "b"})
    assert run_web.call_count == 2
    assert executor.web_calls == 2

    with pytest.raises(ToolError, match=webbudget.ENV_MAX_CALLS):
        handler({"verb": "search", "query": "c"})
    assert run_web.call_count == 2  # call 3 never spawned webglass
    assert executor.web_calls == 2  # never incremented past the cap
    assert executor.web_cap_hit == 2


def test_check_and_increment_default_cap_is_twenty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(webbudget.ENV_MAX_CALLS, raising=False)
    executor = ToolExecutor(tmp_path)
    for _ in range(20):
        webbudget.check_and_increment(executor)
    assert executor.web_calls == 20
    with pytest.raises(ToolError):
        webbudget.check_and_increment(executor)
    assert executor.web_calls == 20


@pytest.mark.parametrize("raw", ["0", "-3", "not-a-number"])
def test_resolve_max_calls_falls_back_to_default_on_bad_value(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(webbudget.ENV_MAX_CALLS, raw)
    assert webbudget.resolve_max_calls() == webbudget.DEFAULT_MAX_CALLS


# ---------------------------------------------------------------------------
# AC: a raised call (timeout / launch failure) counts as FAILED (Qodo #9)
# ---------------------------------------------------------------------------


def test_dispatch_raised_call_counts_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A webglass CLI that hangs past the timeout raises WebToolError; the
    dispatch handler must record it as a failed call (web_failed += 1) and
    re-raise as a clean ToolError."""
    import stat

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "webglass"
    script.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setattr("colleague.web._TIMEOUT_SECONDS", 2)
    monkeypatch.delenv(webbudget.ENV_MAX_CALLS, raising=False)

    executor = ToolExecutor(tmp_path)
    handler = web_schemas.dispatch(executor)["web"]
    with pytest.raises(ToolError):
        handler({"verb": "search", "query": "x"})
    assert executor.web_failed == 1
    # the call was counted (it was attempted) but the failure is recorded
    assert executor.web_calls == 1


def test_dispatch_web_tool_error_counts_failed_without_real_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same contract, without a real subprocess: a WebToolError from run_web
    (e.g. launch failure) is recorded as failed and re-raised as ToolError."""
    from colleague.web import WebToolError

    def _raise(verb, args, root):
        raise WebToolError("webglass verb 'search' failed to launch: permission denied")

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/webglass")
    monkeypatch.delenv(web_schemas.WEB_ENV, raising=False)
    monkeypatch.delenv(webbudget.ENV_MAX_CALLS, raising=False)
    monkeypatch.setattr(web_schemas.web, "run_web", _raise)
    executor = ToolExecutor(tmp_path)
    handler = web_schemas.dispatch(executor)["web"]
    with pytest.raises(ToolError, match="failed to launch"):
        handler({"verb": "search", "query": "x"})
    assert executor.web_failed == 1


# ---------------------------------------------------------------------------
# AC: pre-counted items (Qodo #8, contract with t18) skip BOTH budget hooks
# ---------------------------------------------------------------------------


def test_dispatch_pre_counted_skips_check_and_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When arguments carries _budget_counted: true, dispatch must skip
    check_and_increment AND record_result (the batch loop counts on the main
    thread before submission and records after the join)."""
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/webglass")
    monkeypatch.delenv(web_schemas.WEB_ENV, raising=False)
    monkeypatch.delenv(webbudget.ENV_MAX_CALLS, raising=False)

    check = MagicMock()
    record = MagicMock()
    monkeypatch.setattr(webbudget, "check_and_increment", check)
    monkeypatch.setattr(webbudget, "record_result", record)
    monkeypatch.setattr(
        web_schemas.web,
        "run_web",
        lambda verb, args, root: "exit=0\n"
        + json.dumps({"operation_id": "op-1", "lifecycle_state": "succeeded"}),
    )

    executor = ToolExecutor(tmp_path)
    handler = web_schemas.dispatch(executor)["web"]
    outcome = handler(
        {
            "verb": "search",
            "query": "x",
            "_budget_counted": True,
        }
    )
    assert check.call_count == 0
    assert record.call_count == 0
    # the call still ran and rendered
    assert "op-1" in outcome.result


def test_dispatch_pre_counted_strips_key_before_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The private _budget_counted key must be stripped before the argv is
    built — it never reaches the CLI."""
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/webglass")
    monkeypatch.delenv(web_schemas.WEB_ENV, raising=False)
    monkeypatch.delenv(webbudget.ENV_MAX_CALLS, raising=False)

    check = MagicMock()
    record = MagicMock()
    monkeypatch.setattr(webbudget, "check_and_increment", check)
    monkeypatch.setattr(webbudget, "record_result", record)

    captured: list = []

    def fake_run_web(verb, args, root):
        captured.append((verb, list(args)))
        return "exit=0\n" + json.dumps({"operation_id": "op-1", "lifecycle_state": "succeeded"})

    monkeypatch.setattr(web_schemas.web, "run_web", fake_run_web)

    executor = ToolExecutor(tmp_path)
    handler = web_schemas.dispatch(executor)["web"]
    handler({"verb": "search", "query": "x", "_budget_counted": True})
    verb, args = captured[0]
    assert verb == "search"
    # the private key is gone; only the query reaches the CLI
    assert args == ["x"]
    assert check.call_count == 0
    assert record.call_count == 0


def test_dispatch_normal_path_still_counts_and_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The non-pre-counted path (no _budget_counted key) still runs BOTH
    budget hooks — the skip is opt-in, not the default."""
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/webglass")
    monkeypatch.delenv(web_schemas.WEB_ENV, raising=False)
    monkeypatch.delenv(webbudget.ENV_MAX_CALLS, raising=False)

    check = MagicMock()
    record = MagicMock()
    monkeypatch.setattr(webbudget, "check_and_increment", check)
    monkeypatch.setattr(webbudget, "record_result", record)
    monkeypatch.setattr(
        web_schemas.web,
        "run_web",
        lambda verb, args, root: "exit=0\n"
        + json.dumps({"operation_id": "op-1", "lifecycle_state": "succeeded"}),
    )

    executor = ToolExecutor(tmp_path)
    handler = web_schemas.dispatch(executor)["web"]
    handler({"verb": "search", "query": "x"})
    assert check.call_count == 1
    assert record.call_count == 1


# ---------------------------------------------------------------------------
# AC: the failure counter
# ---------------------------------------------------------------------------


def test_record_result_counts_failed_lifecycle_state(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    webbudget.record_result(executor, {"lifecycle_state": "succeeded"})
    webbudget.record_result(executor, {"lifecycle_state": "failed"})
    webbudget.record_result(executor, None)  # unparseable output also counts
    assert executor.web_failed == 2


def test_record_result_counts_dict_without_lifecycle_state(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    webbudget.record_result(
        executor,
        {
            "code": 1,
            "message": "unrecognized arguments: --json",
            "remediation": "run 'webglass-cli --help' to see valid arguments",
        },
    )
    assert executor.web_failed == 1


def test_record_result_counts_non_dict_envelope(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    webbudget.record_result(executor, [1, 2])
    assert executor.web_failed == 1


def test_record_result_counts_nonzero_exit_code(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    webbudget.record_result(
        executor, {"operation_id": "op-1", "lifecycle_state": "succeeded"}, exit_code=2
    )
    assert executor.web_failed == 1


def test_record_result_zero_exit_with_succeeded_envelope_not_counted(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    webbudget.record_result(
        executor, {"operation_id": "op-1", "lifecycle_state": "succeeded"}, exit_code=0
    )
    assert executor.web_failed == 0


# ---------------------------------------------------------------------------
# AC: the warning line names both continuation commands and the knob
# ---------------------------------------------------------------------------


def test_cap_warning_names_continue_commands_and_knob() -> None:
    warning = webbudget.cap_warning(5, "task-123")
    assert warning["kind"] == webbudget.WARNING_KIND
    detail = warning["detail"]
    assert detail.startswith("web cap 5 reached")
    assert "work --continue task-123" in detail
    assert "session /continue" in detail
    assert webbudget.ENV_MAX_CALLS in detail


def test_finalize_appends_warning_only_on_cap_hit(tmp_path: Path) -> None:
    hit = TaskResult(task_id="t-1", status=OK)
    executor = ToolExecutor(tmp_path)
    executor.web_calls = 3
    executor.web_failed = 1
    executor.web_cap_hit = 3
    webbudget.finalize(hit, executor)
    assert hit.stats.web_calls == 3
    assert hit.stats.web_failed == 1
    assert len(hit.warnings) == 1
    assert hit.warnings[0]["kind"] == webbudget.WARNING_KIND
    assert "work --continue t-1" in hit.warnings[0]["detail"]

    clean = TaskResult(task_id="t-2", status=OK)
    executor2 = ToolExecutor(tmp_path)
    executor2.web_calls = 1
    webbudget.finalize(clean, executor2)
    assert clean.warnings == []


# ---------------------------------------------------------------------------
# AC: WorkStats round-trips web_calls/web_failed; old artifacts default to 0
# ---------------------------------------------------------------------------


def test_workstats_round_trips_web_counters() -> None:
    stats = WorkStats(web_calls=7, web_failed=2)
    data = stats.to_dict()
    assert data["web_calls"] == 7
    assert data["web_failed"] == 2
    restored = WorkStats.from_dict(data)
    assert restored.web_calls == 7
    assert restored.web_failed == 2


def test_workstats_from_dict_defaults_old_artifacts_to_zero() -> None:
    restored = WorkStats.from_dict({})  # an artifact with no web_calls/web_failed key at all
    assert restored.web_calls == 0
    assert restored.web_failed == 0


# ---------------------------------------------------------------------------
# AC: resume_counts reads the counter back out of a continuation seed
# ---------------------------------------------------------------------------


def test_resume_counts_parses_build_continuation_prose() -> None:
    from colleague.escalation import build_continuation

    stats = WorkStats(request="scrape the docs", web_calls=8, web_failed=3)
    result = TaskResult(task_id="tid", status="incomplete", stats=stats)
    prose = build_continuation(result, stats)
    assert webbudget.resume_counts(prose) == (8, 3)


def test_resume_counts_defaults_zero_for_an_ordinary_instruction() -> None:
    assert webbudget.resume_counts("do the thing") == (0, 0)


# ---------------------------------------------------------------------------
# AC: work --continue with a doubled cap resumes at N and allows N more
# ---------------------------------------------------------------------------


def test_continuation_resumes_counter_and_doubled_cap_allows_n_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adir = tmp_path / ".colleague"
    adir.mkdir()
    n = 5
    stats = WorkStats(request="scrape the docs", web_calls=n, web_failed=1)
    prior = TaskResult(
        task_id="task-web-1",
        status="incomplete",
        summary="ran out of steps",
        error="step budget exhausted",
        stats=stats,
    )
    write(prior, adir)

    task_id, seed_text = resolve_continuation(tmp_path, "task-web-1")
    assert task_id == "task-web-1"

    executor = ToolExecutor(tmp_path)
    executor.web_calls, executor.web_failed = webbudget.resume_counts(seed_text)
    assert executor.web_calls == n
    assert executor.web_failed == 1

    monkeypatch.setenv(webbudget.ENV_MAX_CALLS, str(2 * n))
    for _ in range(n):  # exactly N more calls are allowed before the doubled cap
        webbudget.check_and_increment(executor)
    assert executor.web_calls == 2 * n

    with pytest.raises(ToolError):
        webbudget.check_and_increment(executor)
    assert executor.web_calls == 2 * n


# ---------------------------------------------------------------------------
# AC: chain.CONTINUABLE_REASONS is unchanged by this task
# ---------------------------------------------------------------------------


def test_continuable_reasons_pinned_unchanged() -> None:
    assert CONTINUABLE_REASONS == frozenset({"budget-exhausted"})

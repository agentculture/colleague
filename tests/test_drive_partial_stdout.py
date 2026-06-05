"""Drive --json failure path: partial TaskResult goes to stdout (t3 / #XX).

On a failure that carries a partial TaskResult (a DriveAborted-style engine
exception whose .result attribute is a populated TaskResult), ``colleague drive
--json`` must:

* emit parseable JSON to **stdout** (status == "error", non-empty steps);
* exit **non-zero**;
* put the human diagnostic on **stderr** only (stdout is pure JSON).

The success path and the non-json failure path must be byte-identical to today.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague import registry
from colleague.cli import main
from colleague.cli._errors import EXIT_ENV_ERROR, CliError
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.engine import Engine
from colleague.loop import ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Helpers / fake engines
# ---------------------------------------------------------------------------


class _FlakyPartialEngine(Engine):
    """Writes one file then raises mid-loop, producing a partial TaskResult."""

    name = "flaky_partial"

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        first = ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "wip.txt", "content": "work"})]
        )
        state = {"i": 0}

        def complete(_m: list[dict]) -> ModelResponse:
            if state["i"] > 0:
                raise TimeoutError("network blip")
            state["i"] += 1
            return first

        return run(complete, task, max_steps=config.max_steps, progress=config.progress)


# ---------------------------------------------------------------------------
# 1. On failure with a partial result, --json writes parseable JSON to stdout
#    with status == "error" and non-empty steps; exit code is non-zero.
# ---------------------------------------------------------------------------


def test_json_failure_emits_partial_result_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """drive --json on a partial failure emits valid JSON to stdout (status=error, steps>0)."""
    monkeypatch.setattr(registry, "load", lambda name: _FlakyPartialEngine())

    rc = main(
        [
            "drive",
            "do partial work",
            "--repo",
            str(tmp_path),
            "--engine",
            "flaky_partial",
            "--no-pr",
            "--json",
        ]
    )
    assert rc != 0, "failure path must exit non-zero"

    captured = capsys.readouterr()

    # stdout must be parseable JSON
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert len(payload["steps"]) > 0, "partial steps must be present"


# ---------------------------------------------------------------------------
# 2. stdout-is-pure-JSON: no diagnostic text leaks into stdout.
# ---------------------------------------------------------------------------


def test_json_failure_stdout_has_no_diagnostic_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """stdout must contain only the JSON object — no 'error:' or 'hint:' text."""
    monkeypatch.setattr(registry, "load", lambda name: _FlakyPartialEngine())

    main(
        [
            "drive",
            "partial",
            "--repo",
            str(tmp_path),
            "--engine",
            "flaky_partial",
            "--no-pr",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    # Must parse without error (no stray text before/after)
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    # No diagnostic prefixes in the raw text
    assert "error:" not in captured.out
    assert "hint:" not in captured.out


# ---------------------------------------------------------------------------
# 3. Human diagnostic is on stderr; exit code is non-zero.
# ---------------------------------------------------------------------------


def test_json_failure_diagnostic_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The error diagnostic must appear on stderr (as JSON in --json mode), not on stdout."""
    monkeypatch.setattr(registry, "load", lambda name: _FlakyPartialEngine())

    rc = main(
        [
            "drive",
            "partial",
            "--repo",
            str(tmp_path),
            "--engine",
            "flaky_partial",
            "--no-pr",
            "--json",
        ]
    )
    assert rc != 0
    captured = capsys.readouterr()
    # In --json mode emit_error writes a JSON error object to stderr (not "error:" text).
    # Confirm the engine-failure message is present on stderr, not on stdout.
    assert "flaky_partial" in captured.err or "network blip" in captured.err
    assert "flaky_partial" not in captured.out or json.loads(captured.out)["status"] == "error"


# ---------------------------------------------------------------------------
# 4. ask-colleague.sh-style consumer: json.loads(stdout) succeeds (clean JSON).
# ---------------------------------------------------------------------------


def test_json_failure_stdout_is_clean_json_parseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Simulate the ask-colleague.sh consumer: stdout must be directly loadable."""
    monkeypatch.setattr(registry, "load", lambda name: _FlakyPartialEngine())

    main(
        [
            "drive",
            "partial",
            "--repo",
            str(tmp_path),
            "--engine",
            "flaky_partial",
            "--no-pr",
            "--json",
        ]
    )
    stdout_text = capsys.readouterr().out
    # This is what ask-colleague.sh does: json.loads(stdout)
    obj = json.loads(stdout_text)
    assert "status" in obj
    assert "task_id" in obj


# ---------------------------------------------------------------------------
# 5. Success path regression guard: normal mock --json is unchanged.
# ---------------------------------------------------------------------------


def test_success_path_json_output_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A normal successful drive --json still prints result JSON to stdout (regression guard)."""
    rc = main(
        ["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "ok"
    assert payload["pr_url"] is None


# ---------------------------------------------------------------------------
# 6. Non-json failure path: no result JSON leaks to stdout.
# ---------------------------------------------------------------------------


def test_non_json_failure_no_json_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --json, a partial failure must NOT emit result JSON to stdout."""
    monkeypatch.setattr(registry, "load", lambda name: _FlakyPartialEngine())

    rc = main(
        [
            "drive",
            "partial",
            "--repo",
            str(tmp_path),
            "--engine",
            "flaky_partial",
            "--no-pr",
        ]
    )
    assert rc != 0
    captured = capsys.readouterr()
    # stdout must be empty (or at least not JSON)
    assert captured.out.strip() == "" or not captured.out.strip().startswith("{")


# ---------------------------------------------------------------------------
# 7. CliError.result attribute: backward-compatible (None by default).
# ---------------------------------------------------------------------------


def test_cli_error_result_attribute_defaults_to_none() -> None:
    """CliError.result must default to None — no breakage of existing callers."""
    err = CliError(EXIT_ENV_ERROR, "boom", "try again")
    assert err.result is None


def test_cli_error_result_attribute_can_carry_task_result(tmp_path: Path) -> None:
    """CliError.result can hold a TaskResult when explicitly set."""
    task = Task.new(str(tmp_path), "test task")
    result = TaskResult(task_id=task.id, status="error", summary="oops")
    err = CliError(EXIT_ENV_ERROR, "boom", "try again", result=result)
    assert err.result is result
    assert err.result.status == "error"

"""Surviving engine turn timeouts mid-flight (#268).

The observed irc-lens abort: backpressure armed (turns averaging 84s toward the
120s cap), tightened the window ×0.75 — and the very next slow turn blew the cap
and the whole work item aborted, discarding ~30 steps of progress and stranding
4 modified files uncommitted in the (removed) iso worktree. Four asks, four
guards here:

1. a timeout-classified degraded retry now RAISES the per-turn timeout first
   (bounded one-time ×2, :func:`colleague.loop._make_timeout_escalator`) so the
   retry gets real headroom, not just a smaller prompt;
2. the same raise fires proactively when backpressure departs CLEAR;
3. an engine-failure abort commits the iso worktree's WIP onto the
   ``colleague/<id>`` branch (the #222 sweep, extended to the exception path)
   and the error hint names the surviving branch;
4. the timeout surface is documented: `colleague doctor` reports the effective
   value + source, and `work --help` / `colleague learn` name the knob.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.contract import Task
from colleague.loop import (
    ContextControls,
    ModelResponse,
    ToolCall,
    _make_timeout_escalator,
    run,
)

# ---------------------------------------------------------------------------
# The escalator: once-only, x2, visible to a per-call config.timeout reader
# ---------------------------------------------------------------------------


def test_escalator_doubles_once_and_only_once() -> None:
    cfg = SimpleNamespace(timeout=120.0)
    escalate = _make_timeout_escalator(cfg)
    assert escalate() == 240.0
    assert cfg.timeout == 240.0  # a per-call reader (the engine closure) sees it
    assert escalate() is None  # bounded: never raised twice
    assert cfg.timeout == 240.0


def test_escalator_no_positive_timeout_is_dormant() -> None:
    for value in (None, 0, -5):
        cfg = SimpleNamespace(timeout=value)
        escalate = _make_timeout_escalator(cfg)
        assert escalate() is None
        assert cfg.timeout == value


def test_escalator_restores_a_previously_escalated_config() -> None:
    """Qodo PR #271: a config carrying escalated state (base_timeout set) is
    normalized back to the operator's value at every escalator build, so a
    session-reused config starts the next work item at the configured timeout."""
    cfg = SimpleNamespace(timeout=240.0, base_timeout=120.0)
    escalate = _make_timeout_escalator(cfg)
    assert cfg.timeout == 120.0  # restored before the work item starts
    assert escalate() == 240.0  # x2 of the OPERATOR's value, not of 240
    assert cfg.base_timeout == 120.0


def test_escalation_never_compounds_into_child_configs() -> None:
    """Qodo PR #271 (the reported bug): a parent escalation must not raise a
    subagent child's STARTING timeout, nor let the child's own once-only x2
    push past 2x the operator's configured value (120 -> 240 -> 480)."""
    import dataclasses

    from colleague.config import EngineConfig

    parent = EngineConfig.resolve()
    operator_timeout = parent.timeout
    parent_escalate = _make_timeout_escalator(parent)
    assert parent_escalate() == operator_timeout * 2

    # The subagents module derives child configs via dataclasses.replace, which
    # copies the escalated timeout AND the recorded base.
    child = dataclasses.replace(parent)
    assert child.timeout == operator_timeout * 2  # the leak Qodo reported...

    # ...but the child's own escalator build (from_config runs per work item)
    # restores the operator's value first, so the child starts at base and its
    # bounded raise cannot exceed 2x base.
    child_escalate = _make_timeout_escalator(child)
    assert child.timeout == operator_timeout
    assert child_escalate() == operator_timeout * 2
    assert child.timeout == operator_timeout * 2  # never 4x


# ---------------------------------------------------------------------------
# Reactive trigger: a turn timeout raises the cap BEFORE the degraded retry
# ---------------------------------------------------------------------------

_TIMEOUT_ERR = (
    "request to http://localhost:8001/v1/chat/completions timed out after 120s "
    "— raise COLLEAGUE_TIMEOUT for big-context audits"
)


def test_turn_timeout_escalates_then_retry_succeeds(tmp_path: Path) -> None:
    """First completion times out → the escalator fires → the single degraded
    retry runs against the raised cap and the flight SURVIVES."""
    cfg = SimpleNamespace(timeout=120.0)
    timeouts_seen: list[float] = []
    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        timeouts_seen.append(cfg.timeout)
        if turn["n"] == 1:
            raise RuntimeError(_TIMEOUT_ERR)
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "survived"})])

    context = ContextControls(
        budget=100000,
        request_timeout=120.0,
        escalate_timeout=_make_timeout_escalator(cfg),
    )
    result = run(
        complete, Task.new(str(tmp_path), "timeout survival"), max_steps=5, context=context
    )

    assert result.status == "ok"
    assert result.summary == "survived"
    # The retry attempt ran with the RAISED timeout — the escalation happened
    # before the retry, not after the loss.
    assert timeouts_seen == [120.0, 240.0]
    # Recorded honestly in the artifact.
    assert "request timeout raised to 240s" in (result.capacity_warning or "")


def test_timeout_escalation_without_escalator_is_byte_identical(tmp_path: Path) -> None:
    """Direct run() callers (no ContextControls.escalate_timeout) keep the old
    behavior exactly: one shrunken retry, then the give-up propagates as
    WorkAborted carrying the preserved partial — no escalation recorded."""
    from colleague.loop import WorkAborted

    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        raise RuntimeError(_TIMEOUT_ERR)

    context = ContextControls(budget=100000, request_timeout=120.0)
    with pytest.raises(WorkAborted) as ei:
        run(complete, Task.new(str(tmp_path), "no escalator"), max_steps=5, context=context)
    result = ei.value.result
    assert "request timeout raised" not in (result.capacity_warning or "")


# ---------------------------------------------------------------------------
# WIP preservation on the engine-failure abort path (#268 ask 3)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def test_preserve_isolated_wip_reports_commit(git_repo: Path) -> None:
    """The #222 sweep now REPORTS whether it committed, so the engine-failure
    path can point the operator at the surviving branch."""
    from colleague import worktrees
    from colleague.cli._commands.work import _preserve_isolated_wip

    wt = worktrees.isolation_worktree_add(str(git_repo), "tid268", "colleague/tid268-test")
    (Path(wt) / "partial.py").write_text("WIP = True\n", encoding="utf-8")

    assert _preserve_isolated_wip(wt, "engine failure: RuntimeError") is True
    log = _git(git_repo, "log", "--oneline", "colleague/tid268-test").stdout
    assert "WIP committed" in log
    # Empty diff afterwards: a second call is a clean no-op, not an error.
    assert _preserve_isolated_wip(wt, "engine failure: RuntimeError") is False
    worktrees.isolation_worktree_remove(str(git_repo), wt)


def test_engine_failure_path_names_surviving_branch() -> None:
    """Source-level pin: the engine-failure handler (extracted to
    ``_engine_failure_error`` for S3776) preserves WIP and puts the surviving
    branch in the CliError hint (#268 ask 3), and ``execute_work``'s except
    path routes through it with the worktree in hand."""
    source = Path("colleague/cli/_commands/work.py").read_text(encoding="utf-8")
    helper = source.split("def _engine_failure_error", 1)[1].split("\ndef ", 1)[0]
    assert "_preserve_isolated_wip(worktree_path" in helper
    assert "partial work preserved on branch" in helper
    except_body = source.split("except Exception as exc:  # noqa: BLE001 - any failure", 1)[
        1
    ].split("finally:", 1)[0]
    assert "_engine_failure_error(" in except_body
    assert "worktree_path=worktree_path" in except_body


# ---------------------------------------------------------------------------
# The documented timeout surface (#268 ask 4)
# ---------------------------------------------------------------------------


def test_doctor_reports_effective_timeout_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_TIMEOUT", raising=False)
    monkeypatch.delenv("CONVERTIBLE_TIMEOUT", raising=False)
    from colleague.oilcheck.provider import checks

    by_name = {c["id"]: c for c in checks()}
    check = by_name["provider_timeout"]
    assert check["passed"] is True
    assert "120s" in check["message"]
    assert "source: default" in check["message"]


def test_doctor_reports_env_timeout_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TIMEOUT", "300")
    from colleague.oilcheck.provider import checks

    by_name = {c["id"]: c for c in checks()}
    check = by_name["provider_timeout"]
    assert "300s" in check["message"]
    assert "env COLLEAGUE_TIMEOUT" in check["message"]


def test_work_help_documents_timeout_knob() -> None:
    from colleague.cli._commands.work import _configure_work_parser

    parser = argparse.ArgumentParser(prog="work")
    _configure_work_parser(parser)
    assert parser.epilog is not None
    assert "COLLEAGUE_TIMEOUT" in parser.epilog


def test_learn_documents_timeout_knob() -> None:
    import json

    from colleague.cli._commands.learn import _as_json_payload

    payload = json.dumps(_as_json_payload())
    assert "COLLEAGUE_TIMEOUT" in payload

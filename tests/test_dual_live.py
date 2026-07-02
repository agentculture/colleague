"""Opt-in live end-to-end proof of the dual-model deepthink escalation
(plan task t10, spec claims c16/h8, c3/h12).

Sibling to ``test_vllm_live.py`` (the single-model live-proof idiom) and
``test_vllm_live_loop_tools.py`` (the ``culture``/``devague`` model-chosen-tool
proof) — this mirrors both: env-gated so CI and offline runs never touch the
network, and drives a real ``vllm-openai`` work item through
``colleague.cli._commands.work.execute_work``.

Skipped unless ``COLLEAGUE_DUAL_E2E=1`` **and** a live deepthink target is
actually configured (``COLLEAGUE_DEEPTHINK_MODEL`` / ``_BASE_URL`` /
``_API_KEY`` / ``_CONTEXT_BUDGET``, resolved the same way
``colleague/config.py``'s ``EngineConfig.resolve()`` resolves every other
knob). As of 2026-07-02 the reference rig serves no tool-calling-capable
backend at all (see ``docs/live-testing.md`` and issue #66) — this test is
therefore RECORDED AS PENDING there, never claimed as validated, until the rig
can serve two tool-calling-capable OpenAI-compatible endpoints at once.

Run it (with a live dual-model rig up) like::

    COLLEAGUE_DUAL_E2E=1 \\
    COLLEAGUE_BASE_URL=http://localhost:8000/v1 \\
    COLLEAGUE_MODEL=google/gemma-4 \\
    COLLEAGUE_DEEPTHINK_MODEL=sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP \\
    COLLEAGUE_DEEPTHINK_BASE_URL=http://localhost:8001/v1 \\
    uv run pytest tests/test_dual_live.py -v -s

Both servers must expose tool calling (vLLM: ``--enable-auto-tool-choice`` plus
a ``--tool-call-parser`` for each model) — the MAIN model drives the loop and
therefore needs it; the deepthink model is reached only via the tools-off
``Engine.make_complete`` seam (:mod:`colleague.deepthink`), so it does not.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.work import execute_work
from colleague.config import EngineConfig
from colleague.contract import ERROR, Task, TaskResult

pytestmark = pytest.mark.skipif(
    os.environ.get("COLLEAGUE_DUAL_E2E") != "1",
    reason=(
        "set COLLEAGUE_DUAL_E2E=1 with a live dual-model rig (COLLEAGUE_BASE_URL/"
        "_MODEL for the main tool-calling model plus COLLEAGUE_DEEPTHINK_MODEL/"
        "_BASE_URL/_API_KEY/_CONTEXT_BUDGET for the deepthink endpoint) to run "
        "the live dual-model proof"
    ),
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit (the handoff needs a HEAD), no remote."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "calc.py").write_text(
        "def add_all(nums):\n"
        "    total = 0\n"
        "    for n in nums:\n"
        "        total += n\n"
        "    return total\n",
        encoding="utf-8",
    )
    _git(repo, "add", "calc.py")
    _git(repo, "commit", "-m", "initial commit")
    return repo


@pytest.fixture()
def dual_config() -> EngineConfig:
    """Resolve EngineConfig from env (main + COLLEAGUE_DEEPTHINK_*).

    ``COLLEAGUE_DUAL_E2E=1`` alone is not sufficient to run — a live deepthink
    target must actually be declared, or this skips with a clear message
    rather than silently exercising a single-model run under a "dual" test
    name.
    """
    config = EngineConfig.resolve()
    if config.deepthink is None:
        pytest.skip(
            "COLLEAGUE_DUAL_E2E=1 is set but no deepthink target is configured — "
            "set COLLEAGUE_DEEPTHINK_MODEL (and optionally _BASE_URL/_API_KEY/"
            "_CONTEXT_BUDGET) to point at a live second endpoint"
        )
    return config


def _drive(repo: Path, task: Task, config: EngineConfig, label: str) -> TaskResult:
    result, artifact_path = execute_work(
        repo=repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=config,
    )
    print(f"\n[live dual #t10 {label}] drive {result.task_id} -> {artifact_path}")
    print(f"[live dual #t10 {label}] steps: {[(s.tool, s.ok) for s in result.steps]}")
    print(f"[live dual #t10 {label}] deepthink: {result.deepthink}")
    return result


# ---------------------------------------------------------------------------
# 1. The main model escalates a genuine judgment question via the deepthink
#    tool — the end-to-end proof the escalation reaches the second model.
# ---------------------------------------------------------------------------

_JUDGMENT_TASK = (
    "Look at calc.py's add_all function. There are two named design options: "
    "(A) keep the current explicit for-loop, or (B) rewrite it as "
    "`return sum(nums)`. This is a genuine design judgment call, not a "
    "mechanical edit — you MAY use the deepthink tool to think it through "
    "with the stronger reasoning model before you decide. Do not change any "
    "code. State your decision (A or B) and a one-line rationale in your "
    "finish summary."
)


def test_live_dual_model_escalates_via_deepthink_tool(
    git_repo: Path, dual_config: EngineConfig
) -> None:
    """The main model calls the deepthink tool for a judgment question and the
    artifact records at least one NON-degraded call — the proof the
    escalation actually reached the second model, not just a degraded no-op."""
    task = Task.new(str(git_repo), _JUDGMENT_TASK, engine="vllm-openai")
    result = _drive(git_repo, task, dual_config, "deepthink-tool")

    # "Completes" honestly: never crashed. An incomplete run (step-budget /
    # stop) is still a completed proof of the escalation as long as it fired;
    # ERROR is the only outcome this test refuses to call a pass.
    assert result.status != ERROR, result.error
    assert result.deepthink, "no deepthink call was recorded — the escalation never fired"
    live_calls = [call for call in result.deepthink if not call.degraded]
    assert (
        live_calls
    ), f"every deepthink call degraded (never reached the second model): {result.deepthink}"


# ---------------------------------------------------------------------------
# 2. A work item with acceptance criteria triggers the acceptance self-check,
#    which escalates to the deepthink model — the RECORD is the proof (a live
#    weak rig may legitimately degrade the call, per spec h5).
# ---------------------------------------------------------------------------

_ACCEPTANCE_TASK = (
    "Read calc.py and report, in one sentence, what the add_all function "
    "computes. Do not change any code."
)
_ACCEPTANCE_CRITERIA = ["the finish summary states what add_all computes"]


def test_live_dual_model_acceptance_selfcheck_records_deepthink_call(
    git_repo: Path, dual_config: EngineConfig
) -> None:
    """A clean finish on a task with acceptance criteria fires the advisory
    self-check turn, which escalates to the deepthink model. Degraded or not,
    the RECORD on ``result.deepthink`` (point == "acceptance_selfcheck") is
    the proof the escalation point fired end-to-end."""
    task = Task.new(
        str(git_repo),
        _ACCEPTANCE_TASK,
        engine="vllm-openai",
        acceptance=_ACCEPTANCE_CRITERIA,
    )
    result = _drive(git_repo, task, dual_config, "acceptance-selfcheck")

    assert result.status != ERROR, result.error
    selfcheck_calls = [c for c in (result.deepthink or []) if c.point == "acceptance_selfcheck"]
    assert selfcheck_calls, f"no acceptance_selfcheck deepthink call recorded: {result.deepthink}"

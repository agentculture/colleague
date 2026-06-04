"""Opt-in live proof that the `culture` + `devague` loop tools fire (#124, §4).

Sibling to ``test_vllm_live_subagents.py`` / ``test_vllm_live_gated_configs.py``.
Skipped unless ``COLLEAGUE_VLLM_E2E=1`` so CI and offline runs never touch the
network. Like the subagents gap (#122), these tools are *chosen* by the model:
across every captured drive trace the live model invoked only the base five and
never ``culture``/``devague``. The unit suite already proves the tool mechanics
(allow-list, identity injection, the ``confirm``/``reject``/``export`` exclusions,
destination-in-artifact); what it cannot prove is that a *real model* reaches the
tools and they shell out to the operator-installed CLIs.

Covered (each needs the model to choose the tool, so each is a genuine live drive):

* **4a `culture`** — the model calls ``culture(cli='devex', args=['--version'])``
  and it shells out (``exit=0``). Constrained to ``--version`` — a zero-side-effect,
  read-only invocation (``agtag`` cannot post without an explicit ``--repo``, and
  this repo has no remote).
* **4b `devague`** — the model calls ``devague(move='new'|'status', …)`` and it
  shells out. ``devague new`` writes only a self-contained ``.devague/`` in the repo.

DETERMINISTIC (cited in the ledger, not re-proven here): the allow-list rejection
and the ``confirm``/``reject``/``export`` exclusions are enforced by the schema
``enum`` AND in code — a compliant model literally cannot emit a forbidden value,
so they are unreachable live by construction (``tests/test_culture_tools.py``,
``tests/test_devague.py``, ``tests/test_devague_tool.py``). Identity injection is
unit-proven (``tests/test_identity.py``); destination/announcement-in-artifact by
``tests/test_destination_e2e.py``.

Run it (rig up) like::

    COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live_loop_tools.py -v -s
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.drive import execute_drive
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult

pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
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
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def _drive(repo: Path, instruction: str, label: str) -> TaskResult:
    task = Task.new(str(repo), instruction, engine="vllm-openai")
    result, artifact_path = execute_drive(
        repo=repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
    )
    print(f"\n[live #124 {label}] drive {result.task_id} -> {artifact_path}")
    print(f"[live #124 {label}] steps: {[(s.tool, s.ok) for s in result.steps]}")
    return result


# ---------------------------------------------------------------------------
# 4a — the culture tool shells out to an allow-listed AgentCulture CLI
# ---------------------------------------------------------------------------

_CULTURE_TASK = (
    "Use the culture tool to check which version of the devex CLI is installed: "
    "call the culture tool with cli='devex' and args=['--version']. Report the "
    "version it prints, then call finish."
)


def test_4a_culture_shells_out_to_devex(git_repo: Path) -> None:
    result = _drive(git_repo, _CULTURE_TASK, "4a-culture")
    # The whole drive must finish OK — a successful tool call followed by a later
    # drive error must not read as a false "validated live" (parity with 4b).
    assert result.status == OK, result.error
    culture_steps = [(s.arguments.get("cli"), s.ok) for s in result.steps if s.tool == "culture"]
    # Require the SPECIFIC tool the task named (devex) — accepting any allow-listed
    # cli would let the test pass without proving devex actually shelled out.
    devex_calls = [
        s
        for s in result.steps
        if s.tool == "culture" and s.ok and s.arguments.get("cli") == "devex"
    ]
    assert devex_calls, f"no successful culture(cli='devex') call: {culture_steps}"
    # The tool returns 'exit=<code>\n<output>'; --version exits 0. Robust to the
    # exact version string — assert on the shell-out result, not the model's prose.
    assert any("exit=0" in s.result for s in devex_calls), [s.result[:80] for s in devex_calls]


# ---------------------------------------------------------------------------
# 4b — the devague tool shells out to a curated, allow-listed move
# ---------------------------------------------------------------------------

_DEVAGUE_TASK = (
    "This is a vague, new feature idea with no clear goal yet. Use the devague tool "
    "to open a goal-frame: call the devague tool with move='new' and "
    "args=['Users can export their dashboard as a PDF']. Then call the devague tool "
    "with move='status' to inspect the frame. Then call finish."
)


def test_4b_devague_opens_a_goal_frame(git_repo: Path) -> None:
    result = _drive(git_repo, _DEVAGUE_TASK, "4b-devague")
    devague_steps = [(s.arguments.get("move"), s.ok) for s in result.steps if s.tool == "devague"]
    # Require an actual `new` move (the test name claims a frame is OPENED) — accepting
    # a read-only `status`/`show` would let the test pass without the frame being created.
    new_calls = [
        s for s in result.steps if s.tool == "devague" and s.ok and s.arguments.get("move") == "new"
    ]
    assert new_calls, f"no successful devague(move='new') call: {devague_steps}"
    assert any("exit=0" in s.result for s in new_calls), [s.result[:80] for s in new_calls]
    # Soft: did the model also declare arrival (destination/announcement) on finish?
    # Printed, never hard-asserted — that path is flaky and is proven deterministically
    # by tests/test_destination_e2e.py. (.devague/ written by `new` is committed to the
    # throwaway drive branch by the handoff; we assert on steps, not the working tree.)
    print(
        f"[live #124 4b-devague] destination={result.destination!r} "
        f"announcement={result.announcement!r}"
    )
    assert result.status == OK, result.error

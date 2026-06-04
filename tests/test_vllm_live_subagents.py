"""Opt-in live end-to-end proof of subagent delegation against a real vLLM server.

Sibling to ``test_vllm_live.py``. Skipped unless ``COLLEAGUE_VLLM_E2E=1`` (the
deprecated ``CONVERTIBLE_VLLM_E2E`` is still honored) so CI and offline runs never
touch the network. This proves the gap #122 names: across every captured drive
trace the live model invoked only the base five tools and *never* the
``subagent``/``subagents`` delegation tools, so worktree isolation and the merge
child were unexercised against a real model.

It drives a delegation-inviting task (two independent edits in separate files)
through the **production** ``execute_drive`` path — the only path that wires the
``make_spawn``/``make_batch_spawn`` callbacks (a bare ``engine.drive`` leaves them
``None``, so the tools would report "not available"). It then asserts, on
*structural* facts robust to model-text variance:

* the drive populated ``result.sub_results`` (the model reached a delegation tool);
* the *batch* path specifically ran — a ``subagents`` call in the trace, a
  ``merge-`` child, and >=2 parallel children (so a singular ``subagent`` call
  alone, which also fills ``sub_results``, cannot satisfy the test);
* the throwaway worktrees under ``.colleague/worktrees/`` were cleaned up (checked
  in git's worktree registry AND on disk).

``COLLEAGUE_SUBAGENT_CONCURRENCY=2`` exercises the parallel batch path. The caps
(``MAX_SUBAGENT_DEPTH=2`` / ``MAX_SUBAGENT_FANOUT=4``) and the no-force-merge
conflict-surfacing path are structurally enforced and already proven by the unit
suite (``tests/test_subagents.py``, ``tests/test_subagents_parallel.py``); this
live proof covers what unit tests cannot — the live model *choosing* to delegate.

Run it (with the reference rig up) like::

    COLLEAGUE_VLLM_E2E=1 COLLEAGUE_SUBAGENT_CONCURRENCY=2 \\
    uv run pytest tests/test_vllm_live_subagents.py -v -s

The server must expose tool calling (vLLM: ``--enable-auto-tool-choice`` plus a
``--tool-call-parser`` for the model, e.g. ``hermes`` or ``qwen3_coder``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.drive import execute_drive
from colleague.config import EngineConfig
from colleague.contract import OK, Task

pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)

# A task that *invites* delegation: two independent edits in separate files that
# do not depend on each other — the shape the improved `_DEFAULT_SYSTEM` prompt
# points at the `subagents` batch tool for. Kept explicit about the parallel,
# independent structure so a real model recognises the fan-out opportunity.
DELEGATION_TASK = (
    "This repo has two independent files, a.py and b.py, that do not depend on "
    "each other. Make two independent changes in parallel: in a.py, rename the "
    "function `foo` to `foo_renamed` (and update its body's return text to match); "
    "in b.py, add a new top-level function `helper()` that returns the string "
    "'helper'. These two edits are independent, so delegate them as parallel "
    "subagents (one child per file) rather than editing both yourself."
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


def _worktree_paths(repo: Path) -> list[str]:
    proc = _git(repo, "worktree", "list", "--porcelain")
    return [
        line[len("worktree ") :].strip()
        for line in proc.stdout.splitlines()
        if line.startswith("worktree ")
    ]


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit (worktree add needs a HEAD) + two files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "a.py").write_text("def foo():\n    return 'foo'\n", encoding="utf-8")
    (repo / "b.py").write_text("# helpers for b\n", encoding="utf-8")
    _git(repo, "add", "a.py", "b.py")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def test_live_drive_delegates_to_subagents(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Width 2 drives the parallel batch path (read before resolve()).
    monkeypatch.setenv("COLLEAGUE_SUBAGENT_CONCURRENCY", "2")
    config = EngineConfig.resolve()

    task = Task.new(str(git_repo), DELEGATION_TASK, engine="vllm-openai")
    result, artifact_path = execute_drive(
        repo=git_repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=config,
    )

    # Evidence for the ledger stamp: the drive id + where its artifact landed.
    print(f"\n[live #122] drive {result.task_id} -> {artifact_path}")
    print(f"[live #122] sub_results: {[(s.task_id, s.status) for s in result.sub_results]}")

    assert result.status == OK, result.error
    # The delegation signal: the model reached a delegation tool, so the loop folded
    # child results into the artifact (omitted entirely when empty).
    assert result.sub_results, "the model never delegated (no sub_results in the artifact)"

    # Prove the *batch* `subagents` path specifically — `sub_results` alone is also
    # populated by the singular `subagent` tool, so it cannot distinguish the two.
    # Two independent, robust structural signals of the batch path:
    #   1. the loop trace shows a `subagents` tool call, and
    #   2. the batch always appends exactly one merge child (task_id prefixed
    #      `merge-`); the singular tool never produces one.
    # The task asked for one child per file, so require >=2 non-merge children too.
    tools_called = sorted({s.tool for s in result.steps})
    assert (
        "subagents" in tools_called
    ), f"the batch `subagents` tool was never called: {tools_called}"
    children = [s for s in result.sub_results if not s.task_id.startswith("merge-")]
    merges = [s for s in result.sub_results if s.task_id.startswith("merge-")]
    assert merges, "no merge child — the parallel worktree+merge path did not run"
    assert len(children) >= 2, f"expected >=2 parallel children (one per file), got {len(children)}"

    # Worktree lifecycle: every throwaway `sub/<id>` worktree was torn down. Check
    # BOTH git's registry AND the on-disk tree — a registry prune that left an
    # orphaned directory behind would otherwise read as a false "cleaned" pass.
    # Assert on worktree DIRECTORIES, not branches — a conflicted child's branch is
    # intentionally retained while its worktree dir is still removed.
    wt_root = (git_repo / ".colleague" / "worktrees").resolve()
    registered = [p for p in _worktree_paths(git_repo) if p.startswith(str(wt_root))]
    assert registered == [], f"subagent worktrees still registered with git: {registered}"
    on_disk = [p.name for p in wt_root.iterdir() if p.is_dir()] if wt_root.exists() else []
    assert on_disk == [], f"orphaned worktree dirs left on disk under {wt_root}: {on_disk}"

    # The on-disk artifact carries the folded sub_results (#122 checklist).
    assert artifact_path.exists()

"""#196/#201: ``colleague work`` / ``ask-colleague write --apply`` must isolate.

The runtime drives an isolated work item (``isolate=True``, the default for
``colleague work``/``drive``) inside a throwaway git worktree at the operator's
HEAD on the ``colleague/<id>`` branch. Consequences these tests pin:

- A model that commits its own work *during* the loop lands that commit on
  ``colleague/<id>``, never the operator's checked-out branch (#196). Before the
  fix the handoff read the clean tree as "no changes", left no branch, and the
  self-commit advanced the operator's branch.
- The operator's working tree, current branch, and HEAD are byte-identical after
  the run (#196/#201) — the result is recoverable on ``colleague/<id>``.

The concurrent-disjoint and incomplete-no-strand variants live in the
colleague-authored companion suite (t2); this file pins the #196 self-commit
guard + the operator-untouched invariant that t1 implements.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from colleague import registry
from colleague.cli import main
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.engine import Engine
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.tools import ToolExecutor


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init", "-q", "-b", "feature")
    _run(repo, "config", "user.email", "op@example.com")
    _run(repo, "config", "user.name", "Operator")
    (repo / "README.md").write_text("seed\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "init")


def _branches(repo: Path) -> list[str]:
    out = _run(repo, "branch", "--format=%(refname:short)")
    return out.split()


def _colleague_branch(repo: Path) -> str | None:
    return next((b for b in _branches(repo) if b.startswith("colleague/")), None)


def _operator_dirty(repo: Path) -> str:
    """Porcelain status with colleague's own ``.colleague/`` bookkeeping excluded.

    A real repo gitignores ``/.colleague/*`` (artifacts, worktree admin); a bare
    test repo does not, so filter it here — what matters is that no *operator*
    file changed.
    """
    lines = _run(repo, "status", "--porcelain").splitlines()
    return "\n".join(ln for ln in lines if ".colleague/" not in ln)


class _SelfCommitEngine(Engine):
    """An engine whose model writes a file then commits it ITSELF (the #196 trigger)."""

    name = "self-commit"

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        turns = [
            ModelResponse(
                content="writing the file",
                tool_calls=[
                    ToolCall("c1", "write_file", {"path": "newfile.txt", "content": "wip\n"})
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                content="committing it myself",
                tool_calls=[
                    ToolCall(
                        "c2",
                        "run_command",
                        {"command": "git add -A && git commit -m 'model self-commit'"},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                content="done",
                tool_calls=[ToolCall("c3", "finish", {"summary": "self-committed the work"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
        state = {"i": 0}

        def complete(_messages: list[dict]) -> ModelResponse:
            turn = turns[min(state["i"], len(turns) - 1)]
            state["i"] += 1
            return turn

        return run(
            complete,
            task,
            max_steps=config.max_steps,
            system_prompt="",
            model=config.model,
            executor=ToolExecutor(task.repo_path),
            context=ContextControls(budget=config.context_budget_tokens),
        )


def test_model_self_commit_never_lands_on_operator_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#196: a self-committing run lands on colleague/<id>, leaving the operator intact."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.setattr(registry, "load", lambda _name: _SelfCommitEngine())

    before_branch = _run(repo, "rev-parse", "--abbrev-ref", "HEAD")
    before_head = _run(repo, "rev-parse", "HEAD")

    rc = main(
        ["work", "implement a thing", "--repo", str(repo), "--engine", "self-commit", "--no-pr"]
    )
    assert rc == 0

    # The operator is byte-identical: same branch, same HEAD, clean tree (the work
    # never touched their checkout — the whole point of #196/#201).
    assert _run(repo, "rev-parse", "--abbrev-ref", "HEAD") == before_branch == "feature"
    assert _run(repo, "rev-parse", "HEAD") == before_head
    assert _operator_dirty(repo) == ""

    # …and the model's self-commit is recoverable on a colleague/<id> branch.
    cb = _colleague_branch(repo)
    assert cb is not None, "no colleague/<id> branch — the self-commit was stranded (#196)"
    committed = _run(repo, "show", "--stat", "--format=", cb)
    assert "newfile.txt" in committed
    assert "newfile.txt" not in _run(repo, "show", "--stat", "--format=", "feature")


def test_isolated_run_without_self_commit_still_isolates(tmp_path: Path) -> None:
    """The ordinary path (model leaves changes uncommitted) also lands on colleague/<id>."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    # Use the real mock engine (writes a marker, does not self-commit).
    before_head = _run(repo, "rev-parse", "HEAD")
    rc = main(["work", "do it", "--repo", str(repo), "--engine", "mock", "--no-pr"])
    assert rc == 0
    assert _run(repo, "rev-parse", "HEAD") == before_head  # operator HEAD unmoved
    assert _operator_dirty(repo) == ""  # operator tree clean
    assert _colleague_branch(repo) is not None  # work recoverable on a branch

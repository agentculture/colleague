"""Session dirty-tree heal (#168): one explicit choice instead of a refusal.

A colour-TTY session that KNOWS the dispatch would hit the #149 refusal offers
the three-choice heal prompt (commit-onto-work-branch / stash / abort) BEFORE
the doomed run. Off-TTY, ``--json``, and ``--allow-dirty`` sessions fall through
byte-identically — the runtime guard still rules there. The commit choice is a
ONE-RUN waiver, never sticky; the stash choice names its recovery line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from colleague.config import EngineConfig
from colleague.contract import OK, TaskResult
from colleague.cli._commands.session import SessionIO, _Session
from colleague import handoff


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.dev"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _dirty(path: Path) -> None:
    (path / "f.txt").write_text("edited but uncommitted\n")


class _Harness:
    """A directly-constructed session with scripted heal input + a spy work_fn."""

    def __init__(self, repo: Path, *, live: bool, answers: list[str]) -> None:
        self.out_lines: list[str] = []
        self.calls: list[dict] = []

        def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
            self.calls.append(dict(kwargs))
            return (TaskResult(task_id="x", status=OK, summary="done"), repo / "a.json")

        self.session = _Session(
            repo=repo,
            engine_name="mock",
            open_pr=False,
            base="main",
            config=EngineConfig.resolve(model="m"),
            json_mode=False,
            view="markdown",
            io=SessionIO(out=self._out, err=lambda *a, **k: None),
            work_fn=_work_fn,
        )
        self.session._live = live
        answers_iter = iter(answers)
        self.session._read_next = lambda: next(answers_iter, "")

    def _out(self, *args: object, **_k: object) -> None:
        self.out_lines.append(" ".join(str(a) for a in args))

    def dispatch(self, text: str = "change the file") -> None:
        self.session._work_line(text)

    @property
    def output(self) -> str:
        return "\n".join(self.out_lines)


def test_abort_cancels_the_dispatch_with_tree_untouched(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _dirty(tmp_path)
    h = _Harness(tmp_path, live=True, answers=[""])  # empty input == abort (default)
    h.dispatch()
    assert "Choose how to proceed" in h.output
    assert h.calls == []  # the doomed run never started
    assert handoff.working_tree_dirty(tmp_path)  # edits untouched


def test_commit_choice_is_a_one_run_waiver(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _dirty(tmp_path)
    h = _Harness(tmp_path, live=True, answers=["1"])
    h.dispatch()
    assert len(h.calls) == 1
    assert h.calls[0]["allow_dirty"] is True
    # The waiver is consumed: a second dispatch on a now-clean tree passes False.
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "--", "f.txt"], check=True)
    h.dispatch("another change")
    assert len(h.calls) == 2
    assert h.calls[1]["allow_dirty"] is False


def test_commit_choice_prompt_names_consequence_and_undo(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _dirty(tmp_path)
    h = _Harness(tmp_path, live=True, answers=["1"])
    h.dispatch()
    assert "commits your uncommitted tracked edits onto the work branch" in h.output
    assert "git stash pop" in h.output  # every choice's undo is in the one prompt


def test_stash_choice_stashes_and_names_the_recovery(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _dirty(tmp_path)
    h = _Harness(tmp_path, live=True, answers=["2"])
    h.dispatch()
    assert len(h.calls) == 1
    assert h.calls[0]["allow_dirty"] is False
    assert not handoff.working_tree_dirty(tmp_path)  # edits are in the stash
    conversation = " ".join(line.text for line in h.session.state.conversation)
    assert "stash@{0}" in conversation
    assert "git stash pop" in conversation
    stashes = subprocess.run(
        ["git", "-C", str(tmp_path), "stash", "list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "colleague session heal" in stashes


def test_off_tty_never_prompts_and_falls_through(tmp_path: Path) -> None:
    """h12: no interactive prompt can block a pipe — the dispatch proceeds into
    today's runtime-refusal path unchanged (work_fn sees allow_dirty=False)."""
    _git_repo(tmp_path)
    _dirty(tmp_path)
    h = _Harness(tmp_path, live=False, answers=["1"])
    h.dispatch()
    assert "Choose how to proceed" not in h.output
    assert len(h.calls) == 1
    assert h.calls[0]["allow_dirty"] is False


def test_clean_tree_never_prompts(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    h = _Harness(tmp_path, live=True, answers=["1"])
    h.dispatch()
    assert "Choose how to proceed" not in h.output
    assert len(h.calls) == 1


def test_allow_dirty_session_never_prompts(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    _dirty(tmp_path)
    h = _Harness(tmp_path, live=True, answers=["1"])
    h.session.allow_dirty = True
    h.dispatch()
    assert "Choose how to proceed" not in h.output
    assert len(h.calls) == 1
    assert h.calls[0]["allow_dirty"] is True


def test_runtime_guard_is_untouched(tmp_path: Path) -> None:
    """h9: the #149 runtime refusal (bare CLI path) is byte-identical — the heal
    is a session-surface affordance only."""
    _git_repo(tmp_path)
    _dirty(tmp_path)
    assert handoff.working_tree_dirty(tmp_path) is True
    # .eidetic-only churn stays exempt (the recorded runtime exemption).
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "--", "f.txt"], check=True)
    mem = tmp_path / ".eidetic" / "memory"
    mem.mkdir(parents=True)
    (mem / "s.jsonl").write_text("{}\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".eidetic"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "mem"], check=True)
    (mem / "s.jsonl").write_text('{"recall": 1}\n')
    assert handoff.working_tree_dirty(tmp_path) is False


def test_heal_stash_returns_none_on_clean_tree(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    assert handoff.heal_stash(tmp_path) is None


@pytest.mark.parametrize("raw", ["3", "abort", "nonsense"])
def test_non_action_inputs_abort(tmp_path: Path, raw: str) -> None:
    _git_repo(tmp_path)
    _dirty(tmp_path)
    h = _Harness(tmp_path, live=True, answers=[raw])
    h.dispatch()
    assert h.calls == []
    assert handoff.working_tree_dirty(tmp_path)

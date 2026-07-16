"""Chain-episode dispatch plumbing (indefinite-run follow-up, issue #335, c22).

``ChainEpisodeOptions`` (``colleague/cli/_commands/work.py``) gains
``prior_changed`` — the UNION of every prior episode's ``result.changed_files``
(sorted, deduped) — which ``execute_work_chain``'s loop accumulates and hands to
the NEXT episode. ``execute_work`` threads a chain-episode marker + that
accumulated tuple into ``ContextControls`` via two new runtime-only
``EngineConfig`` fields (``chain_episode`` / ``chain_prior_changed`` — the
``role``/``memory_root`` precedent), set PER-CALL from the PRESENCE of
``execute_work``'s ``chain: ChainEpisodeOptions | None`` parameter — never from
``config.until_done`` (that stays ``ContextControls.chain_armed``, untouched).

This is PLUMBING ONLY (t5): nothing in the loop reads these fields yet — the
gate-skip guard that consumes them is the next task (t6). Every test here
proves the fields exist, thread correctly, and stay dormant/False on any
dispatch that is not literally an episode of an armed chain — including the
tricky case ``config.until_done=True`` with no chain dispatch (AC2's honesty
requirement) and a subagent child of a chained episode (AC... c22's
never-inherited requirement, covered in ``tests/test_subagent_budget.py``
alongside the sibling role/counter inheritance tests).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.work import ChainEpisodeOptions, execute_work
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.loop import ContextControls

# ---------------------------------------------------------------------------
# (a) ChainEpisodeOptions carries prior_changed
# ---------------------------------------------------------------------------


def test_chain_episode_options_prior_changed_defaults_empty() -> None:
    """``prior_changed`` defaults to ``()`` — a bare/first-episode options object
    (only ``base_ref``/``prior_view`` set, the pre-#335 shape) is unaffected."""
    opts = ChainEpisodeOptions()
    assert opts.prior_changed == ()


def test_chain_episode_options_carries_explicit_prior_changed() -> None:
    opts = ChainEpisodeOptions(
        base_ref="colleague/abc123",
        prior_changed=("episode-1.txt", "src/foo.py"),
    )
    assert opts.prior_changed == ("episode-1.txt", "src/foo.py")


# ---------------------------------------------------------------------------
# (b) ContextControls.from_config threads the two runtime-only config fields
# ---------------------------------------------------------------------------


def test_from_config_populates_chain_episode_fields() -> None:
    """The single from_config mapping both backends share (all-engines rule):
    an armed config's chain_episode/chain_prior_changed reach ContextControls
    unchanged; a bare EngineConfig() (never touched by execute_work) stays at
    the dormant defaults."""
    armed = EngineConfig.resolve()
    armed.chain_episode = True
    armed.chain_prior_changed = ("episode-1.txt", "episode-2.txt")
    controls = ContextControls.from_config(armed)
    assert controls.chain_episode is True
    assert controls.chain_prior_changed == ("episode-1.txt", "episode-2.txt")

    bare = EngineConfig.resolve()
    bare_controls = ContextControls.from_config(bare)
    assert bare_controls.chain_episode is False
    assert bare_controls.chain_prior_changed == ()


# ---------------------------------------------------------------------------
# (c) execute_work sets the marker ONLY from the PRESENCE of `chain`
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised tmp_path with an initial commit (cwd-scoped identity)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


class _RecorderEngine:
    """Engine stub that finishes cleanly, recording the config it was handed
    (the ``tests/test_mode_artifact.py`` idiom)."""

    def __init__(self, seen: list) -> None:
        self.seen = seen

    def work(self, task, config) -> TaskResult:
        self.seen.append(config)
        return TaskResult(task_id=task.id, status=OK, summary="done")


def _run_execute(git_repo: Path, config: EngineConfig, **kwargs):
    task = Task.new(str(git_repo), "map the loop", engine="mock")
    return execute_work(
        repo=git_repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
        allow_dirty=True,
        **kwargs,
    )


def test_execute_work_sets_marker_true_when_chain_present(git_repo, monkeypatch) -> None:
    seen: list = []
    monkeypatch.setattr("colleague.registry.load", lambda name: _RecorderEngine(seen))
    config = EngineConfig.resolve()

    _run_execute(
        git_repo,
        config,
        chain=ChainEpisodeOptions(prior_changed=("a.py", "b.py")),
    )

    assert seen[-1].chain_episode is True
    assert tuple(seen[-1].chain_prior_changed) == ("a.py", "b.py")


def test_execute_work_leaves_marker_false_when_chain_is_none(git_repo, monkeypatch) -> None:
    seen: list = []
    monkeypatch.setattr("colleague.registry.load", lambda name: _RecorderEngine(seen))
    config = EngineConfig.resolve()

    _run_execute(git_repo, config, chain=None)

    assert seen[-1].chain_episode is False
    assert tuple(seen[-1].chain_prior_changed) == ()


def test_execute_work_until_done_true_without_chain_dispatch_leaves_marker_false(
    git_repo, monkeypatch
) -> None:
    """AC2's honesty requirement: ``config.until_done=True`` alone (e.g. a bare
    ``colleague work --until-done``'s FIRST dispatch never reaching the chain
    loop, or any caller that resolves the knob but calls ``execute_work``
    directly) must NOT set the marker — only an actual chain-loop dispatch
    (``chain is not None``) does."""
    seen: list = []
    monkeypatch.setattr("colleague.registry.load", lambda name: _RecorderEngine(seen))
    config = EngineConfig.resolve()
    config.until_done = True

    _run_execute(git_repo, config, chain=None)

    assert seen[-1].chain_episode is False
    assert tuple(seen[-1].chain_prior_changed) == ()
    # chain_armed (the PRE-EXISTING, untouched marker) is keyed on until_done —
    # it stays free to arm; only the NEW dispatch-keyed marker must stay dormant.
    controls = ContextControls.from_config(seen[-1])
    assert controls.chain_armed is True
    assert controls.chain_episode is False


def test_execute_work_marker_does_not_leak_across_reused_config_object(
    git_repo, monkeypatch
) -> None:
    """A config object reused across two dispatches (the session's one
    long-lived ``EngineConfig``) never lets a chained call's marker bleed onto
    a later unchained call on the SAME object."""
    seen: list = []
    monkeypatch.setattr("colleague.registry.load", lambda name: _RecorderEngine(seen))
    config = EngineConfig.resolve()

    _run_execute(git_repo, config, chain=ChainEpisodeOptions(prior_changed=("x.py",)))
    assert seen[-1].chain_episode is True

    _run_execute(git_repo, config, chain=None)
    assert seen[-1].chain_episode is False
    assert tuple(seen[-1].chain_prior_changed) == ()

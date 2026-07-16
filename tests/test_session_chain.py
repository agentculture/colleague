"""Session-front episode chaining (indefinite-run t9) — flag parity + shared path.

Acceptance criterion 1: ``colleague session --repo . --until-done
[--max-episodes N]`` arms EVERY work item the session dispatches with the SAME
semantics as ``work --until-done`` — the dispatch funnels through the one chain
loop (:func:`colleague.cli._commands.work.execute_work_chain`, the exact
function ``cmd_work``'s ``--until-done`` adapter drives), never a session-only
fork; arming resolves flag > env > ``config.json`` via the same
``_resolve_chain_arming``. Unarmed (no flag, no env, no config key) the
dispatch shape is byte-identical to today — off a colour TTY included (all
tests here run the static Markdown tier, ``_color=False``).

The unit tests pin the dispatch seam with recording fakes (the ``_ok_drive``
pattern from ``tests/test_session.py``); one end-to-end test drives a REAL
two-episode chain through the session with the scripted mock engine (the
``tests/test_work_chain.py`` harness pattern) to prove the session front
reaches the same chain semantics — lineage, chain view, episode diagnostics.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands import session as session_mod
from colleague.cli._commands import work as work_mod
from colleague.cli._commands.session import _configure_session_parser, run_session
from colleague.contract import OK, TaskResult
from colleague.loop import ModelResponse, ToolCall

# ---------------------------------------------------------------------------
# Helpers (the test_session.py harness pattern)
# ---------------------------------------------------------------------------


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _make_args(repo: Path, **overrides: object) -> argparse.Namespace:
    """A session Namespace mirroring ``_configure_session_parser``'s surface."""
    base: dict[str, object] = dict(
        repo=str(repo),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _ok_work(recorder: list | None = None):
    """A fake single-episode work_fn (the ``_ok_drive`` pattern)."""

    def _fake(**kwargs: object) -> tuple[TaskResult, Path]:
        if recorder is not None:
            recorder.append(kwargs)
        return TaskResult(task_id="w", status=OK, summary="done"), Path("art.json")

    return _fake


def _ok_chain(recorder: list | None = None):
    """A fake chain_fn with ``execute_work_chain``'s return shape."""

    def _fake(**kwargs: object) -> tuple[TaskResult, Path]:
        if recorder is not None:
            recorder.append(kwargs)
        return TaskResult(task_id="c", status=OK, summary="chained"), Path("art.json")

    return _fake


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload))


# ---------------------------------------------------------------------------
# Flag parity: the session parser accepts the same chain flags as work
# ---------------------------------------------------------------------------


def test_session_parser_accepts_until_done_and_max_episodes() -> None:
    p = argparse.ArgumentParser()
    _configure_session_parser(p)
    ns = p.parse_args(["--until-done", "--max-episodes", "3"])
    assert ns.until_done is True
    assert ns.max_episodes == 3


def test_session_parser_defaults_leave_chain_unarmed() -> None:
    p = argparse.ArgumentParser()
    _configure_session_parser(p)
    ns = p.parse_args([])
    assert ns.until_done is False
    assert ns.max_episodes is None


# ---------------------------------------------------------------------------
# Shared dispatch path — no session-only fork
# ---------------------------------------------------------------------------


def test_default_chain_fn_is_the_work_chain_loop() -> None:
    """The session's default chain runner IS work.execute_work_chain — the same
    function cmd_work's --until-done adapter drives (no session-only fork)."""
    assert session_mod._default_chain is work_mod.execute_work_chain


def test_unarmed_session_dispatch_shape_is_unchanged(tmp_path: Path) -> None:
    """No flag, no env, no config key: the work item goes through work_fn with
    the pre-t9 kwargs shape and the chain path is never touched (byte-identical
    off a colour TTY)."""
    work_calls: list = []
    chain_calls: list = []
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_work(work_calls),
        _chain_fn=_ok_chain(chain_calls),
        _color=False,
    )
    assert rc == 0
    assert chain_calls == []
    assert len(work_calls) == 1
    assert "cap" not in work_calls[0]  # the single-episode call shape is unchanged


def test_until_done_flag_arms_every_session_dispatch(tmp_path: Path) -> None:
    """--until-done routes the work item through chain_fn (work's chain loop),
    with the same resolved kwargs the single-episode path would carry + cap."""
    work_calls: list = []
    chain_calls: list = []
    rc = run_session(
        _make_args(tmp_path, until_done=True, max_episodes=None),
        input_fn=iter(["do a thing", "another thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_work(work_calls),
        _chain_fn=_ok_chain(chain_calls),
        _color=False,
    )
    assert rc == 0
    assert work_calls == []  # every dispatch chained — none fell to the single path
    assert len(chain_calls) == 2
    for call in chain_calls:
        assert call["cap"] == 5  # default cap
        assert call["engine_name"] == "mock"
        assert call["open_pr"] is False
        assert call["allow_dirty"] is False
        assert call["mode"] == "work"
        assert call["repo"] == tmp_path


def test_max_episodes_flag_sets_the_cap(tmp_path: Path) -> None:
    chain_calls: list = []
    rc = run_session(
        _make_args(tmp_path, until_done=True, max_episodes=3),
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_work(),
        _chain_fn=_ok_chain(chain_calls),
        _color=False,
    )
    assert rc == 0
    assert [c["cap"] for c in chain_calls] == [3]


def test_config_json_arms_the_session_chain(tmp_path: Path) -> None:
    """The same env/config.json legs as work: {"until_done": true} arms a
    flag-less session (resolution via EngineConfig.resolve + the shared
    _resolve_chain_arming)."""
    _write_config(tmp_path, {"until_done": True, "max_episodes": 2})
    chain_calls: list = []
    rc = run_session(
        _make_args(tmp_path),  # no chain flags at all
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_work(),
        _chain_fn=_ok_chain(chain_calls),
        _color=False,
    )
    assert rc == 0
    assert [c["cap"] for c in chain_calls] == [2]


def test_explicit_flag_cap_beats_config_json(tmp_path: Path) -> None:
    _write_config(tmp_path, {"until_done": True, "max_episodes": 5})
    chain_calls: list = []
    rc = run_session(
        _make_args(tmp_path, until_done=True, max_episodes=2),
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_work(),
        _chain_fn=_ok_chain(chain_calls),
        _color=False,
    )
    assert rc == 0
    assert [c["cap"] for c in chain_calls] == [2]


# ---------------------------------------------------------------------------
# --max-steps survives the work-mode profile (#336)
# ---------------------------------------------------------------------------


def test_max_steps_flag_survives_the_work_mode_profile(tmp_path: Path) -> None:
    """#336: run_session must mirror cmd_work's config.explicit_knobs guard
    (work.py:1701-1703). Every session dispatch runs with mode="work"
    (_run_work) and apply_mode_profile — via work._moded_config, the exact
    path execute_work runs before the engine starts — refills any knob NOT
    named in config.explicit_knobs from the work profile's default. The work
    profile's max_steps (40) happens to equal today's built-in default, so an
    UNMARKED explicit --max-steps=5 would silently be clobbered back to 40."""
    work_calls: list = []
    rc = run_session(
        _make_args(tmp_path, max_steps=5),
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_work(work_calls),
        _color=False,
    )
    assert rc == 0
    assert len(work_calls) == 1
    dispatched = work_calls[0]
    effective = work_mod._moded_config(dispatched["config"], dispatched["mode"], dispatched["repo"])
    assert effective.max_steps == 5


# ---------------------------------------------------------------------------
# End-to-end: the session front drives a REAL two-episode chain (mock engine)
# ---------------------------------------------------------------------------


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "init")
    return repo


def _script_two_episode_chain(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Mock script: episode 1 budget-exits after one write; episode 2 finishes."""
    counter = {"n": 0}

    def fake_script(task):
        counter["n"] += 1
        n = counter["n"]

        def complete(_messages):
            if n == 1:
                return ModelResponse(
                    content="episode 1 still working",
                    tool_calls=[
                        ToolCall(
                            "e1",
                            "write_file",
                            {"path": "episode-1.txt", "content": "episode 1 work\n"},
                        )
                    ],
                    prompt_tokens=1,
                    completion_tokens=1,
                )
            return ModelResponse(
                content="done",
                tool_calls=[ToolCall("fin", "finish", {"summary": "chain complete"})],
                prompt_tokens=1,
                completion_tokens=1,
            )

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", fake_script)
    return counter


def _lineage_artifacts(repo: Path) -> list[dict]:
    from colleague.artifact import find_artifact

    last = (repo / ".colleague" / "last_work").read_text().strip()
    chain: list[dict] = []
    task_id: str | None = last
    while task_id:
        path = find_artifact(repo, task_id)
        assert path is not None, f"artifact missing for {task_id}"
        data = json.loads(path.read_text())
        chain.append(data)
        task_id = data.get("continued_from")
    chain.reverse()
    return chain


def test_armed_session_runs_a_real_two_episode_chain(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """One armed session work line = one full chain: episode 1 budget-exits,
    episode 2 continues from its artifact and finishes ok — lineage stamped,
    the chain view accumulated, the t6 episode diagnostics on stderr. This
    drives the REAL execute_work_chain through the session (no fakes), so the
    session front provably reaches the same chain semantics as work."""
    # --max-steps (not the env workaround) keeps the knob operator-decided:
    # run_session now marks it on config.explicit_knobs (#336), the same
    # guard cmd_work uses, so the session's work-mode profile cannot refill
    # it (h1 semantics) even though this rides the flag path, not env.
    _script_two_episode_chain(monkeypatch)
    rc = run_session(
        _make_args(git_repo, until_done=True, max_episodes=4, max_steps=1),
        input_fn=iter(["add a CONTRIBUTING.md file", "q"]),
        out=_CollectingOut(),
        _color=False,
    )
    assert rc == 0
    lineage = _lineage_artifacts(git_repo)
    assert len(lineage) == 2  # episode 2 continued episode 1
    assert lineage[0].get("continued_from") is None
    assert lineage[1]["continued_from"] == lineage[0]["task_id"]
    assert lineage[1]["status"] == "ok"
    view = lineage[1].get("chain")
    assert view is not None and view["episode_count"] == 2
    err = capsys.readouterr().err
    assert "chain: episode 1" in err  # the t6 transition diagnostics flow on stderr
    assert "chain: completed after 2 episode(s)" in err

"""End-to-end agent-native default-session integration (#238 t4).

Demonstrates that the three facets of "colleague is agent-native by default" ship as
ONE default experience in a single session — not three disconnected features — with
the three success signals observable from the recorded session output (no insider
knowledge required):

  1. conversational default on colleague's OWN backend   (#234 / t1)
  2. a legible action feed                                 (#233 / t2)
  3. a pre-use AgentFront-surface probe reflex             (#235 / t3)

The session is driven through the real ``run_session`` seams and the real
``progress_target`` → sink → reducer chain, so the assertions exercise the shipped
code paths rather than re-deriving them. Live-infra reachability (the after-state on
the served 27B, not a mock) is covered separately by the ``COLLEAGUE_VLLM_E2E`` live
suite and the documented CLI smoke; this headless scenario is the CI-able proof that
the three facets compose.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from colleague import registry
from colleague.cli._commands.session import run_session
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.loop import _DEFAULT_SYSTEM
from colleague.tui.from_work import progress_target


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _silent(*args: object, **kwargs: object) -> None:
    pass


def _make_args(tmp_path: Path) -> argparse.Namespace:
    # engine=None + no env → resolve_session_engine falls through to the built-in
    # default (colleague's own served backend).
    return argparse.Namespace(
        repo=str(tmp_path),
        engine=None,
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )


def _make_233_work_fn(capture: dict) -> object:
    """A fake work_fn that captures the resolved backend and replays the #233 mesh
    scenario through the REAL progress_target → progress_sink → reducer chain."""

    def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
        capture["engine_name"] = kwargs.get("engine_name")
        display = kwargs.get("display")
        sink = display.sink if display is not None else None
        task = kwargs.get("task")
        # Four identical culture calls (the #233 spam) followed by a long command.
        culture_args = {"cli": "agtag", "args": ["issues", "fetch"]}
        for i in range(4):
            sink(i, "culture", progress_target(culture_args), True)  # type: ignore[misc]
        long_cmd = {
            "command": 'grep -ri "reterminal" . --include="*.md" --include="*.py" '
            "2>/dev/null | head -30"
        }
        sink(4, "run_command", progress_target(long_cmd), True)  # type: ignore[misc]
        tid = task.id if task is not None else "e2e"  # type: ignore[union-attr]
        return TaskResult(task_id=tid, status=OK, summary="done"), Path("/dev/null")

    return _work_fn


def test_three_facets_ship_as_one_default_experience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COLLEAGUE_SESSION_ENGINE", raising=False)
    monkeypatch.delenv("COLLEAGUE_ENGINE", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ENGINE", raising=False)

    capture: dict = {}
    out = _CollectingOut()

    # A subcommand-naive operator types a free-text goal — no verb named.
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["check the mesh issues and clean them up", "q"]),
        out=out,
        err=_silent,
        _work_fn=_make_233_work_fn(capture),
        _color=False,
    )
    rendered = out.text()

    # ── Facet 1 (#234): conversational default on colleague's OWN backend ──────
    # The free-text goal reached the underlying verb (work_fn fired) without the
    # user typing a subcommand, on the default served backend.
    assert capture.get("engine_name") == "vllm-openai", "session must default to own backend"

    # ── Facet 2 (#233): the action feed is legible ────────────────────────────
    # Grouped (no Nx duplicated [culture] lines), 'what ran + on what', and the long
    # command is not cut past the operative part.
    assert "[culture] agtag issues fetch ×4" in rendered, rendered
    assert "[culture]\n[culture]" not in rendered, "duplicate [culture] spam must be gone"
    assert "head -30" in rendered, "long command must not be truncated past understanding"

    # ── Facet 3 (#235): the SAME backend's prompt carries the AgentFront reflex ─
    engine = registry.load(capture["engine_name"])
    task = Task.new(str(tmp_path), "check the mesh")
    prompt = engine.system_prompt(task, EngineConfig.resolve(repo_path=tmp_path)) or _DEFAULT_SYSTEM
    lower = prompt.lower()
    assert "agentfront" in lower, "the agent's prompt must carry the AgentFront reflex"
    assert "before" in lower and "first" in lower, "the reflex must be a pre-first-use probe"


def test_success_signals_observable_from_feed_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Success signal #2 sharpened: from the feed text ALONE a reader can say exactly
    which tools ran and on what — no dedupe noise, no hidden truncation."""
    monkeypatch.delenv("COLLEAGUE_SESSION_ENGINE", raising=False)
    monkeypatch.delenv("COLLEAGUE_ENGINE", raising=False)

    capture: dict = {}
    out = _CollectingOut()
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["audit the repo for reterminal references", "q"]),
        out=out,
        err=_silent,
        _work_fn=_make_233_work_fn(capture),
        _color=False,
    )
    rendered = out.text()
    # Every distinct action is reconstructable: the mesh read (with its subject), the
    # directory-independent grep — and the repeated mesh read is counted, not stacked.
    assert "[culture] agtag issues fetch ×4" in rendered
    assert "[run_command] grep -ri" in rendered
    assert "..." not in rendered.split("[run_command]")[-1], "the command tail must be intact"


def test_session_help_documents_the_agent_native_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """t5 validation / doc-drift guard: `colleague session --help` must surface the
    agent-native default (routing + the session backend override) so the shipped help
    can't silently regress below the spec's before→after."""
    from colleague.cli import main

    # The rendered CLI returns 0 for a verb's --help (argparse's internal exit is
    # caught + translated by agentfront run_cli); exit-code-equivalent via __main__.
    rc = main(["session", "--help"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "agent-native" in out, "help must name the agent-native entry point"
    assert "work" in out and "plan" in out, "help must mention work/plan routing"
    assert "rout" in out, "help must describe intent routing of a free-text goal"
    assert "colleague_session_engine" in out, "help must document the session backend override"

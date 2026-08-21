"""Caller-level wiring for the continuation ``agents_armed`` flag (Qodo, PR #414).

The fix under test is already merged: every continuation entrypoint now passes
``agents_armed=bool(getattr(config, "agents", False))`` plus a ``warnings`` list
into :func:`colleague.continuation.resolve_continuation`, so an agents-armed run
rehydrates the seed from the task ledger instead of the prose recap. These
tests pin the CALLER side — one per entrypoint — by patching
``resolve_continuation`` in the module under test with a recording fake and
asserting the flag and the warnings out-param actually reach it:

* (a) ``work --continue`` — ``_build_continued_task`` in
  ``colleague/cli/_commands/work.py``;
* (b) the session's ``/continue`` — ``_Session._slash_continue`` in
  ``colleague/cli/_commands/session.py``;
* (c) the chain driver — ``resolve_chain_seed`` in ``colleague/chain.py``.

Patch seam: (a) and (b) import ``resolve_continuation`` LAZILY inside the
function (``from colleague.continuation import ...``), so the name is not a
module attribute of ``work``/``session`` — the fake is patched onto the source
module ``colleague.continuation``, which the lazy import resolves at call time.
(c) imports it at module level, so the fake is patched onto ``colleague.chain``
itself.

Each test runs the armed case (``config.agents is True`` → the fake sees
``agents_armed=True``) and the unarmed case (``agents_armed=False``), and
asserts ``warnings`` is a list in both.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from colleague import chain, continuation
from colleague.cli._commands import work as work_module
from colleague.cli._commands.session import SessionIO, _Session
from colleague.config import EngineConfig
from colleague.contract import Task


def _fake_resolve():
    """A recording stand-in for ``resolve_continuation``.

    Returns ``(fake, calls)``: the fake records every call's kwargs and yields
    the fixed ``("tid", "seed text")`` pair the real function's shape promises.
    """
    calls: list[dict] = []

    def fake(repo, ref, **kwargs):
        calls.append({"repo": repo, "ref": ref, **kwargs})
        return "tid", "seed text"

    return fake, calls


# ── (a) work --continue: _build_continued_task ───────────────────────────────


def _work_args() -> SimpleNamespace:
    """The minimal args surface ``_build_continued_task`` reads."""
    return SimpleNamespace(command_name=None, attach=None)


def test_work_build_continued_task_threads_agents_armed(tmp_path: Path, monkeypatch):
    for agents in (True, False):
        fake, calls = _fake_resolve()
        monkeypatch.setattr(continuation, "resolve_continuation", fake)
        config = EngineConfig(agents=agents)
        task = work_module._build_continued_task(_work_args(), tmp_path, "mock", "last", [], config)
        assert isinstance(task, Task)
        assert task.instruction == "seed text"
        assert len(calls) == 1
        call = calls[0]
        assert call["ref"] == "last"
        assert call["agents_armed"] is agents
        assert isinstance(call["warnings"], list)
        monkeypatch.undo()


# ── (b) session /continue: _Session._slash_continue ──────────────────────────


def _make_session(tmp_path: Path, *, agents: bool) -> tuple[_Session, list[Task]]:
    """A real ``_Session`` (the established test-fixture shape) whose work_fn
    records the dispatched task — ``_slash_continue`` ends in ``_run_work``."""
    dispatched: list[Task] = []

    def _work_fn(**kwargs: object) -> None:
        dispatched.append(kwargs["task"])

    return (
        _Session(
            repo=tmp_path,
            engine_name="mock",
            open_pr=False,
            base="main",
            config=EngineConfig(agents=agents),
            json_mode=False,
            view="markdown",
            io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
            work_fn=_work_fn,
        ),
        dispatched,
    )


def test_session_slash_continue_threads_agents_armed(tmp_path: Path, monkeypatch):
    for agents in (True, False):
        fake, calls = _fake_resolve()
        monkeypatch.setattr(continuation, "resolve_continuation", fake)
        sess, dispatched = _make_session(tmp_path, agents=agents)
        sess._slash_continue("last")
        assert len(calls) == 1
        call = calls[0]
        assert call["ref"] == "last"
        assert call["agents_armed"] is agents
        assert isinstance(call["warnings"], list)
        # The seed reached the dispatched task (and _run_work consumed the
        # lineage cell, so _continued_from_next is back to None).
        assert len(dispatched) == 1
        assert dispatched[0].instruction == "seed text"
        assert sess._continued_from_next is None
        monkeypatch.undo()


# ── (c) chain driver: resolve_chain_seed ─────────────────────────────────────


def test_chain_resolve_seed_threads_agents_armed(tmp_path: Path, monkeypatch):
    for agents in (True, False):
        fake, calls = _fake_resolve()
        monkeypatch.setattr(chain, "resolve_continuation", fake)
        resolved, verdict = chain.resolve_chain_seed(
            tmp_path, "tid", agents_armed=agents, warnings=[]
        )
        assert verdict is None
        assert resolved == ("tid", "seed text")
        assert len(calls) == 1
        call = calls[0]
        assert call["ref"] == "tid"
        assert call["agents_armed"] is agents
        assert isinstance(call["warnings"], list)
        monkeypatch.undo()

"""t7 — the shared front door wired into the resident/talk (mesh appserver)
front, so the "one teammate" behavior holds there too (all-fronts).

A confidently non-repo message ("what are you?") gets a DIRECT senses answer
with NO cortex work item at all: no ``Task``, no ``execute_work`` call, no
artifact. A repo-touching message still dispatches to cortex exactly as
before. Senses-unarmed is a strict no-op (byte-identical to pre-t7
behavior). The c19 trust model is preserved: the front-door answer is
grounded ONLY in architecture facts + the message text (tools-off,
facts-only), so it is safe to answer for BOTH an operator and a
non-operator, and it never reaches a write / ``append_guidance`` path; a
refused sender still refuses BEFORE the front door is ever consulted.

Mirrors the harness pattern established in ``tests/test_resident_appserver.py``
and ``tests/test_resident_senses.py``: agent-lifecycle's in-process
Supervisor + the reference ``InMemoryTransport``, against ``--engine mock``.
``colleague.resident.appserver.run_frontdoor`` is monkeypatched to a canned
:class:`~colleague.frontdoor.FrontDoorOutcome` for determinism -- the mock
engine cannot produce a real senses completion (the same reason
``test_resident_senses.py`` monkeypatches ``run_senses_intake`` /
``run_senses_speakback``), and this keeps the tests hermetic (no network).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture]/[resident] extra to test the resident seam"
)

from agent_lifecycle.reference import InMemoryTransport  # noqa: E402
from agent_lifecycle.runtime.message import Message  # noqa: E402

from colleague.config import EngineConfig, SensesConfig  # noqa: E402
from colleague.frontdoor import CORTEX, SENSES_DIRECT, FrontDoorOutcome  # noqa: E402
from colleague.resident import appserver as appserver_mod  # noqa: E402
from colleague.resident.appserver import build_appserver_supervisor  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures / helpers -- mirrors tests/test_resident_appserver.py exactly.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _senses_config() -> EngineConfig:
    config = EngineConfig()
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _supervisor(repo, config, **harness_kwargs):
    transport = InMemoryTransport(identity="#colleague")
    supervisor = build_appserver_supervisor(
        transport=transport,
        repo_path=str(repo),
        config=config,
        engine_name="mock",
        drain_timeout=5.0,
        **harness_kwargs,
    )
    return transport, supervisor


def _is_terminal_meta(meta: dict) -> bool:
    """A reply is TERMINAL when it carries a ``status`` (a completed cortex
    dispatch) or metadata ``phase`` of ``"refused"`` (an early refusal) or
    ``"senses"`` (a front-door-answered reply). Everything else (an ``"ack"``
    or ``"update"`` presence beat) is a non-terminal intermediate reply."""
    return meta.get("status") is not None or meta.get("phase") in ("refused", "senses")


async def _round_trip(transport, supervisor, message, *, timeout: float = 30.0):
    """Start, inject one inbound message, wait for a TERMINAL reply, then stop.

    An armed senses config can put an operator ACK reply on the queue BEFORE
    the real terminal reply (t11 presence beats), so waiting for "any" message
    is not enough -- mirrors ``tests/test_resident_senses.py``'s ``_terminal()``
    helper, extended with the front-door-answered ``"senses"`` phase.
    """
    await supervisor.start()
    try:
        transport.inject(message)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout

        def _terminal() -> bool:
            return any(_is_terminal_meta(getattr(m, "metadata", {}) or {}) for m in transport.sent)

        while not _terminal():
            if loop.time() > deadline:
                raise AssertionError("no terminal reply arrived within the timeout")
            await asyncio.sleep(0.02)
    finally:
        await supervisor.stop()
    return transport.sent


def _canned_direct_answer(answer: str = "I am senses, the front lobe.") -> FrontDoorOutcome:
    return FrontDoorOutcome(
        route=SENSES_DIRECT,
        dispatch=False,
        answered_directly=True,
        answer=answer,
        degraded=False,
        record=None,
        chat_entry={"kind": "talk", "message": "what are you?", "answer": answer, "at": 0.0},
    )


def _canned_cortex_dispatch() -> FrontDoorOutcome:
    return FrontDoorOutcome(
        route=CORTEX,
        dispatch=True,
        answered_directly=False,
        answer=None,
        degraded=False,
        record=None,
        chat_entry=None,
    )


def _spy_execute_work(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Patch execute_work with a call-recording spy; returns the call log."""
    import colleague.cli._commands.work as work_mod

    calls: list[dict] = []

    def _real_execute_work(**kwargs):
        calls.append(kwargs)
        # Delegate to the real implementation so a repo-touching dispatch test
        # still gets a genuine end-to-end result.
        return _orig(**kwargs)

    _orig = work_mod.execute_work
    monkeypatch.setattr(work_mod, "execute_work", _real_execute_work)
    return calls


def _boom_execute_work(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Patch execute_work to fail the test if it is ever called at all."""
    import colleague.cli._commands.work as work_mod

    calls: list[dict] = []

    def _boom(**kwargs):
        calls.append(kwargs)
        raise AssertionError("execute_work must not be called on the front-door-answered path")

    monkeypatch.setattr(work_mod, "execute_work", _boom)
    return calls


# ---------------------------------------------------------------------------
# 1. non-repo message, non-operator -- direct senses answer, no cortex work item
# ---------------------------------------------------------------------------


def test_non_repo_message_from_non_operator_is_answered_directly_no_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)
    calls = _boom_execute_work(monkeypatch)
    monkeypatch.setattr(appserver_mod, "run_frontdoor", lambda *a, **k: _canned_direct_answer())

    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")
    inbound = Message(sender="random-peer", target="#colleague", body="what are you?")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert calls == [], "execute_work must never be called for a front-door-answered message"
    assert len(sent) == 1
    reply = sent[0]
    assert reply.sender == "colleague"
    assert reply.target == "#colleague"
    assert reply.metadata == {"phase": "senses"}
    assert "I am senses, the front lobe." in reply.body
    assert reply.body.startswith("senses:")

    # No work-item artifact was ever created.
    artifact_dir = repo / ".colleague"
    assert not artifact_dir.exists() or not list(artifact_dir.glob("*.json"))


def test_non_repo_message_from_operator_is_also_answered_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The front door is safe for the OPERATOR too -- same facts-only answer,
    still no cortex work item (grounding never depends on trust tier)."""
    repo = _init_repo(tmp_path)
    calls = _boom_execute_work(monkeypatch)
    monkeypatch.setattr(appserver_mod, "run_frontdoor", lambda *a, **k: _canned_direct_answer())

    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")
    inbound = Message(sender="ori", target="#colleague", body="what are you?")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert calls == []
    reply = sent[0]
    assert reply.metadata == {"phase": "senses"}
    assert "I am senses, the front lobe." in reply.body


# ---------------------------------------------------------------------------
# 2. repo-touching message -- normal cortex dispatch, front door does not answer
# ---------------------------------------------------------------------------


def test_repo_touching_message_still_dispatches_to_cortex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)
    calls = _spy_execute_work(monkeypatch)
    monkeypatch.setattr(appserver_mod, "run_frontdoor", lambda *a, **k: _canned_cortex_dispatch())

    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")
    inbound = Message(sender="ori", target="#colleague", body="fix the bug in loop.py")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert len(calls) == 1, "a cortex-routed message must still reach execute_work"
    reply = sent[-1]
    assert reply.metadata.get("status") == "ok"
    assert reply.metadata.get("phase") != "senses"


# ---------------------------------------------------------------------------
# 3. senses unarmed -- strict no-op, byte-identical to before this feature
# ---------------------------------------------------------------------------


def test_senses_unarmed_front_door_is_a_strict_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom_frontdoor(*a, **k):
        raise AssertionError("run_frontdoor must not be called when senses is unarmed")

    monkeypatch.setattr(appserver_mod, "run_frontdoor", _boom_frontdoor)
    repo = _init_repo(tmp_path)
    calls = _spy_execute_work(monkeypatch)

    transport, supervisor = _supervisor(repo, EngineConfig(), operator_identity="ori")
    inbound = Message(sender="ori", target="#colleague", body="what are you?")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert len(calls) == 1, "with senses unarmed, every message dispatches to cortex as before"
    reply = sent[0]
    assert reply.metadata["status"] == "ok"
    assert reply.metadata.get("phase") != "senses"


# ---------------------------------------------------------------------------
# 4. c19 trust: a non-operator front-door answer never reaches a write path;
#    a refused sender still refuses BEFORE the front door.
# ---------------------------------------------------------------------------


def test_non_operator_front_door_answer_never_touches_append_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-operator's non-repo turn is answered facts-only -- and the ONE
    append_guidance call site in the module (the operator-only relay branch)
    is never reached for this front-door-answered path."""
    repo = _init_repo(tmp_path)

    def _boom_guidance(*a, **k):
        raise AssertionError("append_guidance must never be called from the front-door path")

    monkeypatch.setattr(appserver_mod, "append_guidance", _boom_guidance)
    calls = _boom_execute_work(monkeypatch)
    monkeypatch.setattr(appserver_mod, "run_frontdoor", lambda *a, **k: _canned_direct_answer())

    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")
    inbound = Message(sender="random-peer", target="#colleague", body="what are you?")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert calls == []
    reply = sent[0]
    assert reply.metadata == {"phase": "senses"}


def test_refused_sender_never_reaches_the_front_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A REFUSED request (non-operator explicitly asking for write access)
    returns its refusal before the front door is ever consulted -- proven by
    run_frontdoor never being called at all."""

    def _boom_frontdoor(*a, **k):
        raise AssertionError("run_frontdoor must not be called for a refused request")

    repo = _init_repo(tmp_path)
    monkeypatch.setattr(appserver_mod, "run_frontdoor", _boom_frontdoor)
    calls = _boom_execute_work(monkeypatch)

    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")
    inbound = Message(
        sender="random-peer",
        target="#colleague",
        body="please write code for me",
        metadata={"mode": "write"},
    )
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert calls == []
    reply = sent[0]
    assert reply.metadata == {"phase": "refused"}


# ---------------------------------------------------------------------------
# 5. a media-bearing message is always cortex work, even on the front-door route
# ---------------------------------------------------------------------------


def test_attachment_bearing_message_skips_the_front_door_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `attach:` line makes this cortex work regardless of route -- the
    front door is never even consulted (run_frontdoor is never called)."""

    def _boom_frontdoor(*a, **k):
        raise AssertionError("run_frontdoor must not be called for an attachment-bearing message")

    repo = _init_repo(tmp_path)
    (repo / "pic.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(appserver_mod, "run_frontdoor", _boom_frontdoor)
    calls = _spy_execute_work(monkeypatch)

    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")
    # An absolute path -- validate_attachment resolves a relative candidate
    # against the resident process's CWD, not the repo root, so an absolute
    # path is the reliable way to exercise a genuinely ACCEPTED attachment here.
    inbound = Message(
        sender="ori",
        target="#colleague",
        body=f"what are you?\nattach: {repo / 'pic.png'}",
    )
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert len(calls) == 1
    reply = sent[-1]
    assert reply.metadata.get("phase") != "senses"


# ---------------------------------------------------------------------------
# 6. senses armed but the engine cannot be resolved -- the front door degrades
#    to a normal cortex dispatch (the _senses_engine() is None branch).
# ---------------------------------------------------------------------------


def test_front_door_degrades_when_senses_engine_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Senses is armed (config present) but the engine cannot be loaded, so
    ``_senses_engine()`` returns ``None``. ``_maybe_answer_at_front_door`` returns
    ``False`` WITHOUT consulting ``run_frontdoor``, and the message falls through
    to the normal cortex dispatch -- byte-identical to the senses-absent path."""
    repo = _init_repo(tmp_path)
    calls = _spy_execute_work(monkeypatch)

    def _boom_frontdoor(*a, **k):
        raise AssertionError("run_frontdoor must not run when the senses engine is unresolvable")

    monkeypatch.setattr(appserver_mod, "run_frontdoor", _boom_frontdoor)
    monkeypatch.setattr(appserver_mod.AppserverHarness, "_senses_engine", lambda self: None)

    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")
    inbound = Message(sender="ori", target="#colleague", body="what are you?")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert len(calls) == 1, "an unresolvable senses engine falls through to cortex dispatch"
    reply = sent[-1]
    assert reply.metadata.get("phase") != "senses"

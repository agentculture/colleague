"""t13 — AppserverHarness: colleague implements agent-lifecycle's Harness to
accept mesh WORK REQUESTS and run them as real colleague work items (not bare
chat turns), gated by the c19 trust model.

Proven end-to-end against agent-lifecycle's in-process ``Supervisor`` and the
reference ``InMemoryTransport`` — no IRC, no network (h15: a real mesh
transport for work *requests* is PENDING until upstream ships one). Each
accepted request is dispatched through the SAME ``execute_work`` orchestration
``colleague work`` itself uses (against ``--engine mock``, deterministic, no
live server), so the resulting artifact/branch/status assertions below are a
genuine end-to-end proof, not a mock of colleague's own machinery.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture]/[resident] extra to test the resident seam"
)

from agent_lifecycle.reference import InMemoryTransport  # noqa: E402
from agent_lifecycle.runtime.harness import Harness  # noqa: E402
from agent_lifecycle.runtime.message import Message  # noqa: E402
from agent_lifecycle.runtime.supervisor import Supervisor, SupervisorStatus  # noqa: E402

from colleague.cli._errors import CliError  # noqa: E402
from colleague.config import EngineConfig  # noqa: E402
from colleague.resident.appserver import (  # noqa: E402
    AppserverHarness,
    build_appserver_supervisor,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
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


def _supervisor(repo, **harness_kwargs):
    transport = InMemoryTransport(identity="#colleague")
    supervisor = build_appserver_supervisor(
        transport=transport,
        repo_path=str(repo),
        config=EngineConfig(),
        engine_name="mock",
        drain_timeout=5.0,
        **harness_kwargs,
    )
    return transport, supervisor


async def _round_trip(transport, supervisor, message, *, timeout: float = 30.0):
    """Start, inject one inbound message, wait for its reply, then stop."""
    await supervisor.start()
    try:
        transport.inject(message)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while not transport.sent:
            if loop.time() > deadline:
                raise AssertionError("no reply arrived within the timeout")
            await asyncio.sleep(0.02)
    finally:
        await supervisor.stop()
    return transport.sent


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_satisfies_harness_protocol(tmp_path: Path) -> None:
    """AppserverHarness structurally satisfies agent_lifecycle's Harness Protocol."""
    h = AppserverHarness(str(tmp_path), EngineConfig(), engine_name="mock")
    assert isinstance(h, Harness)


def test_build_returns_unstarted_supervisor(tmp_path: Path) -> None:
    _transport, supervisor = _supervisor(tmp_path, operator_identity="ori")
    assert isinstance(supervisor, Supervisor)
    assert supervisor.status() is SupervisorStatus.STOPPED


# ---------------------------------------------------------------------------
# c19 trust model, end to end
# ---------------------------------------------------------------------------


def test_operator_request_becomes_a_real_work_item_end_to_end(tmp_path: Path) -> None:
    """An operator request is dispatched unrestricted -- write + local handoff."""
    repo = _init_repo(tmp_path)
    transport, supervisor = _supervisor(repo, operator_identity="ori", open_pr=False)

    inbound = Message(sender="ori", target="#colleague", body="write a mock file")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert len(sent) == 1
    reply = sent[0]
    assert reply.sender == "colleague"
    assert reply.target == "#colleague"
    assert reply.metadata["status"] == "ok"
    assert reply.metadata["role"] is None
    assert "mock wrote colleague-mock.md" in reply.body

    artifact_path = Path(reply.metadata["artifact"])
    assert artifact_path.is_file(), "the reply must carry a real artifact pointer"
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert data["status"] == "ok"
    assert data["branch"], "a write-capable dispatch commits onto its own work branch"
    assert data["pr_url"] is None, "open_pr=False -> local commit only, no PR"
    assert "colleague-mock.md" in data["changed_files"]

    # Isolation (#196/#201): the operator's own checked-out tree is untouched.
    assert not (repo / "colleague-mock.md").exists()


def test_non_operator_request_is_downgraded_to_read_only(tmp_path: Path) -> None:
    """A non-operator's plain request runs read-only -- no handoff, no branch."""
    repo = _init_repo(tmp_path)
    transport, supervisor = _supervisor(repo, operator_identity="ori", open_pr=False)

    inbound = Message(sender="random-peer", target="#colleague", body="investigate the repo")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert reply.metadata["role"] == "explorer"

    artifact_path = Path(reply.metadata["artifact"])
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert data.get("branch") is None, "a read-only dispatch never reaches the git handoff"
    assert data.get("pr_url") is None


def test_non_operator_explicit_write_request_is_refused_with_no_dispatch(tmp_path: Path) -> None:
    """A non-operator's EXPLICIT write request is refused before any work runs."""
    repo = _init_repo(tmp_path)
    transport, supervisor = _supervisor(repo, operator_identity="ori")

    inbound = Message(
        sender="random-peer",
        target="#colleague",
        body="please write code for me",
        metadata={"mode": "write"},
    )
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert reply.metadata == {"phase": "refused"}
    assert "random-peer" in reply.body
    assert "operator" in reply.body.lower()

    # Nothing was ever dispatched -- no artifact directory materialised.
    artifact_dir = repo / ".colleague"
    assert not artifact_dir.exists() or not list(artifact_dir.glob("*.json"))


def test_unresolved_operator_identity_downgrades_every_request(tmp_path: Path) -> None:
    """With no operator configured, even a plausible 'operator-shaped' sender is
    still treated as non-operator (fail-safe: no accidental write grant)."""
    repo = _init_repo(tmp_path)
    transport, supervisor = _supervisor(repo, operator_identity=None)

    inbound = Message(sender="ori", target="#colleague", body="do something")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert reply.metadata["role"] == "explorer"


# ---------------------------------------------------------------------------
# Failure surfacing (spec: "supervision failures surface via failure(), never
# silently swallowed")
# ---------------------------------------------------------------------------


def test_expected_work_item_failure_is_caught_and_replied_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CliError (an ordinary "this task failed") is caught -> a graceful error
    reply, and the supervisor stays healthy (no FAILED transition)."""
    repo = _init_repo(tmp_path)
    import colleague.cli._commands.work as work_mod

    def _raise_cli_error(**_kwargs):
        raise CliError(2, "engine 'mock' failed: boom", "check the engine config")

    monkeypatch.setattr(work_mod, "execute_work", _raise_cli_error)

    transport, supervisor = _supervisor(repo, operator_identity="ori")
    inbound = Message(sender="ori", target="#colleague", body="do work")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert supervisor.status() is SupervisorStatus.STOPPED
    assert supervisor.failure() is None
    reply = sent[0]
    assert reply.metadata["status"] == "error"
    assert "boom" in reply.body


def test_unexpected_exception_surfaces_via_supervisor_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuinely unexpected exception (not a CliError) is NOT swallowed here --
    it propagates so agent_lifecycle's Supervisor records it via failure()."""
    repo = tmp_path  # never reaches git/execute_work -- _dispatch is monkeypatched away
    transport = InMemoryTransport(identity="#colleague")
    harness = AppserverHarness(
        str(repo), EngineConfig(), engine_name="mock", operator_identity="ori"
    )

    def _boom(
        self, task, config, presence_sink=None
    ):  # noqa: ANN001 - matches the bound-method shape
        raise RuntimeError("boom - not a CliError, must not be swallowed")

    monkeypatch.setattr(AppserverHarness, "_dispatch", _boom)
    supervisor = Supervisor(transport, harness, drain_timeout=2.0)

    async def _body() -> None:
        await supervisor.start()
        transport.inject(Message(sender="ori", target="#colleague", body="hi"))
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 10.0
        while supervisor.status() is SupervisorStatus.RUNNING:
            if loop.time() > deadline:
                raise AssertionError("supervisor never transitioned to FAILED")
            await asyncio.sleep(0.02)
        await supervisor.stop()

    asyncio.run(_body())

    failure = supervisor.failure()
    assert failure is not None
    assert failure.which == "inbound"
    assert isinstance(failure.error, RuntimeError)
    assert supervisor.status() is SupervisorStatus.STOPPED  # stop() recovers cleanly from FAILED


# ---------------------------------------------------------------------------
# Structural: appserver.py deliberately DOES reach execute_work (the opposite
# of ColleagueHarness's h11 no-handoff invariant) -- pinned so a future edit
# that silently reverts to bare engine.work() is caught.
# ---------------------------------------------------------------------------


def test_appserver_reaches_execute_work_not_bare_engine_work() -> None:
    src = Path("colleague/resident/appserver.py").read_text(encoding="utf-8")
    assert "execute_work" in src
    assert "cli._commands.work" in src


def test_appserver_module_is_confined_to_no_new_subprocess() -> None:
    """The appserver dispatches via execute_work, not a new subprocess consumer."""
    src = Path("colleague/resident/appserver.py").read_text(encoding="utf-8")
    assert "import subprocess" not in src

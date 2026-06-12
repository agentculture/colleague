"""t2 — ColleagueHarness: colleague's bounded loop as an agent-lifecycle Harness.

Covers spec targets c3 (resident can respond), c5 (continuous collaboration),
h8 (durable across turns) and h10 (the bounded step cap bounds a turn, never the
session). Drives the async harness with a fake engine via asyncio.run (no
pytest-asyncio dependency) so the seam is exercised without a live model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture] extra to test the resident seam"
)

from agent_lifecycle.runtime.harness import Harness  # noqa: E402
from agent_lifecycle.runtime.message import Message  # noqa: E402

from colleague.contract import TaskResult  # noqa: E402
from colleague.resident.harness import ColleagueHarness  # noqa: E402


class _FakeEngine:
    """Records each work() call and returns a deterministic TaskResult.

    Stands in for a real backend so the harness seam is tested without a model.
    ``status_for`` lets a test force an 'incomplete' (step-cap-exhausted) turn.
    """

    def __init__(self, status_for=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._status_for = status_for or (lambda i: "completed")

    def work(self, task, config) -> TaskResult:
        self.calls.append((task.instruction, task.repo_path))
        return TaskResult(
            task_id=task.id,
            status=self._status_for(task.instruction),
            summary=f"reply to {task.instruction}",
        )


def _harness(monkeypatch, tmp_path: Path, engine: _FakeEngine, **kw) -> ColleagueHarness:
    monkeypatch.setattr("colleague.registry.load", lambda name: engine)
    return ColleagueHarness(
        str(tmp_path),
        SimpleNamespace(engine="mock"),
        engine_name="mock",
        **kw,
    )


async def _drive(harness: ColleagueHarness, bodies: list[str]) -> list[Message]:
    await harness.start()
    gen = harness.replies()
    out: list[Message] = []
    for body in bodies:
        await harness.feed_message(Message(sender="peer", target="#colleague", body=body))
        out.append(await gen.__anext__())
    await harness.stop()
    return out


def test_satisfies_harness_protocol(monkeypatch, tmp_path: Path) -> None:
    """ColleagueHarness structurally satisfies agent_lifecycle's Harness Protocol."""
    h = _harness(monkeypatch, tmp_path, _FakeEngine())
    assert isinstance(h, Harness)


def test_session_survives_n_messages(monkeypatch, tmp_path: Path) -> None:
    """h10: each message is one bounded turn; the session yields a reply per message."""
    engine = _FakeEngine()
    h = _harness(monkeypatch, tmp_path, engine)
    replies = asyncio.run(_drive(h, ["a", "b", "c"]))
    assert [r.body for r in replies] == ["reply to a", "reply to b", "reply to c"]
    assert len(engine.calls) == 3  # one bounded engine.work per message


def test_step_cap_exhausted_turn_does_not_end_session(monkeypatch, tmp_path: Path) -> None:
    """h10: a turn that exhausts its step budget ('incomplete') still replies and the
    session continues to the next message."""
    engine = _FakeEngine(status_for=lambda i: "incomplete" if i == "big" else "completed")
    h = _harness(monkeypatch, tmp_path, engine)
    replies = asyncio.run(_drive(h, ["small", "big", "after"]))
    assert [r.body for r in replies] == ["reply to small", "reply to big", "reply to after"]
    assert replies[1].metadata["status"] == "incomplete"  # the bounded turn ended...
    assert replies[2].body == "reply to after"  # ...but the session lived on


def test_reply_carries_nick_and_target(monkeypatch, tmp_path: Path) -> None:
    """The reply Message is sent as the resident (sender=nick) back to the source target."""
    h = _harness(monkeypatch, tmp_path, _FakeEngine(), agent_nick="spark-colleague")
    replies = asyncio.run(_drive(h, ["hi"]))
    assert replies[0].sender == "spark-colleague"
    assert replies[0].target == "#colleague"


def test_stop_ends_replies(monkeypatch, tmp_path: Path) -> None:
    """After stop(), the replies() generator terminates (StopAsyncIteration)."""

    async def _body() -> None:
        h = _harness(monkeypatch, tmp_path, _FakeEngine())
        await h.start()
        gen = h.replies()
        await h.stop()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    asyncio.run(_body())


def test_harness_does_not_touch_handoff(monkeypatch, tmp_path: Path) -> None:
    """h3 (additive): the resident turn runs the loop only — no git handoff / PR.

    Asserted structurally: the harness module never references the handoff/PR
    surface, so a conversational turn can never open a branch or PR.
    """
    import re

    src = Path("colleague/resident/harness.py").read_text(encoding="utf-8")
    # No import of, or call into, the handoff/PR surface — a conversational turn
    # must never branch/commit/PR. (The docstring may mention 'handoff' in prose.)
    assert not re.search(r"^\s*(import|from)\s+.*handoff", src, re.MULTILINE)
    assert not re.search(r"\bhandoff\.\w+\(", src)
    assert "execute_work" not in src  # the handoff-wrapping path is never used

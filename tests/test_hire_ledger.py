"""Plan t14 (delegation-follow-ups-a7-p3-hire, covers c38/h22): the
refs-not-payloads ``hire`` task-ledger event.

Acceptance criterion 1 under test: under an armed agents runtime (the
``agents_ledger_path`` attribute :class:`colleague.agents.runtime.AgentsRun`
sets on the resolved config — the documented "visible to every spawn closure
that captured this config" seam) a successful hire appends ONE task-ledger
event ``{agent_id, hirer_id, base_role, prompt_digest, when_digest,
artifact_ref}`` with NO prompt text, under 4096 bytes; unarmed appends
nothing. The ``hire`` kind is an ADDITIVE bump to the closed
:data:`colleague.agents.state.ledger.EVENT_KINDS` vocabulary; replay ignores
it (no snapshot collection moves).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from colleague.agents.state.ledger import (
    EVENT_KINDS,
    TaskLedger,
    derive_snapshot,
    read_ledger,
)
from colleague.contract import prompt_digest_for
from colleague.tools import ToolExecutor

_ARGS: dict[str, Any] = {
    "purpose": "survey wide code surfaces",
    "when": "whenever a brief spans more than five files",
    "base_role": "scout",
    "prompt": "You survey code and report digests with citations.",
}


class _FakeEngine:
    """A vllm-shaped engine double whose candidate replies are scripted."""

    name = "fake"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    def make_complete(self, config: Any, tools: Optional[list] = None):
        def complete(messages: list[dict[str, Any]]) -> Any:
            return SimpleNamespace(content=self.replies.pop(0))

        return complete


def _cfg(ledger_path: Optional[str] = None) -> SimpleNamespace:
    cfg = SimpleNamespace(hire=True, reasoning_effort=None)
    if ledger_path is not None:
        cfg.agents_ledger_path = ledger_path
    return cfg


def _executor(tmp_path, engine, cfg) -> ToolExecutor:
    def _spawn(*_a: Any, **_k: Any):  # pragma: no cover - a hire never spawns
        raise AssertionError("hire_colleague must never spawn a child")

    _spawn.parent_config = cfg
    _spawn.parent_engine = "fake"
    ex = ToolExecutor(tmp_path, spawn=_spawn)
    ex.hire_engine_loader = lambda _name: engine
    ex.task_id = "task-1"
    return ex


def _ledger_file(tmp_path):
    return tmp_path / ".colleague" / "ledger" / "task-1.jsonl"


# ---------------------------------------------------------------------------
# The additive vocabulary bump
# ---------------------------------------------------------------------------


def test_hire_is_a_closed_vocabulary_kind() -> None:
    """``hire`` joined EVENT_KINDS additively — every pre-t14 kind is intact."""
    assert "hire" in EVENT_KINDS
    for kind in (
        "operator_request",
        "operator_input",
        "constraint",
        "acceptance",
        "plan_node",
        "decision",
        "open_loop",
        "evidence",
        "working_set",
        "changed_path",
        "verification",
        "message",
        "delegate",
        "return",
        "invocation",
        "snapshot",
    ):
        assert kind in EVENT_KINDS


def test_replay_ignores_hire_events(tmp_path) -> None:
    """A ``hire`` event moves NO snapshot collection (refs live on the event)."""
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    led.append("hire", {"agent_id": "hire-1", "prompt_digest": "d" * 64})
    read = read_ledger(led.path)  # round-trips through the fail-closed reader
    assert [e.kind for e in read.events] == ["hire"]
    snap = derive_snapshot(read.events)
    assert snap.constraints == ()
    assert snap.decisions == ()
    assert snap.open_loops == ()
    assert snap.delegations == ()


# ---------------------------------------------------------------------------
# AC1 — armed appends exactly one refs-not-payloads event
# ---------------------------------------------------------------------------


def test_armed_hire_appends_one_refs_event(tmp_path) -> None:
    path = _ledger_file(tmp_path)
    ex = _executor(tmp_path, _FakeEngine(["accept"]), _cfg(str(path)))

    outcome = ex.execute("hire_colleague", dict(_ARGS))

    assert outcome.result.startswith("hired: hire-1")
    read = read_ledger(path)
    assert [e.kind for e in read.events] == ["hire"]
    event = read.events[0]
    assert set(event.data) == {
        "agent_id",
        "hirer_id",
        "base_role",
        "prompt_digest",
        "when_digest",
        "artifact_ref",
    }
    minted = ex.hire_roster.get("hire-1")
    assert event.data["agent_id"] == "hire-1"
    assert event.data["hirer_id"] == minted.hirer_id
    assert event.data["base_role"] == "scout"
    assert event.data["prompt_digest"] == minted.prompt_digest
    assert event.data["prompt_digest"] == prompt_digest_for(_ARGS["prompt"])
    assert event.data["when_digest"] == prompt_digest_for(_ARGS["when"])
    # The ref points at where the payload actually lives: the run artifact's
    # hires block (the text rides the artifact; the ledger carries digests).
    assert "task-1" in event.data["artifact_ref"]
    assert "hire-1" in event.data["artifact_ref"]


def test_the_event_carries_no_prompt_text_and_fits_the_cap(tmp_path) -> None:
    path = _ledger_file(tmp_path)
    ex = _executor(tmp_path, _FakeEngine(["accept"]), _cfg(str(path)))
    ex.execute("hire_colleague", dict(_ARGS))

    lines = path.read_text(encoding="utf-8").splitlines()
    event_line = lines[-1]
    assert _ARGS["prompt"] not in event_line  # NO authored prompt text
    assert _ARGS["when"] not in event_line  # NO when-clause text either
    assert len(event_line.encode("utf-8")) < 4096


def test_two_hires_append_two_events_in_order(tmp_path) -> None:
    path = _ledger_file(tmp_path)
    ex = _executor(tmp_path, _FakeEngine(["accept", "accept"]), _cfg(str(path)))
    ex.execute("hire_colleague", dict(_ARGS))
    ex.execute("hire_colleague", dict(_ARGS, base_role="writer"))
    read = read_ledger(path)
    assert [(e.kind, e.data["agent_id"]) for e in read.events] == [
        ("hire", "hire-1"),
        ("hire", "hire-2"),
    ]
    assert [e.seq for e in read.events] == [0, 1]


# ---------------------------------------------------------------------------
# AC1 — unarmed (or refused/failed) appends nothing
# ---------------------------------------------------------------------------


def test_unarmed_hire_appends_nothing(tmp_path) -> None:
    """No ``agents_ledger_path`` on the config (COLLEAGUE_AGENTS off, or the
    runtime never began): the hire mints, the ledger directory stays absent."""
    ex = _executor(tmp_path, _FakeEngine(["accept"]), _cfg())
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("hired: hire-1")
    assert not (tmp_path / ".colleague" / "ledger").exists()


def test_a_none_ledger_path_appends_nothing(tmp_path) -> None:
    cfg = _cfg()
    cfg.agents_ledger_path = None
    ex = _executor(tmp_path, _FakeEngine(["accept"]), cfg)
    assert ex.execute("hire_colleague", dict(_ARGS)).result.startswith("hired:")
    assert not (tmp_path / ".colleague" / "ledger").exists()


def test_a_declined_hire_appends_nothing_even_when_armed(tmp_path) -> None:
    path = _ledger_file(tmp_path)
    ex = _executor(tmp_path, _FakeEngine(["decline: busy", "decline: still busy"]), _cfg(str(path)))
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("not hired:")
    assert not path.exists()


def test_a_ledger_defect_never_unmints_the_hire(tmp_path) -> None:
    """A broken ledger path (here: a directory) degrades — the hire stands
    (the AgentsRun never-lose-the-work-item stance)."""
    broken = tmp_path / "ledger-dir"
    broken.mkdir()
    ex = _executor(tmp_path, _FakeEngine(["accept"]), _cfg(str(broken)))
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("hired: hire-1")
    assert ex.hire_roster.get("hire-1") is not None

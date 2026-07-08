"""Tests for the front-agnostic presence engine (presence-default-everywhere, t6).

Covers:
1. all beats driven through injected callbacks with no TTY/thread/clock, incl.
   the cadence cap + capped-is-recorded rule;
2. both lanes behind it (loop rung drives, off rung is a strict no-op), selected
   per the driver's rung;
3. the engine imports no front module (session / talk / resident) — an
   import-graph pin so fronts never import each other through it.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from colleague.contract import ContextPacket
from colleague.presence import UpdateCadence
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses_loop import RUNG_OFF, SensesLoopDriver


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning = ""
        self.prompt_tokens = 3
        self.completion_tokens = 5


def _make_complete(replies, *, default=None):
    seq = list(replies)
    idx = {"i": 0}
    default = default if default is not None else json.dumps({"move": "wait"})

    def make_complete(config, *, tools):  # noqa: ANN001
        assert tools == []

        def complete(messages):  # noqa: ANN001
            i = idx["i"]
            idx["i"] += 1
            return _FakeResp(seq[i] if i < len(seq) else default)

        return complete

    return make_complete


class _RecordingIO:
    def __init__(self, pending=None, flight="step 3/40 · editing foo.py"):
        self.dispatched: list = []
        self.guided: list = []
        self.rendered: list = []
        self.reads = 0
        self._pending = list(pending or [])
        self._flight = flight

    def _read(self):
        self.reads += 1
        return self._flight

    def _poll(self) -> Optional[str]:
        return self._pending.pop(0) if self._pending else None

    def io(self) -> PresenceIO:
        return PresenceIO(
            dispatch_to_cortex=self.dispatched.append,
            append_guidance=self.guided.append,
            read_flight=self._read,
            render=self.rendered.append,
            poll_operator_input=self._poll,
            feed_tail=lambda: self._flight,
            task_state=lambda: "step 3/40",
        )


def _config(budget: int = 24000):
    return SimpleNamespace(context_budget_tokens=budget)


def _engine(
    replies,
    *,
    io=None,
    cadence=None,
    senses_config="__armed__",
    default=None,
    history_provider=None,
):
    io = io if io is not None else _RecordingIO()
    cfg = _config() if senses_config == "__armed__" else senses_config
    driver = SensesLoopDriver(
        senses_config=cfg,
        make_complete=_make_complete(replies, default=default),
        executor=build_presence_executor(io.io()),
    )
    engine = PresenceEngine(
        driver=driver, io=io.io(), cadence=cadence, history_provider=history_provider
    )
    return engine, io


# ── 1. beats through injected IO ──────────────────────────────────────────────
def test_acknowledge_dispatches_verbatim_and_renders_ack() -> None:
    io = _RecordingIO()
    engine, io = _engine(
        [
            json.dumps(
                {
                    "move": "dispatch_to_cortex",
                    "instruction": "x",
                    "ack": "got it — cortex will fix the bug",
                }
            )
        ],
        io=io,
    )
    packet = ContextPacket(original="fix the null-deref bug in parser.py")
    engine.acknowledge(packet)
    # cortex received the operator's verbatim words ...
    assert io.dispatched and io.dispatched[0].startswith("fix the null-deref bug in parser.py")
    # ... and the operator saw the ack.
    assert any("got it — cortex will fix the bug" in line for line in io.rendered)


def test_operator_message_relays_guidance_and_renders() -> None:
    io = _RecordingIO()
    engine, io = _engine(
        # ack boundary dispatches; the later operator message relays guidance.
        [
            json.dumps({"move": "dispatch_to_cortex", "instruction": "build it"}),
            json.dumps({"move": "guide_cortex", "guidance": "look at config first"}),
        ],
        io=io,
    )
    engine.acknowledge(ContextPacket(original="build the feature"))
    io.dispatched.clear()
    engine.on_operator_message("focus on the config module")
    # the operator's verbatim words were injected into cortex as guidance ...
    assert io.guided and io.guided[0].startswith("focus on the config module")
    # ... and the relay is visible to the operator.
    assert any(line.startswith("→ cortex:") for line in io.rendered)


def test_read_flight_move_reads_via_io() -> None:
    io = _RecordingIO()
    engine, io = _engine(
        [
            json.dumps({"move": "read_flight"}),
            json.dumps({"move": "reply_to_operator", "text": "cortex is on step 3"}),
        ],
        io=io,
    )
    engine.on_operator_message("how's it going?")
    assert io.reads >= 1
    assert any("cortex is on step 3" in line for line in io.rendered)


# ── cadence cap + capped-is-recorded ──────────────────────────────────────────
def test_proactive_updates_fire_on_cadence_and_cap_is_recorded_once() -> None:
    cadence = UpdateCadence(every_steps=2, on_phase_change=False, max_updates=2)
    io = _RecordingIO()
    # every cadence tick yields a reply (a rendered update).
    engine, io = _engine(
        [],
        io=io,
        cadence=cadence,
        default=json.dumps({"move": "reply_to_operator", "text": "still working"}),
    )
    engine.acknowledge(ContextPacket(original="do the thing"))
    io.rendered.clear()

    engine.on_progress_boundary(step_count=2)  # fires update 1
    engine.on_progress_boundary(step_count=4)  # fires update 2
    engine.on_progress_boundary(step_count=6)  # would fire, but cap reached → capped
    engine.on_progress_boundary(step_count=8)  # capped, already recorded → nothing new

    updates = [line for line in io.rendered if "still working" in line]
    assert len(updates) == 2  # exactly the cap
    capped = [c for c in engine.snapshot()["chat"] if c.get("capped")]
    assert len(capped) == 1  # recorded exactly once, never silent
    assert any("update cap reached" in line for line in io.rendered)


def test_live_operator_input_wins_over_a_proactive_update() -> None:
    cadence = UpdateCadence(every_steps=1, on_phase_change=False, max_updates=4)
    io = _RecordingIO(pending=["are you almost done?"])
    engine, io = _engine(
        [json.dumps({"move": "dispatch_to_cortex", "instruction": "x"})],  # ack boundary
        io=io,
        cadence=cadence,
        default=json.dumps({"move": "reply_to_operator", "text": "answering you"}),
    )
    engine.acknowledge(ContextPacket(original="task"))
    io.rendered.clear()
    engine.on_progress_boundary(step_count=2)
    # the pending operator message was answered (not a generic proactive update).
    assert any("answering you" in line for line in io.rendered)


# ── 2. rung selection / off no-op ─────────────────────────────────────────────
def test_off_rung_is_a_strict_no_op_everywhere() -> None:
    io = _RecordingIO(pending=["hello?"])
    engine, io = _engine([json.dumps({"move": "wait"})], io=io, senses_config=None)
    assert engine.rung == RUNG_OFF and engine.active is False
    assert engine.acknowledge(ContextPacket(original="x")) == []
    assert engine.on_progress_boundary(step_count=5, phase_changed=True) == []
    assert engine.on_operator_message("anything") == []
    assert io.dispatched == [] and io.guided == [] and io.rendered == []
    assert engine.snapshot() == {"records": [], "chat": [], "injections": []}


def test_snapshot_merges_driver_and_engine_entries() -> None:
    io = _RecordingIO()
    engine, io = _engine(
        [json.dumps({"move": "dispatch_to_cortex", "instruction": "x", "ack": "on it"})],
        io=io,
    )
    engine.acknowledge(ContextPacket(original="do x"))
    snap = engine.snapshot()
    assert snap["records"] and any(c.get("kind") == "ack" for c in snap["chat"])
    assert set(snap.keys()) == {"records", "chat", "injections"}


def test_history_provider_is_threaded_and_failures_are_swallowed() -> None:
    io = _RecordingIO()

    def boom():
        raise RuntimeError("history unavailable")

    engine, io = _engine(
        [json.dumps({"move": "reply_to_operator", "text": "hi"})],
        io=io,
        history_provider=boom,
    )
    # A raising history provider must never break a turn.
    engine.on_operator_message("hello")
    assert any("hi" in line for line in io.rendered)


# ── 3. import-graph pin ───────────────────────────────────────────────────────
def test_presence_engine_imports_no_front_module() -> None:
    src = Path(__file__).resolve().parents[1] / "colleague" / "presence_engine.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    modules: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    forbidden = {
        "colleague.cli._commands.session",
        "colleague.cli._commands.talk",
        "colleague.resident.appserver",
        "colleague.background",
    }
    assert not (modules & forbidden), (
        "presence_engine must not import any front module — fronts depend on it, "
        f"never the reverse (found: {modules & forbidden})"
    )

"""Talking-to-one arc (task t6): the session middle-manager presence lane.

Pins the t6 contract on the interactive session: on split-mode intake, senses
speaks an acknowledgment BEFORE cortex's first step (``packet.ack`` when the
intake carried one, the FIXED dispatch notice when it didn't — never fabricated
understanding, h2); cadence-gated proactive updates fire at the EXISTING
progress-sink boundaries (labeled ``senses:`` lines joining the conversation —
the raw feed stays); hitting the update cap is recorded once, never silent (h4);
and the ack/update exchanges fold onto ``TaskResult.senses`` (records + chat) so
the whole exchange is reconstructable from the artifact alone (h14). Unarmed
paths (off-TTY / --no-tui / piped / --cortex-only / no senses) never render,
call, or record — byte-identical to today (h9). Lane methods are exercised
directly (the established test_session_talk_lane.py pattern).
"""

from __future__ import annotations

from pathlib import Path

from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import (
    _ACK_DISPATCH_NOTICE,
    SensesSessionOptions,
    SessionIO,
    _Session,
    _WorkSink,
)
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, ContextPacket, SensesBlock, SensesRecord, TaskResult
from colleague.presence import UpdateCadence


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _senses_config() -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _session(tmp_path: Path, *, view: str = "ansi", config=None, cortex_only: bool = False):
    out, err = _CollectingOut(), _CollectingOut()
    result = TaskResult(task_id="t", status=OK, summary="s")

    def _fake_work(**kwargs: object):
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config if config is not None else _senses_config(),
        json_mode=False,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(cortex_only=cortex_only),
    )
    return sess, out, err


def _conversation_lines(sess) -> list[str]:
    return [line.text for line in sess.state.conversation]


def _arm(sess, *, packet=None, cadence=None) -> None:
    """Arm the presence lane directly (the lane methods are the unit under test)."""
    sess._talk_active = True
    sess._talk_task_id = "tid"
    sess._talk_packet = packet
    if cadence is not None:
        sess._update_cadence = cadence


def _stub_update(monkeypatch, reply="reading the config module now", *, degraded=False):
    calls: list[dict] = []

    def _update(feed_tail, packet, senses_config, engine, **kw):
        calls.append({"feed_tail": feed_tail, "packet": packet})
        return {
            "update": None if degraded else reply,
            "latency": 0.5,
            "tokens": 7,
            "degraded": degraded,
        }

    monkeypatch.setattr(session_mod, "run_senses_update", _update)
    return calls


# --- the ack: senses speaks first (c9/h2) ------------------------------------


def test_ack_renders_packet_ack_and_records_chat_entry(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._render_ack("got it — refactoring the parser; handing to cortex now.")
    lines = _conversation_lines(sess)
    assert any("senses: got it — refactoring the parser" in ln for ln in lines)
    assert sess._senses_chat == [
        {
            "kind": "ack",
            "text": "got it — refactoring the parser; handing to cortex now.",
            "fixed": False,
            "at": sess._senses_chat[0]["at"],
        }
    ]


def test_missing_ack_renders_fixed_dispatch_notice_never_fabricated(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._render_ack(None)
    lines = _conversation_lines(sess)
    assert any(f"senses: {_ACK_DISPATCH_NOTICE}" in ln for ln in lines)
    assert sess._senses_chat[0]["fixed"] is True
    assert sess._senses_chat[0]["text"] == _ACK_DISPATCH_NOTICE


def test_ack_speaks_off_tty_when_senses_armed(tmp_path: Path) -> None:
    # c19 PIN-BREAK (presence-default-everywhere, t7): a deliberate, recorded
    # convention change. An off-TTY / piped / --no-tui session with senses ARMED
    # now DOES carry labeled 'senses:' ack lines — presence is the default on
    # every front, no longer TTY-only. (Was: test_ack_is_silent_when_lane_
    # disabled_off_tty, which encoded the pre-arc TTY-only assumption.) The
    # genuinely-unarmed (no senses) and --cortex-only paths stay byte-identical
    # — see test_ack_is_silent_when_cortex_only + test_no_senses_off_tty_is_
    # byte_identical below.
    sess, _o, _e = _session(tmp_path, view="markdown")
    sess._render_ack("understood — on it.")
    assert sess._senses_chat and sess._senses_chat[-1]["kind"] == "ack"
    assert any("senses: understood" in ln for ln in _conversation_lines(sess))


def test_ack_is_silent_when_cortex_only(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi", cortex_only=True)
    sess._render_ack("understood — on it.")
    assert sess._senses_chat == []


# --- proactive updates: cadence-gated at sink boundaries (c10/h4) -------------


def test_update_fires_on_phase_change_and_renders_labeled_line(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = ContextPacket(original="req", interpretation="tidy config")
    _arm(sess, packet=packet, cadence=UpdateCadence(every_steps=100, max_updates=4))
    calls = _stub_update(monkeypatch)

    sess._maybe_proactive_update("", "synthesizing…")  # a NEW phase label

    assert len(calls) == 1
    assert calls[0]["packet"] is packet
    assert any("senses: reading the config module now" in ln for ln in _conversation_lines(sess))
    assert sess._senses_chat[-1]["kind"] == "update"
    assert [r.point for r in sess._update_records] == ["senses-update"]


def test_same_phase_label_does_not_refire(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=100, max_updates=4))
    calls = _stub_update(monkeypatch)

    sess._maybe_proactive_update("", "thinking…")
    sess._maybe_proactive_update("", "thinking…")  # unchanged label — not a change

    assert len(calls) == 1


def test_update_fires_every_n_steps(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import replace

    from agentfront.taui.state import WorkItem

    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=3, on_phase_change=False, max_updates=4))
    calls = _stub_update(monkeypatch)

    # The running cockpit holds the armed work item; the sink boundary reads its
    # step_count for the every-N decision.
    sess.state = replace(
        sess.state,
        work_item=WorkItem(task_id="t", engine="mock", step_count=2, running=True),
    )
    sess._maybe_proactive_update("read_file", "f2.py")
    assert calls == []  # 2 - 0 < 3: not yet

    sess.state = replace(
        sess.state,
        work_item=WorkItem(task_id="t", engine="mock", step_count=3, running=True),
    )
    sess._maybe_proactive_update("read_file", "f3.py")
    assert len(calls) == 1  # fired once when step_count - last(0) >= 3
    assert sess._update_last_step == 3

    sess._maybe_proactive_update("read_file", "f3b.py")
    assert len(calls) == 1  # and not again until another N steps pass


def test_cap_hit_is_recorded_once_never_silent(tmp_path: Path, monkeypatch) -> None:
    # A POSITIVE cap: the first fire runs a real update, then the cap is reached
    # mid-run and recorded exactly once — never repeated, never silent (h4).
    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=100, max_updates=1))
    calls = _stub_update(monkeypatch)

    sess._maybe_proactive_update("", "thinking…")  # phase change → fires (under cap)
    sess._maybe_proactive_update("", "synthesizing…")  # phase change → cap reached, recorded
    sess._maybe_proactive_update("", "compacting…")  # phase change → cap again, stays silent

    assert len(calls) == 1  # exactly one real senses call before the cap
    cap_lines = [ln for ln in _conversation_lines(sess) if "update cap reached" in ln]
    assert len(cap_lines) == 1  # once, never repeated
    capped_entries = [c for c in sess._senses_chat if c.get("capped")]
    assert len(capped_entries) == 1  # exactly one capped chat entry


def test_cap_zero_hard_disables_updates_no_call_no_cap_line(tmp_path: Path, monkeypatch) -> None:
    # COLLEAGUE_SENSES_UPDATE_CAP=0 (max_updates=0) is a HARD DISABLE: no senses
    # call AND no "cap reached" chatter — updates are off entirely, not merely
    # capped-at-zero-with-a-notice (talking-to-one review fix, Qodo #2).
    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=100, max_updates=0))
    calls = _stub_update(monkeypatch)

    sess._maybe_proactive_update("", "thinking…")
    sess._maybe_proactive_update("", "synthesizing…")

    assert calls == []  # no senses call
    assert not any("update cap reached" in ln for ln in _conversation_lines(sess))
    assert sess._senses_chat == []  # no cap chatter recorded at all


def test_degraded_update_counts_toward_cap_and_records(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=100, max_updates=4))
    _stub_update(monkeypatch, degraded=True)

    sess._maybe_proactive_update("", "synthesizing…")

    assert sess._updates_sent == 1  # honest accounting: a degraded call still spends
    assert len(sess._update_records) == 1
    assert sess._update_records[0].degraded is True
    # No text → no conversation line, but the record is there (never silent).
    assert not any("senses: reading" in ln for ln in _conversation_lines(sess))


def test_update_fires_off_tty_when_senses_armed(tmp_path: Path, monkeypatch) -> None:
    # c19 PIN-BREAK (t7): proactive updates now fire off-TTY / piped with senses
    # armed (was test_update_noop_when_lane_unarmed, which asserted the pre-arc
    # TTY-only no-op). A phase change fires the first update. Genuinely-unarmed
    # sessions still no-op — see test_no_senses_off_tty_is_byte_identical.
    sess, _o, _e = _session(tmp_path, view="markdown")
    calls = _stub_update(monkeypatch)
    sess._maybe_proactive_update("", "thinking…")  # phase change → fires
    assert calls  # now fires off-TTY
    assert sess._update_records


def test_sink_tolerates_bare_state_holder_without_presence(tmp_path: Path) -> None:
    """The sink's documented contract: usable against a bare state-holder that
    has neither the talk lane nor the presence lane."""

    class _Holder:
        def __init__(self) -> None:
            from agentfront.taui.state import TAUIState

            self.state = TAUIState(panels=[])
            self.view = "markdown"

    holder = _Holder()
    sink = _WorkSink(holder)
    sink(1, "read_file", "a.py", True)  # must not raise
    sink(2, "", "thinking…", True)


# --- the finalize fold: reconstructable from the artifact alone (h14) ---------


def test_finalize_folds_ack_updates_and_chat_onto_senses_block(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = ContextPacket(original="req", interpretation="tidy", ack="on it.")
    _arm(sess, packet=packet, cadence=UpdateCadence(every_steps=100, max_updates=4))
    _stub_update(monkeypatch)

    sess._render_ack(packet.ack)
    sess._maybe_proactive_update("", "synthesizing…")

    def _speak(summary, senses_config, engine, **kw):
        return "shaped", SensesRecord(point="senses-speakback", latency=0.1, degraded=False)

    monkeypatch.setattr(session_mod, "run_senses_speakback", _speak)
    result = TaskResult(task_id="t", status=OK, summary="RAW")
    # The loop's packet injection sets the split block with the packet riding
    # the task (mirrored here the way test_session_senses.py's fake work_fn does).
    result.senses = SensesBlock(mode="split", packet=packet, records=[])
    intake_rec = SensesRecord(point="senses-intake", latency=0.1, degraded=False)
    shaped = sess._finalize_split_run(result, intake_rec)

    assert shaped == "shaped"
    points = [r.point for r in result.senses.records]
    assert points == ["senses-intake", "senses-update", "senses-speakback"]
    kinds = [entry["kind"] for entry in result.senses.chat]
    assert kinds == ["ack", "update"]
    # Machine-checkable from the serialized artifact alone (h14).
    payload = result.to_dict()["senses"]
    assert payload["packet"]["ack"] == "on it."
    assert any(r["point"] == "senses-update" for r in payload["records"])
    assert [e["kind"] for e in payload["chat"]] == ["ack", "update"]


def test_reset_presence_lane_clears_prior_line_state(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=100, max_updates=0))
    sess._render_ack("hello")
    sess._maybe_proactive_update("", "thinking…")  # records the cap hit
    assert sess._senses_chat != []
    sess._reset_presence_lane()
    assert sess._senses_chat == []
    assert sess._update_records == []
    assert sess._updates_sent == 0
    assert sess._update_cap_recorded is False


# --- clarify-first + continuity (t7: c19/h8, c11/h5) ---------------------------


def _low_confidence_packet(**over):
    defaults = dict(
        original="make it better",
        interpretation="improve something unspecified",
        confidence=0.2,
        task_type="feature",
        omissions=["which area to improve"],
        ack="on it — improving the area you named.",
    )
    defaults.update(over)
    return ContextPacket(**defaults)


def _stub_reintake(monkeypatch, refined_packet):
    calls: list[dict] = []

    def _intake(text, senses_config, engine, **kw):
        calls.append({"text": text, "history": kw.get("history")})
        return refined_packet, SensesRecord(point="senses-intake", latency=0.1, degraded=False)

    monkeypatch.setattr(session_mod, "run_senses_intake", _intake)
    return calls


def _scripted_input(sess, answers: list[str]) -> None:
    it = iter(answers)
    sess._read_next = lambda: next(it, None)


class _EngineStub:
    def make_complete(self, config, tools=None):
        return lambda messages: None

    def make_count_tokens(self, config):
        return lambda messages: 0


def _clarify_env(sess, packet, monkeypatch, refined=None):
    from colleague.presence import ClarifyPolicy

    sess._clarify_policy = ClarifyPolicy(confidence_floor=0.5, max_questions=3)
    refined_packet = (
        refined if refined is not None else _low_confidence_packet(confidence=0.9, omissions=[])
    )
    calls = _stub_reintake(monkeypatch, refined_packet)
    from colleague.contract import Task

    task = Task.new(".", packet.original)
    return task, calls


def test_clarify_asks_grounded_question_and_refines_packet(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = _low_confidence_packet()
    task, calls = _clarify_env(sess, packet, monkeypatch)
    _scripted_input(sess, ["focus on the parser error messages"])

    final = sess._maybe_clarify(task, packet, sess.config, _EngineStub())

    # The question is grounded in the packet's OWN omission — never canned filler.
    lines = _conversation_lines(sess)
    assert any("which area to improve" in ln for ln in lines if ln.startswith("senses:"))
    # The operator's verbatim words joined the instruction; the original survives.
    assert task.instruction.startswith("make it better")
    assert "focus on the parser error messages" in task.instruction
    # Re-intake ran once over the composed text with the history threaded.
    assert len(calls) == 1
    assert calls[0]["text"] == task.instruction
    assert calls[0]["history"]  # non-empty rolling history
    # The refined packet won.
    assert final.confidence == 0.9
    assert task.context_packet is final
    # Both sides of the exchange are on the per-line chat, and a re-intake record folded.
    kinds_roles = [(e["kind"], e.get("role")) for e in sess._senses_chat]
    assert ("clarify", "senses") in kinds_roles
    assert ("clarify", "operator") in kinds_roles
    assert len(sess._clarify_records) == 1


def test_clarify_go_word_dispatches_immediately(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = _low_confidence_packet()
    task, calls = _clarify_env(sess, packet, monkeypatch)
    _scripted_input(sess, ["go"])

    final = sess._maybe_clarify(task, packet, sess.config, _EngineStub())

    assert calls == []  # no re-intake: go dispatches as-is
    assert final is packet
    assert task.instruction == "make it better"  # untouched
    go_entries = [e for e in sess._senses_chat if e.get("go")]
    assert len(go_entries) == 1  # the go itself is recorded (h8)


def test_clarify_eof_dispatches_immediately(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = _low_confidence_packet()
    task, calls = _clarify_env(sess, packet, monkeypatch)
    _scripted_input(sess, [])  # immediate EOF

    final = sess._maybe_clarify(task, packet, sess.config, _EngineStub())

    assert calls == []
    assert final is packet


def test_clarify_never_fires_on_confident_intake(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = _low_confidence_packet(confidence=0.9)
    task, calls = _clarify_env(sess, packet, monkeypatch)
    reads: list[str] = []
    sess._read_next = lambda: reads.append("read") or "never"

    final = sess._maybe_clarify(task, packet, sess.config, _EngineStub())

    assert reads == []  # the input source was never touched
    assert final is packet


def test_clarify_never_fires_without_input_source(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = _low_confidence_packet()
    task, calls = _clarify_env(sess, packet, monkeypatch)
    sess._read_next = None  # direct construction (no run()) — dispatch immediately

    final = sess._maybe_clarify(task, packet, sess.config, _EngineStub())

    assert calls == []
    assert final is packet


def test_clarify_ceiling_bounds_consecutive_questions(tmp_path: Path, monkeypatch) -> None:
    from colleague.presence import ClarifyPolicy

    sess, _o, _e = _session(tmp_path, view="ansi")
    packet = _low_confidence_packet()
    # Re-intake keeps returning a still-low-confidence packet with omissions.
    task, calls = _clarify_env(sess, packet, monkeypatch, refined=_low_confidence_packet())
    sess._clarify_policy = ClarifyPolicy(confidence_floor=0.5, max_questions=2)
    _scripted_input(sess, ["answer one", "answer two", "answer three"])

    sess._maybe_clarify(task, packet, sess.config, _EngineStub())

    questions = [
        e for e in sess._senses_chat if e["kind"] == "clarify" and e.get("role") == "senses"
    ]
    assert len(questions) == 2  # the ceiling held (loop-proofing, h8)
    assert len(calls) == 2
    # Both operator answers up to the ceiling joined the instruction verbatim.
    assert "answer one" in task.instruction and "answer two" in task.instruction
    assert "answer three" not in task.instruction


def test_history_threads_into_subsequent_senses_calls(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=100, max_updates=4))
    sess._render_ack("on it.")
    assert sess._history == [{"role": "senses", "text": "on it."}]

    seen: list = []

    def _update(feed_tail, packet, senses_config, engine, **kw):
        seen.append(kw.get("history"))
        return {"update": "still working", "latency": 0.1, "tokens": 1, "degraded": False}

    monkeypatch.setattr(session_mod, "run_senses_update", _update)
    sess._maybe_proactive_update("", "synthesizing…")

    assert seen == [[{"role": "senses", "text": "on it."}]]
    # And the spoken update itself joined the rolling history.
    assert sess._history[-1] == {"role": "senses", "text": "still working"}


def test_off_tty_session_accumulates_history_when_senses_armed(tmp_path: Path) -> None:
    # c19 PIN-BREAK (t7): an off-TTY session with senses armed now accumulates
    # rolling history (was test_unarmed_session_accumulates_no_history, which
    # asserted the pre-arc off-TTY no-history). Continuity is default everywhere.
    sess, _o, _e = _session(tmp_path, view="markdown")
    sess._render_ack("hello")
    sess._history_append("operator", "typed something")
    assert sess._history  # now accumulates off-TTY when armed


def test_no_senses_off_tty_is_byte_identical(tmp_path: Path) -> None:
    # h1 (default never becomes forced): a genuinely-unarmed session — senses
    # NOT resolved — stays byte-identical on every surface, including off-TTY.
    # This pins the OTHER side of the c19 pin-break: the default arms only when
    # senses actually resolves; nothing to talk to = pre-arc silence.
    unarmed = EngineConfig.resolve(model="cortex-model")  # config.senses stays None
    sess, _o, _e = _session(tmp_path, view="markdown", config=unarmed)
    assert sess._presence_enabled() is False
    sess._render_ack("hello")
    sess._history_append("operator", "typed something")
    assert sess._senses_chat == []
    assert sess._history == []
    assert not any("senses:" in ln for ln in _conversation_lines(sess))


class _FakeLoopEngine:
    """A minimal engine whose completions are scripted coordination moves."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self._i = 0

    def make_complete(self, config, *, tools):  # noqa: ANN001
        assert tools == []

        def complete(messages):  # noqa: ANN001
            import json as _json
            from types import SimpleNamespace

            i, self._i = self._i, self._i + 1
            content = self._replies[i] if i < len(self._replies) else _json.dumps({"move": "wait"})
            return SimpleNamespace(
                content=content, reasoning="", prompt_tokens=1, completion_tokens=1
            )

        return complete

    def make_count_tokens(self, config):  # noqa: ANN001
        return None


def test_session_loop_rung_routes_live_talk_through_the_engine(tmp_path: Path, monkeypatch) -> None:
    # presence-default-everywhere (t7): on the loop rung + interactive TTY, live
    # operator talk rides the senses AGENTIC LOOP (PresenceEngine) — senses picks
    # a coordination move — not the single-turn fixed-beat run_senses_talk.
    import json

    from colleague.contract import Task
    from colleague.senses import senses_engine_config

    sess, _o, _e = _session(tmp_path, view="ansi")
    senses_config = senses_engine_config(sess.config)
    fake = _FakeLoopEngine([json.dumps({"move": "reply_to_operator", "text": "on it"})])
    monkeypatch.setattr(sess, "_senses_engine", lambda: (senses_config, fake))
    talk_called: list[int] = []
    monkeypatch.setattr(session_mod, "run_senses_talk", lambda *a, **k: talk_called.append(1))

    task = Task(id="tid", repo_path=str(tmp_path), instruction="do it")
    sess._begin_talk_lane(task)
    assert sess._presence_engine is not None  # loop rung built the agentic loop

    sess._talk_senses("how's it going?")
    assert talk_called == []  # routed through the engine, not the fixed-beat lane
    assert any("senses: on it" in ln for ln in _conversation_lines(sess))
    assert sess._presence_engine.snapshot()["chat"]  # recorded for the artifact fold


def test_session_beats_rung_keeps_the_fixed_beat_talk(tmp_path: Path, monkeypatch) -> None:
    # The COLLEAGUE_PRESENCE=beats opt-down keeps the live-proven fixed-beat talk
    # lane (no engine built), so the ladder's middle rung is byte-identical to the
    # pre-loop behavior.
    from colleague.contract import Task

    monkeypatch.setenv("COLLEAGUE_PRESENCE", "beats")
    sess, _o, _e = _session(tmp_path, view="ansi")
    task = Task(id="tid", repo_path=str(tmp_path), instruction="do it")
    sess._begin_talk_lane(task)
    assert sess._presence_engine is None  # beats rung → no agentic loop


def test_history_survives_reset_between_work_lines(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._history_append("operator", "first line")
    sess._reset_presence_lane()
    assert sess._history == [{"role": "operator", "text": "first line"}]  # c11: continuity


def test_history_is_capped(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    for i in range(60):
        sess._history_append("operator", f"line {i}")
    assert len(sess._history) == 50
    assert sess._history[0] == {"role": "operator", "text": "line 10"}  # oldest dropped

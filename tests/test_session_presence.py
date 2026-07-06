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


def test_ack_is_silent_when_lane_disabled_off_tty(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="markdown")
    sess._render_ack("understood — on it.")
    assert sess._senses_chat == []
    assert not any("senses: understood" in ln for ln in _conversation_lines(sess))


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
    sess, _o, _e = _session(tmp_path, view="ansi")
    _arm(sess, cadence=UpdateCadence(every_steps=100, max_updates=0))
    calls = _stub_update(monkeypatch)

    sess._maybe_proactive_update("", "thinking…")
    sess._maybe_proactive_update("", "synthesizing…")

    assert calls == []  # capped before any senses call
    cap_lines = [ln for ln in _conversation_lines(sess) if "update cap reached" in ln]
    assert len(cap_lines) == 1  # once, never repeated
    assert sess._senses_chat == [
        {"kind": "update", "capped": True, "at": sess._senses_chat[0]["at"]}
    ]


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


def test_update_noop_when_lane_unarmed(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="markdown")
    calls = _stub_update(monkeypatch)
    sess._maybe_proactive_update("", "thinking…")
    sess._maybe_proactive_update("read_file", "x.py")
    assert calls == []
    assert sess._senses_chat == []
    assert sess._update_records == []


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

"""Tests for the senses coordination loop core (presence-default-everywhere, t5).

Covers the four acceptance criteria:
1. per-boundary completion cap (default 2) + budget windowing via the
   count_tokens seam;
2. the degradation ladder, rung by rung (loop degraded -> beats; unarmed ->
   off; every transition recorded);
3. the verbatim-to-cortex invariant (dispatch/guide carry the operator's words
   verbatim; refinement appends, never rewrites);
4. every loop turn lands as a SensesRecord + a t3-shaped kind-ed chat entry, and
   a loop that never fires leaves the artifact byte-identical.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from colleague.context import count_tokens_chars
from colleague.contract import SENSES_LOOP_POINT_PREFIX, ContextPacket, SensesRecord
from colleague.senses_loop import (
    BOUNDARY_CADENCE_TICK,
    BOUNDARY_OPERATOR_INPUT,
    DEFAULT_LOOP_CAP,
    RUNG_BEATS,
    RUNG_LOOP,
    RUNG_OFF,
    BoundaryContext,
    LoopTurn,
    SensesLoopDriver,
    loop_cap_from_env,
)
from colleague.senses_moves import SensesMoveExecutor


# ── fakes ────────────────────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, content: str, *, reasoning: str = "") -> None:
        self.content = content
        self.reasoning = reasoning
        self.prompt_tokens = 3
        self.completion_tokens = 5


def _scripted_make_complete(replies, *, prompts=None, calls=None):
    """A make_complete factory that returns *replies* one per completion.

    Each reply is a raw completion string, or an ``Exception`` instance to raise
    (a dead/degraded endpoint). Extra completions default to a ``wait`` move.
    """
    seq = list(replies)
    idx = {"i": 0}

    def make_complete(config, *, tools):  # noqa: ANN001
        assert tools == [], "senses loop must always issue tools=[] (tools-off)"

        def complete(messages):  # noqa: ANN001
            if prompts is not None:
                prompts.append(messages)
            if calls is not None:
                calls.append(1)
            i = idx["i"]
            idx["i"] += 1
            reply = seq[i] if i < len(seq) else json.dumps({"move": "wait"})
            if isinstance(reply, Exception):
                raise reply
            return _FakeResp(reply)

        return complete

    return make_complete


def _recording_executor(events):
    def dispatch(instruction):  # noqa: ANN001
        events.append(("dispatch", instruction))
        return "dispatched"

    def guide(guidance):  # noqa: ANN001
        events.append(("guide", guidance))
        return "guided"

    def read_flight():
        events.append(("read_flight",))
        return "step 3/40 · editing foo.py"

    def reply(text):  # noqa: ANN001
        events.append(("reply", text))
        return "replied"

    def clarify(question):  # noqa: ANN001
        events.append(("clarify", question))
        return "clarified"

    return SensesMoveExecutor(
        dispatch_to_cortex=dispatch,
        guide_cortex=guide,
        read_flight=read_flight,
        reply_to_operator=reply,
        clarify=clarify,
    )


def _config(budget: int = 24000):
    # The driver only checks `senses_config is None` and reads
    # `.context_budget_tokens`; a namespace is enough (no live EngineConfig).
    return SimpleNamespace(context_budget_tokens=budget)


def _driver(
    replies,
    *,
    events=None,
    prompts=None,
    calls=None,
    cap=DEFAULT_LOOP_CAP,
    budget=24000,
    fixed_beat_handler=None,
    on_rung_change=None,
    make_count_tokens=None,
    config_override="__default__",
):
    events = events if events is not None else []
    cfg = _config(budget) if config_override == "__default__" else config_override
    return SensesLoopDriver(
        senses_config=cfg,
        make_complete=_scripted_make_complete(replies, prompts=prompts, calls=calls),
        executor=_recording_executor(events),
        make_count_tokens=make_count_tokens,
        per_boundary_cap=cap,
        fixed_beat_handler=fixed_beat_handler,
        on_rung_change=on_rung_change,
    )


def _op(text: str, **kw) -> BoundaryContext:
    return BoundaryContext(kind=BOUNDARY_OPERATOR_INPUT, operator_input=text, **kw)


# ── 1. cap + budget windowing ────────────────────────────────────────────────
def test_per_boundary_cap_bounds_completions_on_nonterminal_moves() -> None:
    calls: list = []
    # read_flight is non-terminal — without a cap this would loop forever.
    replies = [json.dumps({"move": "read_flight"})] * 10
    d = _driver(replies, calls=calls, cap=2)
    turns = d.process_boundary(_op("what's happening?"))
    assert len(calls) == 2  # exactly the cap, never more
    assert len(turns) == 2
    assert all(t.move == "read_flight" for t in turns)


def test_cap_default_is_two() -> None:
    calls: list = []
    d = _driver([json.dumps({"move": "read_flight"})] * 5, calls=calls)  # default cap
    d.process_boundary(_op("status?"))
    assert len(calls) == DEFAULT_LOOP_CAP == 2


def test_terminal_move_ends_the_boundary_before_the_cap() -> None:
    calls: list = []
    d = _driver(
        [json.dumps({"move": "dispatch_to_cortex", "instruction": "x"})], calls=calls, cap=2
    )
    turns = d.process_boundary(_op("do the thing"))
    assert len(calls) == 1  # dispatch is terminal — stops at 1 despite cap 2
    assert len(turns) == 1


def test_read_flight_then_reply_uses_two_turns() -> None:
    events: list = []
    replies = [
        json.dumps({"move": "read_flight"}),
        json.dumps({"move": "reply_to_operator", "text": "cortex is editing foo.py"}),
    ]
    d = _driver(replies, events=events, cap=2)
    turns = d.process_boundary(_op("how's it going?"))
    assert [t.move for t in turns] == ["read_flight", "reply_to_operator"]
    assert ("read_flight",) in events
    assert ("reply", "cortex is editing foo.py") in events


def test_feed_is_windowed_to_budget_via_the_count_tokens_seam() -> None:
    seam_calls: list = []

    def spy_counter(messages):  # noqa: ANN001
        seam_calls.append(messages)
        return count_tokens_chars(messages)

    prompts: list = []
    huge_feed = "\n".join(f"feed line {i} " + "x" * 200 for i in range(500))
    d = _driver(
        [json.dumps({"move": "wait"})],
        prompts=prompts,
        make_count_tokens=spy_counter,
        budget=40,  # tiny budget forces windowing
    )
    d.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK, feed_tail=huge_feed))
    # The injected seam was used (not bypassed) ...
    assert seam_calls, "the count_tokens seam must be consulted for windowing"
    # ... and the sent user prompt is dramatically smaller than the raw feed.
    sent_user = prompts[0][1]["content"]
    assert len(sent_user) < len(huge_feed) / 5


# ── 2. degradation ladder ─────────────────────────────────────────────────────
def test_unarmed_senses_pins_off_and_is_byte_identical() -> None:
    d = SensesLoopDriver(
        senses_config=None,
        make_complete=_scripted_make_complete([json.dumps({"move": "wait"})]),
        executor=_recording_executor([]),
    )
    assert d.rung == RUNG_OFF
    turns = d.process_boundary(_op("anything"))
    assert turns == []
    assert d.records == [] and d.chat == [] and d.injections == []


def test_loop_degradation_falls_to_beats_and_records_the_transition() -> None:
    beat_calls: list = []
    marker_record = SensesRecord(point="fixed-beat:intake")
    marker_turn = LoopTurn(move="beats", record=marker_record)

    def fixed_beat_handler(boundary):  # noqa: ANN001
        beat_calls.append(boundary)
        return [marker_turn]

    rung_changes: list = []
    # First boundary's completion raises (dead endpoint) -> degraded -> beats.
    d = _driver(
        [ConnectionError("senses endpoint down"), json.dumps({"move": "wait"})],
        fixed_beat_handler=fixed_beat_handler,
        on_rung_change=lambda old, new, why: rung_changes.append((old, new, why)),
    )
    assert d.rung == RUNG_LOOP
    turns1 = d.process_boundary(_op("first request"))
    assert turns1 and turns1[0].degraded
    assert d.rung == RUNG_BEATS
    # The transition is an artifact fact, never silent.
    assert any(r.point == "senses-ladder:loop->beats" for r in d.records)
    assert rung_changes == [(RUNG_LOOP, RUNG_BEATS, "loop-degraded")]

    # The NEXT boundary is handled by the fixed-beat lane, not the loop.
    turns2 = d.process_boundary(_op("second request"))
    assert beat_calls, "beats rung must delegate to the fixed-beat handler"
    assert marker_record in d.records
    assert turns2 == [marker_turn]


def test_degraded_completion_records_a_degraded_senses_record() -> None:
    d = _driver([TimeoutError("slow")], cap=1)
    turns = d.process_boundary(_op("hi"))
    assert len(turns) == 1 and turns[0].degraded
    rec = turns[0].record
    assert rec.point == f"{SENSES_LOOP_POINT_PREFIX}degraded"
    assert rec.degraded is True and rec.tokens is None


def test_beats_rung_without_a_handler_is_a_safe_no_op() -> None:
    d = _driver([json.dumps({"move": "wait"})])
    d._rung = RUNG_BEATS  # simulate a prior degradation with no handler wired
    assert d.process_boundary(_op("x")) == []


# ── 3. verbatim-to-cortex invariant ───────────────────────────────────────────
def test_dispatch_carries_operator_words_verbatim_refinement_appended() -> None:
    events: list = []
    verbatim = "add retry with backoff to fetch() exactly as written"
    d = _driver(
        [
            json.dumps(
                {
                    "move": "dispatch_to_cortex",
                    "instruction": "do the retry thing",
                    "ack": "on it — handing this to cortex",
                }
            )
        ],
        events=events,
    )
    d.process_boundary(_op(verbatim))
    dispatched = next(text for kind, text in events if kind == "dispatch")
    # The operator's words are present, verbatim, and FIRST.
    assert dispatched.startswith(verbatim)
    # The model's phrasing is folded in as a refinement, never a rewrite.
    assert "do the retry thing" in dispatched
    assert "[senses refinement:" in dispatched


def test_dispatch_without_refinement_is_pure_verbatim() -> None:
    events: list = []
    verbatim = "rename the widget module to gadget"
    d = _driver(
        [json.dumps({"move": "dispatch_to_cortex", "instruction": verbatim})],
        events=events,
    )
    d.process_boundary(_op(verbatim))
    dispatched = next(text for kind, text in events if kind == "dispatch")
    assert dispatched == verbatim  # echo collapses; no refinement appended


def test_guide_carries_operator_words_verbatim_when_operator_spoke() -> None:
    events: list = []
    verbatim = "focus on the config file first"
    d = _driver(
        [json.dumps({"move": "guide_cortex", "guidance": "maybe look at config"})],
        events=events,
    )
    turns = d.process_boundary(_op(verbatim))
    guided = next(text for kind, text in events if kind == "guide")
    assert guided.startswith(verbatim)
    # The recorded injection carries the same verbatim-preserving text.
    assert turns[0].injection is not None
    assert verbatim in turns[0].injection["text"]


def test_self_initiated_guide_without_operator_input_uses_model_words() -> None:
    events: list = []
    d = _driver(
        [json.dumps({"move": "guide_cortex", "guidance": "tests look flaky — rerun them"})],
        events=events,
    )
    # A cadence tick — no operator spoke, so there is no verbatim to preserve.
    d.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK, feed_tail="…"))
    guided = next(text for kind, text in events if kind == "guide")
    assert guided == "tests look flaky — rerun them"


# ── 4. t3-shaped records + chat; byte-identical when idle ─────────────────────
def test_dispatch_records_loop_point_and_ack_chat_entry() -> None:
    d = _driver(
        [
            json.dumps(
                {
                    "move": "dispatch_to_cortex",
                    "instruction": "x",
                    "ack": "got it, handing to cortex",
                }
            )
        ],
    )
    d.process_boundary(_op("do x"))
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}dispatch_to_cortex" for r in d.records)
    ack = [c for c in d.chat if c.get("kind") == "ack"]
    assert ack and ack[0]["text"] == "got it, handing to cortex" and ack[0]["fixed"] is False


def test_dispatch_without_authored_ack_uses_fixed_notice() -> None:
    d = _driver([json.dumps({"move": "dispatch_to_cortex", "instruction": "x"})])
    d.process_boundary(_op("do x"))
    ack = [c for c in d.chat if c.get("kind") == "ack"][0]
    assert ack["fixed"] is True
    assert ack["text"] == "taking your request to cortex now."


def test_reply_records_talk_shaped_chat_entry_without_kind() -> None:
    d = _driver([json.dumps({"move": "reply_to_operator", "text": "cortex is on step 3"})])
    d.process_boundary(_op("status?"))
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}reply_to_operator" for r in d.records)
    # kind omitted -> implied "talk" (t3 mapping); the flight-talk message/answer shape.
    talk = [c for c in d.chat if "kind" not in c]
    assert talk and talk[0]["answer"] == "cortex is on step 3"
    assert talk[0]["message"] == "status?"


def test_clarify_records_clarify_chat_entry() -> None:
    d = _driver([json.dumps({"move": "clarify", "question": "which module did you mean?"})])
    d.process_boundary(_op("fix the module"))
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}clarify" for r in d.records)
    clar = [c for c in d.chat if c.get("kind") == "clarify"]
    assert clar and clar[0]["role"] == "senses"
    assert clar[0]["text"] == "which module did you mean?"


def test_guide_records_injection_not_chat() -> None:
    d = _driver([json.dumps({"move": "guide_cortex", "guidance": "watch the flaky test"})])
    turns = d.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK, feed_tail="…"))
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}guide_cortex" for r in d.records)
    assert d.chat == []  # a relay is an injection, not operator-facing chat
    assert d.injections and d.injections[0]["source"] == "senses-loop"
    assert turns[0].injection["text"] == "watch the flaky test"


def test_read_flight_and_wait_record_only_no_chat_no_injection() -> None:
    d = _driver(
        [json.dumps({"move": "read_flight"}), json.dumps({"move": "wait"})],
        cap=2,
    )
    d.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK, feed_tail="…"))
    points = {r.point for r in d.records}
    assert f"{SENSES_LOOP_POINT_PREFIX}read_flight" in points
    assert f"{SENSES_LOOP_POINT_PREFIX}wait" in points
    assert d.chat == [] and d.injections == []


def test_every_turn_lands_a_senses_record() -> None:
    replies = [
        json.dumps({"move": "read_flight"}),
        json.dumps({"move": "reply_to_operator", "text": "done reading"}),
    ]
    d = _driver(replies, cap=2)
    turns = d.process_boundary(_op("go"))
    assert all(isinstance(t.record, SensesRecord) for t in turns)
    assert len(d.records) == len(turns)


def test_hallucinated_move_is_refused_and_recorded_as_refused() -> None:
    events: list = []
    d = _driver(
        [json.dumps({"move": "delete_repo", "path": "/"}), json.dumps({"move": "wait"})],
        events=events,
        cap=2,
    )
    d.process_boundary(_op("hi"))
    assert any(r.point == f"{SENSES_LOOP_POINT_PREFIX}refused" for r in d.records)
    # The hallucinated move never reached any coordination callback.
    assert all(kind != "delete_repo" for kind, *_ in events)
    assert d.chat == []


def test_non_json_completion_degrades_to_a_reply() -> None:
    events: list = []
    d = _driver(["cortex is roughly halfway through, looking good"], events=events, cap=1)
    d.process_boundary(_op("how far along?"))
    # parse_move (t1) degrades garbage to reply_to_operator carrying the raw text.
    assert ("reply", "cortex is roughly halfway through, looking good") in events
    talk = [c for c in d.chat if "kind" not in c]
    assert talk and talk[0]["answer"] == "cortex is roughly halfway through, looking good"


def test_loop_that_never_fires_leaves_the_artifact_byte_identical() -> None:
    d = _driver([json.dumps({"move": "wait"})])
    # Constructed but never asked to process a boundary.
    assert d.records == [] and d.chat == [] and d.injections == []


def test_packet_context_is_available_to_the_prompt() -> None:
    prompts: list = []
    packet = ContextPacket(original="fix the bug", interpretation="repair the parser")
    d = _driver([json.dumps({"move": "wait"})], prompts=prompts)
    d.process_boundary(_op("continue", packet=packet, task_state="step 2/40"))
    user = prompts[0][1]["content"]
    assert "fix the bug" in user and "repair the parser" in user and "step 2/40" in user


# ── env knob ──────────────────────────────────────────────────────────────────
def test_loop_cap_from_env_reads_positive_int() -> None:
    assert loop_cap_from_env({"COLLEAGUE_SENSES_LOOP_CAP": "5"}) == 5


def test_loop_cap_from_env_falls_back_on_malformed() -> None:
    assert loop_cap_from_env({"COLLEAGUE_SENSES_LOOP_CAP": "nonsense"}) == DEFAULT_LOOP_CAP
    assert loop_cap_from_env({"COLLEAGUE_SENSES_LOOP_CAP": "-3"}) == DEFAULT_LOOP_CAP
    assert loop_cap_from_env({}) == DEFAULT_LOOP_CAP

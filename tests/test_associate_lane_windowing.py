"""Associate lanes window their request to the SEAT's served-window budget (Qodo #464, #460).

The compact / synthesis lanes build their message lists against the parent
``ContextControls`` budget (the MAIN window). Since plan t22 the associate
seat's ``context_budget_tokens`` is clamped to its SERVED window, which can be
smaller than the parent's — so an armed lane could submit an overlong prompt
and only recover via the wire 400 + cortex@low fallback. Pins:

* ARMED + seat budget smaller than the lane's: the messages the associate
  completion receives fit the seat budget by the repo's own estimator
  (``count_tokens_chars`` / the lane's ``count_tokens``), head + latest turn
  preserved, ONE elision placeholder — trimmed BEFORE dispatch;
* the fallback branch is untouched: cortex@low still receives the ORIGINAL
  (parent-budget) list;
* seat budget NOT smaller than the lane's, or a request that already fits:
  the very same list object passes through (byte-identical);
* UNARMED: ``make_associate_complete`` is ``None`` and the loop's
  ``_seat_complete`` hands the acting completion back unchanged — the
  messages reach it untouched.
"""

from __future__ import annotations

from types import SimpleNamespace

from colleague import associate_seats, loop
from colleague.associate_config import ASSOCIATE_WIRE_MODEL, AssociateConfig
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.loop import ModelResponse

MAIN_BUDGET = 200_000
SEAT_BUDGET = 2_000


def _config(*, armed: bool, seat_budget: int = SEAT_BUDGET) -> EngineConfig:
    cfg = EngineConfig(
        model="cortex-model",
        base_url="http://localhost:8001/v1",
        context_budget_tokens=MAIN_BUDGET,
    )
    if armed:
        cfg.associate = AssociateConfig(
            model="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4",
            base_url="http://localhost:8001/v1",
            api_key="k",
            context_budget=seat_budget,
        )
    return cfg


def _big_history(turns: int = 60, chars: int = 1_000) -> list[dict]:
    """A parent-budget history far larger than the seat budget (~15k tokens by chars/4)."""
    msgs: list[dict] = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "the original assignment"},
    ]
    for i in range(turns):
        msgs.append({"role": "assistant", "content": f"step {i}: " + ("x" * chars)})
    msgs.append({"role": "user", "content": "Summarise the work so far."})
    return msgs


class _RecordingEngine:
    """A fake backend recording the exact message list each seat completion receives."""

    def __init__(self, *, seat_fails: bool = False) -> None:
        self.seat_fails = seat_fails
        self.received: list[tuple[str, list[dict]]] = []

    def make_complete(self, config: EngineConfig, tools=None):  # type: ignore[no-untyped-def]
        assert tools == []

        def complete(messages: list[dict]) -> ModelResponse:
            self.received.append((config.model, messages))
            if config.model == ASSOCIATE_WIRE_MODEL and self.seat_fails:
                raise RuntimeError("associate unreachable")
            return ModelResponse(content=f"from {config.model}", tool_calls=[])

        return complete


def _armed_factory(engine: _RecordingEngine, **kw):  # type: ignore[no-untyped-def]
    factory = associate_seats.make_associate_complete(
        _config(armed=True, **kw), "fake", engine_loader=lambda name: engine
    )
    assert factory is not None
    return factory


def test_armed_lane_request_is_windowed_to_the_seat_budget_before_dispatch() -> None:
    engine = _RecordingEngine()
    factory = _armed_factory(engine)
    warnings: list[str] = []
    complete = factory(
        "compact", warnings.append, count_tokens=count_tokens_chars, lane_budget=MAIN_BUDGET
    )
    assert complete is not None
    history = _big_history()
    assert count_tokens_chars(history) > SEAT_BUDGET  # the premise: far larger than the seat

    resp = complete(history)

    assert resp.content == f"from {ASSOCIATE_WIRE_MODEL}"
    assert warnings == []  # trimmed BEFORE dispatch — no wire failure, no fallback
    assert len(engine.received) == 1
    model, sent = engine.received[0]
    assert model == ASSOCIATE_WIRE_MODEL
    assert count_tokens_chars(sent) <= SEAT_BUDGET
    assert sent[:2] == history[:2]  # system + original assignment preserved
    assert sent[-1] == history[-1]  # the lane's own final instruction preserved
    assert sum("[earlier steps elided" in (m.get("content") or "") for m in sent) == 1
    assert history == _big_history()  # the caller's list is never mutated


def test_synthesis_seat_windows_too_and_the_lane_counter_is_used() -> None:
    engine = _RecordingEngine()
    factory = _armed_factory(engine)
    calls: list[int] = []

    def counting(messages: list[dict]) -> int:
        calls.append(len(messages))
        return count_tokens_chars(messages)

    complete = factory("synthesis", lambda _t: None, count_tokens=counting, lane_budget=MAIN_BUDGET)
    assert complete is not None
    complete(_big_history())
    _, sent = engine.received[0]
    assert count_tokens_chars(sent) <= SEAT_BUDGET
    assert calls, "the lane's own estimator does the counting"


def test_fallback_still_receives_the_original_parent_budget_request() -> None:
    engine = _RecordingEngine(seat_fails=True)
    factory = _armed_factory(engine)
    warnings: list[str] = []
    complete = factory(
        "compact", warnings.append, count_tokens=count_tokens_chars, lane_budget=MAIN_BUDGET
    )
    assert complete is not None
    history = _big_history()
    resp = complete(history)
    assert resp.content == "from cortex-model"
    assert [m for m, _ in engine.received] == [ASSOCIATE_WIRE_MODEL, "cortex-model"]
    assert count_tokens_chars(engine.received[0][1]) <= SEAT_BUDGET  # windowed seat attempt
    assert engine.received[1][1] is history  # cortex@low gets the ORIGINAL list, untouched
    assert len(warnings) == 1 and "compact" in warnings[0]


def test_seat_budget_not_smaller_than_the_lane_passes_the_same_list_through() -> None:
    engine = _RecordingEngine()
    factory = _armed_factory(engine, seat_budget=MAIN_BUDGET)
    complete = factory(
        "compact", lambda _t: None, count_tokens=count_tokens_chars, lane_budget=MAIN_BUDGET
    )
    assert complete is not None
    history = _big_history()
    complete(history)
    assert engine.received[0][1] is history  # byte-identical pass-through


def test_request_that_already_fits_the_seat_passes_the_same_list_through() -> None:
    engine = _RecordingEngine()
    factory = _armed_factory(engine)
    complete = factory(
        "compact", lambda _t: None, count_tokens=count_tokens_chars, lane_budget=MAIN_BUDGET
    )
    assert complete is not None
    small = _big_history(turns=2, chars=100)
    assert count_tokens_chars(small) <= SEAT_BUDGET
    complete(small)
    assert engine.received[0][1] is small


def test_factory_without_lane_knobs_still_windows_to_the_seat() -> None:
    """The two-argument call shape (pre-#464 callers) keeps working and is safe."""
    engine = _RecordingEngine()
    factory = _armed_factory(engine)
    complete = factory("compact", lambda _t: None)
    assert complete is not None
    complete(_big_history())
    assert count_tokens_chars(engine.received[0][1]) <= SEAT_BUDGET


def test_window_to_seat_is_a_pass_through_without_a_positive_seat_budget() -> None:
    history = _big_history()
    assert associate_seats.window_to_seat(history, SimpleNamespace()) is history
    assert (
        associate_seats.window_to_seat(history, SimpleNamespace(context_budget_tokens=0)) is history
    )
    assert (
        associate_seats.window_to_seat(history, SimpleNamespace(context_budget_tokens=True))
        is history
    )


def test_unarmed_seat_complete_hands_the_acting_completion_back_untouched() -> None:
    """UNARMED: no factory → the loop keeps its acting ``complete`` (the same
    callable) and the messages reach it exactly as built."""
    assert associate_seats.make_associate_complete(_config(armed=False), "fake") is None
    received: list[list[dict]] = []

    def acting(messages: list[dict]) -> ModelResponse:
        received.append(messages)
        return ModelResponse(content="acting", tool_calls=[])

    ctx = SimpleNamespace(
        associate_complete=None,
        result=SimpleNamespace(warnings=[]),
        count_tokens=count_tokens_chars,
        context_budget=MAIN_BUDGET,
    )
    for seat in ("compact", "synthesis"):
        chosen = loop._seat_complete(ctx, seat, acting)  # type: ignore[arg-type]
        assert chosen is acting
        history = _big_history()
        chosen(history)
        assert received[-1] is history


def test_loop_seat_complete_forwards_the_lane_counter_and_budget() -> None:
    """The loop's ``_seat_complete`` hands ``ctx.count_tokens`` + ``ctx.context_budget``
    to the factory so the armed seat windows against the lane's own numbers."""
    engine = _RecordingEngine()
    factory = _armed_factory(engine)
    seen: dict = {}

    def spying_factory(seat, warn, **kw):  # type: ignore[no-untyped-def]
        seen.update(kw)
        return factory(seat, warn, **kw)

    ctx = SimpleNamespace(
        associate_complete=spying_factory,
        result=SimpleNamespace(warnings=[]),
        count_tokens=count_tokens_chars,
        context_budget=MAIN_BUDGET,
    )
    chosen = loop._seat_complete(ctx, "compact", lambda m: None)  # type: ignore[arg-type]
    assert seen == {"count_tokens": count_tokens_chars, "lane_budget": MAIN_BUDGET}
    chosen(_big_history())
    assert count_tokens_chars(engine.received[0][1]) <= SEAT_BUDGET
    assert ctx.result.warnings == []

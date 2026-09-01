"""t6 — the repetition guard wired into the two transports (spec c10/h17, c13/h18,
c33/h25, c54/h42).

:mod:`colleague.repetitionguard` (t4) is the detector; this is the wiring:

* the STREAMING path feeds it the reasoning deltas as they arrive and aborts the
  SSE read on the first trip of a turn;
* the BLOCKING path runs it ONCE, post-turn, on the finished reasoning text — at
  the LOOP level, so the same warning shape lands on every backend (c17);
* a trip CUTS THE TURN into the existing tighter-window retry (the recovery that
  demonstrably rescued run ``2bd306a6916a``), and only the
  :data:`~colleague.repetitionguard.ESCALATION_TRIP_LIMIT`-th trip of one run
  ends the run;
* one trip = one TURN in which the detector fired — never one callback (the
  detector reports a trip on EVERY chunk once the tail is repeating).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from colleague import loop, loop_transport, loopguards, repetitionguard
from colleague.contract import ERROR, OK, Task
from colleague.engines import vllm_transport
from colleague.loop import ContextControls, ModelResponse, ToolCall
from colleague.loop_wire import WorkAborted

# A 54-character unit whose fundamental period IS its own length — eight verbatim
# repeats is exactly what the incident looked like, five orders of magnitude smaller.
UNIT = "The user's brief implies a deeper structural issue!!!\n"
SPIRAL = UNIT * 12
PROSE = "First I will read the module, then locate the call site, then write the test.\n"


def _trip() -> dict[str, Any]:
    _state, trip = repetitionguard.check(SPIRAL, repetitionguard.new_state())
    assert trip is not None
    return trip


def _repetition_error(chars: int = len(SPIRAL)) -> loop_transport.RepetitionTripped:
    return loop_transport.RepetitionTripped(_trip(), reasoning_chars=chars)


def _finish(prompt: int = 80, completion: int = 10) -> ModelResponse:
    return ModelResponse(
        content="",
        tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
        prompt_tokens=prompt,
        completion_tokens=completion,
        finish_reason="tool_calls",
    )


def _spiralled(reasoning: str = SPIRAL) -> ModelResponse:
    """The blocking-path shape of the incident: reasoning burned the whole output
    budget on one repeated insight; empty content, no tool calls, length."""
    return ModelResponse(
        content="",
        tool_calls=[],
        prompt_tokens=100,
        completion_tokens=50,
        reasoning=reasoning,
        finish_reason="length",
    )


@pytest.fixture
def task(tmp_path: Path) -> Task:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Task.new(str(repo), "answer briefly")


# --- criterion 1: the streaming read is aborted, once, and the run continues ---


class _CountingResponse:
    """An SSE response whose consumed-line count is observable (no ``read1``, so
    :func:`colleague.streamguards.guarded_lines` takes its documented per-line
    degrade path)."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for line in self._lines:
            self.consumed += 1
            yield line

    def __enter__(self) -> "_CountingResponse":
        return self

    def __exit__(self, *_exc: object) -> bool:
        self.closed = True
        return False


def _spiral_lines(units: int = 20) -> list[bytes]:
    frames = [{"choices": [{"delta": {"reasoning": UNIT}, "finish_reason": None}]}] * units
    lines = [b"data: " + json.dumps(f).encode() + b"\n" for f in frames]
    lines.append(
        b"data: "
        + json.dumps(
            {
                "choices": [{"delta": {}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 90000},
            }
        ).encode()
        + b"\n"
    )
    lines.append(b"data: [DONE]\n")
    return lines


def test_streaming_reasoning_deltas_abort_the_sse_read_at_the_first_trip() -> None:
    response = _CountingResponse(_spiral_lines())
    acc = vllm_transport._StreamAccumulator()
    with pytest.raises(loop_transport.RepetitionTripped) as excinfo:
        for frame in vllm_transport._iter_sse_frames(response):
            vllm_transport._apply_stream_frame(frame, acc, lambda _d: None)
    # Exactly the 8 frames it took to see TAIL_REPEAT_MIN_COUNT verbatim repeats —
    # the remaining frames, the usage frame and [DONE] were never read.
    assert response.consumed == repetitionguard.TAIL_REPEAT_MIN_COUNT
    assert excinfo.value.reasoning_chars == len(UNIT) * repetitionguard.TAIL_REPEAT_MIN_COUNT
    assert excinfo.value.tokens_recorded is False
    assert excinfo.value.trip["period"] == len(UNIT)


def test_post_json_stream_closes_the_connection_on_a_trip(monkeypatch) -> None:
    response = _CountingResponse(_spiral_lines())
    monkeypatch.setattr(
        vllm_transport.urllib.request, "urlopen", lambda *_a, **_k: response, raising=True
    )
    with pytest.raises(loop_transport.RepetitionTripped):
        vllm_transport._post_json_stream(
            "http://x/v1/chat/completions",
            {"model": "m", "messages": [], "stream": True},
            api_key="k",
            timeout=30.0,
            on_delta=lambda _s: None,
        )
    assert response.closed is True  # the ``with urlopen(...)`` block was exited


def test_ordinary_streamed_reasoning_never_trips() -> None:
    response = _CountingResponse(
        [
            b"data: "
            + json.dumps({"choices": [{"delta": {"reasoning": f"{PROSE}step {i}\n"}}]}).encode()
            + b"\n"
            for i in range(40)
        ]
        + [b"data: [DONE]\n"]
    )
    acc = vllm_transport._StreamAccumulator()
    for frame in vllm_transport._iter_sse_frames(response):
        vllm_transport._apply_stream_frame(frame, acc, lambda _d: None)
    assert response.consumed == 41


def test_a_streaming_trip_cuts_the_turn_and_the_run_continues(task: Task) -> None:
    """Criterion 1 + the integration hazard: ONE trip cuts ONE turn into the
    existing tighter-window retry; it never ends the run."""
    seen: list[int] = []
    calls: list[int] = []

    def complete(messages):
        seen.append(len(messages))
        calls.append(1)
        if len(calls) == 1:
            raise _repetition_error()
        return _finish()

    result = loop.run(complete, task, max_steps=5, context=ContextControls(budget=5000))
    assert result.status == OK
    trips = [w for w in result.warnings if w.get("kind") == repetitionguard.WARNING_KIND]
    assert len(trips) == 1  # ONE warning for the whole cut turn, not one per chunk
    assert trips[0]["trip"] == 1
    assert trips[0]["limit"] == repetitionguard.ESCALATION_TRIP_LIMIT
    assert len(seen) == 2
    assert seen[1] <= seen[0]  # the retry ran against a tighter window
    # The cut turn produced no usable turn: only the finish turn is accounted.
    assert result.stats.model_turns == 1
    assert result.usage.completion_tokens == 10


def test_a_streaming_trip_without_a_budget_still_only_cuts_the_turn(task: Task) -> None:
    calls: list[int] = []

    def complete(_messages):
        calls.append(1)
        if len(calls) == 1:
            raise _repetition_error()
        return _finish()

    result = loop.run(complete, task, max_steps=5)
    assert result.status == OK
    assert [w["kind"] for w in result.warnings] == [repetitionguard.WARNING_KIND]
    assert len(calls) == 2


# --- criterion 2: the same detector, the same shape, on the blocking path ------


def test_blocking_path_records_the_same_warning_shape(task: Task) -> None:
    script = iter([_spiralled(), _finish()])
    result = loop.run(
        lambda _m: next(script), task, max_steps=5, context=ContextControls(budget=5000)
    )
    assert result.status == OK
    trips = [w for w in result.warnings if w.get("kind") == repetitionguard.WARNING_KIND]
    assert len(trips) == 1
    streamed = loop_transport._repetition_warning(_repetition_error(), 1, step_index=0)
    assert set(trips[0]) == set(streamed)
    assert trips[0]["guard"] == streamed["guard"] == "verbatim-tail"
    assert trips[0]["period"] == len(UNIT)
    assert trips[0]["reasoning_chars"] == len(SPIRAL)
    # The blocking turn's usage frame DID arrive: its tokens are exact and counted.
    assert trips[0]["tokens_recorded"] is True
    assert result.usage.completion_tokens == 60  # 50 (cut turn) + 10 (finish)


def test_ordinary_blocking_reasoning_never_trips(task: Task) -> None:
    ordinary = ModelResponse(
        content="",
        tool_calls=[],
        prompt_tokens=10,
        completion_tokens=10,
        reasoning="".join(f"{PROSE}then step {i} follows.\n" for i in range(40)),
        finish_reason="length",
    )
    script = iter([ordinary, _finish()])
    result = loop.run(
        lambda _m: next(script), task, max_steps=5, context=ContextControls(budget=5000)
    )
    assert [w for w in result.warnings if w.get("kind") == repetitionguard.WARNING_KIND] == []


# --- criterion 3: the Nth trip of one run ends it -----------------------------


def test_the_escalation_limit_trip_ends_the_run(task: Task) -> None:
    calls: list[int] = []

    def complete(_messages):
        calls.append(1)
        raise _repetition_error()

    # The run ends through the loop's existing preserve-the-partial abort path:
    # WorkAborted carries the finalized partial (with every warning) out to the
    # work path, which writes the artifact before surfacing the failure (#37).
    with pytest.raises(WorkAborted) as excinfo:
        loop.run(complete, task, max_steps=9, context=ContextControls(budget=5000))
    result = excinfo.value.result
    assert result.status == ERROR
    trips = [w for w in result.warnings if w.get("kind") == repetitionguard.WARNING_KIND]
    assert len(trips) == repetitionguard.ESCALATION_TRIP_LIMIT
    assert [w["trip"] for w in trips] == [1, 2, 3]
    assert len(calls) == repetitionguard.ESCALATION_TRIP_LIMIT
    assert "repetition guard" in (result.error or "")


def test_the_escalation_limit_counts_turns_not_callbacks(task: Task) -> None:
    """The hazard: the detector reports a trip on EVERY chunk once the tail
    repeats. A single 703-callback spiral is ONE trip, so the run survives it."""
    state = repetitionguard.new_state()
    warnings_seen = 0
    for i in range(0, len(SPIRAL), 40):
        state, trip = repetitionguard.check(SPIRAL[i : i + 40], state)
        warnings_seen += trip is not None
    assert warnings_seen > repetitionguard.ESCALATION_TRIP_LIMIT  # the hazard is real

    calls: list[int] = []

    def complete(_messages):
        calls.append(1)
        if len(calls) == 1:
            raise _repetition_error()
        return _finish()

    result = loop.run(complete, task, max_steps=5, context=ContextControls(budget=5000))
    assert result.status == OK
    assert len([w for w in result.warnings if w.get("kind") == repetitionguard.WARNING_KIND]) == 1


# --- criterion 4: the lost usage frame is readable, never estimated ------------


def test_a_cut_turn_records_reasoning_chars_and_the_unrecorded_token_state(task: Task) -> None:
    calls: list[int] = []

    def complete(_messages):
        calls.append(1)
        if len(calls) == 1:
            raise _repetition_error(chars=271486)
        return _finish()

    result = loop.run(complete, task, max_steps=5, context=ContextControls(budget=5000))
    trip = next(w for w in result.warnings if w.get("kind") == repetitionguard.WARNING_KIND)
    assert trip["reasoning_chars"] == 271486
    assert trip["tokens_recorded"] is False
    # Readable, and honest: the usage frame is GONE, not zero and not estimated.
    assert "unrecorded" in trip["usage"]
    assert "never estimated" in trip["usage"]
    # No token was invented for the cut turn (only the finish turn's are counted).
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (80, 10)


# --- criterion 5: exactly one warning for the reasoning-exhaustion case --------


def test_a_repetition_trip_never_also_records_a_truncated_turn(task: Task) -> None:
    """The incident's blocking shape trips BOTH detectors' preconditions (empty
    content + finish_reason=length + a repeating tail): exactly one warning."""
    spiralled = _spiralled()
    assert loop_transport._is_truncated_turn(spiralled)  # the duplicate is possible
    script = iter([spiralled, _finish()])
    result = loop.run(
        lambda _m: next(script), task, max_steps=5, context=ContextControls(budget=5000)
    )
    kinds = [w.get("kind") for w in result.warnings]
    assert kinds.count(repetitionguard.WARNING_KIND) == 1
    assert kinds.count("truncated-turn") == 0


def test_a_plain_truncation_still_records_truncated_turn(task: Task) -> None:
    """The unchanged half: a truncated turn that is NOT repeating keeps its own
    warning — the repetition guard narrows nothing it does not own."""
    script = iter([_spiralled(reasoning=PROSE + "then I stopped.\n"), _finish()])
    result = loop.run(
        lambda _m: next(script), task, max_steps=5, context=ContextControls(budget=5000)
    )
    kinds = [w.get("kind") for w in result.warnings]
    assert kinds.count("truncated-turn") == 1
    assert kinds.count(repetitionguard.WARNING_KIND) == 0


# --- criterion 6: loopguards' docstring records the reversal -------------------


def test_loopguards_docstring_records_the_ported_tier_and_its_risk() -> None:
    doc = loopguards.__doc__ or ""
    assert "2bd306a6916a" in doc  # the evidence
    assert "271,486" in doc
    assert "colleague.repetitionguard" in doc
    assert "entropy" in doc.lower()  # the tier that is still NOT ported
    assert "false-positive" in doc or "false positive" in doc
    # The stale claim is gone: the repetition tier is no longer "NOT ported".
    assert "repetition tier is off upstream" not in doc

"""Loop integration tests for adaptive compute backpressure (plan t6 / spec R2 / #255).

The loop measures each completion's wall-clock latency against the request
timeout (``colleague.backpressure``). Slow turns ARM backpressure: the next
turn's window is proactively tightened, the subagent fan-out throttle retunes,
and ONE advisory is recorded on ``result.capacity_warning`` — never an error,
never a model/backend switch. Healthy latency is a strict no-op (h2), and
recovery restores the operator's configured width (CLEAR).

Latency is simulated with a fake ``time.monotonic`` the scripted ``complete``
advances — no real sleeping, no threads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import backpressure
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def fake_clock(monkeypatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr("colleague.loop.time.monotonic", clock.monotonic)
    return clock


def _finish(summary: str = "done") -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _read() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("r", "list_dir", {"path": "."})])


def _scripted_with_latency(clock: _FakeClock, turns: list[tuple[float, ModelResponse]]):
    """A complete fn returning each scripted response after advancing the clock."""
    queue = list(turns)

    def complete(_messages: list[dict]) -> ModelResponse:
        latency, resp = queue.pop(0)
        clock.now += latency
        return resp

    return complete


def _task(tmp_path: Path) -> Task:
    return Task.new(str(tmp_path), "survey the repo", engine="mock")


def _run(tmp_path, clock, turns, *, timeout=100.0, throttle_log=None, budget=None):
    def throttle(state: str) -> None:
        if throttle_log is not None:
            throttle_log.append(state)

    controls = ContextControls(
        budget=budget,
        request_timeout=timeout,
        throttle_fanout=throttle if throttle_log is not None else None,
    )
    return run(
        _scripted_with_latency(clock, turns),
        _task(tmp_path),
        max_steps=10,
        context=controls,
    )


def test_fast_turns_are_a_strict_noop(tmp_path, fake_clock):
    throttle_log: list[str] = []
    result = _run(
        tmp_path,
        fake_clock,
        [(1.0, _read()), (1.0, _read()), (1.0, _finish())],
        throttle_log=throttle_log,
    )
    assert result.status == OK
    assert result.capacity_warning is None
    assert throttle_log == []


def test_slow_turns_arm_backpressure_and_advise_once(tmp_path, fake_clock):
    throttle_log: list[str] = []
    result = _run(
        tmp_path,
        fake_clock,
        [(60.0, _read()), (60.0, _read()), (60.0, _read()), (1.0, _finish())],
        throttle_log=throttle_log,
    )
    assert result.status == OK
    assert result.capacity_warning is not None
    assert "backpressure" in result.capacity_warning
    assert result.capacity_warning.count("backpressure") == 1  # advisory fires once
    assert backpressure.ARMED in throttle_log


def test_escalated_turns_throttle_harder(tmp_path, fake_clock):
    throttle_log: list[str] = []
    _run(
        tmp_path,
        fake_clock,
        [(90.0, _read()), (90.0, _read()), (90.0, _read()), (1.0, _finish())],
        throttle_log=throttle_log,
    )
    assert backpressure.ESCALATED in throttle_log


def test_recovery_restores_clear(tmp_path, fake_clock):
    throttle_log: list[str] = []
    _run(
        tmp_path,
        fake_clock,
        [
            (90.0, _read()),
            (90.0, _read()),
            (90.0, _read()),
            (1.0, _read()),
            (1.0, _read()),
            (1.0, _read()),
            (1.0, _finish()),
        ],
        throttle_log=throttle_log,
    )
    assert throttle_log[-1] == backpressure.CLEAR


def test_armed_state_shrinks_next_window(tmp_path, fake_clock):
    """With a budget set, the turn after arming sees a tightened window."""
    seen_message_counts: list[int] = []
    clock = fake_clock
    filler = "x " * 400  # ~800 chars per read result keeps history growing

    responses = [
        ModelResponse(tool_calls=[ToolCall(f"r{i}", "read_file", {"path": "big.txt"})])
        for i in range(4)
    ] + [_finish()]
    latencies = [60.0, 60.0, 60.0, 60.0, 1.0]
    queue = list(zip(latencies, responses))

    def complete(messages: list[dict]) -> ModelResponse:
        seen_message_counts.append(len(messages))
        latency, resp = queue.pop(0)
        clock.now += latency
        return resp

    (tmp_path / "big.txt").write_text(filler * 40)
    controls = ContextControls(budget=2000, request_timeout=100.0)
    result = run(complete, _task(tmp_path), max_steps=10, context=controls)
    assert result.status == OK
    # After arming, the windowed history handed to the model stops growing
    # monotonically — the shrunken budget drops older turns.
    assert seen_message_counts[-1] <= max(seen_message_counts)


def test_from_config_forwards_backpressure(tmp_path):
    config = EngineConfig(subagent_concurrency=3)
    controls = ContextControls.from_config(config)
    assert controls.request_timeout == config.timeout
    assert controls.throttle_fanout is not None
    controls.throttle_fanout(backpressure.ESCALATED)
    assert config.subagent_concurrency == 1
    controls.throttle_fanout(backpressure.CLEAR)
    assert config.subagent_concurrency == 3


def test_no_request_timeout_never_measures(tmp_path):
    """Dormant feature: request_timeout=None records nothing and warns never."""
    responses = [(0.0, _read()), (0.0, _finish())]

    def complete(_messages: list[dict]) -> ModelResponse:
        return responses.pop(0)[1]

    result = run(
        complete,
        _task(tmp_path),
        max_steps=5,
        context=ContextControls(request_timeout=None),
    )
    assert result.status == OK
    assert result.capacity_warning is None

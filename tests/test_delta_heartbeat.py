"""#479 t10 — in-flight liveness on the streaming path.

Before this, the flight feed's only heartbeat came from :func:`_emit_phase`
at PHASE NOTICES — turn boundaries, compaction, a tripped guard. None of
those fire *during* a single long completion, so a slow turn was silent by
construction (the issue #479 froze-for-25-minutes report). The correction:
:func:`colleague.loop_progress.delta_heartbeat` PIGGYBACKS a throttled
heartbeat onto delta arrival instead — the same seam a streamed completion
already calls once per chunk (``EngineConfig.on_delta``) — with NO timer
thread anywhere.

Acceptance criteria under test (plan t10):
1. a long streamed completion gains flight-feed records while still in
   flight, proven against a REAL slow turn (a generator with genuine
   ``time.sleep`` between chunks — never a pre-baked instantly-yielding list);
2. the throttle piggybacks on delta arrival; no thread is introduced
   (``tests/test_boundary.py`` covers the allow-list separately — this file
   never imports ``threading``/``concurrent.futures``);
3. a missing or raising flight sink stays a no-op, and no heartbeat record
   ever advances ``step_count``;
4. (documentation-only — see the ``loop_progress`` module docstring) the
   blocking path gets no in-flight liveness from this mechanism; nothing
   here claims otherwise.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from colleague import flight
from colleague.contract import Task, TaskResult
from colleague.loop_progress import DELTA_HEARTBEAT_ENV, delta_heartbeat
from colleague.loop_types import _Work


def _records(fp: Path):
    return [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]


def _ctx(tmp_path: Path, *, flight_session=None, max_steps: int = 40) -> _Work:
    """A minimal ``_Work`` — only the fields ``delta_heartbeat``/``_emit_phase``
    read are populated, mirroring the existing minimal-ctx test convention
    (``tests/test_backpressure_guard_suppression.py``)."""
    task = Task.new(str(tmp_path), "a long streamed turn")
    return _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        flight=flight_session,
        max_steps=max_steps,
    )


# ── criterion 1: proven against a real slow turn, not a fake ───────────────


def _real_slow_chunks(n: int, gap: float):
    """A generator that yields *n* chunks separated by a GENUINE
    ``time.sleep`` — real wall-clock delay, not a pre-baked instantly
    iterable list. This is the "real slow turn" fixture the task's acceptance
    criterion demands: a fake stream that yields instantly would never let a
    throttle-by-elapsed-time bug show up."""
    for i in range(n):
        if i:
            time.sleep(gap)
        yield f"chunk-{i} "


def test_heartbeat_lands_on_the_feed_while_the_turn_is_still_in_flight(tmp_path, monkeypatch):
    """The headline proof: mid-stream (only some chunks consumed, the
    generator not yet exhausted) the flight feed already carries a heartbeat
    record — liveness while still in flight, not only after the turn ends."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.05")
    sess = flight.arm(tmp_path, "t-inflight")
    ctx = _ctx(tmp_path, flight_session=sess)
    on_delta = delta_heartbeat(ctx)

    gen = _real_slow_chunks(n=6, gap=0.08)
    consumed = 0
    saw_inflight_heartbeat = False
    for chunk in gen:
        on_delta(chunk)
        consumed += 1
        if consumed < 6:
            records = _records(flight.feed_path(tmp_path, "t-inflight"))
            if any(r.get("type") == "heartbeat" for r in records):
                saw_inflight_heartbeat = True
                break

    assert saw_inflight_heartbeat, (
        "expected a heartbeat record on the feed before the streamed turn "
        "finished consuming its chunks"
    )
    # ...and the record is really a heartbeat, not a step masquerading as one
    records = _records(flight.feed_path(tmp_path, "t-inflight"))
    heartbeats = [r for r in records if r.get("type") == "heartbeat"]
    assert heartbeats
    assert "elapsed" in heartbeats[0]


def test_a_fully_silent_generator_gap_gets_no_heartbeat(tmp_path, monkeypatch):
    """Honest limit acknowledged in the module docstring: the heartbeat is
    driven BY delta arrival — a stretch with no chunks at all produces no
    heartbeat, exactly like before this task (piggybacking, not polling)."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")
    sess = flight.arm(tmp_path, "t-silent")
    ctx = _ctx(tmp_path, flight_session=sess)
    on_delta = delta_heartbeat(ctx)

    on_delta("first chunk")
    time.sleep(0.05)  # real elapsed time passes with NO delta arriving
    records_before = _records(flight.feed_path(tmp_path, "t-silent"))
    heartbeats_before = [r for r in records_before if r.get("type") == "heartbeat"]
    # exactly the one heartbeat from the first (unthrottled, first-ever) call
    assert len(heartbeats_before) == 1


# ── criterion 2: throttled; piggybacked, no polling ─────────────────────────


def test_rapid_deltas_within_the_interval_are_throttled_to_one_record(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "10")  # generous window
    sess = flight.arm(tmp_path, "t-throttle")
    ctx = _ctx(tmp_path, flight_session=sess)
    on_delta = delta_heartbeat(ctx)

    for i in range(50):
        on_delta(f"chunk-{i}")

    records = _records(flight.feed_path(tmp_path, "t-throttle"))
    heartbeats = [r for r in records if r.get("type") == "heartbeat"]
    assert len(heartbeats) == 1


def test_deltas_spread_past_the_interval_each_get_a_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.05")
    sess = flight.arm(tmp_path, "t-spread")
    ctx = _ctx(tmp_path, flight_session=sess)
    on_delta = delta_heartbeat(ctx)

    for chunk in _real_slow_chunks(n=4, gap=0.08):
        on_delta(chunk)

    records = _records(flight.feed_path(tmp_path, "t-spread"))
    heartbeats = [r for r in records if r.get("type") == "heartbeat"]
    assert len(heartbeats) >= 3


def test_empty_chunk_never_counts_as_arrival(tmp_path, monkeypatch):
    """Some transports emit an empty-string sentinel chunk; it must not reset
    the throttle clock or write a record of its own."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "10")
    sess = flight.arm(tmp_path, "t-empty")
    ctx = _ctx(tmp_path, flight_session=sess)
    on_delta = delta_heartbeat(ctx)

    on_delta("")
    on_delta("")
    records = _records(flight.feed_path(tmp_path, "t-empty"))
    assert records == []


def test_invalid_env_value_falls_back_to_the_default_throttle(tmp_path, monkeypatch):
    """An unparsable/non-positive knob degrades to the default THROTTLE, not
    to unthrottled — a bad value must never make the heartbeat fire on every
    delta."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "not-a-number")
    sess = flight.arm(tmp_path, "t-badenv")
    ctx = _ctx(tmp_path, flight_session=sess)
    on_delta = delta_heartbeat(ctx)
    for i in range(20):
        on_delta(f"chunk-{i}")
    records = _records(flight.feed_path(tmp_path, "t-badenv"))
    heartbeats = [r for r in records if r.get("type") == "heartbeat"]
    assert len(heartbeats) == 1


# ── criterion 3: missing/raising sink stays a no-op; step_count untouched ──


def test_missing_flight_and_progress_is_a_strict_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")
    ctx = _ctx(tmp_path, flight_session=None)
    on_delta = delta_heartbeat(ctx)
    on_delta("chunk one")
    time.sleep(0.02)
    on_delta("chunk two")  # must not raise with no flight and no progress sink


def test_a_raising_flight_sink_is_suppressed(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")

    class _RaisingFlight:
        def append_heartbeat(self, **kwargs):
            raise RuntimeError("disk full")

    ctx = _ctx(tmp_path, flight_session=_RaisingFlight())
    on_delta = delta_heartbeat(ctx)
    on_delta("chunk one")
    time.sleep(0.02)
    on_delta("chunk two")  # the raise must be swallowed, exactly like _emit_phase


def test_a_raising_progress_sink_is_suppressed(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")

    def _raising_progress(step_index, tool, target, ok):
        raise RuntimeError("sink exploded")

    task = Task.new(str(tmp_path), "a long streamed turn")
    ctx = _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        progress=_raising_progress,
        max_steps=40,
    )
    on_delta = delta_heartbeat(ctx)
    on_delta("chunk")  # must not raise


def test_no_heartbeat_ever_advances_step_count_or_result_steps(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")
    sess = flight.arm(tmp_path, "t-stepcount")
    ctx = _ctx(tmp_path, flight_session=sess)
    on_delta = delta_heartbeat(ctx)

    before_steps = list(ctx.result.steps)
    before_step_count = ctx.result.stats.step_count
    for chunk in _real_slow_chunks(n=5, gap=0.02):
        on_delta(chunk)

    records = _records(flight.feed_path(tmp_path, "t-stepcount"))
    heartbeats = [r for r in records if r.get("type") == "heartbeat"]
    assert heartbeats  # the mechanism actually fired for this assertion to mean anything
    assert ctx.result.steps == before_steps
    assert ctx.result.stats.step_count == before_step_count


# ── no timer thread: closure-local throttle state, independent per call ────


def test_two_independent_streams_throttle_independently(tmp_path, monkeypatch):
    """No shared/global timer state: two separate ``delta_heartbeat`` calls
    (as two concurrent streamed completions would each get) throttle on
    their own closures, not on any shared clock."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "10")
    sess_a = flight.arm(tmp_path, "t-indep-a")
    sess_b = flight.arm(tmp_path, "t-indep-b")
    ctx_a = _ctx(tmp_path, flight_session=sess_a)
    ctx_b = _ctx(tmp_path, flight_session=sess_b)
    on_delta_a = delta_heartbeat(ctx_a)
    on_delta_b = delta_heartbeat(ctx_b)

    on_delta_a("hello")
    on_delta_b("hello")
    on_delta_a("again")  # throttled against a's own clock
    on_delta_b("again")  # throttled against b's own clock, independently

    heartbeats_a = [
        r for r in _records(flight.feed_path(tmp_path, "t-indep-a")) if r.get("type") == "heartbeat"
    ]
    heartbeats_b = [
        r for r in _records(flight.feed_path(tmp_path, "t-indep-b")) if r.get("type") == "heartbeat"
    ]
    assert len(heartbeats_a) == 1
    assert len(heartbeats_b) == 1

"""#483 — the delta heartbeat, wired into the production work path.

``#479`` t10 shipped :func:`colleague.loop_progress.delta_heartbeat` (a
throttled, ``EngineConfig.on_delta``-shaped liveness callback) and tested it in
isolation (``tests/test_delta_heartbeat.py``) — but *nothing armed it*, so a
real ``colleague work`` run still went silent for the length of a slow
completion. This file covers the missing half: the COMPOSITION seam
(:mod:`colleague.loop_deltaheartbeat`) that chains the heartbeat onto whatever
``on_delta`` the caller pre-armed, at the ONE point where a live
``EngineConfig`` meets loop-owned code (``ContextControls.from_config``), and
binds it to the run's ``_Work`` ctx inside :func:`colleague.loop.run`.

Acceptance criteria under test (plan t4, spec c2/h1):

1. a bare work run whose completion streams GENUINELY slowly (real
   ``time.sleep`` between chunks, never a pre-baked instantly-yielding list)
   writes flight-feed liveness records *mid-turn* — asserted from inside the
   completion, before it returns — at no worse than 3.5s spacing; those records
   never advance ``step_count``; and an armed cockpit sink still receives every
   single chunk;
2. the blocking path's gap is real and preserved: with ``COLLEAGUE_STREAM=0``
   and no pre-armed sink, nothing is installed at all (``config.on_delta``
   stays ``None``, so the engine still sends a blocking request) — the honest
   hole documented in :mod:`colleague.loop_deltaheartbeat`;
3. a missing or raising sink — on either side of the chain — stays a no-op.

No thread is introduced anywhere (``tests/test_boundary.py`` owns that
allow-list; this file imports neither ``threading`` nor ``concurrent.futures``)
and ``colleague/streamguards.py``'s bounds are untouched.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from colleague import loop_deltaheartbeat as dhb
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.loop import run
from colleague.loop_progress import DELTA_HEARTBEAT_DEFAULT, DELTA_HEARTBEAT_ENV
from colleague.loop_types import ContextControls, _Work
from colleague.loop_wire import ModelResponse, ToolCall

#: The acceptance criterion's ceiling on mid-turn liveness spacing.
_MAX_SPACING_SECONDS = 3.5


def _records(fp: Path):
    return [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]


def _heartbeats(repo: Path, task_id: str):
    from colleague import flight

    fp = flight.feed_path(str(repo), task_id)
    if not fp.exists():
        return []
    return [r for r in _records(fp) if r.get("type") == "heartbeat"]


def _slow_chunks(n: int, gap: float):
    """Chunks separated by a GENUINE ``time.sleep`` — a real slow turn, not a
    fake one that yields instantly (a throttle-by-elapsed-time bug would be
    invisible against a fake)."""
    for i in range(n):
        if i:
            time.sleep(gap)
        yield f"chunk-{i} "


def _ctx(tmp_path: Path) -> _Work:
    task = Task.new(str(tmp_path), "a long streamed turn")
    return _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        max_steps=40,
    )


# ── the throttle default itself honours the acceptance ceiling ──────────────


def test_default_throttle_is_within_the_acceptance_spacing() -> None:
    """The shipped default (3.0s) must sit under the criterion's 3.5s bound —
    otherwise a bare run with no env knob would breach it by construction."""
    assert DELTA_HEARTBEAT_DEFAULT <= _MAX_SPACING_SECONDS


# ── AC1: bare work run, mid-turn records, step_count untouched ──────────────


def test_bare_work_run_gets_midturn_liveness_and_never_advances_step_count(tmp_path, monkeypatch):
    """The headline proof, driven through the REAL loop seam.

    A bare config (no cockpit sink) is passed through
    ``ContextControls.from_config`` exactly as both engines do, then a
    completion that streams slowly through ``config.on_delta`` — the same
    late-read seam the vLLM adapter uses (``_dispatch_once`` reads
    ``config.on_delta`` per turn) — is driven by :func:`colleague.loop.run`.
    The feed is read from INSIDE that completion, so the assertion is about
    liveness *while the turn is still in flight*, not after it.
    """
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.05")
    task = Task.new(str(tmp_path), "stream slowly", watch=True)
    config = EngineConfig()
    controls = ContextControls.from_config(config)

    # from_config is the arming point: a bare config leaves here with a chained
    # on_delta even though the caller armed nothing.
    assert config.on_delta is not None

    seen: dict[str, object] = {}

    def complete(_messages):
        for chunk in _slow_chunks(n=6, gap=0.08):
            config.on_delta(chunk)
            beats = _heartbeats(tmp_path, task.id)
            if beats and "midturn" not in seen:
                seen["midturn"] = list(beats)
        seen["final"] = _heartbeats(tmp_path, task.id)
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("c1", "finish", {"summary": "streamed and finished"})],
        )

    result = run(complete, task, max_steps=4, context=controls)

    assert seen.get("midturn"), "no heartbeat reached the feed while the turn was in flight"
    beats = seen["final"]
    assert len(beats) >= 2
    stamps = [b["elapsed"] for b in beats]
    spacing = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(gap <= _MAX_SPACING_SECONDS for gap in spacing), spacing
    # the heartbeats are liveness, never steps: only the `finish` call counted
    assert result.stats.step_count == 1
    assert [s.tool for s in result.steps] == ["finish"]


def test_a_prearmed_sink_still_receives_every_chunk(tmp_path, monkeypatch):
    """An armed cockpit sink loses nothing to the composition: it is called
    FIRST, once per chunk, with the chunk unchanged."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.05")
    chunks: list[str] = []
    task = Task.new(str(tmp_path), "stream slowly", watch=True)
    config = EngineConfig(on_delta=chunks.append)
    controls = ContextControls.from_config(config)

    sent = [f"chunk-{i} " for i in range(6)]

    def complete(_messages):
        for chunk in sent:
            config.on_delta(chunk)
            time.sleep(0.02)
        return ModelResponse(tool_calls=[ToolCall("c1", "finish", {"summary": "ok"})])

    run(complete, task, max_steps=4, context=controls)
    assert chunks == sent


def test_the_ctx_binding_happens_in_run_not_at_from_config(tmp_path, monkeypatch):
    """Before ``run`` binds the ctx there is nothing to beat against, so the
    chained sink is inert (it must not raise, and must not invent a feed)."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")
    task = Task.new(str(tmp_path), "stream slowly", watch=True)
    config = EngineConfig()
    ContextControls.from_config(config)

    config.on_delta("a chunk arriving before any run() call")
    assert _heartbeats(tmp_path, task.id) == []


# ── AC2: the blocking path's gap stays exactly as documented ────────────────


def test_blocking_path_with_no_sink_arms_nothing(monkeypatch):
    """``COLLEAGUE_STREAM=0`` + no pre-armed sink = the blocking request path.

    Nothing may be installed: an ``on_delta`` here would silently flip the vLLM
    adapter's ``streaming = config.on_delta is not None or headless`` decision
    back to streaming. The honest cost — no in-flight liveness on the blocking
    path — is the documented hole, and this test pins it.
    """
    monkeypatch.setenv("COLLEAGUE_STREAM", "0")
    config = EngineConfig()
    controls = ContextControls.from_config(config)
    assert config.on_delta is None
    assert controls.delta_binder is None


def test_blocking_env_with_a_prearmed_sink_still_composes(monkeypatch):
    """A pre-armed sink already forces the streamed path regardless of the
    env knob, so the heartbeat rides along with it."""
    monkeypatch.setenv("COLLEAGUE_STREAM", "0")
    config = EngineConfig(on_delta=lambda _chunk: None)
    ContextControls.from_config(config)
    assert config.on_delta is not None


@pytest.mark.parametrize(
    "value", [None, "", "0", "false", "FALSE", "no", "off", " off ", "1", "true", "yes", "x"]
)
def test_streaming_probe_mirrors_the_transports_own_knob(value, monkeypatch):
    """The arming gate reads ``COLLEAGUE_STREAM`` with the SAME vocabulary the
    transport does — a divergence in either direction would either force a
    blocking run to stream or drop liveness from a streamed one."""
    from colleague.engines.vllm_transport import _headless_streaming_enabled as engine_probe

    if value is None:
        monkeypatch.delenv("COLLEAGUE_STREAM", raising=False)
    else:
        monkeypatch.setenv("COLLEAGUE_STREAM", value)
    assert dhb._headless_streaming_enabled() == engine_probe()


# ── AC2: missing / raising sinks on either side stay no-ops ─────────────────


def test_a_raising_prearmed_sink_never_kills_the_stream(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")
    from colleague import flight

    def _boom(_chunk):
        raise RuntimeError("cockpit exploded")

    config = EngineConfig(on_delta=_boom)
    binder = dhb.arm(config)
    ctx = _ctx(tmp_path)
    object.__setattr__(ctx, "flight", flight.arm(str(tmp_path), ctx.task.id))
    binder(ctx)

    config.on_delta("chunk one")  # must not raise
    assert _heartbeats(tmp_path, ctx.task.id), "the heartbeat still fires past a raising sink"


def test_a_raising_heartbeat_never_kills_the_prearmed_sink(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")

    class _RaisingFlight:
        def append_heartbeat(self, **_kwargs):
            raise RuntimeError("disk full")

    chunks: list[str] = []
    config = EngineConfig(on_delta=chunks.append)
    binder = dhb.arm(config)
    ctx = _ctx(tmp_path)
    object.__setattr__(ctx, "flight", _RaisingFlight())
    binder(ctx)

    config.on_delta("chunk one")
    config.on_delta("chunk two")
    assert chunks == ["chunk one", "chunk two"]


def test_no_flight_and_no_progress_sink_is_a_strict_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "0.01")
    config = EngineConfig()
    binder = dhb.arm(config)
    binder(_ctx(tmp_path))
    config.on_delta("chunk")  # nothing armed downstream: must not raise


def test_binding_into_controls_without_a_binder_is_a_no_op(tmp_path):
    """A direct ``run()`` caller passing a plain ``ContextControls`` (no
    ``from_config``) has no binder at all — the loop-side bind must shrug."""
    dhb.bind(ContextControls(), _ctx(tmp_path))


def test_arming_twice_never_nests_or_double_beats(tmp_path, monkeypatch):
    """Re-using one config for a second run rebinds the SAME chain instead of
    wrapping it again — otherwise every run would leave a stale heartbeat
    writing to a dead run's feed."""
    monkeypatch.setenv(DELTA_HEARTBEAT_ENV, "10")
    from colleague import flight

    chunks: list[str] = []
    config = EngineConfig(on_delta=chunks.append)
    first = dhb.arm(config)
    chained = config.on_delta
    second = dhb.arm(config)
    assert config.on_delta is chained  # rebound, not re-wrapped

    ctx_a = _ctx(tmp_path)
    object.__setattr__(ctx_a, "flight", flight.arm(str(tmp_path), ctx_a.task.id))
    first(ctx_a)
    ctx_b = _ctx(tmp_path)
    object.__setattr__(ctx_b, "flight", flight.arm(str(tmp_path), ctx_b.task.id))
    second(ctx_b)

    config.on_delta("chunk")
    assert chunks == ["chunk"]  # the sink fired exactly once, not twice
    assert _heartbeats(tmp_path, ctx_a.task.id) == []  # the dead run gets nothing
    assert len(_heartbeats(tmp_path, ctx_b.task.id)) == 1

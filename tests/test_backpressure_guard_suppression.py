"""#438 guidance 3: the proactive backpressure timeout raise is suppressed while
the stream guards are armed.

``_escalate_request_timeout`` (loop.py) doubles ``config.timeout`` once, fired
from two places — the backpressure departure-from-CLEAR advisory (proactive) and
a timeout-classified degraded retry (reactive). #438 guidance 3 says the raise
is what pushed runs into the unguarded window: when :mod:`colleague.streamguards`
is armed it already bounds an alive-but-slow stream, so the PROACTIVE
departure-from-CLEAR raise is suppressed while the guards are armed. The
REACTIVE turn-timeout raise is unchanged (it fires on a real timeout, not a
drift).

Acceptance:
1. with guards armed, a backpressure departure-from-CLEAR no longer doubles
   ``config.timeout``; with guards unarmed the existing doubling is unchanged;
2. the existing backpressure tests pass unmodified.

Qodo PR #450 narrowed condition 1 honestly: "the guards are armed" is an
ENVIRONMENT fact, and the env is default-armed, so a blocking
(``COLLEAGUE_STREAM=0``) turn — which never reads its body through the guards —
was losing both the guard and the raise. The suppression now also requires the
backend to report that THIS turn's transport really was guarded; the guarded
(default, streaming) path is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine, _record_transport_guarded
from colleague.loop import (
    _make_timeout_escalator,
    _make_transport_guard_probe,
    _record_turn_latency,
    _turn_transport_guarded,
    _Work,
)


def _ctx(tmp_path: Path, cfg: SimpleNamespace) -> _Work:
    """A minimal ``_Work`` wired with a real escalator bound to *cfg*.

    Only the fields ``_record_turn_latency`` reads are populated; the rest keep
    their defaults (``fanout_throttle``/``flight``/``progress`` are ``None`` —
    strict no-ops on this path).
    """
    task = Task.new(str(tmp_path), "guard suppression")
    return _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        request_timeout=120.0,
        escalate_timeout=_make_timeout_escalator(cfg),
    )


def test_proactive_raise_suppressed_when_guards_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards armed (explicit positive bounds): a departure-from-CLEAR records
    the backpressure advisory but does NOT double ``config.timeout``."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "240")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "1800")
    cfg = SimpleNamespace(timeout=120.0)
    ctx = _ctx(tmp_path, cfg)
    # 90s toward the 120s cap -> ESCALATED (a departure from CLEAR).
    _record_turn_latency(ctx, 90.0)
    assert cfg.timeout == 120.0  # not doubled
    assert "request timeout raised" not in (ctx.result.capacity_warning or "")
    # The backpressure advisory itself is still recorded honestly.
    assert "backpressure" in (ctx.result.capacity_warning or "")


def test_proactive_raise_unchanged_when_guards_unarmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards unarmed (both bounds 0): the existing doubling is unchanged."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "0")
    cfg = SimpleNamespace(timeout=120.0)
    ctx = _ctx(tmp_path, cfg)
    _record_turn_latency(ctx, 90.0)
    assert cfg.timeout == 240.0  # doubled, as before
    assert "request timeout raised to 240s" in (ctx.result.capacity_warning or "")


# ── Qodo PR #450: suppression must follow the ACTIVE transport ──────────────
#
# ``StreamGuards.from_env()`` is default-armed, so the env check above says
# "guarded" even for a turn that never went out on the guarded SSE reader — a
# ``COLLEAGUE_STREAM=0`` run therefore lost the stream guard AND its one-time
# proactive raise. The loop now ANDs the env check with what the backend
# recorded for the turn it just sent (``_make_transport_guard_probe``).


def _ctx_with_probe(tmp_path: Path, cfg: SimpleNamespace) -> _Work:
    """``_ctx`` plus the real transport-guard probe bound to *cfg*."""
    task = Task.new(str(tmp_path), "guard suppression")
    return _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        request_timeout=120.0,
        escalate_timeout=_make_timeout_escalator(cfg),
        transport_guarded=_make_transport_guard_probe(cfg),
    )


def test_proactive_raise_fires_for_an_unguarded_blocking_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COLLEAGUE_STREAM=0: guards armed in the env, but the turn's transport was
    a plain blocking POST — the one-time proactive raise still fires."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "240")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "1800")
    cfg = SimpleNamespace(timeout=120.0)
    _record_transport_guarded(cfg, streaming=False)
    assert cfg.transport_stream_guarded is False
    ctx = _ctx_with_probe(tmp_path, cfg)
    _record_turn_latency(ctx, 90.0)
    assert cfg.timeout == 240.0
    assert "request timeout raised to 240s" in (ctx.result.capacity_warning or "")


def test_proactive_raise_still_suppressed_for_a_guarded_streaming_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default path is untouched: a streamed turn with guards armed keeps
    the #438 suppression exactly as before."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "240")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "1800")
    cfg = SimpleNamespace(timeout=120.0)
    _record_transport_guarded(cfg, streaming=True)
    assert cfg.transport_stream_guarded is True
    ctx = _ctx_with_probe(tmp_path, cfg)
    _record_turn_latency(ctx, 90.0)
    assert cfg.timeout == 120.0
    assert "request timeout raised" not in (ctx.result.capacity_warning or "")


def test_transport_guarded_is_false_when_guards_disarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both halves must hold: guards off in the env means an unguarded turn even
    on the streaming transport."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "0")
    cfg = SimpleNamespace(timeout=120.0)
    _record_transport_guarded(cfg, streaming=True)
    assert cfg.transport_stream_guarded is False


def test_unrecorded_transport_reads_as_guarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backend that records nothing (``mock``) keeps the env-only decision —
    byte-identical to the pre-#450 loop."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "240")
    cfg = SimpleNamespace(timeout=120.0)
    ctx = _ctx_with_probe(tmp_path, cfg)
    assert _turn_transport_guarded(ctx) is True
    _record_turn_latency(ctx, 90.0)
    assert cfg.timeout == 120.0


def test_a_raising_probe_never_breaks_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advisory plumbing: a probe that raises is treated as guarded, never an error."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "240")
    task = Task.new(str(tmp_path), "guard suppression")

    def boom() -> bool:
        raise RuntimeError("probe exploded")

    ctx = _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        request_timeout=120.0,
        transport_guarded=boom,
    )
    assert _turn_transport_guarded(ctx) is True


def test_blocking_dispatch_records_an_unguarded_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End of the seam: the engine's own blocking dispatch records ``False`` —
    the call that carries no ``guards=`` (the bug Qodo found)."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "240")
    config = EngineConfig(timeout=120.0)
    monkeypatch.setattr(
        vllm_openai, "_post_json", lambda *a, **k: {"choices": [{"message": {"content": "hi"}}]}
    )
    VllmOpenAIEngine._dispatch_once("http://x/v1/chat/completions", {}, config, False)
    assert config.transport_stream_guarded is False

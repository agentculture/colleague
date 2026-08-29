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
2. ``colleague/loop.py`` is the only source file changed and the existing
   backpressure tests pass unmodified.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.contract import Task, TaskResult
from colleague.loop import (
    _make_timeout_escalator,
    _record_turn_latency,
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

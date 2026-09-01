"""PR #419 review fix-ups (Qodo r2/r3/r4) — pinned so they stay fixed."""

from __future__ import annotations

import dataclasses

from colleague import effort
from colleague.config import EngineConfig
from colleague.engines import vllm_openai
from colleague.loop import ContextControls, _too_long_min_of


def test_seat_attribute_none_means_send_nothing_not_acting_fallback() -> None:
    """r2: a seat builder that resolved the kill-switch (``None``) must suppress the
    key — presence wins over truthiness; only an ABSENT attribute re-resolves."""
    base = EngineConfig()
    assert vllm_openai._effort_for(base) == base.reasoning_effort_effective == "low"
    seat = dataclasses.replace(base)
    setattr(seat, "reasoning_effort_seat", None)
    assert vllm_openai._effort_for(seat) is None
    assert effort.effort_of(seat) is None
    payload, _ = vllm_openai.VllmOpenAIEngine._build_chat_payload(seat, [], [])
    assert "chat_template_kwargs" not in payload
    fresh = dataclasses.replace(seat)  # replace drops the plain attribute
    assert vllm_openai._effort_for(fresh) == "low"  # v4 acting-seat default (#475)


def test_too_long_min_zero_is_kept_as_disabled() -> None:
    """r3: an explicit 0 (disable the wall-clock trigger) must not be rewritten to 20."""
    assert _too_long_min_of(type("C", (), {"too_long_min": 0})()) == 0
    assert _too_long_min_of(type("C", (), {"too_long_min": None})()) == 20
    assert _too_long_min_of(type("C", (), {})()) == 20
    cfg = EngineConfig()
    cfg.too_long_min = 0
    assert ContextControls.from_config(cfg).too_long_min == 0


def test_ladder_retry_warnings_fold_to_dicts() -> None:
    """r4: the ladder-400 retry warnings are artifact-ready dicts for the work front;
    empty when none fired."""
    cfg = EngineConfig()
    assert vllm_openai.ladder_retry_warnings_as_dicts(cfg) == []
    vllm_openai._record_ladder_retry_warning(
        cfg,
        vllm_openai._LadderRetryWarning(
            seat="cortex",
            effort="medium",
            detail="Supported types are xhigh (default), medium, and low",
        ),
    )
    dicts = vllm_openai.ladder_retry_warnings_as_dicts(cfg)
    assert len(dicts) == 1
    assert isinstance(dicts[0], dict)
    assert "medium" in str(dicts[0])

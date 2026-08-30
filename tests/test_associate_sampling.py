"""t23 (decisions c49/c50): the associate seat sends the operator's MEASURED
profile — depth by default (temperature 0.6, top_p 0.95, thinking on, no
max_tokens), triage only by explicit override — and cortex's payload is
byte-identical to before."""

from __future__ import annotations

from colleague import associate as associate_mod
from colleague.associate_config import (
    ASSOCIATE_PROFILES,
    AssociateConfig,
    resolve_associate_profile,
)
from colleague.config import EngineConfig
from colleague.engines.vllm_openai import VllmOpenAIEngine

_MSGS = [{"role": "user", "content": "hi"}]


def _cfg(monkeypatch, **assoc_kw) -> EngineConfig:
    monkeypatch.setattr(associate_mod, "served_window_budget", lambda a: a.context_budget)
    base = EngineConfig.resolve(discover_lobes=False)
    assoc = AssociateConfig(
        model="nvidia/Nemotron",
        base_url=base.base_url,
        api_key=base.api_key,
        context_budget=100_000,
        wire_model="associate",
        **assoc_kw,
    )
    import dataclasses

    return dataclasses.replace(base, associate=assoc)


def test_depth_profile_is_the_default_and_omits_max_tokens(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_PROFILE", raising=False)
    cfg = _cfg(monkeypatch)
    seat = associate_mod.associate_engine_config(cfg)
    payload, _ = VllmOpenAIEngine._build_chat_payload(seat, _MSGS, [])
    assert payload["temperature"] == 0.6
    assert payload["top_p"] == 0.95
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert "max_tokens" not in payload


def test_triage_profile_only_by_explicit_override(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_PROFILE", "triage")
    prof = resolve_associate_profile({})
    assert prof == ASSOCIATE_PROFILES["triage"]
    cfg = _cfg(monkeypatch, profile=prof)
    seat = associate_mod.associate_engine_config(cfg)
    payload, _ = VllmOpenAIEngine._build_chat_payload(seat, _MSGS, [])
    assert payload["temperature"] == 0.2
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["max_tokens"] == 2048


def test_unknown_profile_name_falls_back_to_depth(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_PROFILE", "nonsense")
    assert resolve_associate_profile({}).name == "depth"


def test_per_value_overrides_replace_single_fields(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_PROFILE", raising=False)
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MAX_TOKENS", "8192")
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_TEMPERATURE", "0.4")
    prof = resolve_associate_profile({})
    assert prof.name == "depth"
    assert prof.max_tokens == 8192
    assert prof.temperature == 0.4
    assert prof.enable_thinking is True
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_MAX_TOKENS")
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_TEMPERATURE")
    assert resolve_associate_profile({"thinking": "false", "top_p": "0.9"}).enable_thinking is False


def test_cortex_payload_is_byte_identical(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_PROFILE", raising=False)
    cfg = _cfg(monkeypatch)
    payload, _ = VllmOpenAIEngine._build_chat_payload(cfg, _MSGS, [])
    assert payload["temperature"] == cfg.temperature
    assert "top_p" not in payload
    assert associate_mod.seat_profile(cfg) is None


def test_profile_rides_the_resolved_seat(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_PROFILE", raising=False)
    cfg = _cfg(monkeypatch)
    assert cfg.associate.profile.name == "depth"
    seat = associate_mod.associate_engine_config(cfg)
    assert associate_mod.seat_profile(seat) is cfg.associate.profile

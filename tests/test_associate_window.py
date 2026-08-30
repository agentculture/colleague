"""#460 (delegation-follow-ups plan task t22): the associate seat is clamped to
its SERVED window, the /tokenize window cache is per (url, model), and the
role-alias retry never hides a context-length 400."""

from __future__ import annotations

import io
import urllib.error

import pytest

from colleague import associate, outputclamp
from colleague.associate_config import AssociateConfig
from colleague.engines import vllm_openai


def _assoc(budget: int = 768_000) -> AssociateConfig:
    return AssociateConfig(
        model="nvidia/Nemotron",
        base_url="http://gw.test/v1",
        api_key="k",
        context_budget=budget,
        wire_model="associate",
    )


def _http_error(code: int, body: str, url: str = "http://gw.test/v1/chat/completions"):
    return urllib.error.HTTPError(url, code, f"HTTP {code}: {body}", {}, io.BytesIO(b""))


# ── the served-window clamp ────────────────────────────────────────────────


def test_budget_is_clamped_to_the_served_window(monkeypatch):
    monkeypatch.setattr(vllm_openai, "_MAX_MODEL_LEN_BY_URL", {}, raising=True)

    def fake_probe(messages, *, url, model, api_key, timeout):
        vllm_openai._MAX_MODEL_LEN_BY_URL[(url, model)] = 128_000
        return 3

    monkeypatch.setattr(vllm_openai, "_tokenize_count", fake_probe)
    budget = associate.served_window_budget(_assoc())
    assert budget == 128_000 - outputclamp.output_clamp_margin(128_000)
    assert budget < 768_000


def test_operator_budget_smaller_than_the_window_wins(monkeypatch):
    monkeypatch.setattr(vllm_openai, "_MAX_MODEL_LEN_BY_URL", {}, raising=True)
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda m, *, url, model, api_key, timeout: vllm_openai._MAX_MODEL_LEN_BY_URL.__setitem__(
            (url, model), 128_000
        ),
    )
    assert associate.served_window_budget(_assoc(100_000)) == 100_000


def test_no_probe_result_leaves_the_configured_budget(monkeypatch):
    monkeypatch.setattr(vllm_openai, "_MAX_MODEL_LEN_BY_URL", {}, raising=True)
    monkeypatch.setattr(vllm_openai, "_tokenize_count", lambda *a, **k: None)
    assert associate.served_window_budget(_assoc()) == 768_000


def test_window_cache_is_per_model_not_per_url(monkeypatch):
    monkeypatch.setattr(vllm_openai, "_MAX_MODEL_LEN_BY_URL", {}, raising=True)
    vllm_openai._MAX_MODEL_LEN_BY_URL[("http://gw.test/tokenize", "cortex-id")] = 262_144
    assert vllm_openai.served_max_model_len("http://gw.test/tokenize", "associate") is None
    assert vllm_openai.served_max_model_len("http://gw.test/tokenize", "cortex-id") == 262_144


# ── the alias retry guard ──────────────────────────────────────────────────


def _seat_config():
    """A config object stamped the way associate_engine_config stamps a seat."""

    class Cfg:
        model = "associate"
        model_refresh_warnings: tuple = ()

    cfg = Cfg()
    setattr(cfg, associate._WIRE_FALLBACK_ATTR, "nvidia/Nemotron")
    return cfg


def test_context_length_400_is_not_treated_as_an_alias_rejection():
    exc = _http_error(
        400, "This model's maximum context length is 128000 tokens. However, you requested…"
    )
    calls = []
    out = associate.retry_role_alias(
        exc, {"model": "associate"}, _seat_config(), lambda: calls.append(1)
    )
    assert out is None
    assert calls == []


def test_fallback_failure_reraises_with_both_bodies():
    original = _http_error(422, "unroutable role alias")
    retry = _http_error(404, '{"error": {"code": "role_infeasible"}}')

    def dispatch():
        raise retry

    with pytest.raises(urllib.error.HTTPError) as info:
        associate.retry_role_alias(original, {"model": "associate"}, _seat_config(), dispatch)
    msg = str(info.value.msg)
    assert "unroutable role alias" in msg and "role_infeasible" in msg
    assert info.value.code == 422  # the ORIGINAL status leads

"""The associate seat-build /tokenize probe: a FAILED probe is remembered per
process (Qodo 4 on PR #464) and the cache-miss -> probe -> store sequence is
serialized by one lock so concurrent seat builds spend at most ONE probe
(Qodo 7). Companion to tests/test_associate_window.py (left untouched)."""

from __future__ import annotations

import threading
import time

import pytest

from colleague import associate
from colleague.associate_config import AssociateConfig
from colleague.engines import vllm_openai


def _assoc(budget: int = 768_000, base_url: str = "http://gw.test/v1") -> AssociateConfig:
    return AssociateConfig(
        model="nvidia/Nemotron",
        base_url=base_url,
        api_key="k",
        context_budget=budget,
        wire_model="associate",
    )


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    """Every test starts with an empty served-window cache and no failed probes."""
    monkeypatch.setattr(vllm_openai, "_MAX_MODEL_LEN_BY_URL", {}, raising=True)
    monkeypatch.setattr(associate, "_PROBE_FAILED", set(), raising=True)


# ── Qodo 4: a failed probe happens at most once per (url, model) per process ──


def test_failed_probe_is_remembered_and_never_repeated(monkeypatch):
    calls: list[tuple[str, str]] = []

    def failing_probe(messages, *, url, model, api_key, timeout):
        calls.append((url, model))
        return None  # an endpoint without /tokenize: no max_model_len, no count

    monkeypatch.setattr(vllm_openai, "_tokenize_count", failing_probe)
    for _ in range(5):  # a run can build five associate sub-seats
        assert associate.served_window_budget(_assoc()) == 768_000
    assert len(calls) == 1, calls
    assert calls[0] == (vllm_openai._tokenize_url("http://gw.test/v1"), "associate")
    # No probe result leaves the configured budget untouched — still true.
    assert associate.served_window_budget(_assoc(100_000)) == 100_000
    assert len(calls) == 1


def test_failed_probe_memo_is_per_url_and_model(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda messages, *, url, model, api_key, timeout: calls.append((url, model)),
    )
    associate.served_window_budget(_assoc())
    associate.served_window_budget(_assoc(base_url="http://other.test/v1"))
    associate.served_window_budget(_assoc())
    associate.served_window_budget(_assoc(base_url="http://other.test/v1"))
    assert sorted(calls) == sorted(
        [
            (vllm_openai._tokenize_url("http://gw.test/v1"), "associate"),
            (vllm_openai._tokenize_url("http://other.test/v1"), "associate"),
        ]
    )


def test_a_later_successful_probe_through_another_path_is_honoured(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda messages, *, url, model, api_key, timeout: calls.append(url),
    )
    assert associate.served_window_budget(_assoc()) == 768_000
    assert associate.served_window_budget(_assoc()) == 768_000
    assert len(calls) == 1
    # The run-start probe (or any other path) later sees max_model_len: the
    # adapter's cache is read BEFORE the failed-probe memo, so it wins.
    url = vllm_openai._tokenize_url("http://gw.test/v1")
    vllm_openai._MAX_MODEL_LEN_BY_URL[(url, "associate")] = 128_000
    budget = associate.served_window_budget(_assoc())
    assert 0 < budget < 128_000
    assert budget == 128_000 - __import__("colleague.outputclamp").outputclamp.output_clamp_margin(
        128_000
    )
    assert len(calls) == 1  # still never re-probed


def test_successful_probe_never_lands_in_the_failed_memo(monkeypatch):
    def probe(messages, *, url, model, api_key, timeout):
        vllm_openai._MAX_MODEL_LEN_BY_URL[(url, model)] = 128_000
        return 3

    monkeypatch.setattr(vllm_openai, "_tokenize_count", probe)
    assert associate.served_window_budget(_assoc()) < 128_000
    assert associate._PROBE_FAILED == set()


# ── Qodo 7: concurrent seat builds on a cache miss produce exactly one probe ──


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_concurrent_cache_miss_produces_exactly_one_probe(monkeypatch, outcome):
    n_threads = 8
    calls: list[str] = []
    calls_lock = threading.Lock()
    start = threading.Barrier(n_threads)

    def slow_probe(messages, *, url, model, api_key, timeout):
        with calls_lock:
            calls.append(url)
        time.sleep(0.05)  # widen the miss window so an unguarded race would show
        if outcome == "success":
            vllm_openai._MAX_MODEL_LEN_BY_URL[(url, model)] = 128_000
            return 3
        return None

    monkeypatch.setattr(vllm_openai, "_tokenize_count", slow_probe)
    budgets: list[int] = []
    errors: list[BaseException] = []

    def build():
        try:
            start.wait(timeout=5)
            budgets.append(associate.served_window_budget(_assoc()))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=build) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, errors
    assert len(budgets) == n_threads
    assert len(calls) == 1, f"expected exactly one probe, saw {len(calls)}"
    if outcome == "success":
        assert len(set(budgets)) == 1
        assert budgets[0] < 128_000
    else:
        assert budgets == [768_000] * n_threads


def test_probe_lock_is_a_lock_not_a_thread():
    """The boundary sanction for associate.py is a lock only — no thread primitive."""
    import inspect

    src = inspect.getsource(associate)
    assert "threading.Lock()" in src
    assert "threading.Thread" not in src
    assert "threading.Timer" not in src

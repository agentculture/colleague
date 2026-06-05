"""Context windowing + bounded reactive overflow degradation in the loop (t4).

Engine-agnostic: every test drives :func:`colleague.loop.run` directly with an
injected ``complete`` callable and a deterministic injected ``count_tokens``, so
the windowing + retry behaviour is verified on the chassis itself (the all-engines
rule — it holds identically for ``mock`` and ``vllm-openai``).

The feature has three moving parts, exercised here:

1. Proactive windowing — each turn the running history is trimmed in place to the
   ``context_budget`` BEFORE ``complete`` is called.
2. Reactive degradation — if ``complete`` raises a *context-overflow* error and a
   budget is set, the budget is shrunk and the history re-windowed, then the call
   retried, up to a small fixed cap (then the original error is re-raised so the
   partial result is preserved via :class:`WorkAborted`).
3. The vLLM ``/tokenize`` exact counter, with its char-estimate fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import ERROR, OK, Task
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.loop import (
    _MAX_OVERFLOW_RETRIES,
    _MAX_TIMEOUT_RETRIES,
    ContextControls,
    ModelResponse,
    ToolCall,
    WorkAborted,
    run,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _word_count_tokens(messages: list[dict]) -> int:
    """A deterministic, injectable token counter: one token per whitespace word.

    Independent of the char/4 heuristic so tests pin behaviour exactly regardless
    of the production estimator.
    """
    total = 0
    for m in messages:
        content = m.get("content")
        if content:
            total += len(str(content).split())
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            total += len(str(fn.get("name") or "").split())
            total += len(str(fn.get("arguments") or "").split())
    return total


# ---------------------------------------------------------------------------
# 1. proactive windowing
# ---------------------------------------------------------------------------


def test_proactive_windowing_trims_history_each_turn(tmp_path: Path) -> None:
    """With a small budget the running history is windowed before each ``complete``.

    A ``complete`` that never finishes keeps appending an assistant turn + a tool
    reply each step, so without windowing the message list would grow unboundedly.
    We record the message-list length the loop hands ``complete`` each turn and
    assert it stays bounded (it does not grow without limit) — proof the loop
    trimmed in place between turns.
    """
    seen_lengths: list[int] = []

    def never_finish(messages: list[dict]) -> ModelResponse:
        seen_lengths.append(len(messages))
        # Each turn requests a list_dir, producing assistant + tool messages that
        # accumulate — windowing must keep the list from growing without bound.
        return ModelResponse(
            content="thinking about the next move " * 4,
            tool_calls=[ToolCall(f"c{len(seen_lengths)}", "list_dir", {"path": "."})],
        )

    task = Task.new(str(tmp_path), "loop and accumulate history")
    run(
        never_finish,
        task,
        max_steps=12,
        context=ContextControls(budget=20, count_tokens=_word_count_tokens),
    )

    # Many turns ran, and the per-turn message length is bounded — the late turns
    # are not unboundedly larger than the early ones (history was windowed).
    assert len(seen_lengths) >= 6
    assert max(seen_lengths) <= min(seen_lengths) + 4


def test_no_budget_does_not_window(tmp_path: Path) -> None:
    """With no ``context_budget`` set the history grows unwindowed (default off).

    This pins that the feature is opt-in: absent a positive budget the loop never
    trims, so behaviour is byte-identical to the pre-feature loop.
    """
    seen_lengths: list[int] = []

    def never_finish(messages: list[dict]) -> ModelResponse:
        seen_lengths.append(len(messages))
        return ModelResponse(
            content="x", tool_calls=[ToolCall(f"c{len(seen_lengths)}", "list_dir", {"path": "."})]
        )

    task = Task.new(str(tmp_path), "loop")
    run(never_finish, task, max_steps=5)  # no context_budget

    # Unwindowed: each turn the list strictly grew (assistant + tool appended).
    assert seen_lengths == sorted(seen_lengths)
    assert seen_lengths[-1] > seen_lengths[0]


# ---------------------------------------------------------------------------
# 2. reactive retry
# ---------------------------------------------------------------------------


def test_reactive_retry_then_recover(tmp_path: Path) -> None:
    """An overflow on the first call is retried (smaller budget) and then recovers.

    The first ``complete`` raises a context-overflow error; the loop shrinks the
    budget, re-windows, and retries. The retry returns a finishing response, so
    the drive completes ``ok``. We assert ``complete`` was called more than once
    and that the history handed to it shrank between the failing call and the
    retry (proof the re-window happened).
    """
    seen_lengths: list[int] = []
    state = {"n": 0}

    # Pre-seed enough turns so there is droppable history to shrink. We do this by
    # letting the loop accumulate first; instead, make the FIRST turn carry a long
    # user prompt so windowing actually has something to shed.
    long_filler = "word " * 200

    def flaky(messages: list[dict]) -> ModelResponse:
        seen_lengths.append(len(messages))
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("This model's maximum context length is 4096 tokens")
        return ModelResponse(tool_calls=[ToolCall("done", "finish", {"summary": "recovered"})])

    task = Task.new(str(tmp_path), f"do the thing {long_filler}")
    result = run(
        flaky,
        task,
        max_steps=10,
        context=ContextControls(budget=10, count_tokens=_word_count_tokens),
    )

    assert result.status == OK
    assert result.summary == "recovered"
    # A retry happened: complete was called at least twice.
    assert state["n"] >= 2
    assert len(seen_lengths) >= 2
    # The re-window shrank the message list between the failing call and the retry.
    assert seen_lengths[1] <= seen_lengths[0]


def test_non_recoverable_overflow_preserves_partial(tmp_path: Path) -> None:
    """An always-overflowing ``complete`` is bounded and yields a preserved partial.

    When every retry still overflows, the loop stops after the bounded cap and
    re-raises — surfaced as :class:`WorkAborted` carrying the partial
    (``status == error``) result. The number of ``complete`` calls is bounded
    (it does NOT loop forever).
    """
    calls = {"n": 0}
    long_filler = "word " * 400

    def always_overflow(messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        raise RuntimeError("maximum context length exceeded: reduce the length")

    task = Task.new(str(tmp_path), f"impossible {long_filler}")
    with pytest.raises(WorkAborted) as excinfo:
        run(
            always_overflow,
            task,
            max_steps=10,
            context=ContextControls(budget=10, count_tokens=_word_count_tokens),
        )

    result = excinfo.value.result
    assert result.status == ERROR
    assert "maximum context length" in (result.error or "").lower() or "RuntimeError" in (
        result.error or ""
    )
    # Bounded: a small fixed number of attempts, never the full max_steps*∞.
    assert 1 < calls["n"] <= 6


def test_non_overflow_error_propagates_immediately(tmp_path: Path) -> None:
    """A generic (non-overflow) error is NOT retried — one call, then WorkAborted.

    Only context-overflow errors trigger the reactive retry. Any other exception
    propagates immediately (preserved as a partial via WorkAborted) exactly as in
    the pre-feature loop — no extra ``complete`` calls.
    """
    calls = {"n": 0}

    def boom(messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        raise ValueError("something unrelated broke")

    task = Task.new(str(tmp_path), "generic failure")
    with pytest.raises(WorkAborted) as excinfo:
        run(
            boom,
            task,
            max_steps=10,
            context=ContextControls(budget=10, count_tokens=_word_count_tokens),
        )

    assert calls["n"] == 1  # not retried
    assert excinfo.value.result.status == ERROR
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_overflow_without_budget_is_not_retried(tmp_path: Path) -> None:
    """With no budget set, an overflow error is also not retried (gate requires budget)."""
    calls = {"n": 0}

    def overflow(messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        raise RuntimeError("maximum context length exceeded")

    task = Task.new(str(tmp_path), "overflow no budget")
    with pytest.raises(WorkAborted):
        run(overflow, task, max_steps=10)  # no context_budget

    assert calls["n"] == 1  # no retry without a budget


# ---------------------------------------------------------------------------
# 2b. reactive degradation on a *request timeout* (#154) — mirrors overflow,
#     but capped lower because each timeout costs a full request-timeout window.
# ---------------------------------------------------------------------------


def test_timeout_reactive_retry_then_recover(tmp_path: Path) -> None:
    """A request timeout on the first call is retried (smaller window) and recovers.

    Mirrors the overflow degradation path (#154): the first ``complete`` raises a
    request-timeout error, the loop shrinks the budget, re-windows, and retries; the
    retry finishes, so the drive completes ``ok`` instead of hard-failing.
    """
    state = {"n": 0}

    def flaky(messages: list[dict]) -> ModelResponse:
        state["n"] += 1
        if state["n"] == 1:
            raise TimeoutError("request to http://x/v1/chat/completions timed out after 120s")
        return ModelResponse(tool_calls=[ToolCall("done", "finish", {"summary": "recovered"})])

    task = Task.new(str(tmp_path), f"do the thing {'word ' * 50}")
    result = run(
        flaky,
        task,
        max_steps=10,
        context=ContextControls(budget=10, count_tokens=_word_count_tokens),
    )

    assert result.status == OK
    assert result.summary == "recovered"
    assert state["n"] >= 2  # a retry happened


def test_non_recoverable_timeout_capped_lower_than_overflow(tmp_path: Path) -> None:
    """A never-recovering request timeout is bounded by the LOWER timeout cap (#154).

    Each timeout attempt costs a full request-timeout window, so the loop retries a
    timeout fewer times than an overflow. The total ``complete`` calls on a persistent
    timeout is exactly ``_MAX_TIMEOUT_RETRIES + 2`` (first attempt + the retries + the
    final re-attempt) — strictly fewer than the overflow floor — and the partial is
    preserved via :class:`WorkAborted`.
    """
    calls = {"n": 0}

    def always_timeout(messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        raise TimeoutError("request to http://x/v1/chat/completions timed out after 120s")

    task = Task.new(str(tmp_path), f"slow {'word ' * 200}")
    with pytest.raises(WorkAborted) as excinfo:
        run(
            always_timeout,
            task,
            max_steps=10,
            context=ContextControls(budget=10, count_tokens=_word_count_tokens),
        )

    assert excinfo.value.result.status == ERROR
    assert "timed out" in (excinfo.value.result.error or "").lower()
    assert calls["n"] == _MAX_TIMEOUT_RETRIES + 2
    # The whole point of the separate cap: a timeout is retried less than an overflow.
    assert _MAX_TIMEOUT_RETRIES + 2 < _MAX_OVERFLOW_RETRIES + 2


def test_overflow_after_timeout_restores_overflow_cap(tmp_path: Path) -> None:
    """An overflow after an earlier timeout still gets the FULL overflow cap (#157).

    ``classify_degradable`` says overflow takes precedence over timeout. The reactive
    loop must honour that: seeing a timeout first must not permanently narrow the cap
    to the (lower) timeout cap and starve the cheaper overflow retries that follow. A
    run that times out once, then overflows forever, must make ``_MAX_OVERFLOW_RETRIES
    + 2`` ``complete`` calls — the overflow floor — not the timeout-capped
    ``_MAX_TIMEOUT_RETRIES + 2``. (The budget starts large so the per-signal cap, not
    the message floor, is the binding constraint.)
    """
    calls = {"n": 0}

    def timeout_then_overflow(messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("request to http://x/v1/chat/completions timed out after 120s")
        raise RuntimeError("maximum context length exceeded: reduce the length")

    task = Task.new(str(tmp_path), f"mixed {'word ' * 50}")
    with pytest.raises(WorkAborted) as excinfo:
        run(
            timeout_then_overflow,
            task,
            max_steps=10,
            context=ContextControls(budget=1000, count_tokens=_word_count_tokens),
        )

    assert excinfo.value.result.status == ERROR
    # Overflow precedence restored the higher cap — strictly more than the timeout cap.
    assert calls["n"] == _MAX_OVERFLOW_RETRIES + 2
    assert calls["n"] > _MAX_TIMEOUT_RETRIES + 2


def test_timeout_without_budget_is_not_retried(tmp_path: Path) -> None:
    """With no budget set, a request timeout is also not retried (gate requires budget)."""
    calls = {"n": 0}

    def timeout(messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        raise TimeoutError("timed out")

    task = Task.new(str(tmp_path), "timeout no budget")
    with pytest.raises(WorkAborted):
        run(timeout, task, max_steps=10)  # no context_budget → pass-through

    assert calls["n"] == 1  # no retry without a budget


# ---------------------------------------------------------------------------
# 3. /tokenize exact counter (+ fallback)
# ---------------------------------------------------------------------------


def _messages() -> list[dict]:
    return [
        {"role": "system", "content": "you are a coder"},
        {"role": "user", "content": "do the work please"},
    ]


def test_tokenize_counter_returns_exact_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``/tokenize`` succeeds, the public counter returns its exact ``count``.

    Patches the low-level :func:`_tokenize_count` (the sanctioned seam) so the
    public counter returns the server's exact integer, NOT the char estimate.
    """
    captured: dict[str, Any] = {}

    def fake_count(messages: list[dict], *, url: str, model: str, api_key: str, timeout: float):
        captured["url"] = url
        captured["model"] = model
        return 4242

    monkeypatch.setattr(vllm_openai, "_tokenize_count", fake_count)

    config = EngineConfig(base_url="http://localhost:8001/v1", model="my-model")
    counter = VllmOpenAIEngine()._make_count_tokens(config)
    assert counter(_messages()) == 4242
    # URL is derived by stripping the trailing /v1 and appending /tokenize; model
    # is threaded through from config.
    assert captured["url"] == "http://localhost:8001/tokenize"
    assert captured["model"] == "my-model"


def test_tokenize_url_strips_v1_with_and_without_trailing_slash() -> None:
    """The /tokenize URL is derived from base_url by stripping a trailing /v1."""
    assert vllm_openai._tokenize_url("http://localhost:8001/v1") == "http://localhost:8001/tokenize"
    assert (
        vllm_openai._tokenize_url("http://localhost:8001/v1/") == "http://localhost:8001/tokenize"
    )
    # A base_url that does not end in /v1 just gets /tokenize appended.
    assert vllm_openai._tokenize_url("http://host:9999") == "http://host:9999/tokenize"


def test_tokenize_counter_falls_back_to_char_estimate_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any ``/tokenize`` failure (counter returns None) falls back to the char estimate.

    The public counter ALWAYS returns an int — exact when ``/tokenize`` works,
    the :func:`count_tokens_chars` estimate otherwise. This graceful fallback is
    what lets retargeting a non-vLLM OpenAI server (no ``/tokenize``) stay a config
    change, not a code change.
    """

    def none_count(messages: list[dict], *, url: str, model: str, api_key: str, timeout: float):
        return None  # endpoint unavailable / error

    monkeypatch.setattr(vllm_openai, "_tokenize_count", none_count)

    config = EngineConfig(base_url="http://localhost:8001/v1")
    counter = VllmOpenAIEngine()._make_count_tokens(config)
    msgs = _messages()
    assert counter(msgs) == count_tokens_chars(msgs)


def test_tokenize_count_returns_none_on_post_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The low-level _tokenize_count returns None when the POST raises (any error)."""

    def boom(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        raise OSError("connection refused")

    monkeypatch.setattr(vllm_openai, "_tokenize_post", boom)
    assert (
        vllm_openai._tokenize_count(
            _messages(),
            url="http://localhost:8001/tokenize",
            model="m",
            api_key="EMPTY",
            timeout=1,
        )
        is None
    )


def test_tokenize_count_returns_none_when_count_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The low-level _tokenize_count returns None when the reply has no int 'count'."""

    def no_count(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        return {"max_model_len": 8192}  # no "count"

    monkeypatch.setattr(vllm_openai, "_tokenize_post", no_count)
    assert (
        vllm_openai._tokenize_count(
            _messages(),
            url="http://localhost:8001/tokenize",
            model="m",
            api_key="EMPTY",
            timeout=1,
        )
        is None
    )


def test_tokenize_count_reads_exact_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """The low-level _tokenize_count reads the integer 'count' from a real reply."""

    def reply(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        assert payload == {"model": "m", "messages": _messages()}
        return {"count": 99, "max_model_len": 8192, "tokens": [1, 2]}

    monkeypatch.setattr(vllm_openai, "_tokenize_post", reply)
    assert (
        vllm_openai._tokenize_count(
            _messages(),
            url="http://localhost:8001/tokenize",
            model="m",
            api_key="EMPTY",
            timeout=1,
        )
        == 99
    )


# ---------------------------------------------------------------------------
# 4. mock parity
# ---------------------------------------------------------------------------


def test_mock_engine_drives_with_windowing(tmp_path: Path) -> None:
    """The mock engine forwards ``context_budget`` and still completes ``ok``.

    All-engines rule: the mock (the contract reference) exercises the same loop
    windowing path. A normal small drive fits easily under the default budget, so
    it completes unchanged — this guards that wiring windowing on did not break the
    contract reference.
    """
    from colleague import registry

    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve()

    result = registry.load("mock").work(Task.new(str(repo), "do work"), cfg)
    assert result.status == OK
    assert result.changed_files

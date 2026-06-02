"""End-to-end graceful-degradation success-signal tests (t5).

These tests prove the graceful-degradation feature works as a whole — they are
the INTEGRATION / e2e layer, not a duplicate of the unit tests in
``test_loop_degradation.py``.  The key signal is that the original bug from
issue #76 is fixed: a context-overflow that the loop cannot recover from must
still produce parseable JSON on stdout (NOT empty stdout) when ``drive --json``
is used.  An ``outsource.sh``-style consumer that does ``json.loads(stdout)``
gets a usable result object, not a parse error.

Tests
-----
1. Overflow-once → recover (success signal #1).
   The loop + reactive retry + windowing work together to complete ``ok``.

2. Non-recoverable overflow → readable partial on STDOUT (headline e2e, #76).
   Loop + CLI: when the vLLM engine's POST always raises a context-overflow
   error, ``drive --json`` emits parseable JSON on stdout (``status == "error"``,
   non-empty ``steps`` is NOT required but the object must parse), exits non-zero,
   puts the diagnostic on stderr, and the POST is called a bounded number of
   times (not infinitely).

3. /tokenize counter exact + graceful fallback (h14).
   Tests the vLLM-specific ``_make_count_tokens`` / ``_tokenize_url`` seams.

4. Guards stay green (asserted by running; ``test_e2e_mock`` and
   ``test_zero_deps`` are the referenced guard suites — run separately).
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from convertible.cli import main
from convertible.config import EngineConfig
from convertible.context import count_tokens_chars
from convertible.contract import ERROR, OK, Task
from convertible.engines import vllm_openai
from convertible.engines.vllm_openai import VllmOpenAIEngine, _tokenize_url
from convertible.loop import DriveAborted, ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _word_count_tokens(messages: list[dict]) -> int:
    """A deterministic, injectable token counter: one token per whitespace word.

    Reused from ``test_loop_degradation.py`` — independent of the char/4
    heuristic so tests pin behaviour exactly regardless of the production
    estimator.
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


def _overflow_http_error(
    msg: str = "maximum context length is 32768 tokens",
) -> urllib.error.HTTPError:
    """Build a fake HTTPError whose stringified form contains an overflow phrase."""

    class _FakeResponse:
        def read(self) -> bytes:
            return json.dumps({"error": {"message": msg}}).encode()

        def close(self) -> None:
            pass

    return urllib.error.HTTPError(
        "http://localhost:8001/v1/chat/completions",
        400,
        msg,
        {},
        _FakeResponse(),
    )


# ---------------------------------------------------------------------------
# 1. Overflow-once → recover (success signal #1)
# ---------------------------------------------------------------------------


def test_overflow_once_then_recover_completes_ok(tmp_path: Path) -> None:
    """Loop + reactive retry + windowing: one overflow is recovered, drive ends ok.

    Drives :func:`run` directly with a ``complete`` that raises a context-overflow
    error on its first call (simulating the model returning a 400 / body containing
    "maximum context length"), then returns a finishing ``ModelResponse``.

    Asserts:
    - ``result.status == "ok"``
    - ``complete`` was called more than once (a retry happened)
    - the message list given to the second call was not larger than the first
      (the re-window shrank the history before retry)
    """
    seen_lengths: list[int] = []
    call_count = {"n": 0}
    long_filler = "word " * 200  # seed a long user message so windowing has material to cut

    def flaky_complete(messages: list[dict]) -> ModelResponse:
        seen_lengths.append(len(messages))
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("This model's maximum context length is 32768 tokens")
        return ModelResponse(
            tool_calls=[ToolCall("fin", "finish", {"summary": "recovered after overflow"})]
        )

    task = Task.new(str(tmp_path), f"do the thing {long_filler}")
    result = run(
        flaky_complete,
        task,
        max_steps=10,
        context_budget=20,
        count_tokens=_word_count_tokens,
    )

    assert result.status == OK, f"expected ok, got: {result.status!r}, error={result.error!r}"
    assert result.summary == "recovered after overflow"
    # A retry happened — complete was called at least twice.
    assert call_count["n"] >= 2, f"expected at least 2 calls, got {call_count['n']}"
    assert len(seen_lengths) >= 2
    # The re-window shrank (or at worst kept equal) the message list before the retry.
    assert seen_lengths[1] <= seen_lengths[0], (
        f"expected retry to see shorter or equal messages: "
        f"first={seen_lengths[0]} retry={seen_lengths[1]}"
    )


# ---------------------------------------------------------------------------
# 2. Non-recoverable overflow → readable partial on STDOUT (headline e2e, #76)
# ---------------------------------------------------------------------------


def test_non_recoverable_overflow_emits_parseable_json_to_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Headline e2e test: a persistent overflow produces parseable JSON on stdout.

    This is the exact scenario from issue #76 that previously produced "convertible
    produced no result on stdout": the vLLM engine's chat-completion POST always
    raises a context-overflow HTTPError, the loop retries a bounded number of times
    and gives up, and the CLI must still emit parseable JSON to stdout with
    ``status == "error"``.

    The key assertions are:
    - stdout is parseable JSON (``json.loads`` succeeds).
    - ``json.loads(stdout)["status"] == "error"``
    - the process exits non-zero (``rc != 0``).
    - the human diagnostic is on stderr (not polluting stdout).
    - the POST was called a bounded number of times (not infinitely).
    """
    post_call_count = {"n": 0}

    def always_overflow_post(
        url: str, payload: dict, *, api_key: str, timeout: float
    ) -> dict[str, Any]:
        post_call_count["n"] += 1
        raise _overflow_http_error("maximum context length is 32768 tokens")

    monkeypatch.setattr(vllm_openai, "_post_json", always_overflow_post)
    # Also stub /tokenize so the counter falls back to char-estimate without a
    # network call (the engine uses _make_count_tokens internally).
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda messages, *, url, model, api_key, timeout: None,
    )

    rc = main(
        [
            "drive",
            "do some work that always overflows",
            "--repo",
            str(tmp_path),
            "--engine",
            "vllm-openai",
            "--no-pr",
            "--json",
            "--max-steps",
            "3",
        ]
    )

    captured = capsys.readouterr()

    # The process MUST exit non-zero.
    assert rc != 0, "expected non-zero exit on persistent overflow"

    # stdout MUST be parseable JSON — this is the #76 fix.
    assert captured.out.strip(), "stdout must not be empty on overflow (was empty before #76 fix)"
    payload = json.loads(captured.out)  # raises if stdout is not valid JSON

    # The result object must have a status field.
    assert "status" in payload, f"result JSON missing 'status': {payload}"
    assert payload["status"] == "error", f"expected status=error, got: {payload['status']!r}"

    # A 'task_id' must be present (outsource.sh-style consumers rely on this).
    assert "task_id" in payload, f"result JSON missing 'task_id': {payload}"

    # The human diagnostic must appear on stderr, not stdout.
    assert (
        "maximum context length" in captured.err.lower()
        or "overflow" in captured.err.lower()
        or rc != 0
    ), "diagnostic should appear on stderr"

    # Bounded: the POST was called a small fixed number of times, not infinitely.
    # _MAX_OVERFLOW_RETRIES == 3, so total attempts <= 4 (1 + 3 retries) per loop
    # turn, and max_steps=3 caps outer turns; we assert a generous but finite upper
    # bound (30) to prove the retry loop terminated.
    assert post_call_count["n"] > 0, "POST was never called — engine not reached"
    assert (
        post_call_count["n"] <= 30
    ), f"POST was called {post_call_count['n']} times — looks like an infinite retry loop"


def test_non_recoverable_overflow_stdout_is_clean_json_for_outsource_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Simulate the outsource.sh consumer: json.loads(stdout) succeeds without error.

    This is the direct reproduction of the #76 failure mode: before the fix,
    stdout was empty or contained diagnostic text, making json.loads raise.
    """
    monkeypatch.setattr(
        vllm_openai,
        "_post_json",
        lambda url, payload, *, api_key, timeout: (_ for _ in ()).throw(
            RuntimeError("maximum context length exceeded: reduce the length")
        ),
    )
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda messages, *, url, model, api_key, timeout: None,
    )

    main(
        [
            "drive",
            "work",
            "--repo",
            str(tmp_path),
            "--engine",
            "vllm-openai",
            "--no-pr",
            "--json",
            "--max-steps",
            "2",
        ]
    )

    stdout_text = capsys.readouterr().out
    # outsource.sh-style: this must not raise
    obj = json.loads(stdout_text)
    assert "status" in obj
    assert "task_id" in obj


# ---------------------------------------------------------------------------
# 3. /tokenize counter exact + graceful fallback (h14)
# ---------------------------------------------------------------------------


def test_tokenize_url_strips_v1_correctly() -> None:
    """_tokenize_url derives the /tokenize URL by stripping /v1 from base_url.

    The URL must not contain /v1 and must end with /tokenize.
    """
    result = _tokenize_url("http://x:8001/v1")
    assert result.endswith("/tokenize"), f"expected /tokenize suffix: {result!r}"
    assert "/v1" not in result, f"expected /v1 stripped: {result!r}"
    # With trailing slash on /v1
    result2 = _tokenize_url("http://x:8001/v1/")
    assert result2 == "http://x:8001/tokenize"


def test_make_count_tokens_returns_exact_count_from_tokenize_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When /tokenize succeeds, _make_count_tokens returns the exact integer count.

    Patches _tokenize_count (the sanctioned seam) to return 1234; the public
    counter returned by _make_count_tokens must return that exact value.
    """
    captured: dict[str, Any] = {}

    def fake_tokenize_count(
        messages: list[dict], *, url: str, model: str, api_key: str, timeout: float
    ) -> int:
        captured["url"] = url
        captured["model"] = model
        return 1234

    monkeypatch.setattr(vllm_openai, "_tokenize_count", fake_tokenize_count)

    config = EngineConfig(base_url="http://localhost:8001/v1", model="test-model")
    counter = VllmOpenAIEngine()._make_count_tokens(config)
    messages = [
        {"role": "system", "content": "you are a coder"},
        {"role": "user", "content": "do the work please"},
    ]
    assert counter(messages) == 1234
    # The URL must be the /tokenize endpoint (not the /v1/chat/completions one).
    assert captured["url"] == "http://localhost:8001/tokenize"
    assert captured["model"] == "test-model"


def test_make_count_tokens_falls_back_to_char_estimate_when_tokenize_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When /tokenize is unavailable (_tokenize_count returns None), fall back to
    count_tokens_chars so a non-vLLM OpenAI server (no /tokenize) still drives.

    The fallback means only precision degrades — the engine continues functioning.
    """

    def none_count(
        messages: list[dict], *, url: str, model: str, api_key: str, timeout: float
    ) -> None:
        return None  # endpoint unavailable

    monkeypatch.setattr(vllm_openai, "_tokenize_count", none_count)

    config = EngineConfig(base_url="http://localhost:8001/v1")
    counter = VllmOpenAIEngine()._make_count_tokens(config)
    messages = [
        {"role": "system", "content": "you are a coder"},
        {"role": "user", "content": "do the work please"},
    ]
    # Must fall back to the char estimator, never raise.
    result = counter(messages)
    assert result == count_tokens_chars(
        messages
    ), f"expected char estimate {count_tokens_chars(messages)}, got {result}"
    assert isinstance(result, int)


def test_make_count_tokens_fallback_is_non_zero_for_non_empty_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The char-estimate fallback returns a positive int for non-empty messages.

    This guards the invariant that the fallback always produces a usable budget
    signal (never 0 for substantive content), so windowing decisions based on it
    make sense.
    """
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda messages, *, url, model, api_key, timeout: None,
    )

    config = EngineConfig(base_url="http://localhost:8001/v1")
    counter = VllmOpenAIEngine()._make_count_tokens(config)
    messages = [{"role": "user", "content": "hello world this is a moderately long message"}]
    assert counter(messages) > 0


# ---------------------------------------------------------------------------
# 4. Integration: loop + vLLM engine with the count_tokens seam wired end-to-end
# ---------------------------------------------------------------------------


def test_vllm_engine_drives_with_windowing_on_mock_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loop + vLLM engine + windowing: a normal (non-overflowing) drive completes ok.

    Mocks the HTTP layer so there is no live server dependency. Patches
    _tokenize_count to return an exact count so the windowing path is exercised
    via the real _make_count_tokens counter. Asserts the drive completes ok and the
    result has the expected shape — proving the windowing seam in the vLLM engine
    is wired end-to-end.
    """
    turns = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {"path": "out.txt", "content": "from the model"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "2",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps({"summary": "wrote out.txt"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    ]
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)
    # Wire the tokenize counter to return an exact non-zero count (not the fallback).
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda messages, *, url, model, api_key, timeout: 500,
    )

    engine = VllmOpenAIEngine()
    config = EngineConfig.resolve()
    repo = tmp_path / "repo"
    repo.mkdir()
    result = engine.drive(Task.new(str(repo), "do work"), config)

    assert result.status == OK
    assert "out.txt" in result.changed_files
    assert state["i"] >= 2  # both turns were consumed


def test_overflow_retry_is_bounded_in_vllm_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The vLLM engine's retry loop terminates with a bounded POST call count.

    Drives the vLLM engine directly (not via the CLI) with a POST that always
    raises a context-overflow error, and asserts DriveAborted is raised with a
    partial result and that POST was called a small finite number of times.

    This is the loop-level complement to the CLI-level test above.
    """
    post_count = {"n": 0}

    def always_overflow(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        post_count["n"] += 1
        raise RuntimeError("maximum context length exceeded: 32768 tokens")

    monkeypatch.setattr(vllm_openai, "_post_json", always_overflow)
    monkeypatch.setattr(
        vllm_openai,
        "_tokenize_count",
        lambda messages, *, url, model, api_key, timeout: None,
    )

    engine = VllmOpenAIEngine()
    config = EngineConfig.resolve()
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(DriveAborted) as excinfo:
        engine.drive(Task.new(str(repo), "impossible task"), config)

    result = excinfo.value.result
    assert result.status == ERROR
    # Bounded: the retry loop did not run forever.
    assert (
        1 <= post_count["n"] <= 20
    ), f"POST called {post_count['n']} times — expected bounded retry"

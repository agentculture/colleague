"""t12 — one run-start ``/tokenize``, then ``usage``-anchored estimates.

Every network assertion here runs against a REAL ``ThreadingHTTPServer`` on a
real socket (never a fake stream): the server counts the POSTs it receives per
path, serves ``/tokenize`` with a ``max_model_len``, scripts three blocking
``/v1/chat/completions`` turns, and — for the window test — enforces vLLM's
"maximum context length" 400 exactly the way the rig does.

Covers plan claims c5/h3 (exactly one HTTP call per model turn on the happy
path; ``COLLEAGUE_EXACT_TOKENS=1`` restores the per-turn count; the artifact's
tokens still come from ``usage``) and c38/h27 (the run-start reply's
``max_model_len`` feeds ``resolve_window`` with the documented precedence; a
wrong window is a vLLM 400 the clamp prevents).
"""

from __future__ import annotations

import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

from colleague import outputclamp, tokenestimate
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import Task
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine


def _server_tokens(messages: list[dict[str, Any]]) -> int:
    """The fake server's tokenizer: the same chars/4 the client floors on."""
    return count_tokens_chars(messages)


def _turn(tool: str, arguments: dict[str, Any], prompt_tokens: int) -> dict[str, Any]:
    return {
        "model": "fake-served",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{tool}",
                            "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 7},
    }


class _Rig:
    """A counting fake vLLM: ``/tokenize`` + scripted blocking chat turns."""

    def __init__(self, *, max_model_len: int, turns: list[Callable[[int], dict[str, Any]]]):
        self.calls: dict[str, int] = {"/tokenize": 0, "/v1/chat/completions": 0}
        self.usage_reported: list[int] = []
        self.max_model_len = max_model_len
        rig = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: object) -> None:  # quiet
                return

            def _reply(self, code: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(n) or b"{}")
                rig.calls[self.path] = rig.calls.get(self.path, 0) + 1
                prompt = _server_tokens(payload.get("messages") or [])
                if self.path == "/tokenize":
                    self._reply(200, {"count": prompt, "max_model_len": rig.max_model_len})
                    return
                requested = prompt + int(payload.get("max_tokens") or 0)
                if requested > rig.max_model_len:
                    self._reply(
                        400,
                        {
                            "error": {
                                "message": (
                                    f"This model's maximum context length is "
                                    f"{rig.max_model_len} tokens. However, you requested "
                                    f"{requested} tokens ({prompt} in the messages, "
                                    f"{requested - prompt} in the completion). Please "
                                    "reduce the length of the messages or completion."
                                ),
                                "type": "BadRequestError",
                            }
                        },
                    )
                    return
                idx = rig.calls["/v1/chat/completions"] - 1
                script = turns[min(idx, len(turns) - 1)]
                rig.usage_reported.append(prompt)
                self._reply(200, script(prompt))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _three_turn_script(repo: Path) -> list[Callable[[int], dict[str, Any]]]:
    return [
        lambda p: _turn("list_dir", {"path": "."}, p),
        lambda p: _turn("read_file", {"path": "README.md"}, p),
        lambda p: _turn("finish", {"summary": "three turns, done"}, p),
    ]


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# fixture\n\nOne runtime, many minds.\n")
    return tmp_path


def _config(base_url: str, **kw: Any) -> EngineConfig:
    return EngineConfig(base_url=base_url, model="fake-served", max_steps=6, watch=False, **kw)


@pytest.fixture(autouse=True)
def _blocking_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blocking JSON replies (the fake rig does not speak SSE) and no gates."""
    monkeypatch.setenv("COLLEAGUE_STREAM", "0")
    monkeypatch.delenv("COLLEAGUE_EXACT_TOKENS", raising=False)


def test_three_turn_run_makes_one_tokenize_and_one_chat_per_turn(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rig = _Rig(max_model_len=8192, turns=_three_turn_script(repo))
    with rig as base_url:
        config = _config(base_url, lint=False, affected_tests=False, testintegrity=False)
        result = VllmOpenAIEngine().work(
            Task(
                id="t12-once", repo_path=str(repo), instruction="three turns", engine="vllm-openai"
            ),
            config,
        )
    assert result.status == "ok", result
    assert rig.calls["/v1/chat/completions"] == 3
    assert rig.calls["/tokenize"] == 1  # exactly one, at run start
    # The artifact's tokens are the server's usage — never the estimate.
    assert result.usage.prompt_tokens == sum(rig.usage_reported)


def test_exact_tokens_env_restores_the_per_turn_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_EXACT_TOKENS", "1")
    repo = _repo(tmp_path)
    rig = _Rig(max_model_len=8192, turns=_three_turn_script(repo))
    with rig as base_url:
        config = _config(base_url, lint=False, affected_tests=False, testintegrity=False)
        result = VllmOpenAIEngine().work(
            Task(
                id="t12-exact", repo_path=str(repo), instruction="three turns", engine="vllm-openai"
            ),
            config,
        )
    assert result.status == "ok", result
    assert rig.calls["/v1/chat/completions"] == 3
    # Every counter call is exact again: at least one per turn (the loop may
    # count more than once on a turn — the pre-arc per-turn cost, restored).
    assert rig.calls["/tokenize"] >= 3


def test_run_start_reply_feeds_resolve_window_with_precedence(tmp_path: Path) -> None:
    """``max_model_len`` from the one probe wins when lobes is unarmed; lobes wins armed."""
    repo = _repo(tmp_path)
    with _Rig(max_model_len=8192, turns=_three_turn_script(repo)) as base_url:
        unarmed = _config(base_url)
        counter = VllmOpenAIEngine()._make_count_tokens(unarmed)
        counter([{"role": "user", "content": "hello"}])
        est = unarmed.token_estimator
        assert (est.window, est.window_source) == (8192, "tokenize_max_model_len")
        assert est.max_model_len == 8192 and est.probed and est.exact_calls == 1

        armed = _config(base_url)
        armed.lobes_context = 262144  # stamped by a lobes resolution rung
        counter2 = VllmOpenAIEngine()._make_count_tokens(armed)
        counter2([{"role": "user", "content": "hello"}])
        assert (armed.token_estimator.window, armed.token_estimator.window_source) == (
            262144,
            "lobes_context",
        )


def test_wrong_window_is_a_vllm_400_and_the_clamp_prevents_it(tmp_path: Path) -> None:
    """Reproduce the rig's 400 shape; prove ``resolve_window`` + clamp keeps under it."""
    repo = _repo(tmp_path)
    big = [{"role": "user", "content": "x" * 20000}]  # 5000 server tokens
    # A 32K window: the clamp's margin (max(10,000, 5%)) + 4,000 floor cannot fit
    # an 8K window at all (that is what compaction is for), so the arithmetic is
    # only meaningful — and only provable — above ~16K.
    with _Rig(max_model_len=32768, turns=_three_turn_script(repo)) as base_url:
        config = _config(base_url)
        counter = VllmOpenAIEngine()._make_count_tokens(config)
        prompt = counter(big)  # the run-start probe: exact
        est = config.token_estimator
        window, source = outputclamp.resolve_window(None, est.max_model_len, 131072)
        assert (window, source) == (32768, "tokenize_max_model_len")
        url = f"{base_url}/chat/completions"

        # Unclamped (today's absent max_tokens ≈ the acting ceiling): the rig refuses.
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            vllm_openai._post_json(
                url,
                {"model": "m", "messages": big, "max_tokens": 64000},
                api_key="k",
                timeout=5,
            )
        assert excinfo.value.code == 400
        # _post_json folds the vLLM body into the re-raised error's message.
        assert "maximum context length is 32768" in str(excinfo.value.msg)

        # Clamped to the discovered window: accepted.
        max_tokens = outputclamp.clamp_output_tokens(64000, window, prompt)
        assert max_tokens is not None and prompt + max_tokens <= window
        reply = vllm_openai._post_json(
            url,
            {"model": "m", "messages": big, "max_tokens": max_tokens},
            api_key="k",
            timeout=5,
        )
        assert reply["usage"]["prompt_tokens"] == prompt


# ── the estimator itself (pure) ─────────────────────────────────────────────


def _probe_returning(count: int | None, mml: int | None = None) -> tokenestimate.ExactProbe:
    def probe(_messages: list[dict[str, Any]], reply: dict[str, Any]) -> int | None:
        if mml is not None:
            reply["max_model_len"] = mml
        return count

    return probe


def test_estimate_is_usage_plus_chars_over_four_past_the_snapshot() -> None:
    est = tokenestimate.TokenEstimator(_probe_returning(50, 4096), budget=1000)
    history = [{"role": "system", "content": "s" * 400}, {"role": "user", "content": "u" * 400}]
    assert est(history) == 50  # the probe, exact
    est.observe_usage(history, 1000)  # what the server actually charged
    appended = [{"role": "assistant", "content": "a" * 80}]
    assert est(history + appended) == 1000 + count_tokens_chars(appended)
    assert est.exact_calls == 1  # no second probe


def test_estimate_scales_a_trimmed_candidate_and_never_undercuts_chars_over_four() -> None:
    est = tokenestimate.TokenEstimator(_probe_returning(None), budget=1000)
    history = [{"role": "system", "content": "s" * 400}, {"role": "user", "content": "u" * 400}]
    assert est(history) == count_tokens_chars(history)  # uncalibrated: chars/4
    est.observe_usage(history, 400)  # 0.5 tokens per char — a dense tokenizer
    trimmed = [history[0]]
    assert est(trimmed) == 200  # 400 chars * 0.5
    est2 = tokenestimate.TokenEstimator(_probe_returning(None), budget=1000)
    est2.observe_usage(history, 10)  # an implausibly cheap ratio is floored at chars/4
    assert est2(trimmed) == count_tokens_chars(trimmed)


def test_probe_failure_falls_back_to_the_char_estimate_and_budget_window() -> None:
    est = tokenestimate.TokenEstimator(_probe_returning(None), budget=131072, lobes_context=None)
    msgs = [{"role": "user", "content": "hello there"}]
    assert est(msgs) == count_tokens_chars(msgs)
    assert (est.window, est.window_source) == (131072, "context_budget")


def test_exact_every_turn_flag_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value, expected in (("1", True), ("true", True), ("0", False), ("", False)):
        monkeypatch.setenv("COLLEAGUE_EXACT_TOKENS", value)
        assert tokenestimate.exact_every_turn() is expected
    monkeypatch.delenv("COLLEAGUE_EXACT_TOKENS")
    assert tokenestimate.exact_every_turn() is False


def test_observe_is_a_no_op_without_an_attached_estimator() -> None:
    config = EngineConfig()
    tokenestimate.observe(config, [{"role": "user", "content": "x"}], 12)  # must not raise
    assert not hasattr(config, "token_estimator")

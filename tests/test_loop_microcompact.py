"""t16 — the loop + adapter wiring: clamp on the wire, escalate-on-length, the
microcompaction floor ahead of the fill-line offer, and the always-on loop guards.

The wire assertions run against a REAL ``ThreadingHTTPServer`` (the t12 rig
idiom, blocking JSON replies) that records every ``/v1/chat/completions``
payload; the loop assertions drive :func:`colleague.loop.run` with a scripted
``complete`` exactly the way ``tests/test_fillline.py`` does.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

from colleague import outputclamp
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import INCOMPLETE, OK, Task
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

# --- the wire ----------------------------------------------------------------------


def _reply(finish_reason: str, prompt: int, tool: str | None, arguments: dict | None) -> dict:
    message: dict[str, Any] = {"content": "" if tool else "done"}
    if tool:
        message["tool_calls"] = [
            {
                "id": f"call-{tool}",
                "type": "function",
                "function": {"name": tool, "arguments": json.dumps(arguments or {})},
            }
        ]
    return {
        "model": "fake-served",
        "choices": [{"finish_reason": finish_reason, "message": message}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": 3},
    }


class _Rig:
    """A counting fake vLLM that also RECORDS every chat payload it receives."""

    def __init__(self, *, max_model_len: int, turns: list[Callable[[int], dict]]):
        self.calls = {"/tokenize": 0, "/v1/chat/completions": 0}
        self.payloads: list[dict] = []
        rig = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: object) -> None:
                return

            def _send(self, code: int, body: dict) -> None:
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
                prompt = count_tokens_chars(payload.get("messages") or [])
                if self.path == "/tokenize":
                    self._send(200, {"count": prompt, "max_model_len": max_model_len})
                    return
                rig.payloads.append(payload)
                idx = rig.calls["/v1/chat/completions"] - 1
                self._send(200, turns[min(idx, len(turns) - 1)](prompt))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(autouse=True)
def _blocking_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STREAM", "0")


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# fixture\n")
    return tmp_path


def _config(base_url: str) -> EngineConfig:
    return EngineConfig(
        base_url=base_url,
        model="fake-served",
        max_steps=6,
        watch=False,
        lint=False,
        affected_tests=False,
        testintegrity=False,
    )


def _work(base_url: str, repo: Path, task_id: str):
    return VllmOpenAIEngine().work(
        Task(id=task_id, repo_path=str(repo), instruction="t16", engine="vllm-openai"),
        _config(base_url),
    )


def _two_turn_script() -> list[Callable[[int], dict]]:
    return [
        lambda p: _reply("tool_calls", p, "list_dir", {"path": "."}),
        lambda p: _reply("tool_calls", p, "finish", {"summary": "done"}),
    ]


def test_every_main_loop_payload_carries_the_seat_clamped_max_tokens(tmp_path: Path) -> None:
    rig = _Rig(max_model_len=262_144, turns=_two_turn_script())
    with rig as base_url:
        result = _work(base_url, _repo(tmp_path), "t16-clamp")
    assert result.status == OK, result
    assert rig.calls["/v1/chat/completions"] == 2
    assert rig.payloads
    for payload in rig.payloads:
        prompt = count_tokens_chars(payload["messages"])
        assert payload["max_tokens"] == outputclamp.clamp_output_tokens(64_000, 262_144, prompt)
        assert prompt + payload["max_tokens"] <= 262_144  # the invariant vLLM would 400 on


def test_kill_switch_omits_max_tokens_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "0")
    rig = _Rig(max_model_len=262_144, turns=_two_turn_script())
    with rig as base_url:
        result = _work(base_url, _repo(tmp_path), "t16-off")
    assert result.status == OK, result
    assert all("max_tokens" not in payload for payload in rig.payloads)


def test_a_length_cut_retries_once_with_a_larger_budget_then_falls_to_truncation(
    tmp_path: Path,
) -> None:
    # Turn 1 is cut (empty, no tool call, finish_reason=length); the retry lands.
    script = [
        lambda p: _reply("length", p, None, None)
        | {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
        lambda p: _reply("tool_calls", p, "finish", {"summary": "done after escalation"}),
    ]
    # A 70k window: the clamp (window - prompt - 10k margin) sits BELOW the 64k
    # ceiling, so the one escalation has room to grow toward it.
    rig = _Rig(max_model_len=70_000, turns=script)
    with rig as base_url:
        result = _work(base_url, _repo(tmp_path), "t16-length")
    assert result.status == OK, result
    assert rig.calls["/v1/chat/completions"] == 2  # ONE escalated retry, no third call
    first, second = rig.payloads
    assert second["messages"] == first["messages"]  # same turn, resent
    assert first["max_tokens"] < 64_000 < 70_000
    assert second["max_tokens"] > first["max_tokens"]
    assert second["max_tokens"] <= 64_000
    prompt = count_tokens_chars(first["messages"])
    assert second["max_tokens"] == min(64_000, 70_000 - prompt)
    assert (
        result.stats.model_turns == 1
    )  # the cut turn's tokens are folded into the retry's usage path


def test_a_length_cut_at_the_ceiling_is_not_retried_and_is_recorded_truncated(
    tmp_path: Path,
) -> None:
    # A window so small the clamp already sits at the window edge: no room to escalate
    # -> no second request; the loop's existing truncated-turn handling records it.
    cut = lambda p: {  # noqa: E731
        "model": "fake-served",
        "choices": [{"finish_reason": "length", "message": {"content": ""}}],
        "usage": {"prompt_tokens": p, "completion_tokens": 1},
    }
    rig = _Rig(max_model_len=5_000, turns=[cut, cut, cut, cut])
    with rig as base_url:
        result = _work(base_url, _repo(tmp_path), "t16-noroom")
    assert result.status != OK
    assert any(w.get("kind") == "truncated-turn" for w in result.warnings)


# --- the loop ------------------------------------------------------------------------


def _task(tmp_path: Path) -> Task:
    return Task.new(str(tmp_path), "do a long thing", engine="mock")


def _run(complete, task, **kwargs):
    cc = ContextControls(
        budget=kwargs.pop("budget", 100),
        count_tokens=kwargs.pop("count_tokens", None),
        autosplit_target=kwargs.pop("autosplit_target", 100),
        fillline_threshold=kwargs.pop("fillline_threshold", 0.8),
    )
    kwargs.setdefault("system_prompt", "sys")
    kwargs.setdefault("max_steps", 40)
    return run(complete, task, context=cc, **kwargs)


def _offered(calls: list[list[dict]]) -> bool:
    return any("declare ONE move" in (m.get("content") or "") for c in calls for m in c)


def _tool_turns(n: int, prompt_at_end: int) -> Callable[[list[dict]], ModelResponse]:
    """A model that makes *n* alternating list_dir calls, reporting a small prompt until
    the last of them (which reports *prompt_at_end*), then finishes."""
    state = {"n": 0, "seen": []}

    def complete(messages: list[dict]) -> ModelResponse:
        state["seen"].append(list(messages))
        last = messages[-1].get("content") or ""
        if "declare ONE move" in last:
            return ModelResponse(
                content="finish-with-handoff", prompt_tokens=5, completion_tokens=1
            )
        if state["n"] >= n:
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
                prompt_tokens=5,
                completion_tokens=1,
            )
        state["n"] += 1
        prompt = prompt_at_end if state["n"] == n else 10
        path = "." if state["n"] % 2 else "./"
        return ModelResponse(
            content="",
            tool_calls=[ToolCall(str(state["n"]), "list_dir", {"path": path})],
            prompt_tokens=prompt,
            completion_tokens=1,
        )

    complete.state = state  # type: ignore[attr-defined]
    return complete


def test_microcompaction_blanks_old_results_at_the_line_before_the_fillline_offer(
    tmp_path: Path,
) -> None:
    complete = _tool_turns(12, prompt_at_end=90)  # 12 tool results, last prompt 90/100
    result = _run(complete, _task(tmp_path), count_tokens=lambda m: 50)
    assert result.status == OK, result
    passes = [w for w in result.warnings if w.get("kind") == "microcompaction"]
    assert len(passes) == 1
    assert passes[0]["blanked"] == 2
    assert passes[0]["step_indices"] == [0, 1]
    assert passes[0]["blanked_total"] == 2
    # The finish turn saw the blanked history: the two oldest tool results are markers.
    final = complete.state["seen"][-1]
    tool_msgs = [m for m in final if m.get("role") == "tool"]
    assert "cleared" in tool_msgs[0]["content"]
    assert "cleared" in tool_msgs[1]["content"]
    assert all("cleared" not in m["content"] for m in tool_msgs[2:])
    # After blanking the (re-estimated) history is under the line -> NO fill-line offer.
    assert not _offered(complete.state["seen"])


def test_fillline_still_offers_when_the_history_stays_over_the_line_after_blanking(
    tmp_path: Path,
) -> None:
    complete = _tool_turns(12, prompt_at_end=90)
    result = _run(complete, _task(tmp_path), count_tokens=lambda m: 95)
    assert any(w.get("kind") == "microcompaction" for w in result.warnings)
    assert _offered(complete.state["seen"])


def test_microcompact_knob_restores_todays_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_MICROCOMPACT", "0")
    complete = _tool_turns(12, prompt_at_end=90)
    _run(complete, _task(tmp_path), count_tokens=lambda m: 50)
    assert complete.state["seen"]
    assert not any("cleared" in (m.get("content") or "") for c in complete.state["seen"] for m in c)
    assert _offered(complete.state["seen"])  # today's path: the 90-token prompt crosses 0.8


def test_identical_call_loop_guard_halts_the_run_and_drops_the_pending_call(
    tmp_path: Path,
) -> None:
    def complete(messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            content="",
            tool_calls=[ToolCall("x", "list_dir", {"path": "."})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == INCOMPLETE
    assert len(result.steps) == 4  # four executed; the fifth identical call was dropped
    trips = [w for w in result.warnings if w.get("kind") == "loop-guard"]
    assert trips == [
        {
            "kind": "loop-guard",
            "guard": "identical-calls",
            "tool": "list_dir",
            "repeats": 5,
            "limit": 5,
            "dropped": 1,
        }
    ]
    assert result.summary.startswith("Stopped after 4 step(s): loop guard tripped")
    assert result.stopped_without_finish is True


def test_calls_per_turn_guard_drops_the_whole_turn(tmp_path: Path) -> None:
    def complete(messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            content="",
            tool_calls=[ToolCall(str(i), "read_file", {"path": f"f{i}"}) for i in range(101)],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == INCOMPLETE
    assert result.steps == []
    trip = next(w for w in result.warnings if w.get("kind") == "loop-guard")
    assert trip["guard"] == "calls-per-turn"
    assert trip["dropped"] == 101


def test_varied_calls_never_trip(tmp_path: Path) -> None:
    complete = _tool_turns(8, prompt_at_end=10)
    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert not any(w.get("kind") == "loop-guard" for w in result.warnings)

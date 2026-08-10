"""Shared vLLM HTTP test doubles — the SSE re-framing of a blocking turn (#393).

Headless SSE streaming is armed by DEFAULT from #393 on
(``colleague.engines.vllm_openai._headless_streaming_enabled``), so a suite
that stubs only the blocking transport (``vllm_openai._post_json``) no longer
intercepts anything on its own: the driver reaches for
``urllib.request.urlopen`` and the SSE reader instead.

Most of those suites pin *transport-independent* behavior — the loop, the
offered tool schema, policy parity, degradation, the artifact shape — not the
wire framing, so ``tests/conftest.py``'s ``_sse_bridge_over_blocking_stubs``
autouse fixture keeps them on the DEFAULT streaming path by answering a
streamed turn from their own blocking stub. This module holds the two pieces
that bridge does it with; a suite that genuinely pins the BLOCKING transport
sets ``COLLEAGUE_STREAM=0`` instead.

Nothing here opens a socket.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["FakeStreamResponse", "sse_lines_for_turn"]


class FakeStreamResponse:
    """Minimal ``http.client.HTTPResponse`` stand-in for the SSE read loop.

    Supports exactly the shape ``_post_json_stream`` relies on:
    ``with urlopen(...) as response: for line in response:``.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "FakeStreamResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


def _delta_frames(message: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``choices[].delta`` frames that reconstruct *message*."""
    frames: list[dict[str, Any]] = []
    for key in ("reasoning", "reasoning_content"):
        chunk = message.get(key)
        if isinstance(chunk, str) and chunk:
            frames.append({"choices": [{"delta": {key: chunk}}]})
    content = message.get("content")
    if isinstance(content, str) and content:
        frames.append({"choices": [{"delta": {"content": content}}]})
    for index, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function") or {}
        frames.append(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "id": call.get("id", ""),
                                    "function": {
                                        "name": function.get("name", ""),
                                        "arguments": function.get("arguments", ""),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )
    return frames


def sse_lines_for_turn(turn: dict[str, Any]) -> list[bytes]:
    """Re-express ONE blocking chat-completions turn as SSE wire lines.

    Content and reasoning ride as single deltas (the driver concatenates
    chunks, so one chunk reconstructs the same string); each tool call rides as
    one fragment carrying its whole ``arguments`` string. The terminal
    ``finish_reason`` frame and the ``include_usage`` usage frame mirror what
    vLLM/OpenAI actually send, so the assembled ``ModelResponse`` matches the
    blocking parse field for field.

    A non-string ``content`` (the OpenAI *parts* shape) has no streaming
    equivalent — a server streams plain text deltas — so it is simply omitted
    here; the suite that pins the parts parser is a blocking-transport suite
    and opts out with ``COLLEAGUE_STREAM=0``.
    """
    choice = (turn.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    frames = _delta_frames(message)
    finish_reason = choice.get("finish_reason")
    if finish_reason:
        # Only when the scripted turn actually carries one: a turn that leaves
        # it unset must keep degrading to the driver's honest "" default on the
        # streamed path too (``data: [DONE]`` alone is a valid terminator), or
        # this bridge would invent a wire value the script never sent.
        frames.append({"choices": [{"delta": {}, "finish_reason": finish_reason}]})
    usage = turn.get("usage")
    if usage:
        frames.append({"choices": [], "usage": usage})
    lines = [f"data: {json.dumps(frame)}\n".encode("utf-8") for frame in frames]
    lines.append(b"data: [DONE]\n")
    return lines

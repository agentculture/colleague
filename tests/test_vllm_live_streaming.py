"""Opt-in live proof: token-streaming feels alive on the real rig (feels-alive t9).

Skipped unless ``COLLEAGUE_VLLM_E2E=1`` so CI and offline runs never touch the
network. Two proofs:

- an ARMED delta sink sees the first visible model output within seconds of the
  completion starting (graded by :func:`colleague.livecheck.classify_streaming_check`
  against the 2026-07-10 baseline: a 13.62s turn, 4.43s longest silent gap);
- an unreachable server yields a DISTINCT no-stream state — a legible connection
  error with zero deltas, never an indistinguishable silence (spec h13).

Config note: the endpoint is resolved at MODULE IMPORT (collection) time —
before the autouse conftest fixture scrubs ``COLLEAGUE_*`` env and redirects
``COLLEAGUE_HOME`` — so the operator's real user-level lobes/config rung is
what gets probed, mirroring how an operator actually runs colleague.
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from colleague.config import EngineConfig
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.livecheck import classify_streaming_check

pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
# Resolved at collection time, before the conftest env scrub (module docstring).
_LIVE_CONFIG = EngineConfig.resolve(repo_path=_REPO_ROOT)

_PROMPT = (
    "Write a short paragraph (4-6 sentences) about what makes a reliable "
    "teammate on a software team."
)


def test_live_streamed_completion_first_delta_beats_full_turn() -> None:
    deltas: list[str] = []
    stamps: list[float] = []
    t0 = time.monotonic()

    def sink(text: str) -> None:
        stamps.append(time.monotonic() - t0)
        deltas.append(text)

    config = replace(_LIVE_CONFIG)
    config.on_delta = sink
    complete = VllmOpenAIEngine().make_complete(config, tools=[])

    t0 = time.monotonic()
    response = complete([{"role": "user", "content": _PROMPT}])
    total = time.monotonic() - t0

    status, detail = classify_streaming_check(stamps[0] if stamps else None, total, len(deltas))
    print(f"\nstreaming live proof: {status} — {detail}")
    assert status in ("passed", "skipped"), detail
    if status == "skipped":
        pytest.skip(detail)
    # The assembled response is still a normal completion (transport-invisible).
    assert (response.content or "") or (response.reasoning or "")


def test_live_dead_server_yields_a_distinct_no_stream_state() -> None:
    deltas: list[str] = []

    config = replace(_LIVE_CONFIG)
    config.base_url = "http://localhost:59999/v1"  # nothing listens here
    config.timeout = 5
    config.on_delta = deltas.append
    complete = VllmOpenAIEngine().make_complete(config, tools=[])

    t0 = time.monotonic()
    # The dead-server path goes through ``_raise_legible_connection_error``
    # (immediate connection-refused — the common case for "nothing listens
    # on this port") or, on an environment where the connection attempt
    # hangs instead of refusing outright, ``_raise_legible_timeout`` — the
    # union of what those two legible-error wrappers genuinely raise.
    with pytest.raises((ConnectionError, TimeoutError)) as excinfo:
        complete([{"role": "user", "content": "hello"}])
    elapsed = time.monotonic() - t0

    # DISTINCT no-stream state: zero deltas plus a legible, prompt error —
    # nothing like the silent-yet-working stream of a live turn (h13).
    assert deltas == []
    message = str(excinfo.value).lower()
    assert "connect" in message or "unreachable" in message or "refused" in message
    print(f"\ndead-server proof: legible error in {elapsed:.2f}s with 0 deltas — {message[:100]}")

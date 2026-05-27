"""Opt-in live end-to-end proof against a real vLLM server (honesty condition h8).

Skipped unless ``CONVERTIBLE_VLLM_E2E=1`` so CI and offline runs never touch the
network. When enabled it drives a real task through the live model and asserts a
real file edit — the demonstration that the whole chassis works against an
OpenAI-compatible server.

Run it (with the reference rig up) like::

    CONVERTIBLE_VLLM_E2E=1 \\
    CONVERTIBLE_BASE_URL=http://localhost:8001/v1 \\
    CONVERTIBLE_MODEL=Qwen/Qwen3-32B \\
    uv run pytest tests/test_vllm_live.py -v

The server must expose tool calling (vLLM: ``--enable-auto-tool-choice`` plus a
``--tool-call-parser`` for the model, e.g. ``hermes`` or ``qwen3_coder``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from convertible.config import EngineConfig
from convertible.contract import OK, Task
from convertible.engines.vllm_openai import VllmOpenAIEngine

pytestmark = pytest.mark.skipif(
    os.environ.get("CONVERTIBLE_VLLM_E2E") != "1",
    reason="set CONVERTIBLE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)


def test_live_drive_edits_a_real_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n\nA project.\n")

    task = Task.new(
        str(repo),
        "Create a file named HELLO.txt containing exactly the text: hello from convertible",
        engine="vllm-openai",
    )
    result = VllmOpenAIEngine().drive(task, EngineConfig.resolve())

    assert result.status == OK, result.error
    assert result.changed_files, "the model made no edits"
    assert (repo / "HELLO.txt").exists()

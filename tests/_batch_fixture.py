"""Shared batch-turn fixture — mock and vllm-openai compared against ONE script.

The mock engine is the contract reference (h8): ``colleague/engines/
mock_scenarios.py``'s constants (``BATCH_READ_PATHS`` / ``BATCH_WRITE_PATH`` /
``BATCH_WRITE_CONTENT``) are the single source of truth for what "the batch
turn" is. This module builds, from those SAME constants, the matching repo
fixture and the fake vllm-openai chat-completions replies — so a test proving
mock and vllm-openai agree is provably comparing the identical calls on both
engines, not two independently-typed lookalikes (spec c39/h28, docs/specs/
2026-08-27-adopt-from-qwen-code.md, plan task t17).

Used by ``tests/test_e2e_mock.py`` and ``tests/test_all_engines_batch.py``.
Not itself a test module (no ``test_`` prefix — pytest never collects it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from colleague.engines.mock_scenarios import (
    BATCH_READ_PATHS,
    BATCH_TASK_MARKER,
    BATCH_WRITE_CONTENT,
    BATCH_WRITE_PATH,
)

#: A task instruction that opts the mock engine into the batch scenario.
BATCH_TASK_INSTRUCTION = f"{BATCH_TASK_MARKER} read three files, then write one"

#: (tool, ok) for the five steps the batch turn + finish turn produce, in
#: request order — every call succeeds against :func:`make_batch_repo`.
EXPECTED_STEP_SHAPE: "tuple[tuple[str, bool], ...]" = (
    ("read_file", True),
    ("read_file", True),
    ("read_file", True),
    ("write_file", True),
    ("finish", True),
)


def make_batch_repo(root: Path) -> Path:
    """A repo with the three files the batch turn's read calls target."""
    root.mkdir(parents=True, exist_ok=True)
    for name in BATCH_READ_PATHS:
        (root / name).write_text(f"{name} body\n")
    return root


def step_shape(result: Any) -> "list[tuple[str, bool]]":
    """(tool, ok) for every recorded step, in request order."""
    return [(s.tool, s.ok) for s in result.steps]


def _batch_turn_reply() -> dict[str, Any]:
    """The fake vllm-openai chat-completions JSON reply for the batch turn.

    Carries the SAME four tool calls, in the SAME order, as
    ``mock_scenarios.batch_turns``'s first turn — built from the identical
    shared constants, so the two engines run call-for-call identical
    ``(name, arguments)`` pairs, not merely same-shaped ones.
    """
    tool_calls = [
        {
            "id": f"vllm-batch-read-{i}",
            "function": {"name": "read_file", "arguments": json.dumps({"path": path})},
        }
        for i, path in enumerate(BATCH_READ_PATHS, start=1)
    ]
    tool_calls.append(
        {
            "id": "vllm-batch-write",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": BATCH_WRITE_PATH, "content": BATCH_WRITE_CONTENT}),
            },
        }
    )
    return {
        "choices": [{"message": {"content": "", "tool_calls": tool_calls}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 4},
    }


def _finish_turn_reply() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "vllm-batch-finish",
                            "function": {
                                "name": "finish",
                                "arguments": json.dumps({"summary": "vllm batch done"}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1},
    }


def vllm_batch_turns() -> "list[dict[str, Any]]":
    """The two scripted vllm-openai chat-completions replies: batch, then finish."""
    return [_batch_turn_reply(), _finish_turn_reply()]

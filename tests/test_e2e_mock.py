"""End-to-end: one contract, swappable engines (c1, c7, h8, h11, h12, h14).

Proves the headline claim without a network: the *same* task driven through two
different engines (the real mock engine and the vLLM driver over mocked HTTP)
yields results of the *identical shape*, and the engine is selected purely by
name through the registry — the only thing that changes is `--engine`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from convertible import registry
from convertible.cli import main
from convertible.config import EngineConfig
from convertible.contract import OK, Task
from convertible.engines import vllm_openai
from convertible.tools import SCHEMAS

# The base tool surface every engine inherits, plus the curated culture tool (t3).
_BASE_TOOLS = {"read_file", "write_file", "list_dir", "run_command", "finish"}
_CULTURE_TOOLS = {"culture"}


def _key_shape(value: Any) -> Any:
    """Recursive key signature, ignoring concrete values — for shape comparison."""
    if isinstance(value, dict):
        return {k: _key_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return _key_shape(value[0]) if value else None
    return None


def _mock_vllm_http(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_same_task_yields_identical_result_shape_across_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_vllm_http(monkeypatch)
    cfg = EngineConfig.resolve()

    mock_repo = tmp_path / "mock"
    vllm_repo = tmp_path / "vllm"
    mock_repo.mkdir()
    vllm_repo.mkdir()

    # Engines are chosen by name, through the registry — only the name differs.
    mock_result = registry.load("mock").drive(Task.new(str(mock_repo), "do work"), cfg)
    vllm_result = registry.load("vllm-openai").drive(Task.new(str(vllm_repo), "do work"), cfg)

    assert mock_result.status == OK
    assert vllm_result.status == OK
    # Identical shape: same keys top-level and in every nested structure (h11/h14).
    assert _key_shape(mock_result.to_dict()) == _key_shape(vllm_result.to_dict())
    # Both actually edited their repo.
    assert mock_result.changed_files and vllm_result.changed_files


def test_engine_swap_needs_no_task_change(tmp_path: Path) -> None:
    """The Task is engine-agnostic: only the `engine` field selects the driver (h12)."""
    a = Task.new(str(tmp_path), "identical instruction", engine="mock")
    b = Task.new(str(tmp_path), "identical instruction", engine="vllm-openai")
    a_fields = a.to_dict()
    b_fields = b.to_dict()
    a_fields.pop("engine")
    a_fields.pop("id")
    b_fields.pop("engine")
    b_fields.pop("id")
    assert a_fields == b_fields  # everything but the engine name is the same


def test_every_engine_exposes_the_culture_tools_identically() -> None:
    """All-engines rule (t3): the curated culture tool lives on the *shared* tool
    surface, beyond the five base tools, so every engine exposes it identically.

    The surface is a single shared ``SCHEMAS`` list: the vLLM engine hands it to
    the model verbatim, and the loop's ``ToolExecutor`` dispatches the same tool
    names for the mock engine. There is no per-engine tool surface — so asserting
    on ``SCHEMAS`` is the honest all-engines guard.
    """
    exposed = {s["function"]["name"] for s in SCHEMAS}
    # Base five remain, the culture tool is added, and nothing else creeps in.
    assert _BASE_TOOLS <= exposed, "the five base tools must remain exposed"
    assert _CULTURE_TOOLS <= exposed, "every engine must expose the culture tool"
    assert exposed == _BASE_TOOLS | _CULTURE_TOOLS, "the tool surface is base-five + culture"

    # The vLLM engine literally hands this shared surface to the model.
    assert vllm_openai.SCHEMAS is SCHEMAS


def test_drive_cli_then_wheels_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["drive", "go", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == OK

    assert main(["wheels", "list", "--json"]) == 0
    names = {e["name"] for e in json.loads(capsys.readouterr().out)["engines"]}
    assert {"mock", "vllm-openai"} <= names

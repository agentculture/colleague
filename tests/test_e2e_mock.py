"""End-to-end: one contract, swappable engines (c1, c7, h8, h11, h12, h14).

Proves the headline claim without a network: the *same* task driven through two
different engines (the real mock engine and the vLLM driver over mocked HTTP)
yields results of the *identical shape*, and the engine is selected purely by
name through the registry — the only thing that changes is `--engine`.

Also guards the policy no-op contract (t7): with no approvals.json present the
artifact shape is byte-identical to a policy-free run — the gate is a strict
default-off feature.
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
    """All-engines rule (t3/t2): the curated culture and devague tools live on the
    *shared* tool surface, beyond the five base tools, so every engine exposes them
    identically.

    The surface is a single shared ``SCHEMAS`` list: the vLLM engine hands it to
    the model verbatim, and the loop's ``ToolExecutor`` dispatches the same tool
    names for the mock engine. There is no per-engine tool surface — so asserting
    on ``SCHEMAS`` is the honest all-engines guard.
    """
    exposed = {s["function"]["name"] for s in SCHEMAS}
    _CHASSIS_TOOLS = {"culture", "devague", "subagent"}
    # Base five remain, the chassis tools are added, and nothing else creeps in.
    assert _BASE_TOOLS <= exposed, "the five base tools must remain exposed"
    assert _CULTURE_TOOLS <= exposed, "every engine must expose the culture tool"
    assert _CHASSIS_TOOLS <= exposed, "every engine must expose all chassis tools"
    assert exposed == _BASE_TOOLS | _CHASSIS_TOOLS, "the tool surface is base-five + chassis"

    # The vLLM engine literally hands this shared surface to the model.
    assert vllm_openai.SCHEMAS is SCHEMAS


def test_no_destination_drive_omits_destination_keys_byte_identical(tmp_path: Path) -> None:
    """A normal mock drive that sets NO destination serializes byte-identically to
    the pre-feature shape (c8/h8): ``to_dict()`` must NOT contain ``destination``
    or ``announcement`` keys.

    The mock engine is the contract reference (the all-engines rule). Its scripted
    finish carries no destination/announcement, so the serialized result must be
    indistinguishable from the result a pre-feature convertible produced — the
    destination concept is additive and default-off, never a null-padded key.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve()

    result = registry.load("mock").drive(Task.new(str(repo), "do work"), cfg)

    assert result.status == OK
    # The drive really ran (it edited the repo), so this is a live, not-empty result.
    assert result.changed_files
    # The destination concept stayed off — the fields are None on the object …
    assert result.destination is None
    assert result.announcement is None
    # … and the serialized shape OMITS both keys entirely (not present-as-null).
    serialized = result.to_dict()
    assert "destination" not in serialized
    assert "announcement" not in serialized

    # Byte-identical guard: the exact key set is the pre-feature key set. Pin it
    # explicitly so any future field addition that leaks into the no-destination
    # path is caught here.
    assert set(serialized.keys()) == {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
    }


def test_no_subagent_drive_omits_sub_results_key_byte_identical(tmp_path: Path) -> None:
    """A normal mock drive that delegates NO subagent serializes byte-identically
    to the pre-feature shape: ``to_dict()`` must NOT contain a ``"sub_results"`` key.

    This mirrors the destination/announcement omit-when-None treatment:
    ``sub_results`` is emitted ONLY when the list is non-empty, so a drive that
    never called the subagent tool is indistinguishable from today's artifact shape.
    The mock engine is the contract reference (the all-engines rule).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve()

    result = registry.load("mock").drive(Task.new(str(repo), "do work"), cfg)

    assert result.status == OK
    # The drive really ran and the sub_results list is empty.
    assert result.changed_files
    assert result.sub_results == []
    # The serialized shape OMITS the key entirely (not present-as-empty-list).
    serialized = result.to_dict()
    assert "sub_results" not in serialized

    # Byte-identical guard: the pinned key set must NOT include sub_results.
    expected_keys = {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
    }
    assert set(serialized.keys()) == expected_keys


def test_drive_cli_then_wheels_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["drive", "go", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == OK

    assert main(["wheels", "list", "--json"]) == 0
    names = {e["name"] for e in json.loads(capsys.readouterr().out)["engines"]}
    assert {"mock", "vllm-openai"} <= names


def test_no_policy_file_artifact_is_byte_identical_to_policy_free_run(
    tmp_path: Path,
) -> None:
    """Policy no-op shape guard (t7 AC1): with NO .convertible/approvals.json present,
    the TaskResult to_dict() key set and step shape are byte-identical to a run in a
    repo that has never had any policy concept applied.

    This proves the gate is a strict default-off feature — its presence in the chassis
    adds zero visible artefact when no policy file exists.
    """
    # Repo A: has a .convertible/ dir but no approvals.json.
    repo_a = tmp_path / "with_dotdir"
    repo_a.mkdir()
    (repo_a / ".convertible").mkdir()
    # Deliberately leave approvals.json absent.

    # Repo B: completely vanilla — no .convertible/ at all.
    repo_b = tmp_path / "vanilla"
    repo_b.mkdir()

    cfg = EngineConfig.resolve()
    result_a = registry.load("mock").drive(Task.new(str(repo_a), "do work"), cfg)
    result_b = registry.load("mock").drive(Task.new(str(repo_b), "do work"), cfg)

    # Both must succeed.
    assert result_a.status == OK
    assert result_b.status == OK

    dict_a = result_a.to_dict()
    dict_b = result_b.to_dict()

    # Key sets are identical — the gate added no new keys.
    assert set(dict_a.keys()) == set(
        dict_b.keys()
    ), f"Key sets differ: {set(dict_a.keys()) ^ set(dict_b.keys())}"

    # The pinned pre-feature key set is unchanged (mirrors the destination no-op guard).
    expected_keys = {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
    }
    assert (
        set(dict_a.keys()) == expected_keys
    ), f"Unexpected extra keys in policy-free run: {set(dict_a.keys()) - expected_keys}"

    # Step shapes are identical.
    steps_a = [(s["tool"], s["ok"]) for s in dict_a["steps"]]
    steps_b = [(s["tool"], s["ok"]) for s in dict_b["steps"]]
    assert steps_a == steps_b

    # No hook_firings in either run (no hooks configured).
    assert dict_a["hook_firings"] == []
    assert dict_b["hook_firings"] == []

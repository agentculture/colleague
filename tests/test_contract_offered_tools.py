"""TaskResult.offered_tools (delegation-follow-ups-a7-p3-hire, plan task t2,
covers c34/h18): the depth-0 curated tool names a work item ACTUALLY ran with,
persisted on the artifact beside ``prompt_digest`` with the same
omit-when-None treatment, on every backend (all-engines rule)."""

from __future__ import annotations

import json

from colleague.contract import OK, Task, TaskResult
from colleague.engines.mock import MockEngine
from colleague.loop import curated_schemas, resolve_role


def _result(**kw) -> TaskResult:
    return TaskResult(task_id="t", status=OK, summary="s", **kw)


def test_offered_tools_round_trips_through_to_dict_and_from_dict():
    r = _result(offered_tools=["read_file", "finish"])
    d = r.to_dict()
    assert d["offered_tools"] == ["read_file", "finish"]
    assert TaskResult.from_dict(json.loads(json.dumps(d))).offered_tools == ["read_file", "finish"]


def test_offered_tools_key_is_omitted_when_none():
    d = _result().to_dict()
    assert "offered_tools" not in d
    assert TaskResult.from_dict(d).offered_tools is None


def test_pre_field_artifact_loads_with_offered_tools_none():
    d = _result().to_dict()
    d.pop("offered_tools", None)
    assert TaskResult.from_dict(d).offered_tools is None


def test_mock_engine_stamps_depth0_curated_names_in_schema_order(tmp_path):
    from colleague.config import EngineConfig

    repo = tmp_path / "mock"
    repo.mkdir()
    (repo / "README.md").write_text("x\n")
    cfg = EngineConfig.resolve()
    result = MockEngine().work(Task.new(str(repo), "do work"), cfg)
    assert result.offered_tools is not None
    role = resolve_role(cfg, str(repo))
    expected = [s["function"]["name"] for s in curated_schemas(role, cfg)]
    assert result.offered_tools == expected
    assert "finish" in result.offered_tools


# ---------------------------------------------------------------------------
# Review findings (colleague second opinion, 2026-08-30, task 8e658025caa2):
# the vllm half of the all-engines stamp, the add-knob -> offered_tools
# composition, and the empty-surface case were unpinned.
# ---------------------------------------------------------------------------


def _finish_turn() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {
                                "name": "finish",
                                "arguments": json.dumps({"summary": "done"}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


def test_vllm_engine_stamps_the_surface_it_put_on_the_wire(tmp_path, monkeypatch):
    import subprocess

    from colleague.config import EngineConfig
    from colleague.engines import vllm_openai

    repo = tmp_path / "vllm"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    captured: list[dict] = []

    def fake_post(url, payload, *, api_key, timeout):
        captured.append(payload)
        return _finish_turn()

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)
    cfg = EngineConfig.resolve()
    result = vllm_openai.VllmOpenAIEngine().work(
        Task.new(str(repo), "do work", engine="vllm-openai"), cfg
    )
    assert captured, "the engine must have sent a completion request"
    wire = [t["function"]["name"] for t in captured[0]["tools"]]
    assert result.offered_tools == wire
    # and identical to what the mock stamps for the same config (all-engines rule)
    role = resolve_role(cfg, str(repo))
    assert result.offered_tools == [s["function"]["name"] for s in curated_schemas(role, cfg)]


def test_add_knob_composes_into_offered_tools_on_the_artifact(tmp_path, monkeypatch):
    from colleague.config import EngineConfig

    repo = tmp_path / "add"
    repo.mkdir()
    (repo / "README.md").write_text("x\n")
    monkeypatch.delenv("COLLEAGUE_ACTING_ADD_TOOLS", raising=False)
    off = MockEngine().work(Task.new(str(repo), "do work"), EngineConfig.resolve())
    assert "subagent" not in (off.offered_tools or [])
    monkeypatch.setenv("COLLEAGUE_ACTING_ADD_TOOLS", "subagent")
    on = MockEngine().work(Task.new(str(repo), "do work"), EngineConfig.resolve())
    assert "subagent" in on.offered_tools
    assert [n for n in on.offered_tools if n != "subagent"] == off.offered_tools


def test_empty_curated_surface_stays_absent_on_the_artifact(tmp_path, monkeypatch):
    """A seat that curated NO surface serializes byte-identically to the
    pre-field artifact (the key is absent, never ``[]``) — on both engines.
    An empty allow-list means UNRESTRICTED in the narrowing code, so an empty
    curated surface is forced at the stamp seam itself."""
    import subprocess

    from colleague.config import EngineConfig
    from colleague.engines import mock as mock_mod
    from colleague.engines import vllm_openai

    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "README.md").write_text("x\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setattr(mock_mod, "curated_schemas", lambda *a, **k: [])
    result = MockEngine().work(Task.new(str(repo), "do work"), EngineConfig.resolve())
    assert result.offered_tools is None
    assert "offered_tools" not in result.to_dict()

    monkeypatch.setattr(vllm_openai, "curated_schemas", lambda *a, **k: [])
    monkeypatch.setattr(
        vllm_openai, "_post_json", lambda url, payload, *, api_key, timeout: _finish_turn()
    )
    result = vllm_openai.VllmOpenAIEngine().work(
        Task.new(str(repo), "do work", engine="vllm-openai"), EngineConfig.resolve()
    )
    assert result.offered_tools is None
    assert "offered_tools" not in result.to_dict()

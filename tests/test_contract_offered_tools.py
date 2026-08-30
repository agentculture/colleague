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

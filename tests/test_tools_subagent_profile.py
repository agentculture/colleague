"""#411 — the model-facing `subagent`/`subagents` tools carry profile + context_mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import tools
from colleague.contract import SubResult


def _sub(**kw) -> SubResult:
    base = dict(
        task_id="c1", engine="mock", model="m", status="ok", summary="done", changed_files=[]
    )
    base.update(kw)
    return SubResult(**base)


def test_subagent_schema_exposes_profile_and_context_mode() -> None:
    schema = next(s for s in tools.SCHEMAS if s["function"]["name"] == "subagent")
    props = schema["function"]["parameters"]["properties"]
    assert "profile" in props and props["context_mode"]["enum"] == ["inherit", "clear"]


def test_subagent_passes_profile_and_context_mode_to_the_spawn(tmp_path: Path) -> None:
    seen: list = []

    def spawn(
        instruction, engine=None, model=None, role=None, *, profile=None, context_mode="inherit"
    ):
        seen.append((instruction, engine, model, role, profile, context_mode))
        return _sub()

    ex = tools.ToolExecutor(str(tmp_path), spawn=spawn)
    ex.execute(
        "subagent", {"instruction": "write tests", "profile": "associate", "context_mode": "clear"}
    )
    assert seen == [("write tests", None, None, None, "associate", "clear")]


def test_subagent_without_profile_keeps_the_legacy_positional_call(tmp_path: Path) -> None:
    seen: list = []

    def legacy_spawn(instruction, engine=None, model=None, role=None):  # no kwargs at all
        seen.append((instruction, engine, model, role))
        return _sub()

    ex = tools.ToolExecutor(str(tmp_path), spawn=legacy_spawn)
    ex.execute("subagent", {"instruction": "plain", "role": "explorer"})
    assert seen == [("plain", None, None, "explorer")]


def test_batch_items_keep_profile_and_context_mode() -> None:
    items = tools._parse_batch_items(
        [
            {"instruction": "a", "profile": "associate", "context_mode": "clear"},
            {"instruction": "b"},
        ]
    )
    assert items[0]["profile"] == "associate" and items[0]["context_mode"] == "clear"
    assert "profile" not in items[1] and "context_mode" not in items[1]
    with pytest.raises(tools.ToolError):
        tools._parse_batch_items([{"nope": 1}])

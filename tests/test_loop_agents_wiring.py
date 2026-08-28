"""#411 t15 — the loop's agents-mode wiring: seam calls only, bodies in agents/runtime.py.

Armed: the loop opens the task ledger at the operator repo, seeds the immutable
request, records ONE invocation per model call (truncation flagged), ledgers
mid-run operator input, narrows a worker-purpose surface on BOTH halves, and
folds ``TaskResult.agents`` on every exit. Unarmed: byte-identical (the mock
parity suite + the pinned key set).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague import loop, tools
from colleague.agents.state.ledger import ledger_path, read_ledger
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall


def _finish(summary: str = "done") -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _list_dir() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("l", "list_dir", {"path": "."})])


@pytest.fixture
def armed(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    repo = tmp_path / "repo"
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "config.json").write_text(json.dumps({"agents": True}), encoding="utf-8")
    cfg = EngineConfig.resolve(repo_path=repo, discover_lobes=False)
    assert cfg.agents is True
    task = Task.new(
        str(repo), "wire the agents runtime", constraints=["stdlib only"], acceptance=["tests pass"]
    )
    return repo, cfg, task


def test_unarmed_is_byte_identical(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    task = Task.new(str(repo), "plain run")
    script = iter([_list_dir(), _finish()])
    result = loop.run(lambda _m: next(script), task, max_steps=4, context=ContextControls())
    assert result.status == OK
    assert "agents" not in result.to_dict()
    assert not (repo / ".colleague" / "ledger").exists()


def test_armed_run_records_every_invocation_and_folds_the_block(armed) -> None:
    repo, cfg, task = armed
    seen_system: list[str] = []
    script = iter([_list_dir(), _finish()])

    def complete(messages):
        seen_system.append(messages[0]["content"])
        return next(script)

    result = loop.run(complete, task, max_steps=4, context=ContextControls.from_config(cfg))
    assert result.status == OK
    # (t13 adds the TaskResult field + to_dict key; the fold targets `result.agents`)
    block = result.agents
    assert block["version"] == 1
    # one per model call: list_dir turn, finish turn, and the advisory acceptance
    # self-check (a tools-off model call — it IS an invocation)
    assert len(block["invocations"]) == 3
    inv = block["invocations"][0]
    assert inv["purpose"] == "thinker_coder"
    assert inv["resolved_model"] == cfg.model
    assert inv["token_estimate"] > 0
    assert inv["token_estimate_source"] in ("chars", "tokenize")
    assert block["ledger_path"] == str(ledger_path(repo, task.id))
    assert block["ledger_digest"]
    # the ledger at the OPERATOR repo carries the immutable request first
    events = read_ledger(Path(block["ledger_path"])).events
    assert events[0].kind == "operator_request"
    assert events[0].data["text"] == task.instruction
    kinds = [e.kind for e in events]
    assert kinds.count("invocation") == 3
    assert "constraint" in kinds
    assert "acceptance" in kinds
    # the static guidance + nucleus rode the system prompt ONCE (cache-friendly)
    assert "associate" in seen_system[0]
    assert seen_system[0] == seen_system[1]
    # tokens stay exact — the estimate never reaches Usage
    assert result.usage.total_tokens == 0


def test_operator_input_outranks_and_lands_on_the_ledger(armed) -> None:
    repo, cfg, task = armed
    script = iter([_list_dir(), _finish()])
    controls = ContextControls.from_config(cfg)
    run = controls.agents_run
    result = loop.run(lambda _m: next(script), task, max_steps=4, context=controls)
    assert result.status == OK
    run.operator_input("actually, only list the docs folder", via="guidance")
    events = read_ledger(Path(run.ledger_path)).events
    ops = [e for e in events if e.kind == "operator_input"]
    assert ops
    assert ops[-1].data["text"].startswith("actually")
    assert ops[-1].seq > events[0].seq


def test_truncated_turn_is_flagged_on_its_invocation_record(armed) -> None:
    repo, cfg, task = armed
    script = iter(
        [
            ModelResponse(
                content="",
                tool_calls=[],
                finish_reason="length",
                prompt_tokens=3,
                completion_tokens=4,
            ),
            _finish(),
        ]
    )
    result = loop.run(
        lambda _m: next(script), task, max_steps=4, context=ContextControls.from_config(cfg)
    )
    flags = [i["truncated"] for i in result.agents["invocations"]]
    assert flags[:2] == [True, False]  # the truncated attempt, then its shrink retry
    assert len(flags) == 3  # + the acceptance self-check call


def test_worker_purpose_is_narrowed_on_both_halves(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve(repo_path=repo, discover_lobes=False)
    cfg.agents = True
    setattr(cfg, "agents_profile", "worker")
    role = loop.resolve_role(cfg, str(repo))
    assert role is not None
    offered = {s["function"]["name"] for s in tools.curate_schemas(role)}
    assert "write_file" not in offered
    assert "edit_file" not in offered
    assert "read_file" in offered
    executor = tools.ToolExecutor(str(repo), allowlist=role)
    with pytest.raises(tools.ToolError, match="not allowed"):
        executor.execute("write_file", {"path": "x.txt", "content": "no"})
    assert not (repo / "x.txt").exists()
    # t5 (q9/q10): thinker_coder no longer equals TOOL_NAMES (it loses
    # web/subagent/subagents and gains the six purposes), so it narrows too.
    setattr(cfg, "agents_profile", "thinker_coder")
    thinker_role = loop.resolve_role(cfg, str(repo))
    assert thinker_role is not None
    thinker_names = set(thinker_role.tool_allowlist)
    assert {"web", "subagent", "subagents"}.isdisjoint(thinker_names)
    assert "code_survey" in thinker_names and "write_file" in thinker_names


def test_aborted_run_still_folds_the_block(armed) -> None:
    repo, cfg, task = armed

    def boom(_messages):
        raise RuntimeError("engine exploded")

    controls = ContextControls.from_config(cfg)
    with pytest.raises(loop.WorkAborted) as excinfo:
        loop.run(boom, task, max_steps=2, context=controls)
    partial = excinfo.value.result
    assert partial.agents is not None
    assert partial.agents["ledger_path"]

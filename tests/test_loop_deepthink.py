"""Loop wiring for the dual-model deepthink escalation (plan t5 / spec c10, c14, c11).

The runtime owns the escalation surface (all-engines rule):

- the ``deepthink`` tool records every call on ``TaskResult.deepthink`` via the
  executor's accumulated records;
- the acceptance self-check escalates to the deepthink model when a dual-model
  config is present, DEGRADES to the main model when the escalation fails
  (spec c13/h5), and records the call either way;
- forced synthesis (#191) and fill-line compaction (#156) NEVER touch the
  deepthink seam (spec c11 — their prompt is the main model's own window);
- both engines forward the same binding (``make_deepthink_run(config, name)``)
  into the executor and the ContextControls (all-engines rule);
- a run with no dual-model config records nothing: ``result.deepthink`` stays
  ``None`` → omitted from the artifact (byte-identical single-model).
"""

from __future__ import annotations

import json

from colleague.config import DeepthinkConfig, EngineConfig
from colleague.contract import OK, DeepthinkCall, Task, TaskResult
from colleague.deepthink import DeepthinkResult
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.tools import ToolExecutor


def _finish(summary: str = "done") -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _deepthink_call(question: str = "why?", context: str = "") -> ModelResponse:
    args: dict = {"question": question}
    if context:
        args["context"] = context
    return ModelResponse(tool_calls=[ToolCall("d", "deepthink", args)])


def _scripted_complete(responses: list[ModelResponse]):
    queue = list(responses)
    calls: list[int] = []

    def complete(_messages: list[dict]) -> ModelResponse:
        calls.append(1)
        return queue.pop(0)

    return complete, calls


def _fake_deepthink(text: str = "deep answer", degraded: bool = False):
    """A fake DeepthinkRun binding: records invocations, returns a canned result."""
    calls: list[tuple[str, str, str]] = []

    def fake(question: str, context: str = "", *, point: str = "tool") -> DeepthinkResult:
        calls.append((question, context, point))
        return DeepthinkResult(text=text, call=DeepthinkCall(point=point, degraded=degraded))

    return fake, calls


def _dual_config(**kwargs) -> EngineConfig:
    return EngineConfig(
        deepthink=DeepthinkConfig(
            model="deep-model",
            base_url="http://localhost:9999/v1",
            api_key="k",
            context_budget=48000,
        ),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# The deepthink tool records onto TaskResult.deepthink
# ---------------------------------------------------------------------------


def test_tool_call_is_recorded_on_result(tmp_path):
    fake, dt_calls = _fake_deepthink(text="the verdict")
    executor = ToolExecutor(str(tmp_path), deepthink=fake)
    complete, _ = _scripted_complete([_deepthink_call("is this sound?", "diff digest"), _finish()])
    task = Task.new(str(tmp_path), "review x")
    result = run(complete, task, max_steps=5, executor=executor)
    assert result.status == OK
    assert dt_calls == [("is this sound?", "diff digest", "tool")]
    assert result.deepthink is not None and len(result.deepthink) == 1
    assert result.deepthink[0].point == "tool"
    assert result.deepthink[0].degraded is False


def test_degraded_tool_call_records_and_degrades_to_notice(tmp_path):
    fake, _ = _fake_deepthink(degraded=True)
    executor = ToolExecutor(str(tmp_path), deepthink=fake)
    outcome = executor.execute("deepthink", {"question": "hard one"})
    assert "judgment" in outcome.result  # the degraded notice, not a crash
    assert len(executor.deepthink_calls) == 1
    assert executor.deepthink_calls[0].degraded is True


def test_plain_string_seam_returns_text_without_record(tmp_path):
    # Back-compat: a str-returning seam still answers but records nothing.
    executor = ToolExecutor(str(tmp_path), deepthink=lambda q, c: f"plain:{q}")
    outcome = executor.execute("deepthink", {"question": "hi"})
    assert outcome.result == "plain:hi"
    assert executor.deepthink_calls == []


def test_no_dual_config_records_nothing(tmp_path):
    complete, _ = _scripted_complete([_finish()])
    task = Task.new(str(tmp_path), "do x")
    result = run(complete, task, max_steps=5)
    assert result.deepthink is None


# ---------------------------------------------------------------------------
# Acceptance self-check escalation (point="acceptance_selfcheck")
# ---------------------------------------------------------------------------


def _outcomes_json() -> str:
    return json.dumps([{"criterion": "x", "met": True, "evidence": "saw it"}])


def test_selfcheck_escalates_to_deepthink_when_bound(tmp_path):
    fake, dt_calls = _fake_deepthink(text=_outcomes_json())
    complete, main_calls = _scripted_complete([_finish()])  # NO main self-check turn
    task = Task.new(str(tmp_path), "do x", acceptance=["file exists"])
    result = run(
        complete,
        task,
        max_steps=5,
        context=ContextControls(deepthink_run=fake),
    )
    assert result.status == OK
    assert len(main_calls) == 1  # work turn only — deepthink graded the criteria
    assert len(dt_calls) == 1
    assert dt_calls[0][2] == "acceptance_selfcheck"
    assert result.acceptance_outcomes == [
        {"criterion": "file exists", "met": True, "evidence": "saw it"}
    ]
    assert result.deepthink is not None
    assert result.deepthink[0].point == "acceptance_selfcheck"


def test_selfcheck_digest_names_task_and_criteria(tmp_path):
    fake, dt_calls = _fake_deepthink(text=_outcomes_json())
    complete, _ = _scripted_complete([_finish("built the parser")])
    task = Task.new(str(tmp_path), "add a parser", goal="config parses", acceptance=["x"])
    run(complete, task, max_steps=5, context=ContextControls(deepthink_run=fake))
    digest = dt_calls[0][0]
    # The deepthink model sees nothing else — the digest must be self-contained.
    assert "add a parser" in digest
    assert "config parses" in digest
    assert "built the parser" in digest
    assert "- x" in digest


def test_selfcheck_degradation_falls_back_to_main_model(tmp_path):
    fake, dt_calls = _fake_deepthink(degraded=True)
    checks = [{"criterion": "x", "met": False, "evidence": "nope"}]
    complete, main_calls = _scripted_complete(
        [_finish(), ModelResponse(content=json.dumps(checks))]
    )
    task = Task.new(str(tmp_path), "do x", acceptance=["x"])
    result = run(complete, task, max_steps=5, context=ContextControls(deepthink_run=fake))
    assert result.status == OK
    assert len(dt_calls) == 1  # escalation attempted once
    assert len(main_calls) == 2  # work turn + main-model fallback self-check (c13)
    assert result.acceptance_outcomes == [{"criterion": "x", "met": False, "evidence": "nope"}]
    # The degraded escalation is recorded honestly.
    assert result.deepthink is not None
    assert result.deepthink[0].point == "acceptance_selfcheck"
    assert result.deepthink[0].degraded is True


def test_selfcheck_unparseable_deepthink_text_falls_back(tmp_path):
    fake, _ = _fake_deepthink(text="all looks great to me!")
    checks = [{"criterion": "x", "met": True, "evidence": "ok"}]
    complete, main_calls = _scripted_complete(
        [_finish(), ModelResponse(content=json.dumps(checks))]
    )
    task = Task.new(str(tmp_path), "do x", acceptance=["x"])
    result = run(complete, task, max_steps=5, context=ContextControls(deepthink_run=fake))
    assert len(main_calls) == 2  # fell back to the main-model turn
    assert result.acceptance_outcomes == [{"criterion": "x", "met": True, "evidence": "ok"}]


def test_selfcheck_without_binding_is_byte_identical(tmp_path):
    checks = [{"criterion": "x", "met": True, "evidence": "ok"}]
    complete, main_calls = _scripted_complete(
        [_finish(), ModelResponse(content=json.dumps(checks))]
    )
    task = Task.new(str(tmp_path), "do x", acceptance=["x"])
    result = run(complete, task, max_steps=5)
    assert len(main_calls) == 2
    assert result.deepthink is None


# ---------------------------------------------------------------------------
# Synthesis / compaction never touch the deepthink seam (spec c11)
# ---------------------------------------------------------------------------


def test_forced_synthesis_never_calls_deepthink(tmp_path):
    fake, dt_calls = _fake_deepthink()
    read = ModelResponse(tool_calls=[ToolCall("r", "list_dir", {"path": "."})])
    complete, _ = _scripted_complete([read, read, ModelResponse(content="synthesized answer")])
    task = Task.new(str(tmp_path), "survey")
    result = run(
        complete,
        task,
        max_steps=2,
        executor=ToolExecutor(str(tmp_path), deepthink=fake),
        context=ContextControls(deepthink_run=fake),
    )
    assert result.summary == "synthesized answer"  # forced synthesis fired (#191)
    assert dt_calls == []  # …against the MAIN model only (spec c11)
    assert result.deepthink is None


# ---------------------------------------------------------------------------
# All-engines wiring: both backends bind the same seam
# ---------------------------------------------------------------------------


def _wiring_probe(monkeypatch, engine_module, engine, config, tmp_path):
    sentinel_fn = lambda question, context="", *, point="tool": DeepthinkResult(  # noqa: E731
        text="", call=DeepthinkCall(point=point)
    )
    seen: dict = {}
    monkeypatch.setattr(
        engine_module,
        "make_deepthink_run",
        lambda cfg, name: seen.update(cfg=cfg, name=name) or sentinel_fn,
    )
    captured: dict = {}

    def fake_run(complete, task, **kwargs):
        captured.update(kwargs)
        # A real TaskResult, not a bare object(): every backend now records
        # TaskResult.prompt_digest on the loop's return value (plan task t7),
        # so a stub standing in for ``run`` must honour the return CONTRACT.
        return TaskResult(task_id=task.id, status=OK)

    monkeypatch.setattr(engine_module, "run", fake_run)
    engine.work(Task.new(str(tmp_path), "x"), config)
    return seen, captured, sentinel_fn


def test_mock_engine_wires_deepthink_binding(monkeypatch, tmp_path):
    from colleague.engines import mock as mock_module

    config = _dual_config()
    seen, captured, sentinel = _wiring_probe(
        monkeypatch, mock_module, mock_module.MockEngine(), config, tmp_path
    )
    assert seen["cfg"] is config and seen["name"] == "mock"
    assert captured["executor"]._deepthink is sentinel
    assert captured["context"].deepthink_run is sentinel


def test_vllm_engine_wires_deepthink_binding(monkeypatch, tmp_path):
    from colleague.engines import vllm_openai as vllm_module

    config = _dual_config()
    seen, captured, sentinel = _wiring_probe(
        monkeypatch, vllm_module, vllm_module.VllmOpenAIEngine(), config, tmp_path
    )
    assert seen["cfg"] is config and seen["name"] == "vllm-openai"
    assert captured["executor"]._deepthink is sentinel
    assert captured["context"].deepthink_run is sentinel


def test_vllm_offers_deepthink_schema_only_under_dual_config(monkeypatch, tmp_path):
    from colleague.engines import vllm_openai as vllm_module

    offered: list = []
    real_make = vllm_module.VllmOpenAIEngine._make_complete

    def spying_make(self, config, tools=None):
        offered.append(tools)
        return real_make(self, config, tools=tools)

    monkeypatch.setattr(vllm_module.VllmOpenAIEngine, "_make_complete", spying_make)
    monkeypatch.setattr(
        vllm_module, "run", lambda complete, task, **kw: TaskResult(task_id=task.id, status=OK)
    )

    engine = vllm_module.VllmOpenAIEngine()
    engine.work(Task.new(str(tmp_path), "x"), _dual_config())
    assert any(t.get("function", {}).get("name") == "deepthink" for t in offered[-1])

    engine.work(Task.new(str(tmp_path), "x"), EngineConfig())
    assert not any(t.get("function", {}).get("name") == "deepthink" for t in offered[-1])

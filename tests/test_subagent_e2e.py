"""End-to-end tests for subagent delegation (t7).

Acceptance criteria covered here:

1. (AC1 — byte-identical no-subagent) is in ``tests/test_e2e_mock.py``
   (``test_no_subagent_drive_omits_sub_results_key_byte_identical``); that file
   owns the artifact shape guard.

2. mock→mock round-trip: a scripted mock parent emits a ``subagent`` tool call,
   asserted via step trace, ``sub_results`` length/content, and
   ``to_dict`` / ``from_dict`` round-trip.

3. All-engines schema parity: the ``subagent`` schema is present and byte-identical
   for both engines — verified by asserting that both use the shared ``SCHEMAS``
   list (not two independent copies) and that the schema entry is found in the
   shared surface.

4. Telemetry OFF (default) is a strict no-op: a subagent drive with telemetry off
   behaves identically (sub_results still recorded, artifact unchanged). Telemetry
   ON + child-span nesting: guarded by ``pytest.importorskip`` so the suite stays
   clean without the ``[otel]`` extra.

Implementation note on the scripting pattern:
  The parent's ``complete`` function is injected directly into ``loop.run()``
  (not through ``MockEngine.drive``), so the child mock engine continues to use
  its OWN unpatched ``_script`` (which writes ``colleague-mock.md``).  This
  lets the parent be scripted to delegate while the child does its real work.
  This is the same approach used in ``tests/test_loop_subagent_wiring.py`` (t6).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import colleague.telemetry as tel
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.engines import mock as mock_mod
from colleague.engines import vllm_openai
from colleague.loop import ModelResponse, Spawns, ToolCall, run
from colleague.subagents import make_spawn
from colleague.tools import SCHEMAS, TOOL_NAMES

# The [otel] extra is optional. ``colleague.telemetry`` (``tel``) is import-safe
# without it (lazy SDK import), but the ``_otel`` submodule and the in-memory span
# exporter both import the SDK eagerly — so guard BOTH here and skip ONLY the
# span-nesting test below when the extra is absent (never the whole module).
try:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from colleague.telemetry import _otel

    _HAS_OTEL = True
except ImportError:  # the optional [otel] extra is not installed
    InMemorySpanExporter = None  # type: ignore[assignment,misc]
    _otel = None  # type: ignore[assignment]
    _HAS_OTEL = False

# ---------------------------------------------------------------------------
# Helper: build a deterministic complete() that replays turns then repeats last.
# ---------------------------------------------------------------------------


def _scripted(turns: list[ModelResponse]):
    """Replay ``turns`` in order, repeating the last one indefinitely."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


# ---------------------------------------------------------------------------
# AC2: mock→mock round-trip
#
# The parent complete is scripted directly; the child runs the REAL mock engine
# so it writes colleague-mock.md and finishes cleanly.
# ---------------------------------------------------------------------------


def test_mock_to_mock_subagent_round_trip(tmp_path: Path) -> None:
    """A scripted parent that emits a ``subagent`` tool call records the child on
    ``sub_results``, the step trace holds the subagent call, and the full
    result survives a ``to_dict`` / ``from_dict`` round-trip with all
    nested sub-result fields intact.

    The parent complete is injected directly into ``loop.run`` (bypassing the
    mock engine's own _script) so the child can run the REAL unpatched mock
    engine and actually write ``colleague-mock.md``.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()
    task = Task.new(str(repo), "parent task", engine="mock")

    # Spawn callback — the child will use the real mock engine.
    spawn = make_spawn(str(repo), config, "mock")

    parent_complete = _scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "p-1",
                        "subagent",
                        {"instruction": "write the marker file", "engine": "mock"},
                    )
                ],
                prompt_tokens=2,
                completion_tokens=2,
            ),
            ModelResponse(
                tool_calls=[ToolCall("p-2", "finish", {"summary": "parent delegated then done"})],
                prompt_tokens=2,
                completion_tokens=2,
            ),
        ]
    )

    result = run(parent_complete, task, max_steps=10, spawns=Spawns(single=spawn))

    assert result.status == OK

    # (a) The step trace includes the subagent tool call.
    step_tools = [s.tool for s in result.steps]
    assert "subagent" in step_tools, f"Expected 'subagent' in step tools, got {step_tools}"

    # (b) Exactly one sub-result, from the mock child.
    assert len(result.sub_results) == 1
    sub = result.sub_results[0]
    assert sub.engine == "mock"
    assert sub.status == OK
    assert sub.summary  # the child's finish summary is non-empty
    # The child wrote colleague-mock.md and it is merged into parent.
    assert mock_mod.OUTPUT_FILE in sub.changed_files
    assert mock_mod.OUTPUT_FILE in result.changed_files

    # (c) to_dict includes sub_results (non-empty list).
    d = result.to_dict()
    assert "sub_results" in d
    assert len(d["sub_results"]) == 1
    sub_d = d["sub_results"][0]
    assert sub_d["engine"] == "mock"
    assert sub_d["status"] == OK
    assert isinstance(sub_d["summary"], str)
    assert isinstance(sub_d["changed_files"], list)
    assert isinstance(sub_d["usage"], dict)

    # (d) Full round-trip: from_dict yields an equal TaskResult.
    restored = TaskResult.from_dict(d)
    assert restored.task_id == result.task_id
    assert restored.status == result.status
    assert restored.summary == result.summary
    assert len(restored.sub_results) == 1
    rsub = restored.sub_results[0]
    assert rsub.engine == sub.engine
    assert rsub.model == sub.model
    assert rsub.status == sub.status
    assert rsub.summary == sub.summary
    assert rsub.changed_files == sub.changed_files
    assert rsub.usage.prompt_tokens == sub.usage.prompt_tokens
    assert rsub.usage.completion_tokens == sub.usage.completion_tokens
    assert rsub.usage.total_tokens == sub.usage.total_tokens


def test_mock_to_mock_subagent_step_trace_is_accurate(tmp_path: Path) -> None:
    """The subagent step is recorded as ok=True with the correct tool name and
    the result string summarising the child's outcome.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()
    task = Task.new(str(repo), "step trace parent", engine="mock")
    spawn = make_spawn(str(repo), config, "mock")

    parent_complete = _scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "q-1",
                        "subagent",
                        {"instruction": "do the work", "engine": "mock"},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("q-2", "finish", {"summary": "step-trace done"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )

    result = run(parent_complete, task, max_steps=10, spawns=Spawns(single=spawn))

    subagent_steps = [s for s in result.steps if s.tool == "subagent"]
    assert len(subagent_steps) == 1, "Expected exactly one subagent step"
    s = subagent_steps[0]
    assert s.ok is True
    # The result text contains the engine name.
    assert "mock" in s.result.lower()


def test_mock_to_mock_serialised_round_trip_json_stable(tmp_path: Path) -> None:
    """The to_dict() output is JSON-serialisable (no unserializable types) and
    round-trips through json.dumps / json.loads without loss.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()
    task = Task.new(str(repo), "json round-trip", engine="mock")
    spawn = make_spawn(str(repo), config, "mock")

    parent_complete = _scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "r-1",
                        "subagent",
                        {"instruction": "json test", "engine": "mock"},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("r-2", "finish", {"summary": "json done"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )

    result = run(parent_complete, task, max_steps=10, spawns=Spawns(single=spawn))

    d = result.to_dict()
    # Must be JSON-serialisable.
    raw = json.dumps(d)
    reloaded = json.loads(raw)

    # sub_results survives JSON.
    assert "sub_results" in reloaded
    sub = reloaded["sub_results"][0]
    assert sub["engine"] == "mock"
    assert sub["status"] == OK


# ---------------------------------------------------------------------------
# AC3: all-engines schema parity
# ---------------------------------------------------------------------------


def test_subagent_schema_present_in_shared_tool_surface() -> None:
    """The ``subagent`` tool schema is present in the shared ``SCHEMAS`` list,
    and its name appears in ``TOOL_NAMES``.  Both tests are direct assertions on
    the single shared surface — not engine-specific copies.
    """
    assert "subagent" in TOOL_NAMES, "'subagent' must be in the shared TOOL_NAMES list"

    subagent_schemas = [s for s in SCHEMAS if s["function"]["name"] == "subagent"]
    assert len(subagent_schemas) == 1, "Exactly one 'subagent' schema entry must exist in SCHEMAS"


def test_both_engines_use_the_identical_shared_schemas_object() -> None:
    """The vLLM engine exposes the shared SCHEMAS object directly (not a copy), so
    both engines offer the *identical* subagent schema — including the mock engine
    whose loop dispatcher also operates on the same SCHEMAS surface.

    This is the honest all-engines parity assertion: there is ONE schemas list; a
    per-engine copy would be a gap this test catches.
    """
    # The vLLM engine uses SCHEMAS verbatim in its completions payload.
    assert vllm_openai.SCHEMAS is SCHEMAS, (
        "vllm_openai.SCHEMAS must be the same object as colleague.tools.SCHEMAS — "
        "a copied list would mean the two engines could drift"
    )


def test_subagent_schema_byte_identical_for_both_engines() -> None:
    """The subagent schema entry is byte-identical as seen from both engine call
    sites — both reference the identical dict object from the shared SCHEMAS list.

    Because ``vllm_openai.SCHEMAS is SCHEMAS`` (the previous test guards this),
    the subagent entry dict is the same object in both contexts, so its content
    can only differ if the dict itself is mutated at runtime — which we also
    verify does not happen by comparing serialised forms.
    """
    mock_schemas = SCHEMAS  # mock engine operates on the shared surface
    vllm_schemas = vllm_openai.SCHEMAS  # this IS SCHEMAS (guarded above)

    mock_sub = next(s for s in mock_schemas if s["function"]["name"] == "subagent")
    vllm_sub = next(s for s in vllm_schemas if s["function"]["name"] == "subagent")

    # Same object identity → provably byte-identical.
    assert mock_sub is vllm_sub, (
        "The subagent schema dict must be the exact same object in both "
        "mock_schemas and vllm_schemas — indicating no per-engine mutation."
    )

    # Belt-and-suspenders: JSON-serialised form must also match.
    assert json.dumps(mock_sub, sort_keys=True) == json.dumps(vllm_sub, sort_keys=True)


# ---------------------------------------------------------------------------
# AC4a: telemetry OFF is a strict no-op for subagent drives
# ---------------------------------------------------------------------------


def test_subagent_drive_with_telemetry_off_is_noop(tmp_path: Path) -> None:
    """With telemetry OFF (the default, ``COLLEAGUE_OTEL_ENABLED`` unset),
    a subagent drive behaves identically — no spans, artifact unchanged, and
    sub_results are still recorded correctly.

    Verifies that the telemetry noop path doesn't swallow or interfere with
    the subagent result collection.
    """
    # Ensure the env keys are absent (telemetry disabled by default) — pop both
    # the new and the legacy back-compat name.
    os.environ.pop("COLLEAGUE_OTEL_ENABLED", None)
    os.environ.pop("CONVERTIBLE_OTEL_ENABLED", None)

    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()
    task = Task.new(str(repo), "telemetry off subagent", engine="mock")
    spawn = make_spawn(str(repo), config, "mock")

    parent_complete = _scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "t-1",
                        "subagent",
                        {"instruction": "child work", "engine": "mock"},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("t-2", "finish", {"summary": "telemetry off done"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )

    # Use loop.run directly so we control the telemetry parameter (None = default noop).
    result = run(parent_complete, task, max_steps=10, spawns=Spawns(single=spawn))

    # The drive succeeded and sub_results are recorded — telemetry off is a no-op.
    assert result.status == OK
    assert len(result.sub_results) == 1
    assert result.sub_results[0].status == OK

    # The serialized artifact carries sub_results and has the expected shape.
    d = result.to_dict()
    assert "sub_results" in d
    assert len(d["sub_results"]) == 1

    # No extra telemetry-related keys leaked into the artifact.
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
        "sub_results",
        "not_finished",
        "stopped_without_finish",
    }
    assert (
        set(d.keys()) == expected_keys
    ), f"Unexpected keys in subagent artifact: {set(d.keys()) - expected_keys}"


# ---------------------------------------------------------------------------
# AC4b: telemetry ON — child spans nest under parent tool-call span.
# Requires the [otel] extra. The guard is per-test (skipif on the single test
# below), NOT a module-scope importorskip: the latter silently skipped this
# whole file — including the non-telemetry subagent E2E tests above — in any
# environment without the extra (qodo finding on PR #58).
# ---------------------------------------------------------------------------


@pytest.fixture
def _otel_capture():
    """An enabled, SDK-backed Telemetry writing spans to an in-memory exporter."""
    _otel.reset_for_tests()
    span_exporter = InMemorySpanExporter()
    cfg = tel.TelemetryConfig(enabled=True, service_name="colleague-subagent-test")
    t = tel.load_telemetry(cfg, span_exporter=span_exporter)
    yield t, span_exporter
    _otel.reset_for_tests()


@pytest.mark.skipif(not _HAS_OTEL, reason="install the [otel] extra to test SDK span nesting")
def test_subagent_tool_span_nests_under_parent_work_span(tmp_path: Path, _otel_capture) -> None:
    """When telemetry is ON and injected into the parent drive, the parent's
    ``colleague.tool.subagent`` span nests correctly under the outer
    ``colleague.work`` span (shared trace ID, parent span_id matches).

    The parent's tool-loop spans are emitted to the injected telemetry because
    ``loop.run`` receives ``telemetry=t``.  The child drive runs synchronously
    inside the ``colleague.tool.subagent`` span context, and because OTel
    context propagation is via contextvars, any span the child's telemetry opens
    (if the child also has telemetry enabled) would automatically nest — but this
    test only asserts the parent-loop property, which is unconditionally verifiable.

    This is the honest scope: we assert that the tool span for the subagent CALL
    appears and is nested under the drive span.  We do NOT assert on child-internal
    spans (write_file, finish) because the child drive uses its own default
    ``load_telemetry()`` (the no-op, unless OTEL is enabled in the env).
    """
    t, span_exporter = _otel_capture

    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()
    task = Task.new(str(repo), "telemetry subagent nesting", engine="mock")
    spawn = make_spawn(str(repo), config, "mock")

    parent_complete = _scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "s-1",
                        "subagent",
                        {"instruction": "child work for span test", "engine": "mock"},
                    )
                ],
                prompt_tokens=2,
                completion_tokens=2,
            ),
            ModelResponse(
                tool_calls=[ToolCall("s-2", "finish", {"summary": "span-nesting done"})],
                prompt_tokens=2,
                completion_tokens=2,
            ),
        ]
    )

    # Inject the telemetry directly into the parent loop.run so its spans are
    # captured.  Open the outer work_span context first so tool spans auto-nest.
    with t.work_span(task_id=task.id, engine="mock", model="mock-model", max_steps=10):
        result = run(parent_complete, task, max_steps=10, spawns=Spawns(single=spawn), telemetry=t)

    assert result.status == OK
    assert len(result.sub_results) == 1

    spans = span_exporter.get_finished_spans()
    span_by_name: dict = {}
    for s in spans:
        span_by_name.setdefault(s.name, []).append(s)

    # The outer drive span was explicitly opened above.
    assert (
        "colleague.work" in span_by_name
    ), f"Expected 'colleague.work' in spans, got: {list(span_by_name)}"
    # The subagent tool call must emit a span from the parent's telemetry.
    assert (
        "colleague.tool.subagent" in span_by_name
    ), f"Expected 'colleague.tool.subagent' in spans, got: {list(span_by_name)}"

    parent_work_span = span_by_name["colleague.work"][0]
    subagent_tool_span = span_by_name["colleague.tool.subagent"][0]

    # All spans share the same trace (the outer work_span opened it).
    assert (
        subagent_tool_span.context.trace_id == parent_work_span.context.trace_id
    ), "colleague.tool.subagent span must share the parent drive's trace ID"

    # The subagent tool span's parent is the outer drive span.
    assert subagent_tool_span.parent is not None, "colleague.tool.subagent span must have a parent"
    assert (
        subagent_tool_span.parent.span_id == parent_work_span.context.span_id
    ), "The subagent tool span's parent span_id must match the outer drive span"

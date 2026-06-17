"""Pre-finish test-integrity gate wired into the loop (#203, task t2).

Exercises the runtime integration via ``run()`` with a scripted ``complete``:
after the loop, the gate runs the mirror-detection heuristic on the changed
files and records any findings on ``result.test_integrity_report``. It is
deterministic and code-locked (fires regardless of model behaviour), advisory
and non-blocking (never blocks the handoff, no network), and a no-finding run is
byte-identical (the report stays ``None`` and is omitted from the artifact).
Default is ON (the all-engines rule); ``ContextControls(testintegrity=False)``
disables it.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _write(path: str, content: str) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall("w", "write_file", {"path": path, "content": content})]
    )


def _finish(summary: str) -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


# A test file + impl file that share the novel attribute ``response_error`` (the
# #203 AWS scenario): present in both, found nowhere else in the tmp repo.
_MIRROR_TEST = 'import exc\n\n\ndef test_x():\n    raise exc.response_error("boom")\n'
_MIRROR_IMPL = 'import exc\n\n\ndef handle():\n    raise exc.response_error("boom")\n'


def _run_mirror(tmp_path: Path, *, context: ContextControls | None = None):
    responses = [
        _write("test_thing.py", _MIRROR_TEST),
        _write("thing.py", _MIRROR_IMPL),
        _finish("wrote a test and impl"),
    ]
    return run(
        scripted(responses),
        Task.new(str(tmp_path), "write a test and an impl"),
        max_steps=6,
        context=context,
    )


def test_gate_flags_mirror_signature_by_default(tmp_path: Path) -> None:
    """Default run() (no ContextControls) fires the gate and flags the mirror."""
    result = _run_mirror(tmp_path)
    assert result.status == OK
    assert result.summary == "wrote a test and impl" or result.summary  # finish stands
    assert result.test_integrity_report is not None
    symbols = {f.symbol for f in result.test_integrity_report.findings}
    assert "response_error" in symbols
    finding = next(f for f in result.test_integrity_report.findings if f.symbol == "response_error")
    assert finding.kind == "attribute"
    assert finding.test_file == "test_thing.py"
    assert finding.impl_file == "thing.py"
    # The finding round-trips into the serialized artifact.
    assert "test_integrity_report" in result.to_dict()


def test_gate_no_findings_is_byte_identical(tmp_path: Path) -> None:
    """A run with no test+impl mirror leaves the report None and omits the key."""
    responses = [_write("m.py", "x = 1\n"), _finish("wrote m.py")]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write m.py"),
        max_steps=5,
    )
    assert result.status == OK
    assert result.test_integrity_report is None
    assert "test_integrity_report" not in result.to_dict()


def test_gate_disabled_is_strict_noop(tmp_path: Path) -> None:
    """ContextControls(testintegrity=False) disables the gate even on a mirror."""
    result = _run_mirror(tmp_path, context=ContextControls(testintegrity=False))
    assert result.status == OK
    assert result.test_integrity_report is None
    assert "test_integrity_report" not in result.to_dict()


def test_gate_not_flagged_when_symbol_exists_elsewhere(tmp_path: Path) -> None:
    """A symbol also present in a non-changed repo file is not novel → not flagged."""
    # Pre-existing file (not in the changed set) that also uses response_error.
    (tmp_path / "legacy.py").write_text("import exc\n\n\ndef old():\n    exc.response_error\n")
    result = _run_mirror(tmp_path)
    assert result.status == OK
    assert result.test_integrity_report is None


def test_gate_does_not_block_handoff(tmp_path: Path) -> None:
    """The gate is non-blocking: the work item finishes OK with the mirror recorded."""
    result = _run_mirror(tmp_path)
    assert result.status == OK
    assert result.not_finished is False
    assert result.test_integrity_report is not None

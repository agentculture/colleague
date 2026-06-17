"""Bounded re-examine turn + config forwarding for the test-integrity gate (#203, t3).

The re-examine turn fires only on a clean finish with a fix-turn budget left; it
asks the model to verify the flagged symbol against the real API shape, re-runs the
gate, and saves/restores the work item's terminal summary/status so its own finish
cannot clobber the real result. Conservative by default (0 retries). Also covers the
EngineConfig.testintegrity / testintegrity_fix_retries resolution (env > default).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from colleague.config import EngineConfig
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


# Mirror on the WRONG attr response_error; the real attr `response` is also present
# in a pre-existing stub so a fix to `response` is NOT novel and clears the finding.
_WRONG_TEST = "import exc\n\n\ndef test_x():\n    return exc.response_error\n"
_WRONG_IMPL = "import exc\n\n\ndef handle():\n    return exc.response_error\n"
_FIXED_TEST = "import exc\n\n\ndef test_x():\n    return exc.response\n"
_FIXED_IMPL = "import exc\n\n\ndef handle():\n    return exc.response\n"


def _seed_stub(tmp_path: Path) -> None:
    # Pre-existing (non-changed) file where the REAL attr `response` already lives,
    # so the re-examine "fix" to `response` is not flagged as a new mirror.
    (tmp_path / "botostub.py").write_text("import exc\n\n\ndef real():\n    return exc.response\n")


def test_reexamine_turn_fixes_and_clears_the_finding(tmp_path: Path) -> None:
    """With a retry budget, the re-examine turn fires, the model fixes the symbol,
    and the re-run gate clears the report — while the original summary is preserved."""
    _seed_stub(tmp_path)
    responses = [
        _write("test_thing.py", _WRONG_TEST),
        _write("thing.py", _WRONG_IMPL),
        _finish("done"),
        # re-examine turn continues the same script:
        _write("thing.py", _FIXED_IMPL),
        _write("test_thing.py", _FIXED_TEST),
        _finish("fixed the mirror"),
    ]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write a test and impl"),
        max_steps=6,
        context=ContextControls(testintegrity=True, testintegrity_fix_retries=1),
    )
    assert result.status == OK
    # The re-examine turn ran, the model fixed response_error -> response (which is
    # not novel — it exists in botostub.py), so the gate cleared the report.
    assert result.test_integrity_report is None
    assert (tmp_path / "thing.py").read_text() == _FIXED_IMPL
    # The re-examine turn's own finish ("fixed the mirror") did not clobber the
    # work item's real summary.
    assert result.summary == "done"


def test_no_retry_budget_records_but_does_not_reexamine(tmp_path: Path) -> None:
    """Default 0 retries: the mirror is recorded but no re-examine turn fires."""
    _seed_stub(tmp_path)
    responses = [
        _write("test_thing.py", _WRONG_TEST),
        _write("thing.py", _WRONG_IMPL),
        _finish("done"),
        # These would only run if a (non-existent) re-examine turn fired:
        _write("thing.py", _FIXED_IMPL),
        _finish("should not happen"),
    ]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write a test and impl"),
        max_steps=6,
        context=ContextControls(testintegrity=True, testintegrity_fix_retries=0),
    )
    assert result.status == OK
    assert result.test_integrity_report is not None
    assert {f.symbol for f in result.test_integrity_report.findings} == {"response_error"}
    # No re-examine turn → the impl was NOT rewritten to the fixed form.
    assert (tmp_path / "thing.py").read_text() == _WRONG_IMPL
    assert result.summary == "done"


# ── config resolution ────────────────────────────────────────────────────


def test_config_testintegrity_defaults_on_and_zero_retries() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = EngineConfig.resolve()
    assert cfg.testintegrity is True
    assert cfg.testintegrity_fix_retries == 0
    d = cfg.to_dict()
    assert d["testintegrity"] is True
    assert d["testintegrity_fix_retries"] == 0


def test_config_testintegrity_env_opt_out_and_retries() -> None:
    env = {
        "COLLEAGUE_TESTINTEGRITY": "0",
        "COLLEAGUE_TESTINTEGRITY_FIX_RETRIES": "2",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = EngineConfig.resolve()
    assert cfg.testintegrity is False
    assert cfg.testintegrity_fix_retries == 2

"""``TaskResult.task_text`` — the brief a run actually ran with, verbatim
(#481, covers c4/h3 of
``docs/specs/2026-09-01-small-fixes-then-effort-balance.md``).

``prompt_digest`` proves WHICH prompt arm a run used, but never recorded the
task text itself, so a measurement rerun had nothing but the operator's
memory of what was typed. This field closes that gap: shape follows
``prompt_digest`` EXACTLY (see ``tests/test_contract_prompt_digest.py``) —
omit-when-``None``, round-tripped by ``from_dict``, populated the moment the
loop's ``TaskResult`` exists so aborted/salvaged runs still carry it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import tasktext
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.engines import vllm_openai
from colleague.engines.mock import MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from tests._batch_fixture import (
    BATCH_TASK_INSTRUCTION,
    make_batch_repo,
    vllm_batch_turns,
)

_MODEL = "Qwen/Qwen3-32B"


# ---------------------------------------------------------------------------
# The pure helper: cap + discoverable truncation marker (never a silent cut).
# ---------------------------------------------------------------------------


def test_prepare_task_text_returns_short_text_verbatim() -> None:
    assert tasktext.prepare_task_text("do a thing") == "do a thing"


def test_prepare_task_text_returns_exactly_cap_sized_text_verbatim() -> None:
    text = "x" * tasktext.MAX_CHARS
    assert tasktext.prepare_task_text(text) == text


def test_prepare_task_text_truncates_over_cap_text_with_a_discoverable_marker() -> None:
    original = "y" * (tasktext.MAX_CHARS + 500)
    prepared = tasktext.prepare_task_text(original)
    assert len(prepared) <= tasktext.MAX_CHARS
    assert f"[truncated: original {len(original)} chars]" in prepared
    # never a silent cut: the marker text is present, not merely a shorter string
    assert prepared != original[: tasktext.MAX_CHARS]


def test_recording_enabled_defaults_true_when_knob_absent() -> None:
    assert tasktext.recording_enabled({}) is True


def test_recording_enabled_false_only_for_exact_string_zero() -> None:
    assert tasktext.recording_enabled({"COLLEAGUE_RECORD_TASK_TEXT": "0"}) is False
    assert tasktext.recording_enabled({"COLLEAGUE_RECORD_TASK_TEXT": "1"}) is True
    assert tasktext.recording_enabled({"COLLEAGUE_RECORD_TASK_TEXT": ""}) is True


# ---------------------------------------------------------------------------
# Artifact shape: beside prompt_digest, omitted when None, round-tripped.
# ---------------------------------------------------------------------------


def test_task_text_defaults_to_none() -> None:
    assert TaskResult(task_id="x", status="ok").task_text is None


def test_task_text_is_omitted_when_none() -> None:
    """A disabled/pre-field run serializes byte-identically — no extra key."""
    assert "task_text" not in TaskResult(task_id="x", status="ok").to_dict()


def test_task_text_sits_beside_prompt_digest() -> None:
    result = TaskResult(
        task_id="x",
        status="ok",
        prompt_digest="cafebabe",
        task_text="do a thing",
    )
    keys = list(result.to_dict())
    assert keys.index("task_text") > keys.index("prompt_digest")


def test_task_text_round_trips_through_from_dict() -> None:
    original = TaskResult(task_id="x", status="ok", task_text="write the output file")
    restored = TaskResult.from_dict(original.to_dict())
    assert restored.task_text == "write the output file"


def test_task_text_absent_from_dict_reads_back_as_none() -> None:
    restored = TaskResult.from_dict({"task_id": "x", "status": "ok"})
    assert restored.task_text is None


# ---------------------------------------------------------------------------
# Acceptance 1 — a run records its brief verbatim, under the cap; over-cap
# briefs carry an explicit truncation marker, never a silent cut.
# ---------------------------------------------------------------------------


def _run_mock(repo: Path, instruction: str = "write the output file") -> TaskResult:
    return MockEngine().work(
        Task.new(str(repo), instruction, engine="mock"),
        EngineConfig(model=_MODEL),
    )


def test_mock_run_records_its_brief_verbatim(tmp_path: Path) -> None:
    result = _run_mock(tmp_path, "write the output file")
    assert result.task_text == "write the output file"
    assert result.to_dict()["task_text"] == "write the output file"


def test_mock_run_with_an_over_cap_brief_carries_an_explicit_truncation_marker(
    tmp_path: Path,
) -> None:
    huge = "z" * (tasktext.MAX_CHARS + 1000)
    result = _run_mock(tmp_path, huge)
    assert result.task_text is not None
    assert len(result.task_text) <= tasktext.MAX_CHARS
    assert f"[truncated: original {len(huge)} chars]" in result.task_text


# ---------------------------------------------------------------------------
# Acceptance 2 — COLLEAGUE_RECORD_TASK_TEXT=0 yields a byte-identical
# artifact (key absent).
# ---------------------------------------------------------------------------


def test_knob_off_leaves_the_artifact_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_RECORD_TASK_TEXT", "0")
    result = _run_mock(tmp_path)
    assert result.task_text is None
    assert "task_text" not in result.to_dict()


def test_knob_on_by_default_records_task_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COLLEAGUE_RECORD_TASK_TEXT", raising=False)
    result = _run_mock(tmp_path)
    assert result.task_text is not None
    assert "task_text" in result.to_dict()


# ---------------------------------------------------------------------------
# All-engines rule — vllm-openai records the field the same way mock does.
# ---------------------------------------------------------------------------


def test_vllm_records_the_same_task_text_as_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turns = vllm_batch_turns()
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    cfg = EngineConfig.resolve()
    mock_repo = make_batch_repo(tmp_path / "mock")
    vllm_repo = make_batch_repo(tmp_path / "vllm")

    mock_result = MockEngine().work(
        Task.new(str(mock_repo), BATCH_TASK_INSTRUCTION, engine="mock"), cfg
    )
    vllm_result = VllmOpenAIEngine().work(
        Task.new(str(vllm_repo), BATCH_TASK_INSTRUCTION, engine="vllm-openai"), cfg
    )

    assert mock_result.task_text == BATCH_TASK_INSTRUCTION
    assert vllm_result.task_text == BATCH_TASK_INSTRUCTION

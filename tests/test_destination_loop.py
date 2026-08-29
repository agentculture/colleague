"""Tests for destination arrival recording in the loop and chassis guidance.

t4: loop records arrival (destination + announcement from finish tool) and
_DEFAULT_SYSTEM carries destination guidance that both engines inherit.
"""

from __future__ import annotations

from pathlib import Path

import colleague.engines.mock as mock_mod
import colleague.engines.vllm_openai as vllm_mod
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.engines.mock import MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.loop import _DEFAULT_SYSTEM, CompleteFn, ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """Returns a complete() that plays back canned responses in order."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _spy_run(captured: dict, key: str):
    """Monkeypatch shim: records system_prompt and returns a minimal result."""

    def spy(complete, task, *, max_steps, system_prompt=None, **kwargs):
        captured[key] = system_prompt
        return TaskResult(task_id=task.id, status="ok")

    return spy


def _capture_both(monkeypatch, repo: Path, model: str) -> dict:
    """Drive both engines with a spy loop.run, return {mock, vllm} system prompts."""
    captured: dict = {}
    monkeypatch.setattr(mock_mod, "run", _spy_run(captured, "mock"))
    monkeypatch.setattr(vllm_mod, "run", _spy_run(captured, "vllm"))

    config = EngineConfig(model=model)
    task = Task(id="t4-1", repo_path=str(repo), instruction="do a thing")
    MockEngine().work(task, config)
    VllmOpenAIEngine().work(task, config)
    return captured


# ---------------------------------------------------------------------------
# 1. Guidance present in _DEFAULT_SYSTEM
# ---------------------------------------------------------------------------


def test_default_system_contains_destination_guidance() -> None:
    """_DEFAULT_SYSTEM mentions 'destination', 'optional'/'advisory', 'announcement'."""
    lower = _DEFAULT_SYSTEM.lower()
    assert "destination" in lower, "_DEFAULT_SYSTEM must mention 'destination'"
    # The guidance should state it is optional/advisory — either word suffices.
    assert (
        "optional" in lower or "advisory" in lower
    ), "_DEFAULT_SYSTEM must state the destination is optional or advisory"
    assert "announcement" in lower, "_DEFAULT_SYSTEM must mention 'announcement'"


def test_default_system_preserves_original_coding_agent_text() -> None:
    """The original coding-agent preamble is still present (no regression)."""
    assert "coding agent" in _DEFAULT_SYSTEM.lower()
    assert "finish" in _DEFAULT_SYSTEM.lower()


def test_default_system_advertises_culture_tools() -> None:
    """_DEFAULT_SYSTEM names the culture tool + the agtag/devex CLIs as optional (#124).

    Like the subagents gap fixed in #122, an unnamed loop tool is invisible to the
    live model — so the prompt must name it. Additive: the existing destination +
    subagents guidance stays intact."""
    lower = _DEFAULT_SYSTEM.lower()
    assert "culture" in lower, "_DEFAULT_SYSTEM must mention the culture tool"
    assert "agtag" in lower, "_DEFAULT_SYSTEM must name the agtag CLI"
    assert "devex" in lower, "_DEFAULT_SYSTEM must name the devex CLI"
    # Pin the CULTURE paragraph's OWN optionality — checking 'optional'/'advisory'
    # anywhere in _DEFAULT_SYSTEM would still pass if only the destination/subagents
    # paragraphs carried it. Anchor on the culture segment.
    culture_seg = lower.split("culture tools", 1)[-1]
    assert culture_seg != lower, "the culture paragraph must start with a 'Culture tools' header"
    assert (
        "optional" in culture_seg or "advisory" in culture_seg
    ), "the culture paragraph itself must be framed optional/advisory"
    # The destination + subagents guidance is untouched (the new paragraph is additive).
    assert "destination" in lower
    assert "announcement" in lower
    assert "subagent" in lower


# ---------------------------------------------------------------------------
# 2. Both engines inherit the guidance (no-layers path uses _DEFAULT_SYSTEM)
# ---------------------------------------------------------------------------


def test_both_engines_inherit_destination_guidance_via_default_system(
    tmp_path: Path, monkeypatch
) -> None:
    """When no AGENTS/skills layers exist, both engines compose the SAME prompt
    on top of _DEFAULT_SYSTEM — so the guidance rides along either way.

    Plan t5 (prompt/surface unification) changed this from ``system_prompt=None``
    on both engines to the acting seat's composed writer prompt, whose BASE is
    ``_DEFAULT_SYSTEM``; the guidance the test is really about is unchanged and
    still asserted, both in the base and in what the engines inject."""
    repo = tmp_path / "repo"
    repo.mkdir()

    captured = _capture_both(monkeypatch, repo, "Qwen/Qwen3-32B")
    # No layers → both engines compose the identical acting-seat prompt.
    assert captured["mock"] == captured["vllm"]
    assert captured["mock"] is not None
    assert captured["mock"].startswith(_DEFAULT_SYSTEM)
    # The guidance lives in _DEFAULT_SYSTEM, which is that prompt's base.
    assert "destination" in _DEFAULT_SYSTEM.lower()
    assert "destination" in captured["mock"].lower()


def test_both_engines_inherit_destination_guidance_via_layered_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    """With an AGENTS.md present, both engines build a prompt starting with
    _DEFAULT_SYSTEM (which contains the destination guidance)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Custom rule.", encoding="utf-8")

    captured = _capture_both(monkeypatch, repo, "Qwen/Qwen3-32B")

    assert captured["mock"] is not None
    assert captured["vllm"] is not None
    # Both engines inherit identically (all-engines rule).
    assert captured["mock"] == captured["vllm"]
    # The layered prompt is built on top of _DEFAULT_SYSTEM.
    assert captured["mock"].startswith(_DEFAULT_SYSTEM)
    # Since _DEFAULT_SYSTEM contains the destination guidance, the full prompt does too.
    lower = captured["mock"].lower()
    assert "destination" in lower
    assert "announcement" in lower


# ---------------------------------------------------------------------------
# 3. Loop records arrival into TaskResult
# ---------------------------------------------------------------------------


def test_loop_records_destination_and_announcement(tmp_path: Path) -> None:
    """finish with destination + announcement → result carries both fields."""
    responses = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "t4-fin",
                    "finish",
                    {
                        "summary": "shipped the feature",
                        "destination": "ship-core-widget",
                        "announcement": "The core widget has shipped.",
                    },
                )
            ]
        )
    ]
    task = Task.new(str(tmp_path), "ship the widget")
    result = run(scripted(responses), task, max_steps=5)

    assert result.status == OK
    assert result.destination == "ship-core-widget"
    assert result.announcement == "The core widget has shipped."
    assert result.summary == "shipped the feature"


def test_loop_records_destination_only(tmp_path: Path) -> None:
    """finish with destination but no announcement → destination set, announcement None."""
    responses = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "t4-fin2",
                    "finish",
                    {
                        "summary": "reached the frame",
                        "destination": "my-goal-frame",
                    },
                )
            ]
        )
    ]
    task = Task.new(str(tmp_path), "reach the frame")
    result = run(scripted(responses), task, max_steps=5)

    assert result.destination == "my-goal-frame"
    assert result.announcement is None


# ---------------------------------------------------------------------------
# 4. No-destination path unchanged
# ---------------------------------------------------------------------------


def test_loop_no_destination_path_unchanged(tmp_path: Path) -> None:
    """finish without destination/announcement → both stay None (byte-identical)."""
    responses = [
        ModelResponse(tool_calls=[ToolCall("t4-nd", "finish", {"summary": "plain finish"})])
    ]
    task = Task.new(str(tmp_path), "plain task")
    result = run(scripted(responses), task, max_steps=5)

    assert result.status == OK
    assert result.destination is None
    assert result.announcement is None
    assert result.summary == "plain finish"


def test_loop_no_tool_calls_no_destination(tmp_path: Path) -> None:
    """Model answers without calling finish → destination and announcement are None."""
    task = Task.new(str(tmp_path), "just reply")
    result = run(scripted([ModelResponse(content="here is my answer")]), task, max_steps=5)

    assert result.destination is None
    assert result.announcement is None
    assert result.summary == "here is my answer"


# ---------------------------------------------------------------------------
# 5. Termination — loop still terminates within max_steps on both paths
# ---------------------------------------------------------------------------


def test_loop_terminates_with_destination(tmp_path: Path) -> None:
    """A finish call carrying a destination still terminates the loop normally."""
    responses = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "t4-term",
                    "finish",
                    {
                        "summary": "done",
                        "destination": "some-slug",
                        "announcement": "Goal reached!",
                    },
                )
            ]
        )
    ]
    task = Task.new(str(tmp_path), "any task")
    result = run(scripted(responses), task, max_steps=10)
    # Loop terminates and the result is valid.
    assert result.status == OK
    assert result.destination == "some-slug"


def test_loop_terminates_without_destination(tmp_path: Path) -> None:
    """A finish call without a destination also terminates correctly."""
    responses = [
        ModelResponse(tool_calls=[ToolCall("t4-term2", "finish", {"summary": "done plain"})])
    ]
    task = Task.new(str(tmp_path), "any task 2")
    result = run(scripted(responses), task, max_steps=10)
    assert result.status == OK
    assert result.destination is None

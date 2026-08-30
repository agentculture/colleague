"""Plan t6 (c51/h38): markup-shaped tool calls become a COUNT on the artifact.

#360's measured failure: the served model emits a tool call as literal markup
*text* in message content, the harness drops it, and the run is externally
indistinguishable from one where the model simply ignored its tools. The
``markup_tool_calls`` counter (:mod:`colleague.toolmarkup` →
``WorkStats.counts``) tells the two apart — for ANY function name, not just the
``finish`` shape #248 mode B already recovers.

Detection only: nothing here (or in the loop) executes recovered markup — a
converted markup call would change what a run *does* and confound every arm of
this arc, so the non-execution pin below is load-bearing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import toolmarkup
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines.mock import MockEngine
from colleague.loop import CompleteFn, ModelResponse, run

_SURVEY_MARKUP = (
    "I'll delegate this.\n"
    "<tool_call>\n"
    "<function=web_survey>\n"
    "<parameter=query>\nrecent vLLM tool-call parsers\n</parameter>\n"
    "</function>\n"
    "</tool_call>"
)

_JSON_MARKUP = '<tool_call>\n{"name": "code_survey", "arguments": {"query": "loop"}}\n</tool_call>'

_FINISH_MARKUP = (
    "<tool_call>\nfunction=finish>\n<parameter=summary>\nThe answer is 42.\n"
    "</parameter>\n</function>\n</tool_call>"
)


def _repeating(responses: list[ModelResponse]) -> CompleteFn:
    """A scripted ``complete()`` that repeats its last response forever."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


# ---------------------------------------------------------------- unit: detection


def test_counts_any_function_name_not_just_finish() -> None:
    assert toolmarkup.names_in(_SURVEY_MARKUP) == ["web_survey"]
    assert toolmarkup.count(_SURVEY_MARKUP) == 1
    assert toolmarkup.names_in(_FINISH_MARKUP) == ["finish"]


def test_counts_the_json_dialect_once() -> None:
    assert toolmarkup.names_in(_JSON_MARKUP) == ["code_survey"]


def test_counts_every_block_in_a_multi_call_turn() -> None:
    assert toolmarkup.count(_SURVEY_MARKUP + "\n" + _JSON_MARKUP) == 2


@pytest.mark.parametrize(
    "prose",
    [
        "",
        "The loop never runs a function=finish string that appears mid-sentence.",
        "Docs discuss <tool_call> markers inline like this one.",
        "A clean prose answer with no markup at all.",
    ],
)
def test_ordinary_prose_counts_zero(prose: str) -> None:
    assert toolmarkup.count(prose) == 0


def test_a_nameless_block_counts_zero() -> None:
    assert toolmarkup.count("<tool_call>\nno function here\n</tool_call>") == 0


def test_argument_text_naming_function_does_not_hide_the_json_call() -> None:
    """Qodo 3888125919: ``function=`` inside an argument VALUE is not a marker.

    De-duplication keys off a *recognised* line-anchored marker, not the raw
    substring — otherwise a genuine JSON call whose arguments merely mention
    ``function=`` counts zero, under-reporting the exact drop this counter
    exists to detect.
    """
    markup = (
        "<tool_call>\n"
        '{"name": "code_survey", "arguments": {"note": "function=example"}}\n'
        "</tool_call>"
    )
    assert toolmarkup.names_in(markup) == ["code_survey"]
    assert toolmarkup.count(markup) == 1


def test_a_genuine_function_block_is_counted_exactly_once() -> None:
    """The de-dup still holds: one block naming ``function=`` is not double-counted."""
    assert toolmarkup.names_in(_SURVEY_MARKUP) == ["web_survey"]
    assert toolmarkup.names_in(_FINISH_MARKUP) == ["finish"]
    # A block carrying BOTH shapes still counts once (the ``function=`` name).
    both = (
        "<tool_call>\n"
        "<function=web_survey>\n"
        '{"name": "code_survey"}\n'
        "</function>\n"
        "</tool_call>"
    )
    assert toolmarkup.names_in(both) == ["web_survey"]


class _ScanCountingStr(str):
    """A ``str`` that records how many characters each :meth:`find` scanned."""

    def __new__(cls, value: str) -> "_ScanCountingStr":
        obj = super().__new__(cls, value)
        obj.scanned = 0  # type: ignore[attr-defined]
        return obj

    def find(self, sub: str, start: int = 0, end: int | None = None) -> int:  # type: ignore[override]  # noqa: E501
        base = str(self)
        idx = base.find(sub, start) if end is None else base.find(sub, start, end)
        stop = len(base) if idx == -1 else idx
        self.scanned += max(0, stop - start)  # type: ignore[attr-defined]
        return idx


def test_many_unterminated_openers_stay_linear() -> None:
    """Qodo 3888125923: block segmentation must not rescan the suffix per opener.

    Counted work, not wall-clock — deterministic and fast. The old
    implementation searched the whole remaining response for a close tag once
    per opener, i.e. ``O(n^2)``; here the bound is a small multiple of the
    response length.
    """
    content = _ScanCountingStr("<tool_call\n" * 2000)
    assert toolmarkup.count(content) == 0
    # Linear pass: a handful of sweeps over the text, never ~2000 of them.
    assert content.scanned <= 4 * len(content)


# ------------------------------------------------------- the artifact-visible count


def test_markup_naming_any_function_lands_on_the_artifact(tmp_path: Path) -> None:
    """AC1: visible in ``stats.counts`` — read WITHOUT parsing the warnings array."""
    result = run(
        _repeating([ModelResponse(content=_SURVEY_MARKUP)]),
        Task.new(str(tmp_path), "delegate a survey"),
        max_steps=10,
    )

    counts = result.to_dict()["stats"]["counts"]
    assert counts["markup_tool_calls"] >= 1
    assert result.stats.counts["markup_tool_calls"] == counts["markup_tool_calls"]


def test_finish_markup_is_counted_and_still_recovered(tmp_path: Path) -> None:
    """The #248 mode B recovery is untouched; the same turn is also counted."""
    result = run(
        _repeating([ModelResponse(content=_FINISH_MARKUP)]),
        Task.new(str(tmp_path), "answer"),
        max_steps=10,
    )

    assert result.status == OK
    assert result.summary == "The answer is 42."
    assert result.finish_recovered == "literal-markup"
    assert result.stats.counts["markup_tool_calls"] == 1


def test_markup_naming_a_real_tool_never_runs_it(tmp_path: Path) -> None:
    """AC3: a COUNT only — markup is never converted into a tool call."""
    victim = tmp_path / "written-by-markup.txt"
    markup = (
        "<tool_call>\n"
        "<function=write_file>\n"
        f"<parameter=path>\n{victim.name}\n</parameter>\n"
        "<parameter=content>\nowned\n</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )
    result = run(
        _repeating([ModelResponse(content=markup)]),
        Task.new(str(tmp_path), "write the file"),
        max_steps=10,
    )

    assert result.stats.counts["markup_tool_calls"] >= 1
    # Counted, never executed: no step ran, no file appeared, nothing changed.
    assert not victim.exists()
    assert result.stats.tool_counts == {}
    assert result.steps == []
    assert result.stats.files_changed == 0


def test_a_run_without_markup_keeps_the_counter_off_the_block(tmp_path: Path) -> None:
    """Omit-when-zero: an ordinary prose run carries no ``markup_tool_calls``."""
    result = run(
        _repeating([ModelResponse(content="Let me check the files:")]),
        Task.new(str(tmp_path), "explore"),
        max_steps=10,
    )
    assert "markup_tool_calls" not in result.stats.counts


def test_a_mock_run_stats_block_is_unchanged(tmp_path: Path) -> None:
    """All-engines byte-identity: a ``mock`` run that sees no markup emits no counts."""
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    result = MockEngine().work(
        Task.new(str(tmp_path), "read a.txt", engine="mock"), EngineConfig.resolve()
    )
    assert result.status == OK
    assert "counts" not in result.to_dict()["stats"]

"""Forced-synthesis output can itself be literal tool-markup (#264).

The t5 literal-markup recovery (``_parse_literal_finish``) re-parses a *finish*
emitted as markup; it did not cover the case where the **forced-synthesis
turn's own text** is markup — that text was used verbatim as the summary, so
the caller got an honest ``incomplete`` with a garbled deliverable (live: work
item 55859cb1d605). The guard: detect the markup shape, retry ONCE with an
explicit plain-prose instruction, salvage the prose prefix otherwise, and fall
through to the next ``_resolve_terminal_summary`` rung when nothing survives.
Runtime-owned (all-engines): exercised through ``loop.run`` with a scripted
complete fn, no backend involved.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import NO_RESULT_PRODUCED, Task
from colleague.loop import (
    _MARKUP_SYNTHESIS_PROMPT,
    ModelResponse,
    ToolCall,
    _strip_tool_markup,
    run,
)

# The live 55859cb1d605 shape: a prose lead-in, then literal markup.
_MARKUP_TAIL = (
    "I'll check what files exist and their contents, then fix any issues.\n\n"
    '<tool_call>="run_command"\n'
    '<parameter="command":\n'
    "find . -name '*.py' -type f | sort\n"
    "</parameter>"
)


# ---------------------------------------------------------------------------
# _strip_tool_markup unit behavior
# ---------------------------------------------------------------------------


def test_strip_cuts_at_line_anchored_marker() -> None:
    assert (
        _strip_tool_markup(_MARKUP_TAIL)
        == "I'll check what files exist and their contents, then fix any issues."
    )


def test_strip_ignores_mid_sentence_mentions() -> None:
    """Prose *about* markup is not markup — only a line-anchored marker cuts."""
    prose = (
        "The loop guards tokens like <parameter=...> and <tool_call> inside "
        "prose without truncating the answer."
    )
    assert _strip_tool_markup(prose) == prose


def test_strip_plain_prose_is_identity() -> None:
    assert _strip_tool_markup("A clean answer.\nSecond line.") == ("A clean answer.\nSecond line.")


# ---------------------------------------------------------------------------
# End-to-end through the loop
# ---------------------------------------------------------------------------


def test_markup_synthesis_retries_to_clean_prose(tmp_path: Path) -> None:
    """First synthesis output is markup → ONE plain-prose retry supplies the
    summary and the artifact records the recovery honestly."""
    turn = {"n": 0}

    def complete(messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] <= 2:  # burn the 2-step budget
            return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])
        if turn["n"] == 3:  # forced synthesis → markup
            return ModelResponse(content=_MARKUP_TAIL)
        # the plain-prose retry
        assert messages[-1]["content"] == _MARKUP_SYNTHESIS_PROMPT
        return ModelResponse(
            content="The repo holds three Python files; the failing test is fixed."
        )

    result = run(complete, Task.new(str(tmp_path), "markup synth"), max_steps=2)

    assert result.summary == "The repo holds three Python files; the failing test is fixed."
    assert result.finish_recovered == "markup-synthesis"
    assert "<tool_call" not in result.summary


def test_markup_synthesis_never_ships_markup(tmp_path: Path) -> None:
    """Markup on the synthesis turn AND on the retry, with no substantive prose
    prefix → the summary falls through to the sentinel, never the markup."""
    pure_markup = '<tool_call>="run_command"\n<parameter="command":\nls\n</parameter>'
    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] <= 2:  # burn the 2-step budget
            return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])
        return ModelResponse(content=pure_markup)  # synthesis AND retry both markup

    result = run(complete, Task.new(str(tmp_path), "stubborn markup"), max_steps=2)

    assert "<tool_call" not in result.summary
    assert "<parameter=" not in result.summary
    assert result.summary == NO_RESULT_PRODUCED


def test_markup_with_substantive_prefix_salvages_prose(tmp_path: Path) -> None:
    """Retry keeps emitting markup, but the first output's prose prefix is
    substantive (>= 80 chars) → the prefix ships, not the markup."""
    long_lead = (
        "The investigation found that the config loader silently ignores a "
        "malformed JSON file, and the fallback default is applied in every "
        "such run across both engines."
    )
    contaminated = (
        long_lead + '\n<tool_call>="run_command"\n<parameter="command":\nls\n</parameter>'
    )
    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] <= 2:
            return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])
        return ModelResponse(content=contaminated)  # synthesis AND retry both dirty

    result = run(complete, Task.new(str(tmp_path), "salvage prefix"), max_steps=2)

    assert result.summary == long_lead
    assert result.finish_recovered == "markup-synthesis"


def test_clean_synthesis_is_untouched(tmp_path: Path) -> None:
    """A clean synthesis answer flows through verbatim — no retry, no marker."""
    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] <= 2:
            return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])
        return ModelResponse(content="Everything read; here is the complete answer.")

    result = run(complete, Task.new(str(tmp_path), "clean synth"), max_steps=2)

    assert result.summary == "Everything read; here is the complete answer."
    assert result.finish_recovered is None

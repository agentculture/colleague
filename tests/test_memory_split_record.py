"""Tests for the retroactive split-next-time record — plan t8, spec c15/h10.

A run ending with a too-hard/too-long signal (the #313 ``budget-exhausted``
incompletion reason, ``step_count >= max_steps``, or wall-clock duration past
``config.too_long_min`` minutes) writes ONE extra 'split-next-time' eidetic
record via colleague/memory.py's remember-after lane. A later recall-before
that surfaces the record renders its recommendation FIRST, ahead of the
ordinary prior-lessons block; a recall with no such record is unaffected.

Covers:
- should_record_split: true for each of the three signals, false otherwise.
- build_split_record: shape (kind, slug, reason, steps, duration, child hint)
  + text embedding colleague.autosplit.build_split_recommendation's message.
- maybe_remember_split: writes exactly one record when the predicate is true,
  none when false — the sole caller of build_split_record/should_record_split.
- build_recall_block: renders a recalled split-next-time record first; byte-
  identical without one.
- a grep guard: colleague/loop.py contains no call to build_split_record or
  should_record_split (only memory.py's after-run lane calls them — the
  write path is never reachable from loop.py's step handling).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from colleague.contract import IncompletionRecord, TaskResult, WorkStats
from colleague.incompletion import REASON_BUDGET_EXHAUSTED
from colleague.memory import (
    SPLIT_RECORD_KIND,
    build_recall_block,
    build_split_record,
    maybe_remember_split,
    should_record_split,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config(**kw):
    base = dict(max_steps=20, too_long_min=20)
    base.update(kw)
    return SimpleNamespace(**base)


def _result(**kw):
    base = dict(task_id="t8-split", status="incomplete", summary="")
    base.update(kw)
    return TaskResult(**base)


# ── should_record_split ──────────────────────────────────────────────────


def test_should_record_split_true_on_budget_exhausted_incompletion() -> None:
    result = _result(
        incompletion=IncompletionRecord(
            reason=REASON_BUDGET_EXHAUSTED,
            evidence="stopped at max steps",
            recommendation="split the task",
        ),
        stats=WorkStats(step_count=5),
    )
    assert should_record_split(result, _config(), duration_seconds=1.0) is True


def test_should_record_split_true_on_steps_at_max() -> None:
    result = _result(stats=WorkStats(step_count=20))
    assert should_record_split(result, _config(max_steps=20), duration_seconds=1.0) is True


def test_should_record_split_true_on_wall_clock_over_too_long_min() -> None:
    result = _result(stats=WorkStats(step_count=3))
    config = _config(max_steps=50, too_long_min=1)
    assert should_record_split(result, config, duration_seconds=61.0) is True


def test_should_record_split_false_when_no_signal_present() -> None:
    result = _result(status="ok", stats=WorkStats(step_count=3))
    config = _config(max_steps=50, too_long_min=20)
    assert should_record_split(result, config, duration_seconds=5.0) is False


def test_should_record_split_false_on_ok_short_run() -> None:
    result = _result(
        status="ok",
        summary="did the thing",
        stats=WorkStats(step_count=4),
    )
    config = _config(max_steps=50, too_long_min=20)
    assert should_record_split(result, config, duration_seconds=30.0) is False


def test_should_record_split_ignores_non_budget_incompletion_reason() -> None:
    result = _result(
        incompletion=IncompletionRecord(
            reason="write-no-changes",
            evidence="0 files",
            recommendation="re-scope",
        ),
        stats=WorkStats(step_count=3),
    )
    config = _config(max_steps=50, too_long_min=20)
    assert should_record_split(result, config, duration_seconds=5.0) is False


def test_should_record_split_wall_clock_exactly_at_boundary_is_false() -> None:
    # Strictly greater-than, not >=: the boundary itself does not fire.
    result = _result(status="ok", stats=WorkStats(step_count=1))
    config = _config(max_steps=50, too_long_min=1)
    assert should_record_split(result, config, duration_seconds=60.0) is False


# ── build_split_record ───────────────────────────────────────────────────


def test_build_split_record_shape() -> None:
    record = build_split_record(
        "t8-split",
        "fix-the-widget",
        reason=REASON_BUDGET_EXHAUSTED,
        steps=20,
        duration_seconds=123.4,
        child_count=3,
        request_excerpt="fix the widget so it spins",
    )
    assert record["id"] == "split-next-time-t8-split"
    meta = record["metadata"]
    assert meta["kind"] == SPLIT_RECORD_KIND
    assert meta["task_slug"] == "fix-the-widget"
    assert meta["reason"] == REASON_BUDGET_EXHAUSTED
    assert meta["steps"] == 20
    assert meta["duration_seconds"] == 123.4
    assert meta["child_count_hint"] == 3


def test_build_split_record_text_embeds_autosplit_recommendation() -> None:
    from colleague.autosplit import build_split_recommendation

    expected_body = build_split_recommendation(per_child_budget_tokens=8000, max_children=4)
    record = build_split_record(
        "t8-split",
        "fix-the-widget",
        reason="max-steps-reached",
        steps=50,
        duration_seconds=10.0,
        child_count=4,
        per_child_budget_tokens=8000,
    )
    assert expected_body in record["text"]
    assert "subagents" in record["text"]
    assert "fix-the-widget" in record["text"]
    assert "max-steps-reached" in record["text"]


def test_build_split_record_child_count_floors_at_one() -> None:
    record = build_split_record(
        "t8-split",
        "slug",
        reason="too-long",
        steps=1,
        duration_seconds=1.0,
        child_count=0,
    )
    assert record["metadata"]["child_count_hint"] == 1


# ── maybe_remember_split ─────────────────────────────────────────────────


def test_maybe_remember_split_writes_exactly_one_record_when_signal_present() -> None:
    result = _result(stats=WorkStats(step_count=20))
    config = _config(max_steps=20, too_long_min=20)
    with patch("colleague.memory.remember", return_value=True) as mock_remember:
        recorded = maybe_remember_split(
            "/repo",
            "t8-split",
            "slug",
            result,
            config,
            duration_seconds=5.0,
        )
    assert recorded is True
    assert mock_remember.call_count == 1
    written_record = mock_remember.call_args.args[1]
    assert written_record["metadata"]["kind"] == SPLIT_RECORD_KIND


def test_maybe_remember_split_writes_nothing_when_signal_absent() -> None:
    result = _result(status="ok", stats=WorkStats(step_count=3))
    config = _config(max_steps=50, too_long_min=20)
    with patch("colleague.memory.remember", return_value=True) as mock_remember:
        recorded = maybe_remember_split(
            "/repo",
            "t8-split",
            "slug",
            result,
            config,
            duration_seconds=5.0,
        )
    assert recorded is False
    mock_remember.assert_not_called()


# ── build_recall_block rendering ─────────────────────────────────────────


def test_recall_block_renders_split_record_first() -> None:
    split_record = build_split_record(
        "prior-task",
        "slug",
        reason=REASON_BUDGET_EXHAUSTED,
        steps=20,
        duration_seconds=42.0,
        child_count=3,
    )
    lesson_record = {"id": "work-lesson-x", "text": "some prior lesson", "metadata": {}}
    block = build_recall_block([lesson_record, split_record])
    assert block.startswith("Split recommendation from a prior attempt:")
    split_idx = block.index("Split recommendation from a prior attempt:")
    lesson_idx = block.index("some prior lesson")
    assert split_idx < lesson_idx


def test_recall_block_byte_identical_without_split_record() -> None:
    lesson_record = {"id": "work-lesson-x", "text": "some prior lesson", "metadata": {}}
    with_only_lesson = build_recall_block([lesson_record])
    assert "Split recommendation" not in with_only_lesson
    assert with_only_lesson == (
        "[memory] Prior lessons recalled from this repo's memory store (advisory):\n"
        "- some prior lesson"
    )


def test_recall_block_empty_without_any_records() -> None:
    assert build_recall_block([]) == ""


def test_recall_block_split_record_alone_renders() -> None:
    split_record = build_split_record(
        "prior-task",
        "slug",
        reason=REASON_BUDGET_EXHAUSTED,
        steps=20,
        duration_seconds=42.0,
        child_count=3,
    )
    block = build_recall_block([split_record])
    assert block.startswith("Split recommendation from a prior attempt:")
    assert "[memory] Prior lessons" not in block


# ── grep guard: loop.py never calls these two functions directly ─────────


def test_loop_never_calls_split_record_builders_directly() -> None:
    """The write path for the split-next-time record lives ONLY in
    colleague/memory.py's after-run lane (``maybe_remember_split``) — never
    reachable from colleague/loop.py, mid-run or otherwise."""
    loop_src = (REPO_ROOT / "colleague" / "loop.py").read_text(encoding="utf-8")
    assert "build_split_record" not in loop_src
    assert "should_record_split" not in loop_src

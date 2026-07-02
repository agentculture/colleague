"""Delivered-vs-dropped verification (t9, decision c25 — spec c15/h13/h5).

After the first media-bearing completion the runtime compares the server's
reported ``prompt_tokens`` against a locally-counted text-only baseline: an
image contributes ~hundreds of prompt tokens, a silent drop contributes ~0 —
the exact signal the live Gemma4 probe exposed (2026-07-02: audio 200-OK'd
with ~0 tokens contributed). Zero extra model turns. Recorded on the
omit-when-None ``TaskResult.media`` (never the word "understood") + a stderr
warning on a drop.
"""

from __future__ import annotations

from pathlib import Path

from colleague import media
from colleague.contract import OK, Task, TaskResult
from colleague.loop import (
    _MEDIA_DELIVERY_FLOOR,
    ContextControls,
    ModelResponse,
    ToolCall,
    _classify_media_delivery,
    run,
)

_TEXT_ONLY = 100  # the fake counter's constant text baseline


def _png(root: Path, name: str = "shot.png") -> str:
    path = root / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return str(path)


def _task_with_image(tmp_path: Path) -> Task:
    attachment = media.validate_attachment(_png(tmp_path))
    return Task.new(str(tmp_path), "what color is this?", attachments=[attachment])


def _controls() -> ContextControls:
    return ContextControls(count_tokens=lambda msgs: _TEXT_ONLY)


def _finish_with_usage(prompt_tokens: int):
    def complete(messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            tool_calls=[ToolCall("1", "finish", {"summary": "done"})],
            prompt_tokens=prompt_tokens,
            completion_tokens=5,
        )

    return complete


# ---------------------------------------------------------------------------
# The pure classifier
# ---------------------------------------------------------------------------


def test_classifier_replays_the_live_silent_drop() -> None:
    """The reproduced probe: 200 OK, prompt_tokens ~= the text-only estimate."""
    assert _classify_media_delivery(_TEXT_ONLY + 3, _TEXT_ONLY, 1) == "dropped"


def test_classifier_delivered_at_the_floor_boundary() -> None:
    at_floor = _TEXT_ONLY + _MEDIA_DELIVERY_FLOOR
    assert _classify_media_delivery(at_floor, _TEXT_ONLY, 1) == "delivered"
    assert _classify_media_delivery(at_floor - 1, _TEXT_ONLY, 1) == "dropped"


def test_classifier_tiny_image_cannot_false_positive() -> None:
    """A genuinely tiny image still contributes one full tile (~260 tokens),
    comfortably above the floor — a real delivery never classifies dropped."""
    one_tile = _TEXT_ONLY + media.IMAGE_TOKEN_ESTIMATE
    assert _classify_media_delivery(one_tile, _TEXT_ONLY, 1) == "delivered"


def test_classifier_no_usage_is_unknown_not_dropped() -> None:
    assert _classify_media_delivery(0, _TEXT_ONLY, 1) == "unknown"


def test_classifier_scales_floor_per_part() -> None:
    two_parts_low = _TEXT_ONLY + _MEDIA_DELIVERY_FLOOR  # only one part's worth
    assert _classify_media_delivery(two_parts_low, _TEXT_ONLY, 2) == "dropped"
    two_parts_full = _TEXT_ONLY + 2 * media.IMAGE_TOKEN_ESTIMATE
    assert _classify_media_delivery(two_parts_full, _TEXT_ONLY, 2) == "delivered"


# ---------------------------------------------------------------------------
# The loop records the verdict
# ---------------------------------------------------------------------------


def test_run_records_dropped_and_warns(tmp_path: Path, capsys) -> None:
    task = _task_with_image(tmp_path)
    result = run(_finish_with_usage(_TEXT_ONLY + 3), task, max_steps=3, context=_controls())
    assert result.status == OK
    assert result.media is not None
    entries = result.media["attachments"]
    assert len(entries) == 1
    assert entries[0]["status"] == "dropped"
    assert entries[0]["path"] == task.attachments[0]["path"]
    assert "NOT delivered" in capsys.readouterr().err


def test_run_records_delivered_silently(tmp_path: Path, capsys) -> None:
    result = run(
        _finish_with_usage(_TEXT_ONLY + media.IMAGE_TOKEN_ESTIMATE + 50),
        _task_with_image(tmp_path),
        max_steps=3,
        context=_controls(),
    )
    assert result.status == OK
    assert result.media["attachments"][0]["status"] == "delivered"
    assert "NOT delivered" not in capsys.readouterr().err


def test_run_without_attachments_has_no_media_key(tmp_path: Path) -> None:
    result = run(
        _finish_with_usage(500),
        Task.new(str(tmp_path), "no media"),
        max_steps=3,
        context=_controls(),
    )
    assert result.status == OK
    assert result.media is None
    assert "media" not in result.to_dict()


def test_mock_scripted_run_without_usage_is_unknown(tmp_path: Path) -> None:
    """A backend that reports no usage yields 'unknown' — a drop is never
    claimed without evidence."""
    result = run(
        _finish_with_usage(0), _task_with_image(tmp_path), max_steps=3, context=_controls()
    )
    assert result.status == OK
    assert result.media["attachments"][0]["status"] == "unknown"


# ---------------------------------------------------------------------------
# Artifact round-trip
# ---------------------------------------------------------------------------


def test_media_round_trips_through_the_artifact(tmp_path: Path) -> None:
    result = run(
        _finish_with_usage(_TEXT_ONLY + 3),
        _task_with_image(tmp_path),
        max_steps=3,
        context=_controls(),
    )
    data = result.to_dict()
    assert "media" in data
    assert data["media"]["attachments"][0]["status"] == "dropped"
    reloaded = TaskResult.from_dict(data)
    assert reloaded.media == result.media


def test_delivery_never_says_understood(tmp_path: Path) -> None:
    """Decision c25: the record's vocabulary is delivered/dropped/unknown."""
    result = run(
        _finish_with_usage(_TEXT_ONLY + 999),
        _task_with_image(tmp_path),
        max_steps=3,
        context=_controls(),
    )
    assert "understood" not in str(result.to_dict().get("media"))


# ---------------------------------------------------------------------------
# Media-rejection degradation (spec c7: the text-only-main half)
# ---------------------------------------------------------------------------

# Verbatim from the live probe 2026-07-02 against the served text-only 27B.
_LIVE_400 = (
    'HTTP Error 400: Bad Request: {"error":{"message":"At most 0 image(s) '
    'may be provided in one prompt. (parameter=image)"}}'
)


def test_media_rejection_classifier() -> None:
    from colleague.context import is_media_rejection

    assert is_media_rejection(_LIVE_400)
    assert is_media_rejection("the model does not support image input")
    assert not is_media_rejection("maximum context length exceeded")
    assert not is_media_rejection("request timed out")


def test_rejecting_endpoint_degrades_to_text_only(tmp_path: Path, capsys) -> None:
    """The live scenario: --attach against a text-only main without a bridge.

    First call raises the verbatim 400; the loop flattens the parts, retries
    text-only, and the run COMPLETES with media recorded dropped — never a
    hard-failed run for an attachment the model cannot take.
    """
    attempts: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        attempts.append([dict(m) for m in messages])
        if any(isinstance(m.get("content"), list) for m in messages):
            raise RuntimeError(_LIVE_400)
        return ModelResponse(
            tool_calls=[ToolCall("1", "finish", {"summary": "done"})],
            prompt_tokens=_TEXT_ONLY + 2,
            completion_tokens=5,
        )

    result = run(complete, _task_with_image(tmp_path), max_steps=3, context=_controls())
    assert result.status == OK
    assert len(attempts) == 2, "exactly one flatten-and-retry"
    assert all(isinstance(m.get("content"), str) for m in attempts[1] if "content" in m)
    assert "[image attachment]" in attempts[1][1]["content"]
    assert result.media["attachments"][0]["status"] == "dropped"
    assert "rejected media content parts" in capsys.readouterr().err

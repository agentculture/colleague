"""Loop wiring for initial media parts (t3, spec c10/h8).

When ``task.attachments`` is non-empty the runtime builds the initial user
message as OpenAI content parts (one text part + one part per attachment) via
:mod:`colleague.media`; with no attachments the message stays a plain string —
the byte-identical baseline every existing caller relies on (h8: downstream
string-assuming code must never meet a surprise list).

Runtime-owned (all-engines): the initial message is composed in ``loop.run``
before any backend sees it, so one pin here covers mock and vllm-openai alike
(the engine-side wire pass-through is t4's ``tests/test_engine_parts.py``).
"""

from __future__ import annotations

from pathlib import Path

from colleague import media
from colleague.contract import OK, Task
from colleague.loop import (
    ModelResponse,
    ToolCall,
    _build_initial_content,
    _build_user_message,
    run,
)


def _png(tmp_path: Path, name: str = "shot.png") -> str:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-image")
    return str(path)


# ---------------------------------------------------------------------------
# _build_initial_content unit behavior
# ---------------------------------------------------------------------------


def test_no_attachments_is_the_plain_string(tmp_path: Path) -> None:
    """Attachment-less tasks keep a str content — NOT a one-part list (h8)."""
    task = Task.new(str(tmp_path), "fix the bug", context="ctx", constraints=["c"])
    content = _build_initial_content(task)
    assert isinstance(content, str)
    assert content == _build_user_message(task)


def test_attachment_builds_text_plus_image_parts(tmp_path: Path) -> None:
    """One image attachment → [text part, image_url part], text first."""
    attachment = media.validate_attachment(_png(tmp_path))
    task = Task.new(str(tmp_path), "what color is this?", attachments=[attachment])
    content = _build_initial_content(task)
    assert isinstance(content, list)
    assert len(content) == 2
    assert content[0] == {"type": "text", "text": _build_user_message(task)}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_attachments_keep_order(tmp_path: Path) -> None:
    first = media.validate_attachment(_png(tmp_path, "a.png"))
    second = media.validate_attachment(_png(tmp_path, "b.png"))
    task = Task.new(str(tmp_path), "compare", attachments=[first, second])
    content = _build_initial_content(task)
    assert [p["type"] for p in content] == ["text", "image_url", "image_url"]


def test_unreadable_attachment_degrades_to_placeholder(tmp_path: Path) -> None:
    """A file that vanished after validation degrades to a text note, no raise."""
    path = _png(tmp_path, "gone.png")
    attachment = media.validate_attachment(path)
    Path(path).unlink()
    task = Task.new(str(tmp_path), "look", attachments=[attachment])
    content = _build_initial_content(task)
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "text"
    assert "gone.png" in content[1]["text"]
    assert "unreadable" in content[1]["text"]


# ---------------------------------------------------------------------------
# The real path: loop.run composes the first user message
# ---------------------------------------------------------------------------


def _capturing_complete(seen: list) -> object:
    def complete(messages: list[dict]) -> ModelResponse:
        if not seen:
            seen.append([dict(m) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    return complete


def test_run_first_user_message_is_parts_with_attachment(tmp_path: Path) -> None:
    attachment = media.validate_attachment(_png(tmp_path))
    task = Task.new(str(tmp_path), "describe the image", attachments=[attachment])
    seen: list = []
    result = run(_capturing_complete(seen), task, max_steps=2)
    assert result.status == OK
    first_user = seen[0][1]
    assert first_user["role"] == "user"
    assert isinstance(first_user["content"], list)
    assert first_user["content"][1]["type"] == "image_url"


def test_run_first_user_message_stays_str_without_attachment(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "no media here")
    seen: list = []
    result = run(_capturing_complete(seen), task, max_steps=2)
    assert result.status == OK
    first_user = seen[0][1]
    assert first_user["role"] == "user"
    assert isinstance(first_user["content"], str)

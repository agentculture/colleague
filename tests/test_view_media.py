"""view_media loop tool (t5, spec c12/h10).

A read-only tool loading an image file from the repo into the conversation as
a content part mid-work — the media sibling of ``read_file``. Repo-confined
via the same ``_safe_path`` check, size-capped, images-only, curated into the
read-only roles (pure read). The loop folds a media-carrying
:class:`~colleague.tools.ToolOutcome` into a follow-up user message holding
the content part (tool-message content stays a plain string — the wire-safe
convention every OpenAI-compatible server accepts).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.contract import OK, Task
from colleague.loop import ModelResponse, ToolCall, run
from colleague.roles import BUILTIN_ROLES
from colleague.tools import MAX_MEDIA_BYTES, SCHEMAS, ToolError, ToolExecutor


def _png(root: Path, name: str = "img.png", size: int = 64) -> Path:
    path = root / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * size)
    return path


# ---------------------------------------------------------------------------
# Schema + role curation
# ---------------------------------------------------------------------------


def test_schema_registered() -> None:
    assert "view_media" in {s["function"]["name"] for s in SCHEMAS}


def test_readonly_roles_include_view_media() -> None:
    """Pure read: every read-only built-in role may view repo images."""
    for role_name in ("explorer", "planner", "reviewer", "validator"):
        assert "view_media" in BUILTIN_ROLES[role_name].tool_allowlist


# ---------------------------------------------------------------------------
# Executor behavior
# ---------------------------------------------------------------------------


def test_loads_repo_image_as_part(tmp_path: Path) -> None:
    _png(tmp_path)
    ex = ToolExecutor(tmp_path)
    outcome = ex.execute("view_media", {"path": "img.png"})
    assert outcome.media_part is not None
    assert outcome.media_part["type"] == "image_url"
    assert outcome.media_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert "img.png" in outcome.result
    assert outcome.changed_file is None


def test_refuses_path_outside_repo(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    with pytest.raises(ToolError, match="escapes the repo root"):
        ex.execute("view_media", {"path": "../outside.png"})


def test_refuses_oversize_file_naming_the_cap(tmp_path: Path) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(b"\x00" * (MAX_MEDIA_BYTES + 1))
    ex = ToolExecutor(tmp_path)
    with pytest.raises(ToolError, match=str(MAX_MEDIA_BYTES)):
        ex.execute("view_media", {"path": "big.png"})


def test_refuses_non_image(tmp_path: Path) -> None:
    (tmp_path / "note.wav").write_bytes(b"RIFFxxxx")
    ex = ToolExecutor(tmp_path)
    with pytest.raises(ToolError, match="image"):
        ex.execute("view_media", {"path": "note.wav"})


def test_refuses_unknown_extension(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hi")
    ex = ToolExecutor(tmp_path)
    with pytest.raises(ToolError):
        ex.execute("view_media", {"path": "notes.txt"})


def test_missing_file_is_a_clean_error(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    with pytest.raises(ToolError):
        ex.execute("view_media", {"path": "ghost.png"})


def test_withholding_role_refuses_even_a_hallucinated_call(tmp_path: Path) -> None:
    _png(tmp_path)
    ex = ToolExecutor(tmp_path, allowlist=("read_file", "finish"))
    with pytest.raises(ToolError, match="not allowed"):
        ex.execute("view_media", {"path": "img.png"})


# ---------------------------------------------------------------------------
# Loop fold: the part reaches the next model turn as a user parts message
# ---------------------------------------------------------------------------


def test_loop_folds_media_part_into_next_turn(tmp_path: Path) -> None:
    _png(tmp_path)
    seen: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append([dict(m) for m in messages])
        if len(seen) == 1:
            return ModelResponse(tool_calls=[ToolCall("1", "view_media", {"path": "img.png"})])
        return ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "saw it"})])

    result = run(complete, Task.new(str(tmp_path), "look at img.png"), max_steps=4)
    assert result.status == OK

    second_turn = seen[1]
    tool_msgs = [m for m in second_turn if m.get("role") == "tool"]
    assert tool_msgs, "the view_media tool result message must be present"
    assert all(isinstance(m["content"], str) for m in tool_msgs)

    parts_msgs = [
        m for m in second_turn if m.get("role") == "user" and isinstance(m.get("content"), list)
    ]
    assert parts_msgs, "the folded parts user message must be present"
    part_types = [p["type"] for p in parts_msgs[-1]["content"]]
    assert "image_url" in part_types


def test_loop_without_view_media_has_no_parts_messages(tmp_path: Path) -> None:
    """Baseline: a run that never calls view_media sees only string content."""
    seen: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append([dict(m) for m in messages])
        if len(seen) == 1:
            return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])
        return ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})])

    result = run(complete, Task.new(str(tmp_path), "no media"), max_steps=4)
    assert result.status == OK
    assert all(isinstance(m["content"], str) for m in seen[1] if "content" in m)

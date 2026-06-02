"""Always-on per-drive statistics (DriveStats) — contract, loop, engines (t1/t2/t3/t5).

Proves the ROI-stats feature end to end without a network: the contract
round-trips, the loop populates timing / tool-counts / bytes / reasoning sizes,
the vLLM parser captures the model-gear ``message.reasoning`` (previously
discarded) while taking tokens verbatim from ``usage``, and the executor sums
exact UTF-8 bytes written.
"""

from __future__ import annotations

from pathlib import Path

from colleague import registry
from colleague.config import EngineConfig
from colleague.contract import OK, DriveStats, Task, TaskResult
from colleague.engines import vllm_openai
from colleague.engines.mock import OUTPUT_FILE
from colleague.tools import ToolExecutor

# --- t1: contract round-trip + back-compat ---------------------------------


def test_drivestats_round_trips() -> None:
    stats = DriveStats(
        request="do the thing",
        started_at="2026-05-31T00:00:00+00:00",
        duration_seconds=1.25,
        model_turns=3,
        step_count=4,
        tool_counts={"write_file": 2, "finish": 1},
        files_changed=2,
        bytes_written=512,
        reasoning_chars=900,
        reasoning_bytes=900,
        answer_chars=10,
        answer_bytes=12,
    )
    assert DriveStats.from_dict(stats.to_dict()) == stats


def test_taskresult_always_emits_stats_and_round_trips() -> None:
    result = TaskResult(task_id="t1", status=OK)
    d = result.to_dict()
    # Always-on: the stats key is present even on a bare result (not omit-when-empty).
    assert "stats" in d
    assert TaskResult.from_dict(d) == result


def test_taskresult_from_dict_tolerates_missing_stats_block() -> None:
    """A pre-feature artifact (no 'stats' key) still loads — back-compat."""
    legacy = {
        "task_id": "old1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "artifacts_path": None,
        "error": None,
        "branch": None,
        "pr_url": None,
        "hook_firings": [],
        "command": None,
    }
    loaded = TaskResult.from_dict(legacy)
    assert loaded.stats == DriveStats()  # defaulted, not crashed


# --- t2: vLLM captures message.reasoning; tokens verbatim from usage --------


def _model_gear_shaped_response(reasoning: str, content: str) -> dict:
    """An OpenAI response shaped like the live model-gear server: a separate
    ``message.reasoning`` field and a ``usage`` WITHOUT completion_tokens_details."""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content, "reasoning": reasoning},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 22, "completion_tokens": 309, "total_tokens": 331},
    }


def test_vllm_parse_captures_reasoning_and_exact_tokens() -> None:
    reasoning = "Here's a thinking process: 2+2 is 4."
    content = "\n\nFour"
    resp = vllm_openai._parse_response(_model_gear_shaped_response(reasoning, content))
    assert resp.reasoning == reasoning
    assert resp.content == content
    # Tokens are taken EXACTLY from usage — never estimated.
    assert resp.prompt_tokens == 22
    assert resp.completion_tokens == 309


def test_vllm_parse_supports_reasoning_content_alias() -> None:
    """Some servers name the field reasoning_content; both are honored."""
    data = {
        "choices": [{"message": {"content": "ok", "reasoning_content": "thinking"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    resp = vllm_openai._parse_response(data)
    assert resp.reasoning == "thinking"


def test_vllm_parse_no_reasoning_field_is_empty() -> None:
    data = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    resp = vllm_openai._parse_response(data)
    assert resp.reasoning == ""


# --- t3: executor accumulates exact UTF-8 bytes written --------------------


def test_executor_accumulates_utf8_bytes_written(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    assert ex.bytes_written == 0
    ex.execute("write_file", {"path": "a.txt", "content": "abc"})
    assert ex.bytes_written == 3
    # Multibyte: a 2-byte UTF-8 char counts as 2 bytes, not 1 char.
    ex.execute("write_file", {"path": "b.txt", "content": "é"})  # 2 UTF-8 bytes
    assert ex.bytes_written == 5
    # Non-write tools leave the counter unchanged.
    ex.execute("list_dir", {"path": "."})
    assert ex.bytes_written == 5


def test_bytes_written_matches_on_disk_size_no_newline_translation(tmp_path: Path) -> None:
    """bytes_written must equal the actual on-disk byte count (Qodo: no CRLF
    translation). With newline="" the file bytes == len(content.encode('utf-8'))
    on every platform, so the counter is exact."""
    ex = ToolExecutor(tmp_path)
    content = "line1\nline2\nline3\n"  # 3 LFs — default newline=None would inflate on Windows
    ex.execute("write_file", {"path": "multi.txt", "content": content})
    on_disk = (tmp_path / "multi.txt").read_bytes()
    assert ex.bytes_written == len(content.encode("utf-8"))
    assert ex.bytes_written == len(on_disk)  # exact match to what's on disk
    assert b"\r\n" not in on_disk  # no newline translation


# --- t5: the loop populates DriveStats on a real (mock) drive ---------------


def test_mock_drive_populates_drive_stats(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    result = registry.load("mock").drive(
        Task.new(str(repo), "build a thing"), EngineConfig.resolve()
    )
    stats = result.stats

    assert result.status == OK
    assert stats.request == "build a thing"
    assert stats.started_at  # ISO timestamp present
    assert stats.duration_seconds >= 0.0
    assert stats.model_turns == 2  # the mock's two scripted turns
    assert stats.step_count == len(result.steps)
    # tool_counts aggregated from the steps (write_file then finish).
    assert stats.tool_counts.get("write_file") == 1
    assert stats.tool_counts.get("finish") == 1
    assert stats.files_changed == 1
    # bytes_written == the on-disk UTF-8 size of the marker file the mock wrote.
    assert stats.bytes_written == (repo / OUTPUT_FILE).read_bytes().__len__()
    assert stats.bytes_written > 0
    # The mock emits deterministic reasoning + answer text, so both are non-zero.
    assert stats.reasoning_chars > 0
    assert stats.reasoning_bytes >= stats.reasoning_chars
    assert stats.answer_chars > 0

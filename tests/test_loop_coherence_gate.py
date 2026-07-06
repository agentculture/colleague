"""Coherence gate wired into the loop (#294, colleague#291 S3).

Exercises the runtime integration via ``run()`` with a scripted ``complete``
(the ``test_loop_lint_gate.py`` harness): the gate scores changed ``.md``
files after the loop and records ``result.coherence_report`` — advisory,
warn-only, omit-when-None, never blocking. Default (no
``ContextControls.coherence``) is a strict no-op.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run

_PAYLOAD = {"meaning_score": 0.5, "subdimensions": {}, "diagnostics": []}


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


def _fake_coherence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COHERENCE_EMBED_URL", "http://localhost:8001/v1")
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "coherence"
    script.write_text("#!/bin/sh\necho '" + json.dumps(_PAYLOAD) + "'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")


def test_default_run_is_strict_noop(tmp_path: Path, monkeypatch) -> None:
    """Default run() (no ContextControls.coherence) never touches the report."""
    _fake_coherence(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    responses = [_write("notes.md", "# Notes\n"), _finish("done")]
    result = run(scripted(responses), Task.new(str(repo), "write notes"), max_steps=5)
    assert result.status == OK
    assert result.coherence_report is None
    assert "coherence_report" not in result.to_dict()


def test_md_write_records_report_and_never_blocks(tmp_path: Path, monkeypatch) -> None:
    _fake_coherence(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    responses = [_write("notes.md", "# Notes\n"), _finish("done")]
    result = run(
        scripted(responses),
        Task.new(str(repo), "write notes"),
        max_steps=5,
        context=ContextControls(coherence=True),
    )
    assert result.status == OK  # advisory: scoring never flips the status
    assert result.coherence_report is not None
    assert result.coherence_report.status == "scored"
    assert result.coherence_report.files[0]["path"] == "notes.md"
    assert "coherence_report" in result.to_dict()


def test_no_md_change_is_byte_identical(tmp_path: Path, monkeypatch) -> None:
    _fake_coherence(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    responses = [_write("code.py", "x = 1\n"), _finish("done")]
    result = run(
        scripted(responses),
        Task.new(str(repo), "write code"),
        max_steps=5,
        context=ContextControls(coherence=True),
    )
    assert result.coherence_report is None
    assert "coherence_report" not in result.to_dict()


def test_missing_cli_records_skipped_never_blocks(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("COHERENCE_EMBED_URL", "http://localhost:8001/v1")
    responses = [_write("notes.md", "# Notes\n"), _finish("done")]
    result = run(
        scripted(responses),
        Task.new(str(repo), "write notes"),
        max_steps=5,
        context=ContextControls(coherence=True),
    )
    assert result.status == OK
    assert result.coherence_report is not None
    assert result.coherence_report.status == "skipped"


def test_embed_env_reaches_the_gate(tmp_path: Path, monkeypatch) -> None:
    """The lobes-resolved embedder env (t19) rides ContextControls into the report."""
    _fake_coherence(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.delenv("COHERENCE_EMBED_URL", raising=False)
    monkeypatch.delenv("COHERENCE_EMBED_MODEL", raising=False)
    responses = [_write("notes.md", "# Notes\n"), _finish("done")]
    result = run(
        scripted(responses),
        Task.new(str(repo), "write notes"),
        max_steps=5,
        context=ContextControls(
            coherence=True,
            embed_env={
                "COHERENCE_EMBED_URL": "http://localhost:8001/v1",
                "COHERENCE_EMBED_MODEL": "Qwen/Qwen3-Embedding-0.6B",
            },
        ),
    )
    assert result.coherence_report is not None
    assert result.coherence_report.embed_url == "http://localhost:8001/v1"


def test_config_resolution_precedence(tmp_path: Path, monkeypatch) -> None:
    """env COLLEAGUE_COHERENCE > config.json {"coherence"} > default-on (#294)."""
    repo = tmp_path / "cfgrepo"
    (repo / ".colleague").mkdir(parents=True)
    monkeypatch.delenv("COLLEAGUE_COHERENCE", raising=False)
    monkeypatch.delenv("CONVERTIBLE_COHERENCE", raising=False)
    assert EngineConfig.resolve(repo_path=repo, discover_lobes=False).coherence is True
    (repo / ".colleague" / "config.json").write_text('{"coherence": false}')
    assert EngineConfig.resolve(repo_path=repo, discover_lobes=False).coherence is False
    monkeypatch.setenv("COLLEAGUE_COHERENCE", "1")
    assert EngineConfig.resolve(repo_path=repo, discover_lobes=False).coherence is True

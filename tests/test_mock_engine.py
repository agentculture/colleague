"""Mock engine: deterministic, networkless, full-contract (R6, h6)."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from convertible.config import EngineConfig
from convertible.contract import OK, Task
from convertible.engines.mock import OUTPUT_FILE, MockEngine


def test_mock_drives_and_writes_marker(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "set up the project", engine="mock")
    result = MockEngine().drive(task, EngineConfig.resolve())

    assert result.status == OK
    assert result.changed_files == [OUTPUT_FILE]
    assert (tmp_path / OUTPUT_FILE).exists()
    assert "set up the project" in (tmp_path / OUTPUT_FILE).read_text()


def test_mock_is_deterministic(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "same task")
    cfg = EngineConfig.resolve()
    first = MockEngine().drive(task, cfg).to_dict()
    second = MockEngine().drive(task, cfg).to_dict()
    assert first == second


def test_mock_never_touches_the_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_a: object, **_k: object) -> object:
        raise AssertionError("mock engine must not open a network connection")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    result = MockEngine().drive(Task.new(str(tmp_path), "offline"), EngineConfig.resolve())
    assert result.status == OK

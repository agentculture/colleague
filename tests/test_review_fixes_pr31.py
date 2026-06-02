"""Regression tests for the Qodo review findings on PR #31.

Each test pins a fix for one of the five bugs the adversarial review flagged on
the mesh-member integration. Findings 1 and 4 defend the confirmed read-only
honesty condition (h12); 2 defends the loop's never-abort contract; 3 the
clone-cannot-hang robustness bound; 5 identity-resolution correctness.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import colleague.neighbours as nb
from colleague.contract import Task
from colleague.hooks import HookConfig
from colleague.identity import resolve_identity
from colleague.loop import ModelResponse, ToolCall, run
from colleague.neighbours import NeighbourError, NeighbourManager
from colleague.tools import ToolError, ToolExecutor


def _write_neighbours_config(repo: Path, entries: list[dict]) -> None:
    import json

    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "neighbours.json").write_text(json.dumps(entries), encoding="utf-8")


# Finding 1 — clone path escape: a hostile/typo'd name must not escape the clone root.
class TestCloneNameEscape:
    @pytest.mark.parametrize("evil", ["../escape", "a/b", "..", ".", "", "sub/../../x"])
    def test_clone_all_refuses_escaping_names(self, tmp_path: Path, evil: str) -> None:
        _write_neighbours_config(tmp_path, [{"name": evil, "url": "https://example/x.git"}])
        with pytest.raises(NeighbourError):
            NeighbourManager(tmp_path).clone_all()

    def test_absolute_name_refused(self, tmp_path: Path) -> None:
        _write_neighbours_config(tmp_path, [{"name": "/etc/evil", "url": "x"}])
        with pytest.raises(NeighbourError):
            NeighbourManager(tmp_path).clone_all()

    def test_clone_path_refuses_escaping_name(self, tmp_path: Path) -> None:
        _write_neighbours_config(tmp_path, [{"name": "../escape", "url": "x"}])
        with pytest.raises(NeighbourError):
            NeighbourManager(tmp_path).clone_path("../escape")


# Finding 2 — a clone failure at drive start must NOT abort the loop.
class TestCloneFailureNonFatal:
    def test_drive_completes_when_clone_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_neighbours_config(tmp_path, [{"name": "sibling", "url": "https://bad/x.git"}])

        def boom(self):  # noqa: ANN001 - test stub
            raise NeighbourError("simulated clone failure")

        monkeypatch.setattr(NeighbourManager, "clone_all", boom)

        responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])]
        task = Task.new(str(tmp_path), "just finish")
        result = run((lambda r: lambda _m: r[0])(responses), task, max_steps=5, hooks=HookConfig())
        assert result.status == "ok"

    def test_cleanup_failure_does_not_mask_result(self, tmp_path: Path, monkeypatch) -> None:
        def boom(self):  # noqa: ANN001 - test stub
            raise OSError("simulated cleanup failure")

        monkeypatch.setattr(NeighbourManager, "cleanup", boom)
        responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])]
        task = Task.new(str(tmp_path), "just finish")
        result = run((lambda r: lambda _m: r[0])(responses), task, max_steps=5, hooks=HookConfig())
        assert result.status == "ok"


# Finding 3 — git clone/fetch cannot hang forever: a timeout maps to NeighbourError.
class TestGitTimeout:
    def test_clone_timeout_becomes_neighbour_error(self, tmp_path: Path, monkeypatch) -> None:
        _write_neighbours_config(tmp_path, [{"name": "sibling", "url": "https://slow/x.git"}])

        def fake_run(*args, **kwargs):
            assert kwargs.get("timeout") == NeighbourManager._GIT_TIMEOUT_SECONDS
            raise subprocess.TimeoutExpired(cmd="git clone", timeout=kwargs["timeout"])

        monkeypatch.setattr(nb.subprocess, "run", fake_run)
        with pytest.raises(NeighbourError, match="timed out"):
            NeighbourManager(tmp_path).clone_all()


# Finding 4 — write_file must NOT write into a clone (read-only contract, h12).
class TestCloneWriteRefused:
    def test_write_into_clone_refused(self, tmp_path: Path) -> None:
        ex = ToolExecutor(tmp_path)
        with pytest.raises(ToolError, match="read-only"):
            ex.execute(
                "write_file",
                {"path": ".colleague/neighbours/sibling/x.txt", "content": "nope"},
            )

    def test_read_from_clone_still_works(self, tmp_path: Path) -> None:
        clone_file = tmp_path / ".colleague" / "neighbours" / "sibling" / "facts.txt"
        clone_file.parent.mkdir(parents=True, exist_ok=True)
        clone_file.write_text("known content", encoding="utf-8")
        ex = ToolExecutor(tmp_path)
        outcome = ex.execute("read_file", {"path": ".colleague/neighbours/sibling/facts.txt"})
        assert "known content" in outcome.result


# Finding 5 — an indented (nested) nick: must not be misread as the top-level nick.
class TestTopLevelNickOnly:
    def test_indented_nick_not_resolved(self, tmp_path: Path) -> None:
        (tmp_path / "culture.yaml").write_text(
            "agents:\n  - nick: nested-should-not-win\n", encoding="utf-8"
        )
        # No top-level nick and no .colleague identity → None.
        assert resolve_identity(tmp_path, user_home=tmp_path / "no-home") is None

    def test_top_level_nick_resolved(self, tmp_path: Path) -> None:
        (tmp_path / "culture.yaml").write_text(
            "nick: top-level-wins\nagents:\n  - nick: nested\n", encoding="utf-8"
        )
        assert resolve_identity(tmp_path, user_home=tmp_path / "no-home") == "top-level-wins"

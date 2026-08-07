"""Memory failure invariants — plan t19, spec c10/h10/c11/h11.

Two invariants pinned at the loop level:

1. A ``remember`` failure (absent CLI / non-zero exit) still returns the
   work-item result unchanged — the lesson store is best-effort and must
   never mask the deliverable.

2. A ``recall`` failure injects nothing and never raises — advisory context
   only, never a precondition.

These invariants hold for every backend (the all-engines rule) because the
memory wiring lives in the loop, not in any engine module.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from colleague.contract import OK, Task, TaskResult
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_FINISH = ModelResponse(
    tool_calls=[
        ToolCall(
            "f",
            "finish",
            {
                "summary": (
                    "The survey found the adapter seam in alpha.py and the retry loop "
                    "in beta.py; the timeout classification is swallowed in beta.py's "
                    "except clause, which is where the fix belongs."
                )
            },
        )
    ]
)


def scripted(responses: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _fake_eidetic_failing_remember(bin_dir: Path, log: Path) -> None:
    """Install a fake ``eidetic`` that succeeds for recall but fails for
    remember (exit code 1), logging each call."""
    script = bin_dir / "eidetic"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'a').write("
        "json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}) + '\\n')\n"
        "if sys.argv[1] == 'recall':\n"
        "    print('[]')\n"
        "    sys.exit(0)\n"
        "# remember always fails\n"
        "print('store error', file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _fake_eidetic_failing_recall(bin_dir: Path, log: Path) -> None:
    """Install a fake ``eidetic`` that fails for recall (exit code 1) but
    succeeds for remember, logging each call."""
    script = bin_dir / "eidetic"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'a').write("
        "json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}) + '\\n')\n"
        "# recall always fails\n"
        "print('recall error', file=sys.stderr)\n"
        "sys.exit(1)\n"
        "if sys.argv[1] == 'remember':\n"
        "    sys.exit(0)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _fake_eidetic_raises(bin_dir: Path, log: Path) -> None:
    """Install a fake ``eidetic`` that raises an exception on every call."""
    script = bin_dir / "eidetic"
    script.write_text(
        "#!/usr/bin/env python3\n" "import sys\n" "raise RuntimeError('eidetic internal error')\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".eidetic" / "memory").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# Invariant 1: remember failure never masks the work-item result (c10/h10)
# ---------------------------------------------------------------------------


class TestRememberFailureDoesNotMaskResult:
    """A remember failure (non-zero exit) still returns the work-item result
    unchanged — the lesson store is best-effort."""

    def test_remember_nonzero_exit_returns_ok_result(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """When eidetic remember exits non-zero, the run still finishes OK
        and the result is unchanged — only lesson_recorded is False."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_failing_remember(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        # The result is OK — remember failure did not mask it.
        assert result.status == OK
        # The recall succeeded (empty list), so memory field exists.
        assert result.memory is not None
        # But the lesson was NOT recorded because remember failed.
        assert result.memory.get("lesson_recorded") is False

    def test_remember_failure_result_summary_unchanged(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """The finish summary is identical whether remember succeeds or fails —
        the store never touches the deliverable."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_failing_remember(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        # Summary is the one the model produced, untouched.
        assert result.summary == _FINISH.tool_calls[0].arguments["summary"]

    def test_remember_failure_artifact_serializes_cleanly(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """The artifact (to_dict) serializes cleanly even when remember fails —
        no None-poisoning or partial state leaks."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_failing_remember(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        d = result.to_dict()
        # Round-trips cleanly.
        restored = TaskResult.from_dict(d)
        assert restored.status == OK
        assert restored.memory is not None
        assert restored.memory.get("lesson_recorded") is False


# ---------------------------------------------------------------------------
# Invariant 2: recall failure injects nothing and never raises (c11/h11)
# ---------------------------------------------------------------------------


class TestRecallFailureInjectsNothing:
    """A recall failure (non-zero exit, exception, absent CLI) injects no
    context and never raises — advisory only, never a precondition."""

    def test_recall_nonzero_exit_injects_no_context(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """When eidetic recall exits non-zero, no memory block is injected
        and the run proceeds normally."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_failing_recall(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        seen_messages: list[list[dict]] = []

        def complete(messages: list[dict]) -> ModelResponse:
            seen_messages.append([dict(m) for m in messages])
            return _FINISH

        result = run(
            complete,
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        # The run finishes OK — recall failure did not block it.
        assert result.status == OK
        # No memory block was injected (the first turn has no [memory] prefix).
        first_turn = seen_messages[0]
        joined = json.dumps(first_turn)
        assert "[memory]" not in joined

    def test_recall_failure_result_memory_field_shows_zero_recalled(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """When recall fails (non-zero exit), the result's memory field records
        zero recalled — no misleading data, and the run is diagnosable."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_failing_recall(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        assert result.status == OK
        # recall returned [] (non-zero exit → empty list), so memory records
        # the attempt with zero results — diagnosable, not silent.
        assert result.memory is not None
        assert result.memory.get("recalled") == 0
        assert result.memory.get("injected_chars") == 0

    def test_recall_exception_never_raises(self, repo: Path, tmp_path: Path, monkeypatch) -> None:
        """When eidetic raises an exception, the run does not crash —
        the exception is swallowed and the run continues."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_raises(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        # This must not raise — recall failure is best-effort.
        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        assert result.status == OK

    def test_recall_cli_absent_never_raises(self, repo: Path, monkeypatch) -> None:
        """When eidetic is not on PATH, recall returns [] without raising —
        the run proceeds normally with zero recalled."""
        empty_bin = repo / "emptybin"
        empty_bin.mkdir()
        monkeypatch.setenv("PATH", str(empty_bin))

        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            result = run(
                scripted([_FINISH]),
                Task.new(str(repo), "do the work"),
                max_steps=5,
                context=ContextControls(memory=True),
            )

        assert result.status == OK
        # CLI absent → recall returns [], loop records zero recalled.
        assert result.memory is not None
        assert result.memory.get("recalled") == 0
        assert result.memory.get("injected_chars") == 0

    def test_recall_failure_does_not_affect_changed_files(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """A recall failure does not corrupt the changed_files tracking —
        the result's changed_files list is unaffected."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_failing_recall(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        assert result.status == OK
        # changed_files is a clean list (empty since we didn't write anything).
        assert isinstance(result.changed_files, list)


# ---------------------------------------------------------------------------
# Cross-invariant: both recall and remember fail simultaneously
# ---------------------------------------------------------------------------


class TestBothMemoryCallsFail:
    """When both recall and remember fail, the run still completes with an
    OK result — the memory subsystem is entirely best-effort."""

    def test_both_fail_result_is_ok(self, repo: Path, tmp_path: Path, monkeypatch) -> None:
        """Both recall and remember fail — the run still finishes OK."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_raises(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        assert result.status == OK
        # Summary is untouched.
        assert result.summary == _FINISH.tool_calls[0].arguments["summary"]

    def test_both_fail_artifact_round_trips(self, repo: Path, tmp_path: Path, monkeypatch) -> None:
        """The artifact serializes and deserializes cleanly when both calls fail."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "eidetic.log"
        _fake_eidetic_raises(bin_dir, log)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        result = run(
            scripted([_FINISH]),
            Task.new(str(repo), "do the work"),
            max_steps=5,
            context=ContextControls(memory=True),
        )

        d = result.to_dict()
        restored = TaskResult.from_dict(d)
        assert restored.status == OK
        assert restored.summary == result.summary

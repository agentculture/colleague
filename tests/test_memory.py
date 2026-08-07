"""Tests for colleague/memory.py — eidetic CLI adapter.

Pattern-matches colleague/culture.py and colleague/devague.py:
subprocess shell-out, identity env injection, curated allow-list.

Public API:
  recall(repo_path, query, top_k=5) -> list[dict]
  remember(repo_path, record: dict) -> bool

Only the two eidetic verbs ``recall`` and ``remember`` are reachable
(via an allow-list constant).  When the ``eidetic`` CLI is absent,
both functions are strict no-ops (return [] / False, never raise).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import colleague.memory as memory_mod

# ---------------------------------------------------------------------------
# Helpers — fake eidetic executable
# ---------------------------------------------------------------------------


def _make_fake_eidetic(directory: Path) -> Path:
    """Write an executable shell script that captures argv and writes it to a
    log file, then echoes JSON output for ``recall`` or success for ``remember``.

    The script records every invocation in ``eidetic.log`` (under cwd, which
    is the repo root) so tests can inspect argv, cwd, and environment.
    """
    script = directory / "eidetic"
    script.write_text(
        "#!/bin/sh\n"
        'LOG="$(pwd)/eidetic.log"\n'
        'echo "ARGV: $@" >> "$LOG"\n'
        'echo "CWD: $(pwd)" >> "$LOG"\n'
        'echo "SCOPE: ${COLLEAGUE_IDENTITY:-<unset>}" >> "$LOG"\n'
        'echo "---" >> "$LOG"\n'
        'if [ "$1" = "recall" ]; then\n'
        '  echo \'[{"id":"1","query":"test","content":"result"}]\'\n'
        'elif [ "$1" = "remember" ]; then\n'
        '  echo "ok"\n'
        "fi\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ---------------------------------------------------------------------------
# Allow-list constant
# ---------------------------------------------------------------------------


class TestAllowList:
    def test_allowed_verbs_constant(self) -> None:
        assert memory_mod.ALLOWED_VERBS == frozenset({"recall", "remember"})

    def test_allowed_verbs_is_frozenset(self) -> None:
        assert isinstance(memory_mod.ALLOWED_VERBS, frozenset)


# ---------------------------------------------------------------------------
# recall() — happy path
# ---------------------------------------------------------------------------


class TestRecallHappyPath:
    def test_recall_returns_list_of_dicts(self, tmp_path: Path, monkeypatch) -> None:
        _make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        result = memory_mod.recall(tmp_path, "test query", top_k=3)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_recall_parses_eidetic_013_envelope(self, tmp_path: Path, monkeypatch) -> None:
        """eidetic >= 0.13 wraps results: {query, mode, truncated, items}.

        The pre-0.13 bare-list shape stays accepted (the test above); this
        pins the envelope shape so recall never silently degrades to
        recalled=0 again (caught live in the #387 proof session).
        """
        script = tmp_path / "eidetic"
        script.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "recall" ]; then\n'
            '  echo \'{"query":"q","mode":"hybrid","truncated":false,'
            '"items":[{"id":"env-1","content":"wrapped"}]}\'\n'
            "fi\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        result = memory_mod.recall(tmp_path, "test query", top_k=3)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == "env-1"

    def test_recall_passes_correct_argv(self, tmp_path: Path, monkeypatch) -> None:
        _make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        memory_mod.recall(tmp_path, "my query", top_k=5)

        log = tmp_path / "eidetic.log"
        assert log.exists()
        lines = log.read_text().splitlines()
        argv_line = lines[0]
        assert "recall" in argv_line
        assert "my query" in argv_line
        assert "--json" in argv_line
        assert "--top-k" in argv_line
        assert "5" in argv_line
        assert "--scope" in argv_line
        assert "colleague" in argv_line
        assert "--visibility" in argv_line
        assert "public" in argv_line

    def test_recall_runs_with_cwd_at_repo_path(self, tmp_path: Path, monkeypatch) -> None:
        _make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        memory_mod.recall(tmp_path, "test")

        log = tmp_path / "eidetic.log"
        lines = log.read_text().splitlines()
        cwd_line = lines[1]
        assert f"CWD: {Path(tmp_path).resolve()}" in cwd_line

    def test_recall_default_top_k_is_5(self, tmp_path: Path, monkeypatch) -> None:
        """Default top_k=5 is used when not specified."""
        _make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        memory_mod.recall(tmp_path, "test")

        lines_text = (tmp_path / "eidetic.log").read_text()
        assert "--top-k 5" in lines_text


# ---------------------------------------------------------------------------
# recall() — CLI absent (strict no-op)
# ---------------------------------------------------------------------------


class TestRecallCliAbsent:
    def test_recall_returns_empty_list_when_cli_absent(self, tmp_path: Path, monkeypatch) -> None:
        """When eidetic is not on PATH, recall returns [] without raising."""
        empty_bin = tmp_path / "emptybin"
        empty_bin.mkdir()
        # monkeypatch (not a bare os.environ assignment) so PATH is restored —
        # a clobbered PATH breaks every later test in the same worker.
        monkeypatch.setenv("PATH", str(empty_bin))
        # Ensure eidetic is not found
        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            result = memory_mod.recall(tmp_path, "test")
        assert result == []

    def test_recall_no_subprocess_when_cli_absent(self, tmp_path: Path) -> None:
        """No subprocess is attempted when eidetic is absent."""
        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            with patch.object(subprocess, "run", side_effect=AssertionError("should not run")):
                result = memory_mod.recall(tmp_path, "test")
        assert result == []


# ---------------------------------------------------------------------------
# recall() — malformed JSON output degrades to []
# ---------------------------------------------------------------------------


class TestRecallMalformedJson:
    def test_recall_malformed_json_returns_empty_list(self, tmp_path: Path, monkeypatch) -> None:
        """When eidetic outputs invalid JSON, recall returns [] without raising."""
        script = tmp_path / "eidetic"
        script.write_text(
            "#!/bin/sh\n" 'echo "not valid json {{{"\n',
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        result = memory_mod.recall(tmp_path, "test")

        assert result == []

    def test_recall_empty_output_returns_empty_list(self, tmp_path: Path, monkeypatch) -> None:
        """When eidetic outputs nothing, recall returns []."""
        script = tmp_path / "eidetic"
        script.write_text(
            "#!/bin/sh\n" 'echo ""\n',
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        result = memory_mod.recall(tmp_path, "test")

        assert result == []


# ---------------------------------------------------------------------------
# remember() — happy path
# ---------------------------------------------------------------------------


class TestRememberHappyPath:
    def test_remember_returns_true_on_success(self, tmp_path: Path, monkeypatch) -> None:
        _make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        record = {"key": "value", "data": "test"}
        result = memory_mod.remember(tmp_path, record)

        assert result is True

    def test_remember_passes_correct_argv(self, tmp_path: Path, monkeypatch) -> None:
        _make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        record = {"key": "value"}
        memory_mod.remember(tmp_path, record)

        log = tmp_path / "eidetic.log"
        lines = log.read_text().splitlines()
        argv_line = lines[0]
        assert "remember" in argv_line
        assert "--scope" in argv_line
        assert "colleague" in argv_line
        assert "--visibility" in argv_line
        assert "public" in argv_line

    def test_remember_passes_record_json(self, tmp_path: Path, monkeypatch) -> None:
        """The record dict is serialized as JSON and passed to eidetic."""
        script = tmp_path / "eidetic"
        script.write_text(
            "#!/bin/sh\n" 'echo "$@" > "$(pwd)/remember_args.log"\n',
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        record = {"key": "value", "nested": {"a": 1}}
        memory_mod.remember(tmp_path, record)

        args_log = tmp_path / "remember_args.log"
        args_text = args_log.read_text()
        # The JSON should be in the args
        parsed = json.loads(args_text.split("remember", 1)[1].strip().split("--scope")[0].strip())
        assert parsed == record


# ---------------------------------------------------------------------------
# remember() — CLI absent (strict no-op)
# ---------------------------------------------------------------------------


class TestRememberCliAbsent:
    def test_remember_returns_false_when_cli_absent(self, tmp_path: Path) -> None:
        """When eidetic is not on PATH, remember returns False without raising."""
        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            result = memory_mod.remember(tmp_path, {"key": "value"})
        assert result is False

    def test_remember_no_subprocess_when_cli_absent(self, tmp_path: Path) -> None:
        """No subprocess is attempted when eidetic is absent."""
        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            with patch.object(subprocess, "run", side_effect=AssertionError("should not run")):
                result = memory_mod.remember(tmp_path, {"key": "value"})
        assert result is False


# ---------------------------------------------------------------------------
# remember() — non-zero exit degrades to False
# ---------------------------------------------------------------------------


class TestRememberFailure:
    def test_remember_nonzero_exit_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """When eidetic remember exits non-zero, remember returns False."""
        script = tmp_path / "eidetic"
        script.write_text(
            "#!/bin/sh\n" 'echo "error" >&2\n' "exit 1\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        result = memory_mod.remember(tmp_path, {"key": "value"})

        assert result is False


# ---------------------------------------------------------------------------
# Identity injection
# ---------------------------------------------------------------------------


class TestIdentityInjection:
    def test_identity_env_reaches_child(self, tmp_path: Path, monkeypatch) -> None:
        """COLLEAGUE_IDENTITY is injected into the eidetic child process."""
        (tmp_path / "culture.yaml").write_text("nick: test-agent\n", encoding="utf-8")
        _make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        memory_mod.recall(tmp_path, "test")

        log = tmp_path / "eidetic.log"
        lines = log.read_text().splitlines()
        scope_line = lines[2]
        assert "SCOPE: test-agent" in scope_line


# ---------------------------------------------------------------------------
# Embedder env overrides (one-embedder increment, S2, colleague#291/#292 t19):
# recall/remember merge env_overrides into the eidetic subprocess env, but an
# operator-set env var of the SAME name always wins.
# ---------------------------------------------------------------------------


class TestEmbedEnvOverrides:
    def _capture_recall_env(self, tmp_path: Path, **kwargs) -> dict:
        captured: dict = {}

        def _fake_run(argv, **run_kwargs):
            captured["env"] = run_kwargs.get("env")
            result = Mock()
            result.returncode = 0
            result.stdout = "[]"
            return result

        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/eidetic"
            with patch.object(subprocess, "run", side_effect=_fake_run):
                memory_mod.recall(tmp_path, "query", **kwargs)
        return captured["env"]

    def test_recall_merges_env_overrides_into_subprocess_env(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.delenv("EIDETIC_EMBED_URL", raising=False)
        env = self._capture_recall_env(
            tmp_path, env_overrides={"EIDETIC_EMBED_URL": "http://embed-host:9000/v1"}
        )
        assert env["EIDETIC_EMBED_URL"] == "http://embed-host:9000/v1"

    def test_recall_operator_set_env_var_survives_injection(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """An operator-exported env var of the SAME name is NEVER overwritten
        by a lobes-discovered override (operator wins)."""
        monkeypatch.setenv("EIDETIC_EMBED_URL", "http://operator-set:1234/v1")
        env = self._capture_recall_env(
            tmp_path, env_overrides={"EIDETIC_EMBED_URL": "http://lobes-discovered:9000/v1"}
        )
        assert env["EIDETIC_EMBED_URL"] == "http://operator-set:1234/v1"

    def test_recall_no_env_overrides_is_byte_identical(self, tmp_path: Path, monkeypatch) -> None:
        """Absent env_overrides (lobes unarmed/no embedder) reproduces today's
        env exactly — no new keys added."""
        monkeypatch.delenv("EIDETIC_EMBED_URL", raising=False)
        env_default = self._capture_recall_env(tmp_path)
        env_explicit_empty = self._capture_recall_env(tmp_path, env_overrides={})
        assert env_default == env_explicit_empty
        assert "EIDETIC_EMBED_URL" not in env_default

    def test_remember_merges_env_overrides_into_subprocess_env(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.delenv("EIDETIC_EMBED_MODEL", raising=False)
        captured: dict = {}

        def _fake_run(argv, **run_kwargs):
            captured["env"] = run_kwargs.get("env")
            result = Mock()
            result.returncode = 0
            result.stdout = "ok"
            return result

        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/eidetic"
            with patch.object(subprocess, "run", side_effect=_fake_run):
                memory_mod.remember(
                    tmp_path,
                    {"key": "value"},
                    env_overrides={"EIDETIC_EMBED_MODEL": "Qwen/Qwen3-Embedding-0.6B"},
                )
        assert captured["env"]["EIDETIC_EMBED_MODEL"] == "Qwen/Qwen3-Embedding-0.6B"

    def test_remember_operator_set_env_var_survives_injection(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("EIDETIC_EMBED_MODEL", "operator-chosen-model")
        captured: dict = {}

        def _fake_run(argv, **run_kwargs):
            captured["env"] = run_kwargs.get("env")
            result = Mock()
            result.returncode = 0
            result.stdout = "ok"
            return result

        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/eidetic"
            with patch.object(subprocess, "run", side_effect=_fake_run):
                memory_mod.remember(
                    tmp_path,
                    {"key": "value"},
                    env_overrides={"EIDETIC_EMBED_MODEL": "lobes-discovered-model"},
                )
        assert captured["env"]["EIDETIC_EMBED_MODEL"] == "operator-chosen-model"


# ---------------------------------------------------------------------------
# Allow-list enforcement — only recall and remember are reachable
# ---------------------------------------------------------------------------


class TestAllowListEnforcement:
    def test_only_recall_and_remember_are_allowed(self) -> None:
        """No other verbs are in the allow-list."""
        assert "export" not in memory_mod.ALLOWED_VERBS
        assert "delete" not in memory_mod.ALLOWED_VERBS
        assert "search" not in memory_mod.ALLOWED_VERBS

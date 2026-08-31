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

    ``--version`` is answered as 0.13.0 WITHOUT logging (so the per-process
    rerank probe, #467, does not shift the log's line indices) — the argv the
    existing assertions pin therefore stays byte-identical to the pre-rerank
    surface (acceptance 1: an older CLI never sees ``--rerank``).
    """
    script = directory / "eidetic"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        '  echo "eidetic-cli 0.13.0"\n'
        "  exit 0\n"
        "fi\n"
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
        # The 0.13.0 stub must never see the opt-in rerank flag (#467):
        # the argv stays byte-identical to the pre-rerank surface.
        assert "--rerank" not in argv_line

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


# ---------------------------------------------------------------------------
# Recall thresholding + supersedes hygiene, injection-only (plan t6, c10/h9)
# ---------------------------------------------------------------------------


class TestFilterRecallRecordsThreshold:
    def test_below_min_score_is_excluded_with_a_reason(self) -> None:
        records = [
            {"id": "a", "text": "keep me", "score": 0.9},
            {"id": "b", "text": "drop me", "score": 0.1},
        ]
        kept, excluded = memory_mod.filter_recall_records(records, min_score=0.5)
        assert [r["id"] for r in kept] == ["a"]
        assert excluded == [{"id": "b", "reason": "below-min-score"}]

    def test_below_min_signal_is_excluded_with_a_reason(self) -> None:
        records = [
            {"id": "a", "text": "fresh", "signal": 0.8},
            {"id": "b", "text": "stale", "signal": 0.05},
        ]
        kept, excluded = memory_mod.filter_recall_records(records, min_signal=0.2)
        assert [r["id"] for r in kept] == ["a"]
        assert excluded == [{"id": "b", "reason": "below-min-signal"}]

    def test_record_missing_score_or_signal_field_is_never_excluded(self) -> None:
        """Nothing to threshold ⇒ fail open, not closed (matches the rest of
        the memory seam's degrade stance)."""
        records = [{"id": "a", "text": "no fields at all"}]
        kept, excluded = memory_mod.filter_recall_records(records, min_score=0.9, min_signal=0.9)
        assert kept == records
        assert excluded == []

    def test_non_numeric_score_is_never_excluded(self) -> None:
        records = [{"id": "a", "text": "weird", "score": "not-a-number"}]
        kept, excluded = memory_mod.filter_recall_records(records, min_score=0.5)
        assert kept == records
        assert excluded == []

    def test_no_thresholds_configured_keeps_everything(self) -> None:
        records = [{"id": "a", "score": 0.0}, {"id": "b", "signal": 0.0}]
        kept, excluded = memory_mod.filter_recall_records(records)
        assert kept == records
        assert excluded == []

    def test_missing_id_falls_back_to_positional_reference(self) -> None:
        records = [{"text": "no id here", "score": 0.0}]
        _, excluded = memory_mod.filter_recall_records(records, min_score=0.5)
        assert excluded == [{"id": "#0", "reason": "below-min-score"}]


class TestFilterRecallRecordsSupersedes:
    def test_superseded_sibling_is_dropped_in_favor_of_the_superseding_record(self) -> None:
        records = [
            {"id": "old", "text": "the old lesson"},
            {"id": "new", "text": "the new lesson", "supersedes": "old"},
        ]
        kept, excluded = memory_mod.filter_recall_records(records)
        assert [r["id"] for r in kept] == ["new"]
        assert excluded == [{"id": "old", "reason": "superseded-by:new"}]

    def test_supersedes_pointing_outside_the_batch_is_left_alone(self) -> None:
        """A supersedes id not present in THIS recalled batch is not
        actionable here — nothing is dropped."""
        records = [{"id": "new", "text": "lesson", "supersedes": "not-in-batch"}]
        kept, excluded = memory_mod.filter_recall_records(records)
        assert kept == records
        assert excluded == []

    def test_self_referential_supersedes_is_ignored(self) -> None:
        records = [{"id": "a", "text": "lesson", "supersedes": "a"}]
        kept, excluded = memory_mod.filter_recall_records(records)
        assert kept == records
        assert excluded == []

    def test_threshold_and_supersedes_compose(self) -> None:
        records = [
            {"id": "low", "text": "weak", "score": 0.1},
            {"id": "old", "text": "old lesson", "score": 0.9},
            {"id": "new", "text": "new lesson", "score": 0.9, "supersedes": "old"},
        ]
        kept, excluded = memory_mod.filter_recall_records(records, min_score=0.5)
        assert [r["id"] for r in kept] == ["new"]
        assert {"id": "low", "reason": "below-min-score"} in excluded
        assert {"id": "old", "reason": "superseded-by:new"} in excluded


class TestFilterForInjectionEnvWrapper:
    def test_default_env_applies_configured_thresholds(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_RECALL_MIN_SCORE", "0.5")
        records = [
            {"id": "a", "score": 0.9},
            {"id": "b", "score": 0.1},
        ]
        kept, excluded = memory_mod.filter_for_injection(records)
        assert [r["id"] for r in kept] == ["a"]
        assert excluded == [{"id": "b", "reason": "below-min-score"}]

    def test_hygiene_disabled_env_is_a_strict_identity(self, monkeypatch) -> None:
        """COLLEAGUE_RECALL_HYGIENE=0 restores pre-t6 behavior byte-for-byte —
        every record kept, nothing excluded — even with thresholds set AND a
        supersedes edge present."""
        monkeypatch.setenv("COLLEAGUE_RECALL_HYGIENE", "0")
        monkeypatch.setenv("COLLEAGUE_RECALL_MIN_SCORE", "0.99")
        records = [
            {"id": "old", "score": 0.0},
            {"id": "new", "score": 0.0, "supersedes": "old"},
        ]
        kept, excluded = memory_mod.filter_for_injection(records)
        assert kept == records
        assert excluded == []

    def test_falsy_spellings_all_disable(self, monkeypatch) -> None:
        for spelling in ("0", "false", "False", "no", "off", "OFF"):
            monkeypatch.setenv("COLLEAGUE_RECALL_HYGIENE", spelling)
            assert memory_mod.recall_hygiene_enabled() is False
        monkeypatch.delenv("COLLEAGUE_RECALL_HYGIENE", raising=False)
        assert memory_mod.recall_hygiene_enabled() is True

    def test_injectable_env_mapping_does_not_touch_real_process_env(self, monkeypatch) -> None:
        """The 3-arg pure functions accept an explicit mapping for tests
        without needing monkeypatch at all."""
        monkeypatch.delenv("COLLEAGUE_RECALL_HYGIENE", raising=False)
        monkeypatch.delenv("COLLEAGUE_RECALL_MIN_SCORE", raising=False)
        env = {"COLLEAGUE_RECALL_HYGIENE": "0"}
        assert memory_mod.recall_hygiene_enabled(env) is False
        assert memory_mod.recall_hygiene_enabled() is True
        assert memory_mod.recall_min_score({"COLLEAGUE_RECALL_MIN_SCORE": "0.7"}) == 0.7
        assert memory_mod.recall_min_score({}) is None

    def test_unparseable_threshold_degrades_to_no_op(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_RECALL_MIN_SCORE", "not-a-float")
        assert memory_mod.recall_min_score() is None
        assert "search" not in memory_mod.ALLOWED_VERBS


# ---------------------------------------------------------------------------
# eidetic --rerank opt-in behind a per-process version probe (#467,
# eidetic-cli#39). recall passes --rerank iff ONE cached `eidetic --version`
# probe parses >= 0.14.0; ANY probe failure or an older CLI withholds the
# flag so a flag-rejecting 0.13 CLI can never silently yield recalled=0
# (the #387-class failure).
# ---------------------------------------------------------------------------


def _make_versioned_eidetic(
    directory: Path,
    version_output: str,
    *,
    version_exit: int = 0,
    reject_unknown_flags: bool = False,
) -> Path:
    """Write a fake eidetic that answers ``--version`` (logging each probe to
    ``probe.log``) and answers ``recall`` with one item, logging its argv to
    ``eidetic.log``. With *reject_unknown_flags*, any ``--rerank`` in the
    recall argv exits 2 with no output — mimicking a 0.13 CLI's unknown-flag
    rejection."""
    script = directory / "eidetic"
    reject = ""
    if reject_unknown_flags:
        reject = (
            'for arg in "$@"; do\n'
            '  if [ "$arg" = "--rerank" ]; then\n'
            '    echo "Error: no such option: --rerank" >&2\n'
            "    exit 2\n"
            "  fi\n"
            "done\n"
        )
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        '  echo "probe" >> "$(pwd)/probe.log"\n'
        f'  echo "{version_output}"\n'
        f"  exit {version_exit}\n"
        "fi\n"
        f"{reject}"
        'echo "ARGV: $@" >> "$(pwd)/eidetic.log"\n'
        'if [ "$1" = "recall" ]; then\n'
        '  echo \'[{"id":"r1","text":"recalled"}]\'\n'
        "fi\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


class TestRecallRerankProbe:
    def test_probe_env_is_path_only(self, tmp_path: Path, monkeypatch) -> None:
        """The --version probe passes ONLY PATH — no identity/embedder env, no
        inherited secrets (Qodo #478-1). Pinned via a stub that dumps its env."""
        script = tmp_path / "eidetic"
        envdump = tmp_path / "env.dump"
        script.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "--version" ]; then\n'
            f"  env > {envdump}\n"
            '  echo "eidetic-cli 0.14.0"\n'
            "  exit 0\n"
            "fi\n"
        )
        script.chmod(0o755)
        monkeypatch.setenv("EIDETIC_API_SECRET", "hunter2")
        monkeypatch.setattr(memory_mod, "_RERANK_PROBE_CACHE", {})
        assert memory_mod._rerank_supported(str(script)) is True
        dumped = envdump.read_text()
        assert "hunter2" not in dumped
        assert "EIDETIC_API_SECRET" not in dumped
        assert "PATH=" in dumped

    def _arm(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
        # A fresh per-test cache: the probe result is cached per process,
        # keyed by resolved CLI path.
        monkeypatch.setattr(memory_mod, "_RERANK_PROBE_CACHE", {})

    def test_013_cli_gets_no_rerank_and_items_are_returned(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _make_versioned_eidetic(tmp_path, "eidetic-cli 0.13.0")
        self._arm(tmp_path, monkeypatch)

        result = memory_mod.recall(tmp_path, "q")

        assert [r["id"] for r in result] == ["r1"]
        argv_line = (tmp_path / "eidetic.log").read_text()
        assert "--rerank" not in argv_line

    def test_014_cli_gets_rerank(self, tmp_path: Path, monkeypatch) -> None:
        _make_versioned_eidetic(tmp_path, "eidetic-cli 0.14.0")
        self._arm(tmp_path, monkeypatch)

        result = memory_mod.recall(tmp_path, "q")

        assert [r["id"] for r in result] == ["r1"]
        assert "--rerank" in (tmp_path / "eidetic.log").read_text()

    def test_newer_cli_gets_rerank(self, tmp_path: Path, monkeypatch) -> None:
        _make_versioned_eidetic(tmp_path, "eidetic-cli 1.2.3")
        self._arm(tmp_path, monkeypatch)

        memory_mod.recall(tmp_path, "q")

        assert "--rerank" in (tmp_path / "eidetic.log").read_text()

    def test_probe_nonzero_exit_withholds_rerank(self, tmp_path: Path, monkeypatch) -> None:
        _make_versioned_eidetic(tmp_path, "eidetic-cli 0.14.0", version_exit=1)
        self._arm(tmp_path, monkeypatch)

        result = memory_mod.recall(tmp_path, "q")

        assert [r["id"] for r in result] == ["r1"]
        assert "--rerank" not in (tmp_path / "eidetic.log").read_text()

    def test_unparseable_version_withholds_rerank(self, tmp_path: Path, monkeypatch) -> None:
        _make_versioned_eidetic(tmp_path, "something with no version in it")
        self._arm(tmp_path, monkeypatch)

        result = memory_mod.recall(tmp_path, "q")

        assert [r["id"] for r in result] == ["r1"]
        assert "--rerank" not in (tmp_path / "eidetic.log").read_text()

    def test_flag_rejecting_013_cli_can_never_yield_recalled_zero(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A 0.13 CLI that exits 2 on unknown flags still returns its items:
        the WITHHOLD (not a retry) is what protects against the #387-class
        silent recalled=0 failure."""
        _make_versioned_eidetic(tmp_path, "eidetic-cli 0.13.0", reject_unknown_flags=True)
        self._arm(tmp_path, monkeypatch)

        result = memory_mod.recall(tmp_path, "q")

        assert [r["id"] for r in result] == ["r1"]
        assert "--rerank" not in (tmp_path / "eidetic.log").read_text()

    def test_probe_runs_once_per_process(self, tmp_path: Path, monkeypatch) -> None:
        """Two recalls fire exactly ONE `eidetic --version` probe (cached in
        a module global, keyed by CLI path)."""
        _make_versioned_eidetic(tmp_path, "eidetic-cli 0.14.0")
        self._arm(tmp_path, monkeypatch)

        memory_mod.recall(tmp_path, "q1")
        memory_mod.recall(tmp_path, "q2")

        probe_lines = (tmp_path / "probe.log").read_text().splitlines()
        assert len(probe_lines) == 1
        assert (tmp_path / "eidetic.log").read_text().count("--rerank") == 2


# ── supersedes chains and cycles ─────────────────────────────────────────────
# Regression for qodo-code-review on PR #402 (comment 3746408309).


def test_supersedes_chain_names_the_terminal_survivor() -> None:
    """A<-B<-C must report BOTH A and B as superseded-by C.

    Naming B would point a debugger at a record that is itself excluded and
    therefore absent from the injected block.
    """
    kept, excluded = memory_mod.filter_recall_records(
        [{"id": "A"}, {"id": "B", "supersedes": "A"}, {"id": "C", "supersedes": "B"}]
    )
    assert [r["id"] for r in kept] == ["C"]
    assert {e["id"]: e["reason"] for e in excluded} == {
        "A": "superseded-by:C",
        "B": "superseded-by:C",
    }


def test_a_supersedes_cycle_drops_nothing() -> None:
    """A cycle has no terminal superseder, so applying it would exclude every
    record in the cycle and could silently empty the recall block."""
    records = [{"id": "X", "supersedes": "Y"}, {"id": "Y", "supersedes": "X"}]
    kept, excluded = memory_mod.filter_recall_records(records)
    assert [r["id"] for r in kept] == ["X", "Y"]
    assert excluded == []

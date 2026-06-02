"""Back-compat coverage for the convertible -> colleague rename.

The canonical names are ``colleague`` / ``.colleague/`` / ``COLLEAGUE_*``; the
legacy ``convertible`` names survive only as **deprecated read fallbacks** at the
lowest precedence. These tests pin that contract so a future cleanup that drops
the fallback fails loudly here rather than silently breaking a not-yet-migrated
repo or operator env.

What is intentionally NOT covered (writes always go to the new name): writing to
``.convertible/`` — there is no such code path by design.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.artifact import artifact_read_dirs
from colleague.config import EngineConfig, resolve_engine
from colleague.configdir import collect_files, config_roots
from colleague.feedback import get_last_drive, read_feedback, set_last_drive, write_feedback
from colleague.identity import identity_env, resolve_identity
from colleague.neighbours import NeighbourManager
from colleague.telemetry import TelemetryConfig

_ENGINE_KEYS = ("COLLEAGUE_ENGINE", "CONVERTIBLE_ENGINE")
_MODEL_KEYS = ("COLLEAGUE_MODEL", "CONVERTIBLE_MODEL")
_OTEL_KEYS = ("COLLEAGUE_OTEL_ENABLED", "CONVERTIBLE_OTEL_ENABLED")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test from a clean slate for every dual-prefix key it touches."""
    for key in _ENGINE_KEYS + _MODEL_KEYS + _OTEL_KEYS:
        monkeypatch.delenv(key, raising=False)


# --- env vars: COLLEAGUE_ wins, CONVERTIBLE_ is the fallback ----------------


def test_resolve_engine_legacy_env_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "mock")
    assert resolve_engine(None) == "mock"


def test_resolve_engine_new_env_beats_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "vllm-openai")
    monkeypatch.setenv("COLLEAGUE_ENGINE", "mock")
    assert resolve_engine(None) == "mock"


def test_engine_config_legacy_model_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_MODEL", "legacy-model")
    assert EngineConfig.resolve().model == "legacy-model"


def test_engine_config_new_model_beats_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_MODEL", "legacy-model")
    monkeypatch.setenv("COLLEAGUE_MODEL", "new-model")
    assert EngineConfig.resolve().model == "new-model"


def test_telemetry_legacy_otel_enabled_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    assert TelemetryConfig.resolve().enabled is True


def test_telemetry_new_otel_beats_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    # New name explicitly off wins over legacy on.
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.setenv("COLLEAGUE_OTEL_ENABLED", "false")
    assert TelemetryConfig.resolve().enabled is False


# --- identity: both keys emitted -------------------------------------------


def test_identity_env_emits_both_names() -> None:
    assert identity_env("bot") == {
        "COLLEAGUE_IDENTITY": "bot",
        "CONVERTIBLE_IDENTITY": "bot",
    }


# --- config dir: .colleague/ wins, .convertible/ is the fallback -----------


def test_config_roots_repo_beats_user_then_new_beats_legacy(tmp_path: Path) -> None:
    # Repo overrides user (the module invariant), and within each level the new
    # name overrides the legacy one — so a repo-level legacy dir still outranks
    # any user-level dir.
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    for d in (
        repo / ".colleague",
        repo / ".convertible",
        home / ".colleague",
        home / ".convertible",
    ):
        d.mkdir(parents=True)
    roots = config_roots(repo, user_home=home)
    assert roots == [
        repo / ".colleague",
        repo / ".convertible",
        home / ".colleague",
        home / ".convertible",
    ]


def test_repo_legacy_dir_shadows_user_new_dir(tmp_path: Path) -> None:
    # Regression: a repo-level .convertible/ must still beat a user-level
    # .colleague/ (repo-overrides-user invariant holds across the rename).
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    (repo / ".convertible" / "skills").mkdir(parents=True)
    (repo / ".convertible" / "skills" / "foo.md").write_text("repo-legacy\n", encoding="utf-8")
    (home / ".colleague" / "skills").mkdir(parents=True)
    (home / ".colleague" / "skills" / "foo.md").write_text("user-new\n", encoding="utf-8")
    found = collect_files(repo, "skills", suffix=".md", user_home=home)
    assert found["foo"].read_text(encoding="utf-8") == "repo-legacy\n"


def test_collect_files_reads_legacy_convertible_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".convertible" / "skills").mkdir(parents=True)
    (repo / ".convertible" / "skills" / "foo.md").write_text("# foo\n", encoding="utf-8")
    found = collect_files(repo, "skills", suffix=".md", user_home=tmp_path / "home")
    assert set(found) == {"foo"}


def test_collect_files_new_dir_shadows_legacy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".convertible" / "skills").mkdir(parents=True)
    (repo / ".convertible" / "skills" / "foo.md").write_text("legacy\n", encoding="utf-8")
    (repo / ".colleague" / "skills").mkdir(parents=True)
    (repo / ".colleague" / "skills" / "foo.md").write_text("new\n", encoding="utf-8")
    found = collect_files(repo, "skills", suffix=".md", user_home=tmp_path / "home")
    assert found["foo"].read_text(encoding="utf-8") == "new\n"


# --- artifacts/feedback: read legacy, write new ----------------------------


def test_artifact_read_dirs_order(tmp_path: Path) -> None:
    assert artifact_read_dirs(tmp_path) == [tmp_path / ".colleague", tmp_path / ".convertible"]


def test_feedback_reads_legacy_record(tmp_path: Path) -> None:
    legacy = tmp_path / ".convertible"
    legacy.mkdir()
    record = {
        "task_id": "leg1",
        "rating": 5,
        "notes": "old",
        "by": "x",
        "at": "2026-01-01T00:00:00+00:00",
    }
    (legacy / "leg1.feedback.json").write_text(json.dumps(record), encoding="utf-8")
    fb = read_feedback(tmp_path, "leg1")
    assert fb is not None and fb.rating == 5 and fb.notes == "old"


def test_feedback_write_targets_new_dir_and_shadows_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / ".convertible"
    legacy.mkdir()
    (legacy / "t1.feedback.json").write_text(
        json.dumps({"task_id": "t1", "rating": 1, "notes": "old"}), encoding="utf-8"
    )
    write_feedback(tmp_path, "t1", rating=4, notes="new")
    # Write landed in the new dir, not the legacy one.
    assert (tmp_path / ".colleague" / "t1.feedback.json").is_file()
    # Read now prefers the new record.
    fb = read_feedback(tmp_path, "t1")
    assert fb is not None and fb.rating == 4 and fb.notes == "new"


def test_last_drive_reads_legacy_pointer(tmp_path: Path) -> None:
    legacy = tmp_path / ".convertible"
    legacy.mkdir()
    (legacy / "last_drive").write_text("legacy-id\n", encoding="utf-8")
    assert get_last_drive(tmp_path) == "legacy-id"


def test_last_drive_new_pointer_shadows_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / ".convertible"
    legacy.mkdir()
    (legacy / "last_drive").write_text("legacy-id\n", encoding="utf-8")
    set_last_drive(tmp_path, "new-id")
    assert (tmp_path / ".colleague" / "last_drive").is_file()
    assert get_last_drive(tmp_path) == "new-id"


# --- identity.json + neighbours.json honor the same fallback ----------------


def test_identity_json_read_from_legacy_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".convertible").mkdir(parents=True)
    (repo / ".convertible" / "identity.json").write_text('{"as": "legacy-bot"}', encoding="utf-8")
    assert resolve_identity(repo, user_home=tmp_path / "home") == "legacy-bot"


def test_identity_json_new_dir_shadows_legacy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".convertible").mkdir(parents=True)
    (repo / ".convertible" / "identity.json").write_text('{"as": "legacy-bot"}', encoding="utf-8")
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "identity.json").write_text('{"as": "new-bot"}', encoding="utf-8")
    assert resolve_identity(repo, user_home=tmp_path / "home") == "new-bot"


def test_neighbours_config_read_from_legacy_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".convertible").mkdir(parents=True)
    (repo / ".convertible" / "neighbours.json").write_text(
        json.dumps([{"name": "peer", "url": "https://example.invalid/peer.git"}]),
        encoding="utf-8",
    )
    mgr = NeighbourManager(repo)
    assert [e["name"] for e in mgr.neighbours()] == ["peer"]


def test_neighbours_config_new_dir_shadows_legacy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".convertible").mkdir(parents=True)
    (repo / ".convertible" / "neighbours.json").write_text(
        json.dumps([{"name": "old", "url": "https://example.invalid/old.git"}]),
        encoding="utf-8",
    )
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "neighbours.json").write_text(
        json.dumps([{"name": "new", "url": "https://example.invalid/new.git"}]),
        encoding="utf-8",
    )
    mgr = NeighbourManager(repo)
    assert [e["name"] for e in mgr.neighbours()] == ["new"]

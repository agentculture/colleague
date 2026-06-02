"""Process-level identity resolution (t1).

Tests the module-level API:
- resolve_identity(repo_path, *, user_home=None) -> str | None
- identity_env(identity) -> dict[str, str]

Acceptance:
1. resolve_identity returns the culture.yaml nick when a repo-root culture.yaml
   is present and has a `nick:` field.
2. resolve_identity falls back to .colleague/identity.json `as` field when
   there is no culture.yaml nick.
3. resolve_identity returns None when neither source provides an identity.
4. identity_env returns both {"COLLEAGUE_IDENTITY": identity} and the legacy
   {"CONVERTIBLE_IDENTITY": identity} when identity is set, and an empty dict
   when identity is None.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague.identity import identity_env, resolve_identity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# resolve_identity — culture.yaml nick (primary source)
# ---------------------------------------------------------------------------


def test_resolve_identity_from_culture_yaml_nick(tmp_path: Path) -> None:
    """Returns nick from a top-level nick: field in culture.yaml."""
    repo = _repo(tmp_path)
    _write(repo / "culture.yaml", "nick: colleague\nsome_other: field\n")

    result = resolve_identity(repo)
    assert result == "colleague"


def test_resolve_identity_culture_yaml_nick_with_whitespace(tmp_path: Path) -> None:
    """Strips surrounding whitespace from the nick value."""
    repo = _repo(tmp_path)
    _write(repo / "culture.yaml", "nick:   my-agent   \n")

    result = resolve_identity(repo)
    assert result == "my-agent"


def test_resolve_identity_culture_yaml_nick_multiline(tmp_path: Path) -> None:
    """Finds nick: even when it's not the first line of culture.yaml."""
    repo = _repo(tmp_path)
    _write(
        repo / "culture.yaml",
        "version: 1\nmesh: main\nnick: deep-colleague\n",
    )

    result = resolve_identity(repo)
    assert result == "deep-colleague"


def test_resolve_identity_culture_yaml_no_nick_field(tmp_path: Path) -> None:
    """culture.yaml present but without nick: falls through to next source."""
    repo = _repo(tmp_path)
    _write(repo / "culture.yaml", "version: 1\nmesh: main\n")
    # No .colleague/identity.json either → expect None
    result = resolve_identity(repo, user_home=_home(tmp_path))
    assert result is None


def test_resolve_identity_culture_yaml_empty_nick_skipped(tmp_path: Path) -> None:
    """An empty nick: value is treated as absent and falls through."""
    repo = _repo(tmp_path)
    _write(repo / "culture.yaml", "nick:\n")

    result = resolve_identity(repo, user_home=_home(tmp_path))
    assert result is None


# ---------------------------------------------------------------------------
# resolve_identity — .colleague/identity.json fallback (secondary source)
# ---------------------------------------------------------------------------


def test_resolve_identity_from_identity_json(tmp_path: Path) -> None:
    """Falls back to .colleague/identity.json 'as' field when no culture.yaml nick."""
    repo = _repo(tmp_path)
    identity_file = repo / ".colleague" / "identity.json"
    identity_file.parent.mkdir(parents=True, exist_ok=True)
    identity_file.write_text(json.dumps({"as": "my-bot"}), encoding="utf-8")

    result = resolve_identity(repo, user_home=_home(tmp_path))
    assert result == "my-bot"


def test_resolve_identity_identity_json_missing_as_key(tmp_path: Path) -> None:
    """identity.json without 'as' key returns None."""
    repo = _repo(tmp_path)
    identity_file = repo / ".colleague" / "identity.json"
    identity_file.parent.mkdir(parents=True, exist_ok=True)
    identity_file.write_text(json.dumps({"other": "stuff"}), encoding="utf-8")

    result = resolve_identity(repo, user_home=_home(tmp_path))
    assert result is None


def test_resolve_identity_identity_json_empty_as_skipped(tmp_path: Path) -> None:
    """An empty 'as' value in identity.json is treated as absent."""
    repo = _repo(tmp_path)
    identity_file = repo / ".colleague" / "identity.json"
    identity_file.parent.mkdir(parents=True, exist_ok=True)
    identity_file.write_text(json.dumps({"as": ""}), encoding="utf-8")

    result = resolve_identity(repo, user_home=_home(tmp_path))
    assert result is None


def test_resolve_identity_culture_yaml_wins_over_identity_json(tmp_path: Path) -> None:
    """culture.yaml nick takes priority over .colleague/identity.json."""
    repo = _repo(tmp_path)
    _write(repo / "culture.yaml", "nick: yaml-nick\n")
    identity_file = repo / ".colleague" / "identity.json"
    identity_file.parent.mkdir(parents=True, exist_ok=True)
    identity_file.write_text(json.dumps({"as": "json-nick"}), encoding="utf-8")

    result = resolve_identity(repo)
    assert result == "yaml-nick"


# ---------------------------------------------------------------------------
# resolve_identity — user-level .colleague fallback
# ---------------------------------------------------------------------------


def test_resolve_identity_user_level_identity_json(tmp_path: Path) -> None:
    """Falls back to user-level ~/.colleague/identity.json when repo has nothing."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    user_identity = home / ".colleague" / "identity.json"
    user_identity.parent.mkdir(parents=True, exist_ok=True)
    user_identity.write_text(json.dumps({"as": "user-bot"}), encoding="utf-8")

    result = resolve_identity(repo, user_home=home)
    assert result == "user-bot"


def test_resolve_identity_repo_identity_json_shadows_user(tmp_path: Path) -> None:
    """Repo .colleague/identity.json shadows user-level identity.json."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    repo_identity = repo / ".colleague" / "identity.json"
    repo_identity.parent.mkdir(parents=True, exist_ok=True)
    repo_identity.write_text(json.dumps({"as": "repo-bot"}), encoding="utf-8")

    user_identity = home / ".colleague" / "identity.json"
    user_identity.parent.mkdir(parents=True, exist_ok=True)
    user_identity.write_text(json.dumps({"as": "user-bot"}), encoding="utf-8")

    result = resolve_identity(repo, user_home=home)
    assert result == "repo-bot"


# ---------------------------------------------------------------------------
# resolve_identity — neither source present
# ---------------------------------------------------------------------------


def test_resolve_identity_none_when_nothing_present(tmp_path: Path) -> None:
    """Returns None when neither culture.yaml nor identity.json is present."""
    repo = _repo(tmp_path)
    result = resolve_identity(repo, user_home=_home(tmp_path))
    assert result is None


def test_resolve_identity_no_culture_yaml_no_colleague_dir(tmp_path: Path) -> None:
    """Returns None when neither culture.yaml nor .colleague/ exist at all."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    result = resolve_identity(repo, user_home=home)
    assert result is None


# ---------------------------------------------------------------------------
# identity_env
# ---------------------------------------------------------------------------


def test_identity_env_with_identity() -> None:
    """Returns both the new COLLEAGUE_IDENTITY and legacy CONVERTIBLE_IDENTITY keys."""
    result = identity_env("colleague")
    assert result == {
        "COLLEAGUE_IDENTITY": "colleague",
        "CONVERTIBLE_IDENTITY": "colleague",
    }


def test_identity_env_none_returns_empty_dict() -> None:
    """Returns empty dict when identity is None."""
    result = identity_env(None)
    assert result == {}


def test_identity_env_empty_string_returns_empty_dict() -> None:
    """Returns empty dict when identity is an empty string."""
    result = identity_env("")
    assert result == {}


def test_identity_env_does_not_mutate(tmp_path: Path) -> None:
    """Each call returns a fresh dict (no shared state)."""
    a = identity_env("bot-a")
    b = identity_env("bot-b")
    assert a != b
    assert a == {"COLLEAGUE_IDENTITY": "bot-a", "CONVERTIBLE_IDENTITY": "bot-a"}
    assert b == {"COLLEAGUE_IDENTITY": "bot-b", "CONVERTIBLE_IDENTITY": "bot-b"}

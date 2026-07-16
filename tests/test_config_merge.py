"""Per-key config merge across configdir roots (task t1).

Plan: docs/plans/2026-07-09-colleague-now-feels-at-home-on-your-machine-arm-th.md
(task t1). Spec: docs/specs/2026-07-09-colleague-now-feels-at-home-on-your-machine-arm-th.md
(claims c6, h1, h2, c3, h12, h16).

Bug being fixed: :func:`colleague.configdir.resolve_file` returns only the
*first* existing match across config roots (whole-file shadowing) — so a
repo-level ``.colleague/config.json`` that doesn't mention ``lobes`` used to
make a user-level ``~/.colleague/config.json`` that DOES declare one
disappear entirely. A machine-wide default should survive a repo config that
simply doesn't talk about it.

The fix: :func:`colleague.configdir.resolve_files` (plural) returns EVERY
existing match, precedence-ordered; ``colleague.config``'s
``load_config_file``/``_load_lobes_override``/the senses/voice/deepthink
section loaders now merge those matches PER TOP-LEVEL KEY (repo wins per-key,
user fills the gaps) instead of reading a single resolved file.

Isolation: the user-level "home" here is a fake directory pointed to via the
``COLLEAGUE_HOME`` env var (the task t1 addendum hermeticity guard — see
``tests/conftest.py`` and ``colleague/configdir.py``'s ``_default_user_home``)
rather than monkeypatching ``Path.home()`` directly, since the autouse
``_isolate_provider_env`` fixture already arms ``COLLEAGUE_HOME`` for every
test; setting it again here (in the test body, after that fixture runs) wins
and lets us point at a home directory we control and can write fixtures into.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.config import (
    _load_deepthink_overrides,
    _load_lobes_override,
    _load_senses_overrides,
    _load_voice_overrides,
    load_config_file,
    resolve_lobes_gateway_url,
)
from colleague.configdir import resolve_files


def _write_config(root: Path, payload: dict) -> None:
    """Write a ``.colleague/config.json`` inside *root*."""
    cfg_dir = root / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_legacy_config(root: Path, payload: dict) -> None:
    """Write a legacy ``.convertible/config.json`` inside *root*."""
    cfg_dir = root / ".convertible"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_malformed_config(root: Path) -> None:
    """Write an unparseable ``.colleague/config.json`` inside *root*."""
    cfg_dir = root / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text("not json at all", encoding="utf-8")


def _arm_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point COLLEAGUE_HOME at a fresh, test-owned "home" directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("COLLEAGUE_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# The failing-first shadow-bug reproduction.
# ---------------------------------------------------------------------------


def test_repo_config_without_lobes_falls_through_to_user_lobes_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo config.json that never mentions ``lobes`` must not shadow a
    user-level default that DOES declare one — the whole point of a
    machine-wide default (this is the reproduction that must fail against the
    pre-fix whole-file-shadowing ``resolve_file``)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "x"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"lobes": "http://localhost:8001"})

    assert resolve_lobes_gateway_url(repo) == "http://localhost:8001"


# ---------------------------------------------------------------------------
# Byte-identical guarantee: a repo-level key, once present, still wins outright.
# ---------------------------------------------------------------------------


def test_repo_lobes_key_wins_over_user_lobes_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo config carrying ``lobes`` behaves exactly as before the merge —
    it wins outright over a user-level ``lobes``, never falls through."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"lobes": "http://repo-gateway:9001"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"lobes": "http://user-gateway:9002"})

    assert resolve_lobes_gateway_url(repo) == "http://repo-gateway:9001"


def test_load_config_file_merges_endpoint_keys_per_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``load_config_file`` merges base_url/api_key/model per-key: a repo value
    for a key it defines wins; a key the repo never mentions (``api_key``
    here) falls through to the user-level file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"base_url": "http://repo/v1", "model": "repo-model"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(
        home,
        {"base_url": "http://user/v1", "model": "user-model", "api_key": "user-key"},
    )

    assert load_config_file(repo) == {
        "base_url": "http://repo/v1",
        "model": "repo-model",
        "api_key": "user-key",
    }


# ---------------------------------------------------------------------------
# Malformed JSON at any single level skips THAT level only, never raises.
# ---------------------------------------------------------------------------


def test_malformed_repo_json_skips_repo_level_falls_through_to_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_malformed_config(repo)

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"lobes": "http://user-gateway:9003"})

    assert resolve_lobes_gateway_url(repo) == "http://user-gateway:9003"
    # The malformed repo file contributes nothing (not even a partial parse);
    # the user file has no base_url/api_key/model, so this is empty too.
    assert load_config_file(repo) == {}


def test_malformed_user_json_skips_user_level_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "x"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_malformed_config(home)

    assert resolve_lobes_gateway_url(repo) is None
    assert load_config_file(repo) == {"model": "x"}


# ---------------------------------------------------------------------------
# Legacy .convertible roots keep their existing place in precedence order.
# ---------------------------------------------------------------------------


def test_legacy_convertible_root_keeps_its_precedence_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order is [repo/.colleague, repo/.convertible, user/.colleague,
    user/.convertible]. A repo/.colleague file that omits ``lobes`` falls
    through to repo/.convertible BEFORE it ever reaches the user level."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "x"})  # repo/.colleague — no lobes
    _write_legacy_config(repo, {"lobes": "http://legacy-repo:9004"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"lobes": "http://user-gateway:9005"})

    assert resolve_lobes_gateway_url(repo) == "http://legacy-repo:9004"


# ---------------------------------------------------------------------------
# Merge granularity is the TOP-LEVEL KEY only — no deep merge inside a section.
# ---------------------------------------------------------------------------


def test_senses_section_is_top_level_key_no_deep_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo-level ``senses`` section wholly replaces a user-level one: the
    user's extra ``base_url`` must NOT leak into the merged result just
    because the repo's section omits it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"senses": {"model": "repo-senses-model"}})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(
        home,
        {"senses": {"model": "user-senses-model", "base_url": "http://user-senses/v1"}},
    )

    assert _load_senses_overrides(repo) == {"model": "repo-senses-model"}


def test_deepthink_section_falls_through_whole_when_repo_omits_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo config that never mentions ``deepthink`` at all falls through to
    the user's whole section (still no deep merge — there's nothing at the
    repo level to merge with)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "x"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(
        home,
        {"deepthink": {"model": "user-deepthink-model", "context_budget": "9000"}},
    )

    assert _load_deepthink_overrides(repo) == {
        "model": "user-deepthink-model",
        "context_budget": "9000",
    }


def test_voice_section_falls_through_whole_when_repo_omits_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "x"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"voice": {"stt_model": "user-stt-model"}})

    assert _load_voice_overrides(repo) == {"stt_model": "user-stt-model"}


def test_lobes_url_shape_via_nested_url_key_still_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nested ``{"lobes": {"url": ...}}`` shape also participates in the
    per-key merge (``lobes`` is still just one top-level key)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "x"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"lobes": {"url": "http://nested-gateway:9006"}})

    assert _load_lobes_override(repo) == "http://nested-gateway:9006"


# ---------------------------------------------------------------------------
# configdir.resolve_files itself: every match, precedence order, never raises.
# ---------------------------------------------------------------------------


def test_resolve_files_returns_all_matches_precedence_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_cfg_dir = repo / ".colleague"
    repo_cfg_dir.mkdir()
    (repo_cfg_dir / "config.json").write_text("{}", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    home_cfg_dir = home / ".colleague"
    home_cfg_dir.mkdir()
    (home_cfg_dir / "config.json").write_text("{}", encoding="utf-8")

    matches = resolve_files(repo, "config.json", user_home=home)
    assert matches == [repo_cfg_dir / "config.json", home_cfg_dir / "config.json"]


def test_resolve_files_includes_legacy_root_in_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    legacy_cfg_dir = repo / ".convertible"
    legacy_cfg_dir.mkdir()
    (legacy_cfg_dir / "config.json").write_text("{}", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    home_cfg_dir = home / ".colleague"
    home_cfg_dir.mkdir()
    (home_cfg_dir / "config.json").write_text("{}", encoding="utf-8")

    matches = resolve_files(repo, "config.json", user_home=home)
    assert matches == [legacy_cfg_dir / "config.json", home_cfg_dir / "config.json"]


def test_resolve_files_empty_when_no_matches(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    assert resolve_files(repo, "config.json", user_home=home) == []


def test_resolve_files_skips_non_file_candidates(tmp_path: Path) -> None:
    """A same-named directory (not a file) is never returned as a match."""
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_cfg_dir = repo / ".colleague"
    (repo_cfg_dir / "config.json").mkdir(parents=True)  # a dir, not a file

    home = tmp_path / "home"
    home.mkdir()

    assert resolve_files(repo, "config.json", user_home=home) == []


# ---------------------------------------------------------------------------
# Chain overrides ride the per-key merge (#334 / PR #338 review).
# ---------------------------------------------------------------------------


def test_repo_config_without_compaction_cap_falls_through_to_user_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo config.json that omits the chain keys must not shadow user-level ones.

    _load_chain_overrides used to read via resolve_file (whole-file shadowing,
    the same bug _merged_config_json fixed for lobes/senses): a repo-level
    config.json defining only e.g. ``model`` hid a user-level
    ``compaction_cap``/``max_episodes``/``until_done`` entirely (PR #338
    review finding 2).
    """
    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"compaction_cap": 2, "max_episodes": 7})
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "some-model"})  # omits every chain key

    from colleague.config import _load_chain_overrides

    until_done, max_episodes, compaction_cap = _load_chain_overrides(repo)
    assert compaction_cap == "2"
    assert max_episodes == "7"
    assert until_done is None


def test_repo_chain_keys_still_beat_user_level_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-key precedence is unchanged: a repo-level key wins over user-level."""
    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"compaction_cap": 9})
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"compaction_cap": 3})

    from colleague.config import _load_chain_overrides

    _, _, compaction_cap = _load_chain_overrides(repo)
    assert compaction_cap == "3"

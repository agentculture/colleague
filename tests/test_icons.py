"""Icons vocabulary module: resolve emoji | ascii | none and apply to panel labels.

Tests the public API:
- ICON_MODES, DEFAULT_ICON_MODE constants
- resolve_icons(flag, repo_path) -> str  (precedence: flag > env > config.json > default)
- ICONS vocabulary dict
- icon(key, mode) -> str
- label(text, key, mode) -> str

Acceptance:
1. ascii/none produce NO emoji characters in any label.
2. Default emoji output is glyph + space + text.
3. Resolution follows flag > env > config.json > default precedence.
4. Legacy CONVERTIBLE_ICONS works when COLLEAGUE_ICONS unset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from colleague import icons

# ── constants ────────────────────────────────────────────────────────────────


def test_icon_modes_constant() -> None:
    assert icons.ICON_MODES == ("emoji", "ascii", "none")


def test_default_icon_mode_constant() -> None:
    assert icons.DEFAULT_ICON_MODE == "emoji"


# ── resolve_icons: default ──────────────────────────────────────────────────


def test_resolve_default_when_nothing_set(tmp_path, monkeypatch) -> None:
    """With no flag, env, or config, resolve returns 'emoji'."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    assert icons.resolve_icons(repo_path=tmp_path) == "emoji"


def test_resolve_default_explicit_none_flag(tmp_path, monkeypatch) -> None:
    """flag=None means 'not set', so fall through to env/config/default."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    assert icons.resolve_icons(flag=None, repo_path=tmp_path) == "emoji"


# ── resolve_icons: flag precedence ──────────────────────────────────────────


def test_resolve_flag_wins_over_env(tmp_path, monkeypatch) -> None:
    """Explicit flag beats env var."""
    monkeypatch.setenv("COLLEAGUE_ICONS", "ascii")
    assert icons.resolve_icons(flag="none", repo_path=tmp_path) == "none"


def test_resolve_flag_case_insensitive(tmp_path) -> None:
    """Flag values are accepted case-insensitively."""
    assert icons.resolve_icons(flag="ASCII", repo_path=tmp_path) == "ascii"
    assert icons.resolve_icons(flag="NONE", repo_path=tmp_path) == "none"
    assert icons.resolve_icons(flag="Emoji", repo_path=tmp_path) == "emoji"


def test_resolve_flag_invalid_falls_to_default(tmp_path) -> None:
    """Unrecognized flag value falls through to default 'emoji'."""
    assert icons.resolve_icons(flag="unicode", repo_path=tmp_path) == "emoji"


# ── resolve_icons: env precedence ───────────────────────────────────────────


def test_resolve_env_colleague_icons(tmp_path, monkeypatch) -> None:
    """COLLEAGUE_ICONS env var is picked up."""
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    monkeypatch.setenv("COLLEAGUE_ICONS", "ascii")
    assert icons.resolve_icons(repo_path=tmp_path) == "ascii"


def test_resolve_env_legacy_convertible_icons(tmp_path, monkeypatch) -> None:
    """CONVERTIBLE_ICONS works as a legacy fallback when COLLEAGUE_ICONS unset."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.setenv("CONVERTIBLE_ICONS", "none")
    assert icons.resolve_icons(repo_path=tmp_path) == "none"


def test_resolve_env_colleague_beats_legacy(tmp_path, monkeypatch) -> None:
    """COLLEAGUE_ICONS takes precedence over CONVERTIBLE_ICONS."""
    monkeypatch.setenv("COLLEAGUE_ICONS", "ascii")
    monkeypatch.setenv("CONVERTIBLE_ICONS", "none")
    assert icons.resolve_icons(repo_path=tmp_path) == "ascii"


def test_resolve_env_invalid_falls_to_default(tmp_path, monkeypatch) -> None:
    """Unrecognized env value falls through to default."""
    monkeypatch.setenv("COLLEAGUE_ICONS", "braille")
    assert icons.resolve_icons(repo_path=tmp_path) == "emoji"


# ── resolve_icons: config.json precedence ───────────────────────────────────


def _write_config(tmp_path: Path, payload: dict) -> None:
    """Write a .colleague/config.json inside *tmp_path*."""
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_config_icons(tmp_path, monkeypatch) -> None:
    """icons key in config.json is picked up."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    _write_config(tmp_path, {"icons": "ascii"})
    assert icons.resolve_icons(repo_path=tmp_path) == "ascii"


def test_resolve_config_overrides_default(tmp_path, monkeypatch) -> None:
    """Config.json value overrides the default."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    _write_config(tmp_path, {"icons": "none"})
    assert icons.resolve_icons(repo_path=tmp_path) == "none"


def test_resolve_env_overrides_config(tmp_path, monkeypatch) -> None:
    """Env var overrides config.json."""
    _write_config(tmp_path, {"icons": "none"})
    monkeypatch.setenv("COLLEAGUE_ICONS", "ascii")
    assert icons.resolve_icons(repo_path=tmp_path) == "ascii"


def test_resolve_config_invalid_falls_to_default(tmp_path, monkeypatch) -> None:
    """Unrecognized config value falls through to default."""
    _write_config(tmp_path, {"icons": "unicode"})
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    assert icons.resolve_icons(repo_path=tmp_path) == "emoji"


def test_resolve_config_missing_icons_key(tmp_path, monkeypatch) -> None:
    """Config without 'icons' key falls through to default."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    _write_config(tmp_path, {"base_url": "http://example/v1"})
    assert icons.resolve_icons(repo_path=tmp_path) == "emoji"


def test_resolve_config_malformed_json(tmp_path, monkeypatch) -> None:
    """Malformed config.json is ignored, falls through to default."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("{broken", encoding="utf-8")
    assert icons.resolve_icons(repo_path=tmp_path) == "emoji"


# ── full precedence chain ───────────────────────────────────────────────────


def test_full_precedence_flag_over_env_over_config(tmp_path, monkeypatch) -> None:
    """flag > env > config.json > default."""
    _write_config(tmp_path, {"icons": "none"})
    monkeypatch.setenv("COLLEAGUE_ICONS", "emoji")
    assert icons.resolve_icons(flag="ascii", repo_path=tmp_path) == "ascii"


# ── ICONS vocabulary ────────────────────────────────────────────────────────


def test_icons_has_required_keys() -> None:
    """ICONS covers the required semantic keys."""
    required = {
        "policy",
        "context",
        "capacity",
        "mode",
        "ledger",
        "activity",
        "next",
        "ok",
        "warn",
        "run",
        "idle",
    }
    assert required.issubset(set(icons.ICONS.keys()))


def test_icons_modes_covered() -> None:
    """Each semantic key has entries for all three modes."""
    for key, modes in icons.ICONS.items():
        for mode in icons.ICON_MODES:
            assert mode in modes, f"Key '{key}' missing mode '{mode}'"


def test_icons_none_mode_is_empty_string() -> None:
    """For mode 'none', every glyph is the empty string."""
    for key, modes in icons.ICONS.items():
        assert modes["none"] == "", f"Key '{key}' mode 'none' should be '', got {modes['none']!r}"


def test_icons_emoji_mode_is_non_empty() -> None:
    """For mode 'emoji', every glyph is a non-empty string."""
    for key, modes in icons.ICONS.items():
        assert modes["emoji"], f"Key '{key}' mode 'emoji' should be non-empty"


def test_icons_ascii_mode_is_non_empty() -> None:
    """For mode 'ascii', every glyph is a non-empty string."""
    for key, modes in icons.ICONS.items():
        assert modes["ascii"], f"Key '{key}' mode 'ascii' should be non-empty"


# ── icon() ───────────────────────────────────────────────────────────────────


def test_icon_known_key_emoji() -> None:
    """icon('policy', 'emoji') returns the emoji glyph."""
    result = icons.icon("policy", "emoji")
    assert result == icons.ICONS["policy"]["emoji"]


def test_icon_known_key_ascii() -> None:
    """icon('policy', 'ascii') returns the ASCII glyph."""
    result = icons.icon("policy", "ascii")
    assert result == icons.ICONS["policy"]["ascii"]


def test_icon_known_key_none() -> None:
    """icon('policy', 'none') returns empty string."""
    assert icons.icon("policy", "none") == ""


def test_icon_unknown_key_returns_empty() -> None:
    """icon with an unknown key returns empty string."""
    assert icons.icon("nonexistent", "emoji") == ""


def test_icon_none_mode_always_empty() -> None:
    """icon always returns '' for mode 'none', regardless of key."""
    assert icons.icon("policy", "none") == ""
    assert icons.icon("nonexistent", "none") == ""


# ── label() ──────────────────────────────────────────────────────────────────


def test_label_emoji_composes_glyph_space_text() -> None:
    """label with emoji mode returns 'glyph text'."""
    glyph = icons.ICONS["policy"]["emoji"]
    result = icons.label("Run policy", "policy", "emoji")
    assert result == f"{glyph} Run policy"


def test_label_none_returns_text_unchanged() -> None:
    """label with none mode returns text unchanged."""
    assert icons.label("Run policy", "policy", "none") == "Run policy"


def test_label_unknown_key_returns_text_unchanged() -> None:
    """label with unknown key returns text unchanged."""
    assert icons.label("Run policy", "nonexistent", "emoji") == "Run policy"


def test_label_ascii_composes_glyph_space_text() -> None:
    """label with ascii mode returns 'glyph text'."""
    glyph = icons.ICONS["policy"]["ascii"]
    result = icons.label("Run policy", "policy", "ascii")
    assert result == f"{glyph} Run policy"


# ── acceptance: no emoji in ascii/none labels ───────────────────────────────


_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u26FF\u2700-\u27BF]")


def test_no_emoji_in_ascii_labels() -> None:
    """No emoji character appears in any ascii-mode label."""
    for key in icons.ICONS:
        lbl = icons.label("sample text", key, "ascii")
        assert _EMOJI_RE.search(lbl) is None, f"Emoji found in ascii label for key '{key}': {lbl!r}"


def test_no_emoji_in_none_labels() -> None:
    """No emoji character appears in any none-mode label."""
    for key in icons.ICONS:
        lbl = icons.label("some text", key, "none")
        assert _EMOJI_RE.search(lbl) is None, f"Emoji found in none label for key '{key}': {lbl!r}"
        assert lbl == "some text", f"none label should equal input text, got {lbl!r}"


# ── acceptance: emoji default is byte-identical ─────────────────────────────


def test_emoji_label_byte_identical() -> None:
    """Default emoji label is glyph + space + text."""
    glyph = icons.ICONS["policy"]["emoji"]
    expected = f"{glyph} Run policy"
    assert icons.label("Run policy", "policy", "emoji") == expected


# ── acceptance: strict no-op when unset ─────────────────────────────────────


def test_strict_noop_when_unset(tmp_path, monkeypatch) -> None:
    """When nothing is set, resolve_icons returns 'emoji' (the default)."""
    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    # No config file present
    assert icons.resolve_icons(repo_path=tmp_path) == "emoji"


# ── per-key merge: user-level icons survives repo config that omits it ──────


def _arm_home(tmp_path: Path, monkeypatch) -> Path:
    """Point COLLEAGUE_HOME at a fresh, test-owned "home" directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("COLLEAGUE_HOME", str(home))
    return home


def test_user_icons_survives_repo_config_that_omits_key(tmp_path, monkeypatch) -> None:
    """A user-level config.json icons value survives a repo config.json that
    omits the key — per-key merge, not whole-file shadowing (task t5)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"model": "some-model"})  # no 'icons' key

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"icons": "ascii"})

    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    assert icons.resolve_icons(repo_path=repo) == "ascii"


def test_repo_icons_still_beats_user_icons(tmp_path, monkeypatch) -> None:
    """Explicit > env > config precedence unchanged: a repo-level 'icons'
    key still wins over a user-level one (task t5)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_config(repo, {"icons": "none"})

    home = _arm_home(tmp_path, monkeypatch)
    _write_config(home, {"icons": "ascii"})

    monkeypatch.delenv("COLLEAGUE_ICONS", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ICONS", raising=False)
    assert icons.resolve_icons(repo_path=repo) == "none"

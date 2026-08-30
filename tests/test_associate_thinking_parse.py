"""``COLLEAGUE_ASSOCIATE_THINKING`` / config.json ``associate.thinking`` (t23):
only explicit spellings flip the profile's ``enable_thinking``; anything else
is IGNORED so a typo never silently disables thinking (Qodo 5 on PR #464).
Companion to tests/test_associate_sampling.py (left untouched)."""

from __future__ import annotations

import pytest

from colleague.associate_config import ASSOCIATE_PROFILES, resolve_associate_profile


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "True", "yes", "YES", "on", "On", " on "])
def test_explicit_true_spellings_turn_thinking_on(monkeypatch, raw):
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_PROFILE", "triage")  # thinking off by default
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_THINKING", raw)
    prof = resolve_associate_profile({})
    assert prof.name == "triage"
    assert prof.enable_thinking is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "False", "no", "NO", "off", "Off", " off "])
def test_explicit_false_spellings_turn_thinking_off(monkeypatch, raw):
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_THINKING", raw)
    prof = resolve_associate_profile({})
    assert prof.name == "depth"
    assert prof.enable_thinking is False


@pytest.mark.parametrize("raw", ["treu", "flase", "maybe", "2", "y", "n", "t", "f", "enabled"])
def test_unknown_spelling_keeps_the_depth_profiles_true(monkeypatch, raw):
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_THINKING", raw)
    prof = resolve_associate_profile({})
    assert prof == ASSOCIATE_PROFILES["depth"]
    assert prof.enable_thinking is True


def test_unknown_spelling_keeps_the_triage_profiles_false(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_PROFILE", "triage")
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_THINKING", "treu")
    prof = resolve_associate_profile({})
    assert prof == ASSOCIATE_PROFILES["triage"]
    assert prof.enable_thinking is False


def test_blank_value_is_ignored(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_THINKING", "   ")
    assert resolve_associate_profile({}).enable_thinking is True


def test_config_json_section_follows_the_same_rule(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_THINKING", raising=False)
    assert resolve_associate_profile({"thinking": "treu"}).enable_thinking is True
    assert resolve_associate_profile({"thinking": "OFF"}).enable_thinking is False
    assert resolve_associate_profile({"thinking": "Yes"}).enable_thinking is True
    # A JSON boolean arrives stringified by load_associate_overrides ("True"/"False").
    assert resolve_associate_profile({"thinking": "False"}).enable_thinking is False
    assert resolve_associate_profile({"thinking": "True"}).enable_thinking is True


def test_env_typo_does_not_override_a_valid_section_value(monkeypatch):
    """Env wins per key, but an ignored env value leaves the section's value alone."""
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_THINKING", "treu")
    # _pick returns the env value (non-empty) — it is the parsed result that is
    # ignored, so the profile default stands rather than the section's "false".
    prof = resolve_associate_profile({"thinking": "false"})
    assert prof.enable_thinking is True

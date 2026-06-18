"""Tests for subagent depth cap and total-agent budget config fields."""

import pytest

from colleague.config import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_FANOUT,
    MAX_SUBAGENT_TOTAL,
    EngineConfig,
)


class TestModuleConstants:
    """Module-level constants for subagent bounds."""

    def test_max_subagent_depth_is_4(self):
        assert MAX_SUBAGENT_DEPTH == 4

    def test_max_subagent_total_is_24(self):
        assert MAX_SUBAGENT_TOTAL == 24

    def test_max_subagent_fanout_unchanged(self):
        assert MAX_SUBAGENT_FANOUT == 4


class TestEngineConfigDefaults:
    """EngineConfig default values for the new fields."""

    def test_default_subagent_depth(self):
        cfg = EngineConfig()
        assert cfg.subagent_depth == 4

    def test_default_subagent_total(self):
        cfg = EngineConfig()
        assert cfg.subagent_total == 24


class TestEngineConfigResolveEnv:
    """resolve() honours COLLEAGUE_SUBAGENT_DEPTH and COLLEAGUE_SUBAGENT_TOTAL env vars."""

    def test_env_var_subagent_depth(self, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_DEPTH", "6")
        cfg = EngineConfig.resolve()
        assert cfg.subagent_depth == 6

    def test_env_var_subagent_total(self, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_TOTAL", "50")
        cfg = EngineConfig.resolve()
        assert cfg.subagent_total == 50

    def test_env_var_both(self, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_DEPTH", "8")
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_TOTAL", "100")
        cfg = EngineConfig.resolve()
        assert cfg.subagent_depth == 8
        assert cfg.subagent_total == 100


class TestEngineConfigResolveSubagentCapsAreEnvOnly:
    """``subagent_depth`` / ``subagent_total`` are env-only knobs (no CLI flag, no
    production caller), kept off ``resolve``'s signature to hold it under the
    SonarCloud S107 parameter ceiling — exactly like ``temperature`` / ``timeout``.
    They resolve from the env var (then the built-in default); there is no
    explicit ``resolve(...)`` keyword for them."""

    def test_resolve_rejects_explicit_subagent_depth_kwarg(self):
        with pytest.raises(TypeError):
            EngineConfig.resolve(subagent_depth=3)

    def test_resolve_rejects_explicit_subagent_total_kwarg(self):
        with pytest.raises(TypeError):
            EngineConfig.resolve(subagent_total=10)

    def test_env_var_drives_resolution(self, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_DEPTH", "6")
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_TOTAL", "50")
        cfg = EngineConfig.resolve()
        assert cfg.subagent_depth == 6
        assert cfg.subagent_total == 50


class TestEngineConfigToDict:
    """to_dict() includes the new fields."""

    def test_to_dict_includes_subagent_depth(self):
        cfg = EngineConfig()
        d = cfg.to_dict()
        assert "subagent_depth" in d
        assert d["subagent_depth"] == 4

    def test_to_dict_includes_subagent_total(self):
        cfg = EngineConfig()
        d = cfg.to_dict()
        assert "subagent_total" in d
        assert d["subagent_total"] == 24

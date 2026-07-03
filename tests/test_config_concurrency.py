"""Tests for subagent concurrency configuration."""

import os

from colleague.config import EngineConfig, ResolveOverrides, effective_concurrency


class TestEngineConfigConcurrency:
    """Test subagent_concurrency field resolution in EngineConfig."""

    def test_subagent_concurrency_default(self):
        """subagent_concurrency defaults to 1."""
        config = EngineConfig()
        assert config.subagent_concurrency == 1

    def test_subagent_concurrency_resolve_default(self):
        """EngineConfig.resolve() defaults subagent_concurrency to 1 when no env set."""
        # Clear any env vars that might exist
        env_backup = {}
        for key in ["COLLEAGUE_SUBAGENT_CONCURRENCY", "CONVERTIBLE_SUBAGENT_CONCURRENCY"]:
            env_backup[key] = os.environ.pop(key, None)
        try:
            config = EngineConfig.resolve()
            assert config.subagent_concurrency == 1
        finally:
            for key, value in env_backup.items():
                if value is not None:
                    os.environ[key] = value

    def test_subagent_concurrency_from_colleague_env(self, monkeypatch):
        """subagent_concurrency resolves from COLLEAGUE_SUBAGENT_CONCURRENCY."""
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_CONCURRENCY", "3")
        config = EngineConfig.resolve()
        assert config.subagent_concurrency == 3

    def test_subagent_concurrency_from_convertible_env_fallback(self, monkeypatch):
        """subagent_concurrency falls back to CONVERTIBLE_SUBAGENT_CONCURRENCY."""
        monkeypatch.delenv("COLLEAGUE_SUBAGENT_CONCURRENCY", raising=False)
        monkeypatch.setenv("CONVERTIBLE_SUBAGENT_CONCURRENCY", "2")
        config = EngineConfig.resolve()
        assert config.subagent_concurrency == 2

    def test_subagent_concurrency_colleague_takes_precedence(self, monkeypatch):
        """COLLEAGUE_SUBAGENT_CONCURRENCY takes precedence over CONVERTIBLE."""
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_CONCURRENCY", "3")
        monkeypatch.setenv("CONVERTIBLE_SUBAGENT_CONCURRENCY", "2")
        config = EngineConfig.resolve()
        assert config.subagent_concurrency == 3

    def test_subagent_concurrency_explicit_arg(self):
        """Explicit subagent_concurrency arg in resolve() takes highest precedence."""
        config = EngineConfig.resolve(overrides=ResolveOverrides(subagent_concurrency=5))
        assert config.subagent_concurrency == 5

    def test_subagent_concurrency_empty_env_defaults(self, monkeypatch):
        """Empty COLLEAGUE_SUBAGENT_CONCURRENCY env var defaults to 1."""
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_CONCURRENCY", "")
        config = EngineConfig.resolve()
        assert config.subagent_concurrency == 1

    def test_subagent_concurrency_non_numeric_env_defaults(self, monkeypatch):
        """Non-numeric COLLEAGUE_SUBAGENT_CONCURRENCY env var defaults to 1."""
        monkeypatch.setenv("COLLEAGUE_SUBAGENT_CONCURRENCY", "not_a_number")
        # Should not raise, should default to 1
        config = EngineConfig.resolve()
        assert config.subagent_concurrency == 1


class TestEffectiveConcurrency:
    """Test the effective_concurrency clamping helper."""

    def test_effective_concurrency_one(self):
        """effective_concurrency(1) returns 1."""
        assert effective_concurrency(1) == 1

    def test_effective_concurrency_three(self):
        """effective_concurrency(3) returns 3 (max allowed)."""
        assert effective_concurrency(3) == 3

    def test_effective_concurrency_zero_clamps_to_one(self):
        """effective_concurrency(0) clamps to 1."""
        assert effective_concurrency(0) == 1

    def test_effective_concurrency_negative_clamps_to_one(self):
        """effective_concurrency(-5) clamps to 1."""
        assert effective_concurrency(-5) == 1

    def test_effective_concurrency_large_clamps_to_max(self):
        """effective_concurrency(10) clamps to 3 (MAX_SUBAGENT_FANOUT - 1)."""
        assert effective_concurrency(10) == 3

    def test_effective_concurrency_very_large_clamps_to_max(self):
        """effective_concurrency(100) clamps to 3."""
        assert effective_concurrency(100) == 3

    def test_effective_concurrency_two(self):
        """effective_concurrency(2) returns 2."""
        assert effective_concurrency(2) == 2

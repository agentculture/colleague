"""EngineConfig.subagent_spawn field + depth/fanout constants."""

from __future__ import annotations

from colleague.config import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_FANOUT,
    EngineConfig,
)


def test_subagent_spawn_defaults_to_none() -> None:
    """EngineConfig.subagent_spawn defaults to None."""
    cfg = EngineConfig.resolve()
    assert cfg.subagent_spawn is None


def test_subagent_spawn_excluded_from_eq() -> None:
    """Two configs that differ only in subagent_spawn are equal (compare=False)."""
    cfg1 = EngineConfig.resolve()
    cfg2 = EngineConfig.resolve()

    # Set one to a mock callable
    cfg2.subagent_spawn = lambda: None

    # They should still be equal because subagent_spawn has compare=False
    assert cfg1 == cfg2


def test_subagent_spawn_excluded_from_repr() -> None:
    """repr() does not mention subagent_spawn (repr=False)."""
    cfg = EngineConfig.resolve()
    cfg.subagent_spawn = lambda: None

    repr_str = repr(cfg)
    assert "subagent_spawn" not in repr_str


def test_subagent_spawn_excluded_from_to_dict() -> None:
    """subagent_spawn does not appear in to_dict() output."""
    cfg = EngineConfig.resolve()
    cfg.subagent_spawn = lambda: None

    snapshot = cfg.to_dict()
    assert "subagent_spawn" not in snapshot


def test_to_dict_has_expected_keys() -> None:
    """to_dict() contains exactly the serializable config keys (unchanged from today)."""
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()

    expected_keys = {
        "base_url",
        "model",
        "max_steps",
        "temperature",
        "timeout",
        "context_budget_tokens",
        "autosplit_target_tokens",
        "fillline_threshold",
        "fanout_files",
        "plan_offer_tokens",
        "max_continue_nudges",
        "synthesis_reserve_steps",
        "max_output_chars",
        "lint",
        "lint_fix_retries",
        "testintegrity",
        "testintegrity_fix_retries",
        "testintegrity_reviewer_model",
        "affected_tests",
        "affected_tests_fix_retries",
        "affected_tests_depth",
        "affected_tests_max_files",
    }
    assert set(snapshot.keys()) == expected_keys


def test_max_subagent_depth_constant() -> None:
    """MAX_SUBAGENT_DEPTH is defined and equals 2."""
    assert MAX_SUBAGENT_DEPTH == 2


def test_max_subagent_fanout_constant() -> None:
    """MAX_SUBAGENT_FANOUT is defined and equals 4."""
    assert MAX_SUBAGENT_FANOUT == 4

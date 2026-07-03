"""Engine config resolution: explicit > CONVERTIBLE_* > OPENAI_* > default."""

from __future__ import annotations

import pytest

from colleague.config import EngineConfig, ResolveOverrides, resolve_engine


def test_defaults_point_at_vllm_reference() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://localhost:8001/v1"
    assert cfg.model == "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"
    assert cfg.api_key == "EMPTY"
    assert cfg.max_steps == 40


def test_explicit_args_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_BASE_URL", "http://env:9/v1")
    cfg = EngineConfig.resolve(base_url="http://explicit:1/v1")
    assert cfg.base_url == "http://explicit:1/v1"


def test_colleague_env_wins_over_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai/v1")
    monkeypatch.setenv("CONVERTIBLE_BASE_URL", "http://colleague/v1")
    assert EngineConfig.resolve().base_url == "http://colleague/v1"


def test_openai_env_used_as_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONVERTIBLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")
    assert EngineConfig.resolve().api_key == "sk-fallback"


def test_numeric_env_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_MAX_STEPS", "7")
    assert EngineConfig.resolve().max_steps == 7


def test_fanout_files_knob(monkeypatch: pytest.MonkeyPatch) -> None:
    """#188: the mapping fan-out files-read trigger N is env-tunable (parked v1)."""
    assert EngineConfig.resolve().fanout_files == 12  # default
    assert (
        EngineConfig.resolve(overrides=ResolveOverrides(fanout_files=3)).fanout_files == 3
    )  # explicit
    monkeypatch.setenv("COLLEAGUE_FANOUT_FILES", "5")
    assert EngineConfig.resolve().fanout_files == 5  # env


def test_max_continue_nudges_knob(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configurable continue-nudge cap: default 2, env-tunable, explicit flag wins."""
    assert EngineConfig.resolve().max_continue_nudges == 2  # default
    monkeypatch.setenv("COLLEAGUE_MAX_CONTINUE_NUDGES", "5")
    assert EngineConfig.resolve().max_continue_nudges == 5  # env
    assert (
        EngineConfig.resolve(overrides=ResolveOverrides(max_continue_nudges=3)).max_continue_nudges
        == 3
    )  # explicit wins over env
    monkeypatch.setenv("CONVERTIBLE_MAX_CONTINUE_NUDGES", "7")
    monkeypatch.delenv("COLLEAGUE_MAX_CONTINUE_NUDGES", raising=False)
    assert EngineConfig.resolve().max_continue_nudges == 7  # CONVERTIBLE fallback


def test_to_dict_redacts_api_key() -> None:
    cfg = EngineConfig.resolve(api_key="sk-secret")
    snapshot = cfg.to_dict()
    assert "api_key" not in snapshot
    assert "sk-secret" not in str(snapshot)


# ---------------------------------------------------------------------------
# Engine selection: explicit > CONVERTIBLE_ENGINE > vllm-openai (never mock).
# ---------------------------------------------------------------------------


def test_resolve_engine_default_is_real_not_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare invocation must NOT silently fall back to the no-op mock (#53)."""
    monkeypatch.delenv("CONVERTIBLE_ENGINE", raising=False)
    engine = resolve_engine(None)
    assert engine == "vllm-openai"
    assert engine != "mock"


def test_resolve_engine_explicit_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "vllm-openai")
    assert resolve_engine("mock") == "mock"


def test_resolve_engine_env_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "mock")
    assert resolve_engine(None) == "mock"


def test_resolve_engine_blank_env_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty env var must not win — it falls through to the built-in default."""
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "")
    assert resolve_engine(None) == "vllm-openai"


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_resolve_engine_blank_explicit_falls_through_to_env(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """An explicit but blank --engine (e.g. --engine '' or --engine "$UNSET") must
    fall through to CONVERTIBLE_ENGINE, not resolve to an invalid engine name."""
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "mock")
    assert resolve_engine(blank) == "mock"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_resolve_engine_blank_explicit_and_env_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """Blank explicit AND blank/unset env → the built-in default, never ''."""
    monkeypatch.setenv("CONVERTIBLE_ENGINE", blank)
    assert resolve_engine(blank) == "vllm-openai"


def test_resolve_engine_strips_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONVERTIBLE_ENGINE", raising=False)
    assert resolve_engine("  mock  ") == "mock"


# ---------------------------------------------------------------------------
# autosplit_target_tokens: tunable split-capacity knob (issue #151).
# ---------------------------------------------------------------------------


def test_autosplit_target_tokens_default() -> None:
    """autosplit_target_tokens defaults to 1_000_000 when no env or arg is set."""
    cfg = EngineConfig.resolve()
    assert cfg.autosplit_target_tokens == 1_000_000


def test_autosplit_target_tokens_colleague_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_AUTOSPLIT_TARGET overrides the default."""
    monkeypatch.setenv("COLLEAGUE_AUTOSPLIT_TARGET", "500000")
    monkeypatch.delenv("CONVERTIBLE_AUTOSPLIT_TARGET", raising=False)
    cfg = EngineConfig.resolve()
    assert cfg.autosplit_target_tokens == 500_000


def test_autosplit_target_tokens_colleague_wins_over_convertible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COLLEAGUE_AUTOSPLIT_TARGET is preferred over CONVERTIBLE_AUTOSPLIT_TARGET."""
    monkeypatch.setenv("COLLEAGUE_AUTOSPLIT_TARGET", "300000")
    monkeypatch.setenv("CONVERTIBLE_AUTOSPLIT_TARGET", "999999")
    cfg = EngineConfig.resolve()
    assert cfg.autosplit_target_tokens == 300_000


def test_autosplit_target_tokens_explicit_wins_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit resolve(overrides=ResolveOverrides(autosplit_target_tokens=...))
    arg beats the env var."""
    monkeypatch.setenv("COLLEAGUE_AUTOSPLIT_TARGET", "500000")
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(autosplit_target_tokens=800_000))
    assert cfg.autosplit_target_tokens == 800_000


def test_autosplit_target_tokens_in_to_dict() -> None:
    """autosplit_target_tokens appears in to_dict() snapshot."""
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(autosplit_target_tokens=750_000))
    snapshot = cfg.to_dict()
    assert "autosplit_target_tokens" in snapshot
    assert snapshot["autosplit_target_tokens"] == 750_000


# ---------------------------------------------------------------------------
# autosplit_children: derived-children helper (issue #151).
# ---------------------------------------------------------------------------


def test_autosplit_children_clamps_to_max_fanout_minus_one() -> None:
    """1_000_000 / 192_000 = ceil(5.2) = 6, clamped down to MAX_SUBAGENT_FANOUT - 1 == 3."""
    from colleague.config import MAX_SUBAGENT_FANOUT, autosplit_children

    result = autosplit_children(1_000_000, 192_000)
    assert result == MAX_SUBAGENT_FANOUT - 1


def test_autosplit_children_returns_one_for_small_target() -> None:
    """200_000 / 250_000 = ceil(0.8) = 1."""
    from colleague.config import autosplit_children

    assert autosplit_children(200_000, 250_000) == 1


def test_autosplit_children_returns_two_for_equal_halves() -> None:
    """500_000 / 250_000 = ceil(2.0) = 2."""
    from colleague.config import autosplit_children

    assert autosplit_children(500_000, 250_000) == 2


def test_autosplit_children_non_positive_budget_guard() -> None:
    """A non-positive per_child_budget returns MAX_SUBAGENT_FANOUT - 1."""
    from colleague.config import MAX_SUBAGENT_FANOUT, autosplit_children

    assert autosplit_children(10, 0) == MAX_SUBAGENT_FANOUT - 1


def test_autosplit_children_huge_target_no_overflow() -> None:
    """Regression (#151 Qodo): an absurd target uses integer ceiling math, never a float.

    ``math.ceil(target / budget)`` would raise OverflowError once ``target`` exceeds
    float range; integer ceiling division stays exact and clamps cleanly.
    """
    from colleague.config import MAX_SUBAGENT_FANOUT, autosplit_children

    huge = 10**400  # well beyond float range — float division would OverflowError
    assert autosplit_children(huge, 192_000) == MAX_SUBAGENT_FANOUT - 1

"""Dual-model deepthink config resolution (task t1).

Spec: docs/specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md
(claims c8/h1, c2/h11). Plan: docs/plans/2026-07-01-colleague-drives-with-two-minds
-a-fast-wide-window.md (task t1).

``EngineConfig.deepthink`` is an OPTIONAL second OpenAI-compatible endpoint the
runtime may escalate hard-reasoning turns to. It is resolved through the same
precedence pattern as every other knob in ``colleague/config.py``:

    COLLEAGUE_DEEPTHINK_* env (CONVERTIBLE_DEEPTHINK_* deprecated fallback)
    > a ``deepthink`` section in .colleague/config.json
    > absent (None).

Presence is keyed SOLELY on the resolved model being a non-empty,
non-whitespace string; base_url/api_key then default to the already-resolved
MAIN endpoint's own values, and context_budget defaults to 48000 (a
64K-window-sized share, matching the main model's 192000-for-256K
proportion). These tests intentionally use ARBITRARY endpoint/model names
(never a specific reference-rig model) to pin the endpoint-agnostic honesty
condition (h1): nothing in the design may hard-code a specific pair of models.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from colleague.config import DeepthinkConfig, EngineConfig

# Every env var that can influence a resolve() under test — main endpoint +
# deepthink — cleared per test so a developer's shell / CI environment can
# never leak into a resolution (mirrors test_config_file.py's isolation).
_ALL_ENV = (
    "COLLEAGUE_BASE_URL",
    "CONVERTIBLE_BASE_URL",
    "OPENAI_BASE_URL",
    "COLLEAGUE_API_KEY",
    "CONVERTIBLE_API_KEY",
    "OPENAI_API_KEY",
    "COLLEAGUE_MODEL",
    "CONVERTIBLE_MODEL",
    "COLLEAGUE_DEEPTHINK_MODEL",
    "CONVERTIBLE_DEEPTHINK_MODEL",
    "COLLEAGUE_DEEPTHINK_BASE_URL",
    "CONVERTIBLE_DEEPTHINK_BASE_URL",
    "COLLEAGUE_DEEPTHINK_API_KEY",
    "CONVERTIBLE_DEEPTHINK_API_KEY",
    "COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET",
    "CONVERTIBLE_DEEPTHINK_CONTEXT_BUDGET",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    # Prevent a real ~/.colleague/config.json on the dev/CI machine from being
    # picked up by configdir's user-level fallback (test_config_file.py idiom).
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Absent everywhere: deepthink is None, byte-identical to a pre-feature config.
# ---------------------------------------------------------------------------


def test_absent_everywhere_deepthink_is_none() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is None


def test_absent_everywhere_repo_path_still_none(tmp_path: Path) -> None:
    """No env, no deepthink config-file section (even with repo_path given)."""
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is None


def test_absent_to_dict_has_no_deepthink_key() -> None:
    snapshot = EngineConfig.resolve().to_dict()
    assert "deepthink" not in snapshot


def test_absent_field_for_field_identical_to_bare_default() -> None:
    """resolve() with nothing configured reproduces the dataclass's own bare
    defaults field-for-field (dataclass __eq__ over every compare=True field),
    proving the new deepthink field changed nothing else about resolution."""
    assert EngineConfig.resolve() == EngineConfig()


def test_absent_to_dict_matches_pre_deepthink_keys() -> None:
    """The full to_dict() key set is exactly what it was before this feature
    (no stray key added) when deepthink is not configured."""
    snapshot = EngineConfig.resolve().to_dict()
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
        "review_fanout_folders",
        "plan_offer_tokens",
        "max_continue_nudges",
        "synthesis_reserve_steps",
        "max_output_chars",
        "subagent_depth",
        "subagent_total",
        "lint",
        "memory",
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


# ---------------------------------------------------------------------------
# DeepthinkConfig shape: a frozen dataclass with exactly the four fields.
# ---------------------------------------------------------------------------


def test_deepthink_config_is_frozen_dataclass() -> None:
    dc = DeepthinkConfig(
        model="endpoint-alpha-model",
        base_url="http://endpoint-alpha/v1",
        api_key="key-alpha",
        context_budget=48000,
    )
    assert dc.model == "endpoint-alpha-model"
    assert dc.base_url == "http://endpoint-alpha/v1"
    assert dc.api_key == "key-alpha"
    assert dc.context_budget == 48000
    with pytest.raises(FrozenInstanceError):
        dc.model = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Env-only, config-file-only, and env-overrides-config-file.
# ---------------------------------------------------------------------------


def test_env_only_activates_deepthink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-beta-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "endpoint-beta-model"


def test_env_only_all_four_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-beta-model")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://endpoint-beta/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_API_KEY", "key-beta")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET", "32000")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink == DeepthinkConfig(
        model="endpoint-beta-model",
        base_url="http://endpoint-beta/v1",
        api_key="key-beta",
        context_budget=32000,
    )


def test_env_convertible_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deprecated CONVERTIBLE_DEEPTHINK_* fallback is honored, matching
    every other knob's rename back-compat."""
    monkeypatch.setenv("CONVERTIBLE_DEEPTHINK_MODEL", "endpoint-gamma-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "endpoint-gamma-model"


def test_config_file_only_activates_deepthink(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "deepthink": {
                "model": "endpoint-delta-model",
                "base_url": "http://endpoint-delta/v1",
                "api_key": "key-delta",
                "context_budget": 16000,
            }
        },
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink == DeepthinkConfig(
        model="endpoint-delta-model",
        base_url="http://endpoint-delta/v1",
        api_key="key-delta",
        context_budget=16000,
    )


def test_config_file_deepthink_absent_no_repo_path_needed_is_none() -> None:
    """No repo_path at all (the common no-config-file caller) → still None."""
    assert EngineConfig.resolve().deepthink is None


def test_config_file_without_deepthink_section_is_absent(tmp_path: Path) -> None:
    """A config.json with no ``deepthink`` key at all → deepthink stays None."""
    _write_config(tmp_path, {"base_url": "http://endpoint-epsilon/v1"})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is None


def test_env_overrides_config_file_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, {"deepthink": {"model": "endpoint-config-model"}})
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-env-model")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "endpoint-env-model"


def test_env_overrides_config_file_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        {
            "deepthink": {
                "model": "endpoint-zeta-model",
                "base_url": "http://endpoint-config/v1",
            }
        },
    )
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://endpoint-env/v1")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == "http://endpoint-env/v1"


def test_env_overrides_config_file_context_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        {"deepthink": {"model": "endpoint-eta-model", "context_budget": 20000}},
    )
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET", "24000")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.context_budget == 24000


# ---------------------------------------------------------------------------
# Defaults: base_url/api_key inherit the MAIN endpoint; context_budget = 48000.
# ---------------------------------------------------------------------------


def test_base_url_defaults_to_main_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-theta-model")
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://main-endpoint/v1")
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://main-endpoint/v1"
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == "http://main-endpoint/v1"


def test_api_key_defaults_to_main_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-iota-model")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-key")
    cfg = EngineConfig.resolve()
    assert cfg.api_key == "main-secret-key"
    assert cfg.deepthink is not None
    assert cfg.deepthink.api_key == "main-secret-key"


def test_base_url_and_api_key_default_with_explicit_main_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defaults inherit the RESOLVED main values even when those came from an
    explicit resolve(...) argument, not just env/config-file.

    There is no explicit resolve() kwarg for deepthink (env/config-file only,
    per the interface contract), so it is activated via env for this
    assertion; the main endpoint is supplied via explicit resolve() args.
    """
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-kappa-model")
    cfg = EngineConfig.resolve(
        base_url="http://explicit-main/v1",
        api_key="explicit-main-key",
        model="explicit-main-model",
    )
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == "http://explicit-main/v1"
    assert cfg.deepthink.api_key == "explicit-main-key"


def test_context_budget_default_is_48000(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-lambda-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.context_budget == 48000


def test_explicit_deepthink_base_url_beats_main_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-mu-model")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://deepthink-own-endpoint/v1")
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://main-endpoint/v1")
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://main-endpoint/v1"
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == "http://deepthink-own-endpoint/v1"


# ---------------------------------------------------------------------------
# Malformed context_budget never raises; falls back to the default.
# ---------------------------------------------------------------------------


def test_malformed_env_context_budget_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-nu-model")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET", "not-a-number")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.context_budget == 48000


def test_malformed_config_file_context_budget_falls_back_to_default(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"deepthink": {"model": "endpoint-xi-model", "context_budget": "not-a-number"}},
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.context_budget == 48000


# ---------------------------------------------------------------------------
# Redaction: the deepthink api_key never leaks through to_dict().
# ---------------------------------------------------------------------------


def test_to_dict_redacts_deepthink_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "endpoint-omicron-model")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_API_KEY", "sk-deepthink-super-secret")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "sk-main-super-secret")
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()
    assert "deepthink" in snapshot
    deepthink_snapshot = snapshot["deepthink"]
    assert isinstance(deepthink_snapshot, dict)
    assert "api_key" not in deepthink_snapshot
    # Neither the main nor the deepthink secret leaks anywhere in the snapshot.
    rendered = json.dumps(snapshot)
    assert "sk-deepthink-super-secret" not in rendered
    assert "sk-main-super-secret" not in rendered


def test_to_dict_deepthink_only_present_when_configured() -> None:
    assert "deepthink" not in EngineConfig.resolve().to_dict()


# ---------------------------------------------------------------------------
# Endpoint-agnostic: two arbitrary endpoints, no dependence on specific names.
# ---------------------------------------------------------------------------


def test_endpoint_agnostic_arbitrary_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any pair of OpenAI-compatible endpoints can play main and deepthink —
    nothing requires a specific reference-rig model/endpoint name."""
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://widget-server:9001/v1")
    monkeypatch.setenv("COLLEAGUE_MODEL", "widget-main-model")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://gadget-server:9002/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "gadget-deepthink-model")
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://widget-server:9001/v1"
    assert cfg.model == "widget-main-model"
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == "http://gadget-server:9002/v1"
    assert cfg.deepthink.model == "gadget-deepthink-model"


def test_config_py_diff_names_no_specific_reference_models() -> None:
    """The words lobes/gemma/qwen must not appear in the deepthink-config code
    this task added (grepped against the source directly, not just tests) —
    the design must not hard-code the reference rig's specific model names.

    Note: colleague/config.py's PRE-EXISTING built-in ``_DEFAULT_MODEL``
    already names a Qwen checkpoint (predates this feature and is unrelated to
    deepthink); this test scans only for the deepthink-specific identifiers
    added by this task, never the whole file, so it can't be defeated by that
    pre-existing unrelated default.
    """
    import inspect

    from colleague import config as config_module

    banned = ("lobes", "gemma", "qwen")
    deepthink_symbols = [
        config_module.DeepthinkConfig,
        config_module._load_deepthink_overrides,
        config_module._resolve_deepthink,
    ]
    for symbol in deepthink_symbols:
        source = inspect.getsource(symbol).lower()
        for word in banned:
            assert word not in source, f"{word!r} must not appear in {symbol!r}"


# ---------------------------------------------------------------------------
# Empty / whitespace COLLEAGUE_DEEPTHINK_MODEL is treated as absent.
# ---------------------------------------------------------------------------


def test_empty_env_model_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "")
    assert EngineConfig.resolve().deepthink is None


def test_whitespace_env_model_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "   ")
    assert EngineConfig.resolve().deepthink is None


def test_whitespace_config_file_model_is_absent(tmp_path: Path) -> None:
    _write_config(tmp_path, {"deepthink": {"model": "   "}})
    assert EngineConfig.resolve(repo_path=tmp_path).deepthink is None


def test_whitespace_model_is_absent_regardless_of_other_deepthink_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per the interface contract: presence is keyed SOLELY on the model — a
    whitespace-only model means absent even with base_url/api_key/budget set."""
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "  ")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://endpoint-pi/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_API_KEY", "key-pi")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET", "9999")
    assert EngineConfig.resolve().deepthink is None


def test_config_file_deepthink_section_without_model_key_is_absent(tmp_path: Path) -> None:
    """A deepthink section present but missing the model key entirely (only
    base_url set) is not dual-model — the model IS the presence signal."""
    _write_config(tmp_path, {"deepthink": {"base_url": "http://endpoint-rho/v1"}})
    assert EngineConfig.resolve(repo_path=tmp_path).deepthink is None


def test_model_is_stripped_of_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "  endpoint-sigma-model  ")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "endpoint-sigma-model"

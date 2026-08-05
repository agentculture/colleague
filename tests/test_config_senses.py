"""Senses config resolution (cortex/senses arc, task t3).

Spec: docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md
(claims c7, h2). Plan: docs/plans/2026-07-03-colleague-drives-with-a-cortex-and
-senses-it-resol.md (task t3).

``EngineConfig.senses`` is an OPTIONAL second OpenAI-compatible endpoint the
runtime may use as the multimodal front door (intake / speak-back), mirroring
``EngineConfig.deepthink`` field-for-field. It is resolved through the SAME
precedence pattern as every other knob in ``colleague/config.py``:

    COLLEAGUE_SENSES_* env (CONVERTIBLE_SENSES_* deprecated fallback)
    > a ``senses`` section in .colleague/config.json
    > absent (None).

Presence is keyed SOLELY on the resolved model being a non-empty,
non-whitespace string; base_url/api_key then default to the already-resolved
MAIN endpoint's own values, and context_budget defaults to 24000 (sized for
the senses model's 32768-token / 32K window — the same ~75% headroom ratio
deepthink uses for its own window). This task is explicitly SCOPED to
``env > config.json > absent`` only — the lobes discovery rung (t4) is not
built here, and deepthink's own resolution is untouched (pinned by running
the existing deepthink config tests unmodified alongside these).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from colleague.config import EngineConfig, SensesConfig

# Every env var that can influence a resolve() under test — main endpoint +
# senses — cleared per test so a developer's shell / CI environment can never
# leak into a resolution (mirrors test_deepthink_config.py's isolation).
_ALL_ENV = (
    "COLLEAGUE_BASE_URL",
    "CONVERTIBLE_BASE_URL",
    "OPENAI_BASE_URL",
    "COLLEAGUE_API_KEY",
    "CONVERTIBLE_API_KEY",
    "OPENAI_API_KEY",
    "COLLEAGUE_MODEL",
    "CONVERTIBLE_MODEL",
    "COLLEAGUE_SENSES_MODEL",
    "CONVERTIBLE_SENSES_MODEL",
    "COLLEAGUE_SENSES_BASE_URL",
    "CONVERTIBLE_SENSES_BASE_URL",
    "COLLEAGUE_SENSES_API_KEY",
    "CONVERTIBLE_SENSES_API_KEY",
    "COLLEAGUE_SENSES_CONTEXT_BUDGET",
    "CONVERTIBLE_SENSES_CONTEXT_BUDGET",
    "COLLEAGUE_SENSES_MULTIMODAL",
    "CONVERTIBLE_SENSES_MULTIMODAL",
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
# Absent everywhere: senses is None, byte-identical to a pre-feature config.
# ---------------------------------------------------------------------------


def test_absent_everywhere_senses_is_none() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.senses is None


def test_absent_everywhere_repo_path_still_none(tmp_path: Path) -> None:
    """No env, no senses config-file section (even with repo_path given)."""
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is None


def test_absent_to_dict_has_no_senses_key() -> None:
    snapshot = EngineConfig.resolve().to_dict()
    assert "senses" not in snapshot


def test_absent_field_for_field_identical_to_bare_default() -> None:
    """resolve() with nothing configured reproduces the dataclass's own bare
    defaults field-for-field (dataclass __eq__ over every compare=True field),
    proving the new senses field changed nothing else about resolution."""
    assert EngineConfig.resolve() == EngineConfig()


def test_absent_to_dict_matches_pre_senses_keys() -> None:
    """The full to_dict() key set is exactly what it was before this feature
    (no stray key added) when senses is not configured."""
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
        "coherence",  # the coherence gate flag (#294)
        "memory",
        "lint_fix_retries",
        "testintegrity",
        "testintegrity_fix_retries",
        "testintegrity_reviewer_model",
        "affected_tests",
        "affected_tests_fix_retries",
        "affected_tests_depth",
        "affected_tests_max_files",
        "compaction_cap",
        "three_tier",  # three-tier-execution arc, plan task t3
    }
    assert set(snapshot.keys()) == expected_keys


# ---------------------------------------------------------------------------
# SensesConfig shape: a frozen dataclass mirroring DeepthinkConfig.
# ---------------------------------------------------------------------------


def test_senses_config_is_frozen_dataclass() -> None:
    sc = SensesConfig(
        model="endpoint-alpha-model",
        base_url="http://endpoint-alpha/v1",
        api_key="key-alpha",
        context_budget=24000,
    )
    assert sc.model == "endpoint-alpha-model"
    assert sc.base_url == "http://endpoint-alpha/v1"
    assert sc.api_key == "key-alpha"
    assert sc.context_budget == 24000
    assert sc.multimodal is False
    with pytest.raises(FrozenInstanceError):
        sc.model = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Env-only, config-file-only, and env-overrides-config-file.
# ---------------------------------------------------------------------------


def test_env_only_activates_senses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-beta-model")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.model == "endpoint-beta-model"


def test_env_only_all_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-beta-model")
    monkeypatch.setenv("COLLEAGUE_SENSES_BASE_URL", "http://endpoint-beta/v1")
    monkeypatch.setenv("COLLEAGUE_SENSES_API_KEY", "key-beta")
    monkeypatch.setenv("COLLEAGUE_SENSES_CONTEXT_BUDGET", "16000")
    monkeypatch.setenv("COLLEAGUE_SENSES_MULTIMODAL", "true")
    cfg = EngineConfig.resolve()
    assert cfg.senses == SensesConfig(
        model="endpoint-beta-model",
        base_url="http://endpoint-beta/v1",
        api_key="key-beta",
        context_budget=16000,
        multimodal=True,
    )


def test_env_convertible_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deprecated CONVERTIBLE_SENSES_* fallback is honored, matching
    deepthink's rename back-compat."""
    monkeypatch.setenv("CONVERTIBLE_SENSES_MODEL", "endpoint-gamma-model")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.model == "endpoint-gamma-model"


def test_config_file_only_activates_senses(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "senses": {
                "model": "endpoint-delta-model",
                "base_url": "http://endpoint-delta/v1",
                "api_key": "key-delta",
                "context_budget": 12000,
            }
        },
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses == SensesConfig(
        model="endpoint-delta-model",
        base_url="http://endpoint-delta/v1",
        api_key="key-delta",
        context_budget=12000,
    )


def test_config_file_senses_absent_no_repo_path_needed_is_none() -> None:
    """No repo_path at all (the common no-config-file caller) → still None."""
    assert EngineConfig.resolve().senses is None


def test_config_file_without_senses_section_is_absent(tmp_path: Path) -> None:
    """A config.json with no ``senses`` key at all → senses stays None."""
    _write_config(tmp_path, {"base_url": "http://endpoint-epsilon/v1"})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is None


def test_env_overrides_config_file_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, {"senses": {"model": "endpoint-config-model"}})
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-env-model")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is not None
    assert cfg.senses.model == "endpoint-env-model"


def test_env_overrides_config_file_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        {
            "senses": {
                "model": "endpoint-zeta-model",
                "base_url": "http://endpoint-config/v1",
            }
        },
    )
    monkeypatch.setenv("COLLEAGUE_SENSES_BASE_URL", "http://endpoint-env/v1")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is not None
    assert cfg.senses.base_url == "http://endpoint-env/v1"


def test_env_overrides_config_file_context_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        {"senses": {"model": "endpoint-eta-model", "context_budget": 8000}},
    )
    monkeypatch.setenv("COLLEAGUE_SENSES_CONTEXT_BUDGET", "20000")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is not None
    assert cfg.senses.context_budget == 20000


def test_env_overrides_config_file_multimodal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        {"senses": {"model": "endpoint-upsilon-model", "multimodal": False}},
    )
    monkeypatch.setenv("COLLEAGUE_SENSES_MULTIMODAL", "true")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is not None
    assert cfg.senses.multimodal is True


# ---------------------------------------------------------------------------
# Defaults: base_url/api_key inherit the MAIN endpoint; context_budget = 24000;
# multimodal defaults False.
# ---------------------------------------------------------------------------


def test_base_url_defaults_to_main_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-theta-model")
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://main-endpoint/v1")
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://main-endpoint/v1"
    assert cfg.senses is not None
    assert cfg.senses.base_url == "http://main-endpoint/v1"


def test_api_key_defaults_to_main_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-iota-model")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-key")
    cfg = EngineConfig.resolve()
    assert cfg.api_key == "main-secret-key"
    assert cfg.senses is not None
    assert cfg.senses.api_key == "main-secret-key"


def test_base_url_and_api_key_default_with_explicit_main_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defaults inherit the RESOLVED main values even when those came from an
    explicit resolve(...) argument, not just env/config-file."""
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-kappa-model")
    cfg = EngineConfig.resolve(
        base_url="http://explicit-main/v1",
        api_key="explicit-main-key",
        model="explicit-main-model",
    )
    assert cfg.senses is not None
    assert cfg.senses.base_url == "http://explicit-main/v1"
    assert cfg.senses.api_key == "explicit-main-key"


def test_context_budget_default_is_24000(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-lambda-model")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.context_budget == 24000


def test_multimodal_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-phi-model")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.multimodal is False


def test_multimodal_settable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-chi-model")
    monkeypatch.setenv("COLLEAGUE_SENSES_MULTIMODAL", "1")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.multimodal is True


def test_multimodal_settable_via_config_file(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"senses": {"model": "endpoint-psi-model", "multimodal": True}},
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is not None
    assert cfg.senses.multimodal is True


def test_explicit_senses_base_url_beats_main_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-mu-model")
    monkeypatch.setenv("COLLEAGUE_SENSES_BASE_URL", "http://senses-own-endpoint/v1")
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://main-endpoint/v1")
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://main-endpoint/v1"
    assert cfg.senses is not None
    assert cfg.senses.base_url == "http://senses-own-endpoint/v1"


# ---------------------------------------------------------------------------
# INTENTIONAL: an explicitly-empty config.json base_url/api_key falls through
# to the main endpoint (Qodo #2, cortex/senses PR #281) — pins the behavior
# documented in ``_resolve_senses``'s docstring + the inline comment above
# its base_url/api_key ``_pick`` calls. This mirrors ``_resolve_deepthink``'s
# identical ``file_x or main_x`` pattern field-for-field; it is not a lost
# override, since a JSON string field cannot express "explicitly blank"
# differently from "key omitted" any more usefully than "absent" already does.
# ---------------------------------------------------------------------------


def test_config_file_empty_base_url_and_api_key_fall_through_to_main(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"senses": {"model": "endpoint-omega-model", "base_url": "", "api_key": ""}},
    )
    cfg = EngineConfig.resolve(
        repo_path=tmp_path,
        base_url="http://main-endpoint/v1",
        api_key="main-secret-key",
    )
    assert cfg.senses is not None
    assert cfg.senses.base_url == "http://main-endpoint/v1"
    assert cfg.senses.api_key == "main-secret-key"


# ---------------------------------------------------------------------------
# Malformed context_budget never raises; falls back to the default.
# ---------------------------------------------------------------------------


def test_malformed_env_context_budget_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-nu-model")
    monkeypatch.setenv("COLLEAGUE_SENSES_CONTEXT_BUDGET", "not-a-number")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.context_budget == 24000


def test_malformed_config_file_context_budget_falls_back_to_default(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"senses": {"model": "endpoint-xi-model", "context_budget": "not-a-number"}},
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.senses is not None
    assert cfg.senses.context_budget == 24000


# ---------------------------------------------------------------------------
# Redaction: the senses api_key never leaks through to_dict().
# ---------------------------------------------------------------------------


def test_to_dict_senses_api_key_not_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors DeepthinkConfig.to_dict() exactly: the nested sub-dict carries
    only model/base_url/context_budget, so api_key is simply absent (never
    included, never merely redacted-in-place)."""
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-omicron-model")
    monkeypatch.setenv("COLLEAGUE_SENSES_API_KEY", "sk-senses-super-secret")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "sk-main-super-secret")
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()
    assert "senses" in snapshot
    senses_snapshot = snapshot["senses"]
    assert isinstance(senses_snapshot, dict)
    assert "api_key" not in senses_snapshot
    # Neither the main nor the senses secret leaks anywhere in the snapshot.
    rendered = json.dumps(snapshot)
    assert "sk-senses-super-secret" not in rendered
    assert "sk-main-super-secret" not in rendered


def test_to_dict_senses_only_present_when_configured() -> None:
    assert "senses" not in EngineConfig.resolve().to_dict()


# ---------------------------------------------------------------------------
# Empty / whitespace COLLEAGUE_SENSES_MODEL is treated as absent.
# ---------------------------------------------------------------------------


def test_empty_env_model_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "")
    assert EngineConfig.resolve().senses is None


def test_whitespace_env_model_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "   ")
    assert EngineConfig.resolve().senses is None


def test_whitespace_config_file_model_is_absent(tmp_path: Path) -> None:
    _write_config(tmp_path, {"senses": {"model": "   "}})
    assert EngineConfig.resolve(repo_path=tmp_path).senses is None


def test_whitespace_model_is_absent_regardless_of_other_senses_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per the interface contract: presence is keyed SOLELY on the model — a
    whitespace-only model means absent even with base_url/api_key/budget set."""
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "  ")
    monkeypatch.setenv("COLLEAGUE_SENSES_BASE_URL", "http://endpoint-pi/v1")
    monkeypatch.setenv("COLLEAGUE_SENSES_API_KEY", "key-pi")
    monkeypatch.setenv("COLLEAGUE_SENSES_CONTEXT_BUDGET", "9999")
    assert EngineConfig.resolve().senses is None


def test_config_file_senses_section_without_model_key_is_absent(tmp_path: Path) -> None:
    """A senses section present but missing the model key entirely (only
    base_url set) is not senses-declared — the model IS the presence signal."""
    _write_config(tmp_path, {"senses": {"base_url": "http://endpoint-rho/v1"}})
    assert EngineConfig.resolve(repo_path=tmp_path).senses is None


def test_model_is_stripped_of_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "  endpoint-sigma-model  ")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.model == "endpoint-sigma-model"


# ---------------------------------------------------------------------------
# Deepthink resolution is untouched: senses and deepthink coexist independently.
# ---------------------------------------------------------------------------


def test_deepthink_and_senses_resolve_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "deepthink-model")
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "senses-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "deepthink-model"
    assert cfg.senses is not None
    assert cfg.senses.model == "senses-model"


def test_senses_configured_alone_leaves_deepthink_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "senses-only-model")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.deepthink is None

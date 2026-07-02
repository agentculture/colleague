"""Test-integrity reviewer defaults to the deepthink model (task t7).

Spec: docs/specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md
(claim c10(d)). Plan: docs/plans/2026-07-01-colleague-drives-with-two-minds
-a-fast-wide-window.md (task t7).

The existing test-integrity gate (#203) can spawn a DIFFERENT-model reviewer
subagent when ``EngineConfig.testintegrity_reviewer_model`` names one (empty =
unconfigured, record-only). When dual-model deepthink (task t1) is configured
and the operator has NOT set an explicit reviewer model, the deepthink model
becomes the reviewer default — the strong reasoner is the natural diverse
reviewer for a mirrored-test finding.

The default is guarded to the SAME endpoint as the main model: the reviewer
subagent switch (``colleague/subagents.py``) carries only a model name — the
child inherits the parent's ``base_url``/``api_key`` via
``dataclasses.replace(parent_config, model=..., role=...)`` — so defaulting to
a deepthink model served on a DIFFERENT endpoint would point the reviewer
subagent at a model name the main endpoint doesn't serve. When the deepthink
base_url differs from the main base_url, the reviewer model is left unset
(empty); the cross-endpoint reviewer default is a documented v1 follow-up
needing the subagent switch to carry an endpoint of its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.config import EngineConfig

# Every env var that can influence this resolution: main endpoint, deepthink,
# and the test-integrity reviewer model — cleared per test so a developer's
# shell / CI environment can never leak into a resolution (mirrors
# test_deepthink_config.py's isolation idiom).
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
    "COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL",
    "CONVERTIBLE_TESTINTEGRITY_REVIEWER_MODEL",
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
# Same-endpoint dual config + no explicit reviewer -> defaults to deepthink.
# ---------------------------------------------------------------------------


def test_same_endpoint_dual_config_defaults_reviewer_to_deepthink_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deepthink base_url defaults to the main endpoint (t1 behavior) when not
    explicitly set, so a bare ``COLLEAGUE_DEEPTHINK_MODEL`` is already a
    same-endpoint dual config -> the reviewer should default to it."""
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "deepthink-reviewer-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == cfg.base_url
    assert cfg.testintegrity_reviewer_model == "deepthink-reviewer-model"


def test_same_endpoint_dual_config_both_explicitly_set_equal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when BOTH base_urls are explicitly (not just default-inherited)
    set to the same value, the equality check still applies."""
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://shared-rig:9000/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://shared-rig:9000/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "shared-rig-deepthink-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.testintegrity_reviewer_model == "shared-rig-deepthink-model"


def test_dual_config_via_config_file_still_defaults_reviewer(tmp_path: Path) -> None:
    """The deepthink config need not come from env — a config-file-sourced
    deepthink section (no explicit base_url, so it inherits the main
    endpoint) still backfills the reviewer default."""
    _write_config(
        tmp_path,
        {"deepthink": {"model": "file-sourced-deepthink-model"}},
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == cfg.base_url
    assert cfg.testintegrity_reviewer_model == "file-sourced-deepthink-model"


# ---------------------------------------------------------------------------
# Different-endpoint dual config -> reviewer stays empty (the honest guard).
# ---------------------------------------------------------------------------


def test_different_endpoint_dual_config_reviewer_stays_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://main-endpoint/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://deepthink-only-endpoint/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "cross-endpoint-deepthink-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url != cfg.base_url
    assert cfg.testintegrity_reviewer_model == ""


def test_different_endpoint_dual_config_via_config_file_reviewer_stays_empty(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        {
            "deepthink": {
                "model": "file-cross-endpoint-model",
                "base_url": "http://file-deepthink-endpoint/v1",
            }
        },
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url != cfg.base_url
    assert cfg.testintegrity_reviewer_model == ""


# ---------------------------------------------------------------------------
# Explicit reviewer value still wins over the deepthink default.
# ---------------------------------------------------------------------------


def test_explicit_env_reviewer_wins_over_same_endpoint_deepthink_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "deepthink-reviewer-model")
    monkeypatch.setenv("COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL", "explicit-reviewer-model")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.testintegrity_reviewer_model == "explicit-reviewer-model"


def test_convertible_fallback_reviewer_wins_over_deepthink_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deprecated CONVERTIBLE_TESTINTEGRITY_REVIEWER_MODEL fallback still
    wins too, matching the rename back-compat convention used everywhere
    else in this module."""
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "deepthink-reviewer-model")
    monkeypatch.setenv("CONVERTIBLE_TESTINTEGRITY_REVIEWER_MODEL", "legacy-explicit-reviewer")
    cfg = EngineConfig.resolve()
    assert cfg.testintegrity_reviewer_model == "legacy-explicit-reviewer"


def test_explicit_reviewer_wins_even_with_config_file_dual_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"deepthink": {"model": "file-sourced-deepthink-model"}})
    monkeypatch.setenv("COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL", "explicit-reviewer-model")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.testintegrity_reviewer_model == "explicit-reviewer-model"


def test_explicit_reviewer_wins_even_on_different_endpoint_dual_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit reviewer model wins regardless of endpoint match — the
    same-endpoint guard only governs the DEFAULT, never an explicit value."""
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://main-endpoint/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_BASE_URL", "http://deepthink-only-endpoint/v1")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "cross-endpoint-deepthink-model")
    monkeypatch.setenv("COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL", "explicit-reviewer-model")
    cfg = EngineConfig.resolve()
    assert cfg.testintegrity_reviewer_model == "explicit-reviewer-model"


# ---------------------------------------------------------------------------
# Whitespace-only explicit reviewer value is treated as unset.
# ---------------------------------------------------------------------------


def test_whitespace_only_explicit_reviewer_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "deepthink-reviewer-model")
    monkeypatch.setenv("COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL", "   ")
    cfg = EngineConfig.resolve()
    assert cfg.testintegrity_reviewer_model == "deepthink-reviewer-model"


def test_whitespace_only_explicit_reviewer_no_dual_config_stays_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No dual config to fall back to -> the whitespace value is preserved
    exactly as the pre-feature resolution would have left it (never raises,
    never invents a model name out of nothing)."""
    monkeypatch.setenv("COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL", "   ")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is None
    assert cfg.testintegrity_reviewer_model == "   "


# ---------------------------------------------------------------------------
# No dual config at all -> resolution is completely unchanged (byte-identical).
# ---------------------------------------------------------------------------


def test_no_dual_config_reviewer_resolution_unchanged() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is None
    assert cfg.testintegrity_reviewer_model == ""


def test_no_dual_config_explicit_reviewer_still_resolves_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL", "single-model-reviewer")
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is None
    assert cfg.testintegrity_reviewer_model == "single-model-reviewer"


def test_no_dual_config_matches_bare_default_field_for_field() -> None:
    """Proves this task changed nothing about single-model resolution: a bare
    resolve() is still field-for-field identical to the dataclass's own
    defaults (mirrors test_deepthink_config.py's equivalent guard)."""
    assert EngineConfig.resolve() == EngineConfig()


# ---------------------------------------------------------------------------
# to_dict() snapshot reflects the defaulted reviewer model like any other
# resolved field (no special-casing / no leak of the deepthink api_key via
# this path).
# ---------------------------------------------------------------------------


def test_to_dict_reflects_defaulted_reviewer_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "deepthink-reviewer-model")
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()
    assert snapshot["testintegrity_reviewer_model"] == "deepthink-reviewer-model"

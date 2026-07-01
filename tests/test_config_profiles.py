"""Tests for the mode-profile default layer (``apply_mode_profile``, plan t2 / spec R1).

The layer fills constraint knobs a mode profile declares, but ONLY for knobs
the operator left untouched: an explicit CLI flag (``explicit=``) or a set
``COLLEAGUE_*``/``CONVERTIBLE_*`` env var always wins (honesty condition h1 —
a profile changes only *defaults*). Operator overlays at
``.colleague/profiles.json`` and ``.colleague/<sanitized-model>/profiles.json``
override the built-in catalog per field, per-model-first, via exact-path
construction (h7 — no sibling globbing).
"""

import json

import pytest

from colleague.config import EngineConfig, apply_mode_profile
from colleague.layers import sanitize_model


class _StubProfile:
    """Duck-typed stand-in for colleague.profiles.ModeProfile (built by t1)."""

    def __init__(
        self,
        max_steps=30,
        context_budget_fraction=0.75,
        synthesis_reserve_steps=3,
        timeout=90.0,
        fillline_threshold=0.7,
    ):
        self.max_steps = max_steps
        self.context_budget_fraction = context_budget_fraction
        self.synthesis_reserve_steps = synthesis_reserve_steps
        self.timeout = timeout
        self.fillline_threshold = fillline_threshold


def _resolve_stub(mode):
    return _StubProfile() if mode == "explore" else None


_PROFILE_ENV_VARS = (
    "COLLEAGUE_MAX_STEPS",
    "CONVERTIBLE_MAX_STEPS",
    "COLLEAGUE_TIMEOUT",
    "CONVERTIBLE_TIMEOUT",
    "COLLEAGUE_CONTEXT_BUDGET",
    "CONVERTIBLE_CONTEXT_BUDGET",
    "COLLEAGUE_FILLLINE_THRESHOLD",
    "CONVERTIBLE_FILLLINE_THRESHOLD",
    "COLLEAGUE_SYNTHESIS_RESERVE_STEPS",
    "CONVERTIBLE_SYNTHESIS_RESERVE_STEPS",
)


@pytest.fixture(autouse=True)
def _clean_profile_env(monkeypatch):
    for var in _PROFILE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _default_config():
    return EngineConfig()


def test_no_mode_is_identity():
    config = _default_config()
    assert apply_mode_profile(config, None, resolve=_resolve_stub) is config
    assert apply_mode_profile(config, "", resolve=_resolve_stub) is config


def test_unknown_mode_is_identity():
    config = _default_config()
    assert apply_mode_profile(config, "warp", resolve=_resolve_stub) is config


def test_profile_fills_untouched_knobs():
    config = _default_config()
    applied = apply_mode_profile(config, "explore", resolve=_resolve_stub)
    assert applied.max_steps == 30
    assert applied.synthesis_reserve_steps == 3
    assert applied.timeout == 90.0
    assert applied.fillline_threshold == 0.7
    assert applied.context_budget_tokens == int(config.context_budget_tokens * 0.75)


def test_non_profile_fields_untouched():
    config = _default_config()
    applied = apply_mode_profile(config, "explore", resolve=_resolve_stub)
    assert applied.model == config.model
    assert applied.max_output_chars == config.max_output_chars
    assert applied.subagent_concurrency == config.subagent_concurrency


def test_explicit_flag_wins():
    config = _default_config()
    applied = apply_mode_profile(config, "explore", explicit={"max_steps"}, resolve=_resolve_stub)
    assert applied.max_steps == config.max_steps
    assert applied.synthesis_reserve_steps == 3


def test_env_var_wins(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_STEPS", "55")
    config = EngineConfig(max_steps=55)
    applied = apply_mode_profile(config, "explore", resolve=_resolve_stub)
    assert applied.max_steps == 55
    assert applied.timeout == 90.0  # untouched knobs still fill


def test_legacy_env_var_also_wins(monkeypatch):
    monkeypatch.setenv("CONVERTIBLE_TIMEOUT", "240")
    config = EngineConfig(timeout=240.0)
    applied = apply_mode_profile(config, "explore", resolve=_resolve_stub)
    assert applied.timeout == 240.0
    assert applied.max_steps == 30


def test_empty_env_var_does_not_win(monkeypatch):
    # _pick treats an empty env value as absent; the profile layer must mirror it.
    monkeypatch.setenv("COLLEAGUE_MAX_STEPS", "")
    applied = apply_mode_profile(_default_config(), "explore", resolve=_resolve_stub)
    assert applied.max_steps == 30


def test_repo_overlay_overrides_builtin(tmp_path):
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "profiles.json").write_text(
        json.dumps({"explore": {"max_steps": 25, "context_budget_fraction": 0.5}}),
        encoding="utf-8",
    )
    config = _default_config()
    applied = apply_mode_profile(config, "explore", repo_path=tmp_path, resolve=_resolve_stub)
    assert applied.max_steps == 25
    assert applied.context_budget_tokens == int(config.context_budget_tokens * 0.5)
    # Fields the overlay does not name still come from the built-in profile.
    assert applied.synthesis_reserve_steps == 3


def test_per_model_overlay_wins_and_is_exact_path(tmp_path):
    base = tmp_path / ".colleague"
    base.mkdir()
    (base / "profiles.json").write_text(
        json.dumps({"explore": {"max_steps": 25}}), encoding="utf-8"
    )
    for model, steps in (("org/ModelX", 22), ("org/ModelY", 11)):
        overlay_dir = base / sanitize_model(model)
        overlay_dir.mkdir()
        (overlay_dir / "profiles.json").write_text(
            json.dumps({"explore": {"max_steps": steps}}), encoding="utf-8"
        )
    applied_x = apply_mode_profile(
        EngineConfig(model="org/ModelX"),
        "explore",
        repo_path=tmp_path,
        resolve=_resolve_stub,
    )
    assert applied_x.max_steps == 22  # own overlay, never a sibling's
    applied_z = apply_mode_profile(
        EngineConfig(model="org/ModelZ"),
        "explore",
        repo_path=tmp_path,
        resolve=_resolve_stub,
    )
    assert applied_z.max_steps == 25  # repo overlay; ModelY's 11 never leaks


def test_overlay_absolute_budget(tmp_path):
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "profiles.json").write_text(
        json.dumps({"explore": {"context_budget_tokens": 50000}}), encoding="utf-8"
    )
    applied = apply_mode_profile(
        _default_config(), "explore", repo_path=tmp_path, resolve=_resolve_stub
    )
    assert applied.context_budget_tokens == 50000


def test_overlay_defines_mode_without_builtin_profile(tmp_path):
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "profiles.json").write_text(
        json.dumps({"auto": {"max_steps": 12}}), encoding="utf-8"
    )
    applied = apply_mode_profile(
        _default_config(), "auto", repo_path=tmp_path, resolve=_resolve_stub
    )
    assert applied.max_steps == 12
    # Fields the overlay does not name stay untouched (no builtin for auto).
    assert applied.timeout == _default_config().timeout


def test_malformed_overlay_is_ignored(tmp_path):
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "profiles.json").write_text("{not json", encoding="utf-8")
    applied = apply_mode_profile(
        _default_config(), "explore", repo_path=tmp_path, resolve=_resolve_stub
    )
    assert applied.max_steps == 30  # builtin still applies, no raise


def test_invalid_overlay_values_fall_back_per_field(tmp_path):
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "profiles.json").write_text(
        json.dumps(
            {
                "explore": {
                    "max_steps": "lots",
                    "fillline_threshold": 1.5,
                    "timeout": -1,
                    "context_budget_fraction": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    config = _default_config()
    applied = apply_mode_profile(config, "explore", repo_path=tmp_path, resolve=_resolve_stub)
    # Every invalid overlay value falls back to the built-in profile value.
    assert applied.max_steps == 30
    assert applied.fillline_threshold == 0.7
    assert applied.timeout == 90.0
    assert applied.context_budget_tokens == int(config.context_budget_tokens * 0.75)


def test_runtime_only_fields_survive_replace():
    config = EngineConfig(role="explorer")
    applied = apply_mode_profile(config, "explore", resolve=_resolve_stub)
    assert applied.role == "explorer"

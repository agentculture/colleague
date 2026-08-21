"""Presence-lane ladder rung config resolution (presence-default-everywhere arc, task t4).

Spec: docs/specs/2026-07-08-colleague-s-middle-manager-presence-is-now-its-def.md
(requirement "the middle-manager presence is the DEFAULT state", honesty h1).
Plan: docs/plans/2026-07-08-colleague-s-middle-manager-presence-is-now-its-def.md
(task t4).

``colleague.config.resolve_presence_rung(config, ...)`` decides which rung of
the presence lane's bounded degradation ladder is active for a work item:

    "loop"  — the senses agentic loop (t5), the DEFAULT rung whenever senses
              is armed and not disarmed.
    "beats" — today's fixed-beat lane (intake/ack/updates/talk), an explicit
              operator opt-down via COLLEAGUE_PRESENCE=beats / config.json
              {"presence": "beats"}.
    "off"   — cortex-only: either no senses model is resolved at all (nothing
              to talk to), or the operator disarmed the lane via
              --cortex-only / COLLEAGUE_PRESENCE=off|0 / config.json
              {"presence": "off"}.

Precedence (highest first): an explicit ``cortex_only=True`` argument >
COLLEAGUE_PRESENCE env (CONVERTIBLE_PRESENCE deprecated fallback) > a
top-level "presence" key in .colleague/config.json > the built-in default
("loop" when armed, structurally "off" when senses is unarmed).

This is scoped STRICTLY to config resolution (t4) — no front (session/talk/
background/resident/work) is wired here; those are t7-t11. Every front
resolves through the SAME EngineConfig, so a single resolution test covering
"senses armed -> loop" (plus the off-switch precedence) suffices for all of
them, per the plan's own acceptance note.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.config import EngineConfig, SensesConfig, resolve_presence_rung

# Every env var that can influence resolve_presence_rung under test.
_ALL_ENV = ("COLLEAGUE_PRESENCE", "CONVERTIBLE_PRESENCE")


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


def _senses_config(**overrides) -> SensesConfig:
    defaults = dict(
        model="senses-sentinel-model",
        base_url="http://senses-endpoint/v1",
        api_key="senses-key",
        context_budget=24000,
    )
    defaults.update(overrides)
    return SensesConfig(**defaults)


def _armed_config(**overrides) -> EngineConfig:
    """A resolved-looking EngineConfig with senses armed, nothing else set."""
    return EngineConfig(senses=_senses_config(), **overrides)


def _unarmed_config(**overrides) -> EngineConfig:
    """A resolved-looking EngineConfig with senses NOT resolved (senses=None)."""
    return EngineConfig(senses=None, **overrides)


# ---------------------------------------------------------------------------
# Default-on: senses armed + zero additional flags -> "loop".
# ---------------------------------------------------------------------------


def test_senses_armed_zero_flags_defaults_to_loop() -> None:
    """The default rung whenever senses resolves and nothing disarms it: loop.

    No cortex_only, no env, no repo_path/config.json — the ladder's top rung
    fires with NO extra flag, matching every front (session/talk/background/
    resident/work) since they all resolve through the same EngineConfig.
    """
    cfg = _armed_config()
    assert resolve_presence_rung(cfg) == "loop"


def test_senses_armed_via_full_resolve_defaults_to_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same default-on behaviour through the real EngineConfig.resolve()
    plumbing (env-declared senses), not just a hand-built dataclass — proving
    the resolver works against what a front would actually receive."""
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "endpoint-resolved-model")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert resolve_presence_rung(cfg) == "loop"


# ---------------------------------------------------------------------------
# Senses unarmed: "off", and to_dict() stays byte-identical.
# ---------------------------------------------------------------------------


def test_senses_unarmed_is_off() -> None:
    cfg = _unarmed_config()
    assert resolve_presence_rung(cfg) == "off"


def test_senses_unarmed_is_off_even_with_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing to talk to overrides any opt-down/opt-in — there is no ladder
    to run at all when senses never resolved."""
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "loop")
    cfg = _unarmed_config()
    assert resolve_presence_rung(cfg) == "off"


def test_senses_unarmed_engine_config_to_dict_byte_identical() -> None:
    """Building/consulting the presence resolver must not perturb
    EngineConfig.to_dict() for a senses-less config — the byte-identical
    guarantee this repo treats as sacred. No new key appears."""
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
        "coherence",
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
        "reasoning_effort",  # thinking-effort ladder, #416 t2
        "reasoning_effort_seats",  # thinking-effort ladder, #416 t2
        "too_long_min",  # thinking-effort ladder, #416 t2
    }
    assert set(snapshot.keys()) == expected_keys
    assert EngineConfig.resolve() == EngineConfig()


# ---------------------------------------------------------------------------
# Off-switch on every front: --cortex-only (flag) forces "off" over anything.
# ---------------------------------------------------------------------------


def test_cortex_only_flag_overrides_armed_senses() -> None:
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, cortex_only=True) == "off"


def test_cortex_only_flag_beats_env_beats(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag wins over env: even COLLEAGUE_PRESENCE=loop can't out-rank an
    explicit cortex_only=True."""
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "loop")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, cortex_only=True) == "off"


def test_cortex_only_flag_beats_config_file(tmp_path: Path) -> None:
    _write_config(tmp_path, {"presence": "loop"})
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, cortex_only=True, repo_path=tmp_path) == "off"


# ---------------------------------------------------------------------------
# Off-switch via COLLEAGUE_PRESENCE env var.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["off", "0", "OFF", "  off  ", "false", "no"])
def test_env_off_values_force_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("COLLEAGUE_PRESENCE", value)
    cfg = _armed_config()
    assert resolve_presence_rung(cfg) == "off"


def test_env_convertible_fallback_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deprecated CONVERTIBLE_PRESENCE fallback is honored, matching the
    rename back-compat convention used by every other knob."""
    monkeypatch.setenv("CONVERTIBLE_PRESENCE", "off")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg) == "off"


# ---------------------------------------------------------------------------
# Off-switch via a top-level "presence" key in .colleague/config.json.
# ---------------------------------------------------------------------------


def test_config_file_off_forces_off(tmp_path: Path) -> None:
    _write_config(tmp_path, {"presence": "off"})
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "off"


def test_config_file_absent_presence_key_defaults_to_loop_when_armed(tmp_path: Path) -> None:
    _write_config(tmp_path, {"base_url": "http://somewhere/v1"})
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "loop"


def test_no_repo_path_skips_config_file_lookup_safely() -> None:
    """repo_path=None (the common no-config-file caller) never raises and
    resolves via env/default only."""
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=None) == "loop"


# ---------------------------------------------------------------------------
# The "beats" opt-down: an explicit ladder rung between loop and off.
# ---------------------------------------------------------------------------


def test_env_beats_selects_beats_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "beats")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg) == "beats"


def test_config_file_beats_selects_beats_lane(tmp_path: Path) -> None:
    _write_config(tmp_path, {"presence": "beats"})
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "beats"


def test_env_loop_is_explicit_and_matches_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "loop")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg) == "loop"


def test_beats_unreachable_when_senses_unarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An opt-down to 'beats' still can't manufacture a ladder when there is
    nothing to talk to."""
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "beats")
    cfg = _unarmed_config()
    assert resolve_presence_rung(cfg) == "off"


# ---------------------------------------------------------------------------
# Precedence: flag > env > config.json > default.
# ---------------------------------------------------------------------------


def test_env_beats_overrides_config_file_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"presence": "off"})
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "beats")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "beats"


def test_env_off_overrides_config_file_beats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"presence": "beats"})
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "off")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "off"


def test_config_file_beats_overrides_default_loop(tmp_path: Path) -> None:
    _write_config(tmp_path, {"presence": "beats"})
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "beats"


def test_full_precedence_chain_flag_wins_over_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"presence": "beats"})
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "beats")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, cortex_only=True, repo_path=tmp_path) == "off"


# ---------------------------------------------------------------------------
# Never raises on malformed env/config — falls through to the next rung.
# ---------------------------------------------------------------------------


def test_malformed_env_value_falls_through_to_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"presence": "beats"})
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "not-a-real-rung")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "beats"


def test_malformed_env_value_falls_through_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "garbage")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg) == "loop"


def test_malformed_config_file_value_falls_through_to_default(tmp_path: Path) -> None:
    _write_config(tmp_path, {"presence": "not-a-real-rung"})
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "loop"


def test_empty_env_value_falls_through_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg) == "loop"


def test_malformed_config_json_file_never_raises(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text("{not valid json", encoding="utf-8")
    cfg = _armed_config()
    assert resolve_presence_rung(cfg, repo_path=tmp_path) == "loop"


# ---------------------------------------------------------------------------
# The rung is resolvable and recorded: a plain, importable, callable API.
# ---------------------------------------------------------------------------


def test_resolve_presence_rung_is_importable_from_config_module() -> None:
    from colleague.config import resolve_presence_rung as reimported

    assert reimported is resolve_presence_rung


def test_return_value_is_always_one_of_the_three_rungs(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague.config import PRESENCE_RUNGS

    assert PRESENCE_RUNGS == ("loop", "beats", "off")
    for cortex_only in (True, False):
        for cfg in (_armed_config(), _unarmed_config()):
            assert resolve_presence_rung(cfg, cortex_only=cortex_only) in PRESENCE_RUNGS


def test_explicit_env_mapping_is_honored_over_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit env= mapping (as a front might pass a snapshot) is used
    instead of silently reading the real process environment."""
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "beats")
    cfg = _armed_config()
    # An explicit, different env mapping overrides the real process env.
    assert resolve_presence_rung(cfg, env={"COLLEAGUE_PRESENCE": "off"}) == "off"
    assert resolve_presence_rung(cfg, env={}) == "loop"

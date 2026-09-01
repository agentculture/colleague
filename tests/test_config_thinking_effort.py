"""Config wiring for the per-seat thinking-effort ladder (#416 t2).

Covers spec targets c5, h5, c16, h12, c26, h17.

``EngineConfig`` gains ``reasoning_effort`` (a GLOBAL override; the literal
value ``"default"`` is the kill-switch sentinel) and ``reasoning_effort_seats``
(a per-seat override map), resolved in ``resolve()`` via the existing
``_pick`` precedence (flag > env > .colleague/config.json > default). Every
value is validated against :mod:`colleague.effort`'s ladder — an unknown
value raises ``CliError`` naming it (c37).

``to_dict()`` carries ``reasoning_effort`` / ``reasoning_effort_seats`` /
``too_long_min`` ALWAYS (never omitted), so the artifact config snapshot is
identical on mock and vllm-openai.

``EngineConfig.reasoning_effort_effective`` resolves the ACTING seat's
effective rung (cortex, or worker when three-tier's worker seat is armed):
"medium" by default, "low" when the top-level ``--role explorer`` rule
applies (unless an explicit override set it), ``None`` under the kill switch,
and an explicit override always wins.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli._errors import CliError
from colleague.config import EngineConfig, WorkerConfig

_ALL_ENV = (
    "COLLEAGUE_BASE_URL",
    "CONVERTIBLE_BASE_URL",
    "OPENAI_BASE_URL",
    "COLLEAGUE_API_KEY",
    "CONVERTIBLE_API_KEY",
    "OPENAI_API_KEY",
    "COLLEAGUE_MODEL",
    "CONVERTIBLE_MODEL",
    "COLLEAGUE_LOBES_URL",
    "COLLEAGUE_REASONING_EFFORT",
    "COLLEAGUE_TOO_LONG_MIN",
    "COLLEAGUE_CORTEX_REASONING_EFFORT",
    "COLLEAGUE_WORKER_REASONING_EFFORT",
    "COLLEAGUE_DEEPTHINK_REASONING_EFFORT",
    "COLLEAGUE_SENSES_REASONING_EFFORT",
    "COLLEAGUE_EVALUATOR_REASONING_EFFORT",
    "COLLEAGUE_DESIGN_REASONING_EFFORT",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    # Prevent a real ~/.colleague/config.json on the dev/CI machine (which
    # may arm lobes) from leaking into these tests (test_config_senses.py
    # idiom).
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Slice A: reasoning_effort / reasoning_effort_seats resolution.
# ---------------------------------------------------------------------------


def test_absent_everywhere_defaults() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.reasoning_effort is None
    assert cfg.reasoning_effort_seats == {}


def test_absent_field_for_field_identical_to_bare_default() -> None:
    assert EngineConfig.resolve() == EngineConfig()


def test_env_global(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "high")
    cfg = EngineConfig.resolve()
    assert cfg.reasoning_effort == "high"


def test_env_per_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_WORKER_REASONING_EFFORT", "xhigh")
    monkeypatch.setenv("COLLEAGUE_SENSES_REASONING_EFFORT", "off")
    cfg = EngineConfig.resolve()
    assert cfg.reasoning_effort_seats == {"worker": "xhigh", "senses": "off"}


@pytest.mark.parametrize(
    "seat_env",
    [
        "COLLEAGUE_CORTEX_REASONING_EFFORT",
        "COLLEAGUE_WORKER_REASONING_EFFORT",
        "COLLEAGUE_DEEPTHINK_REASONING_EFFORT",
        "COLLEAGUE_SENSES_REASONING_EFFORT",
        "COLLEAGUE_EVALUATOR_REASONING_EFFORT",
        "COLLEAGUE_DESIGN_REASONING_EFFORT",
    ],
)
def test_every_seat_env_key_recognised(monkeypatch: pytest.MonkeyPatch, seat_env: str) -> None:
    monkeypatch.setenv(seat_env, "low")
    cfg = EngineConfig.resolve()
    seat = seat_env[len("COLLEAGUE_") : -len("_REASONING_EFFORT")].lower()
    assert cfg.reasoning_effort_seats == {seat: "low"}


def test_config_json_global(tmp_path: Path) -> None:
    _write_config(tmp_path, {"reasoning_effort": "low"})
    cfg = EngineConfig.resolve(repo_path=tmp_path, discover_lobes=False)
    assert cfg.reasoning_effort == "low"


def test_config_json_per_seat(tmp_path: Path) -> None:
    _write_config(tmp_path, {"reasoning_effort_seats": {"cortex": "high", "worker": "off"}})
    cfg = EngineConfig.resolve(repo_path=tmp_path, discover_lobes=False)
    assert cfg.reasoning_effort_seats == {"cortex": "high", "worker": "off"}


def test_env_beats_config_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_config(
        tmp_path, {"reasoning_effort": "low", "reasoning_effort_seats": {"cortex": "off"}}
    )
    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "high")
    monkeypatch.setenv("COLLEAGUE_CORTEX_REASONING_EFFORT", "xhigh")
    cfg = EngineConfig.resolve(repo_path=tmp_path, discover_lobes=False)
    assert cfg.reasoning_effort == "high"
    assert cfg.reasoning_effort_seats == {"cortex": "xhigh"}


def test_kill_switch_sentinel_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "default")
    cfg = EngineConfig.resolve()
    assert cfg.reasoning_effort == "default"


def test_kill_switch_sentinel_per_seat_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_CORTEX_REASONING_EFFORT", "default")
    cfg = EngineConfig.resolve()
    assert cfg.reasoning_effort_seats == {"cortex": "default"}


def test_unknown_value_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "extreme")
    with pytest.raises(CliError) as exc_info:
        EngineConfig.resolve()
    message = str(exc_info.value)
    for rung in ("off", "low", "medium", "high", "xhigh", "default"):
        assert rung in message


def test_unknown_value_config_json_raises(tmp_path: Path) -> None:
    _write_config(tmp_path, {"reasoning_effort": "bogus"})
    with pytest.raises(CliError):
        EngineConfig.resolve(repo_path=tmp_path, discover_lobes=False)


def test_unknown_value_per_seat_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_WORKER_REASONING_EFFORT", "bogus")
    with pytest.raises(CliError):
        EngineConfig.resolve()


# ---------------------------------------------------------------------------
# Slice B: to_dict() keys + config show.
# ---------------------------------------------------------------------------


def test_to_dict_carries_reasoning_effort_keys_unset() -> None:
    snapshot = EngineConfig.resolve().to_dict()
    assert snapshot["reasoning_effort"] is None
    assert snapshot["reasoning_effort_seats"] == {}


def test_to_dict_carries_reasoning_effort_keys_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "high")
    monkeypatch.setenv("COLLEAGUE_WORKER_REASONING_EFFORT", "xhigh")
    snapshot = EngineConfig.resolve().to_dict()
    assert snapshot["reasoning_effort"] == "high"
    assert snapshot["reasoning_effort_seats"] == {"worker": "xhigh"}


def test_to_dict_pre_existing_keys_still_present() -> None:
    """Every pre-existing to_dict key survives (test_config_senses.py /
    test_config_subagent.py's exact-key-set pins are updated in this same
    slice to add the two new always-present keys)."""
    snapshot = EngineConfig.resolve().to_dict()
    for key in (
        "base_url",
        "model",
        "max_steps",
        "temperature",
        "timeout",
        "context_budget_tokens",
        "compaction_cap",
        "three_tier",
    ):
        assert key in snapshot


def test_config_show_prints_effort_table() -> None:
    from colleague.cli._commands.config import _config_show

    rendered = _config_show(".")
    text = rendered._text
    assert "reasoning_effort:" in text
    for seat in ("cortex", "worker", "deepthink", "evaluator", "senses", "design"):
        assert f"{seat}: " in text


def test_config_show_names_kill_switch_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague.cli._commands.config import _config_show

    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "default")
    rendered = _config_show(".")
    text = rendered._text
    assert "kill-switch" in text
    assert "cortex: None" in text


# ---------------------------------------------------------------------------
# Slice C: acting-seat effective effort, top-level --role explorer, too_long_min.
# ---------------------------------------------------------------------------


def test_acting_seat_effective_defaults_low_cortex() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.worker is None
    assert cfg.reasoning_effort_effective == "low"  # v4 seat default (#475)


def test_acting_seat_effective_prefers_worker_when_armed() -> None:
    cfg = EngineConfig.resolve()
    cfg.worker = WorkerConfig(
        model="worker-model", base_url="http://worker/v1", api_key="k", context=32768
    )
    # Worker seat table default is also "low" (v4, #475), but the per-seat
    # lookup must key off "worker", not "cortex" — pin that via an explicit
    # worker override that would be invisible if the wrong seat were consulted.
    cfg.reasoning_effort_seats = {"cortex": "off"}
    assert cfg.reasoning_effort_effective == "low"
    cfg.reasoning_effort_seats = {"worker": "xhigh"}
    assert cfg.reasoning_effort_effective == "xhigh"


def test_explorer_role_defaults_low() -> None:
    cfg = EngineConfig.resolve()
    cfg.role = "explorer"
    assert cfg.reasoning_effort_effective == "low"


def test_explorer_role_explicit_override_wins_off_selectable() -> None:
    cfg = EngineConfig.resolve()
    cfg.role = "explorer"
    cfg.reasoning_effort_seats = {"cortex": "off"}
    assert cfg.reasoning_effort_effective == "off"


def test_explorer_role_explicit_global_override_wins() -> None:
    cfg = EngineConfig.resolve()
    cfg.role = "explorer"
    cfg.reasoning_effort = "xhigh"
    assert cfg.reasoning_effort_effective == "xhigh"


def test_non_explorer_role_keeps_acting_seat_value() -> None:
    cfg = EngineConfig.resolve()
    cfg.role = "writer"
    assert cfg.reasoning_effort_effective == "low"  # v4 seat default (#475)


def test_kill_switch_effective_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "default")
    cfg = EngineConfig.resolve()
    assert cfg.reasoning_effort_effective is None
    cfg.role = "explorer"
    assert cfg.reasoning_effort_effective is None


def test_too_long_min_default() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.too_long_min == 20
    assert cfg.to_dict()["too_long_min"] == 20


def test_too_long_min_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TOO_LONG_MIN", "45")
    cfg = EngineConfig.resolve()
    assert cfg.too_long_min == 45


def test_too_long_min_config_json(tmp_path: Path) -> None:
    _write_config(tmp_path, {"too_long_min": 5})
    cfg = EngineConfig.resolve(repo_path=tmp_path, discover_lobes=False)
    assert cfg.too_long_min == 5


def test_too_long_min_env_beats_config_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_config(tmp_path, {"too_long_min": 5})
    monkeypatch.setenv("COLLEAGUE_TOO_LONG_MIN", "99")
    cfg = EngineConfig.resolve(repo_path=tmp_path, discover_lobes=False)
    assert cfg.too_long_min == 99

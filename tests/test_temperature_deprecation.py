"""Temperature knob deprecation lane (reasoning-aware-sampling-defaults arc,
plan task t7, spec c9/h11 + c42/h32).

``CONVERTIBLE_TEMPERATURE`` (the legacy rename alias) is REMOVED — its value
is ignored and a run that sets it gets a loud warning. ``COLLEAGUE_TEMPERATURE``
is DEPRECATED over one release: it still applies exactly as it does today,
but warns, naming ``.colleague/models.json`` as the per-half replacement. A
run with neither set is completely silent.
"""

from __future__ import annotations

import pytest

from colleague.cli._commands._work_support import _stamp_run_metadata
from colleague.config import EngineConfig
from colleague.config_resolve import TemperatureDeprecationWarning
from colleague.contract import OK, TaskResult


def test_neither_variable_set_is_silent(capsys: pytest.CaptureFixture) -> None:
    """A plain run with no temperature env vars carries no warning and
    prints nothing."""
    cfg = EngineConfig.resolve()
    assert cfg.temperature_deprecation_warnings == ()
    err = capsys.readouterr().err
    assert err == ""


def test_convertible_temperature_removed_and_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """CONVERTIBLE_TEMPERATURE is removed: its VALUE never applies, and a
    warning is recorded + printed."""
    monkeypatch.setenv("CONVERTIBLE_TEMPERATURE", "1.9")
    cfg = EngineConfig.resolve()

    # The legacy alias's value is IGNORED — resolution falls through to the
    # builtin default, never 1.9.
    assert cfg.temperature == 0.0

    assert len(cfg.temperature_deprecation_warnings) == 1
    warning = cfg.temperature_deprecation_warnings[0]
    assert isinstance(warning, TemperatureDeprecationWarning)
    assert warning.variable == "CONVERTIBLE_TEMPERATURE"
    assert warning.kind == "removed"

    err = capsys.readouterr().err
    assert "CONVERTIBLE_TEMPERATURE" in err
    assert "removed" in err.lower()


def test_colleague_temperature_still_applies_and_warns_deprecated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """COLLEAGUE_TEMPERATURE still works THIS release — same value, same
    meaning as today — but warns that it is deprecated."""
    monkeypatch.setenv("COLLEAGUE_TEMPERATURE", "0.6")
    cfg = EngineConfig.resolve()

    # Back-compat guarantee (acceptance 2): the value still applies.
    assert cfg.temperature == 0.6

    assert len(cfg.temperature_deprecation_warnings) == 1
    warning = cfg.temperature_deprecation_warnings[0]
    assert warning.variable == "COLLEAGUE_TEMPERATURE"
    assert warning.kind == "deprecated"

    err = capsys.readouterr().err
    assert "COLLEAGUE_TEMPERATURE" in err
    assert "deprecated" in err.lower()
    # .colleague/models.json is named as the replacement.
    assert ".colleague/models.json" in err
    # Acceptance 6: a reader can tell BOTH halves collapse to the one value.
    assert "thinking" in err.lower()
    assert "non-thinking" in err.lower() or "non_thinking" in err.lower()


def test_both_variables_set_records_both_warnings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("CONVERTIBLE_TEMPERATURE", "1.9")
    monkeypatch.setenv("COLLEAGUE_TEMPERATURE", "0.6")
    cfg = EngineConfig.resolve()

    # COLLEAGUE_TEMPERATURE wins over the removed alias, as it always has.
    assert cfg.temperature == 0.6
    kinds = {w.kind for w in cfg.temperature_deprecation_warnings}
    assert kinds == {"removed", "deprecated"}

    err = capsys.readouterr().err
    assert err.count("\n") == 2  # one line per warning, no duplicates


def test_warning_prints_exactly_once_per_resolve(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("COLLEAGUE_TEMPERATURE", "0.6")
    EngineConfig.resolve()
    err = capsys.readouterr().err
    assert err.count("COLLEAGUE_TEMPERATURE is deprecated") == 1


def test_pre_arc_operator_config_resolves_identically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 2: an operator config predating this arc (COLLEAGUE_TEMPERATURE
    set, no knowledge of CONVERTIBLE_TEMPERATURE ever existing) resolves to the
    SAME temperature value in this release."""
    monkeypatch.setenv("COLLEAGUE_TEMPERATURE", "0.42")
    cfg = EngineConfig.resolve()
    assert cfg.temperature == 0.42


def test_default_temperature_unset_is_zero() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.temperature == 0.0


def test_to_dict_of_warning_carries_message() -> None:
    warning = TemperatureDeprecationWarning("COLLEAGUE_TEMPERATURE", "deprecated")
    data = warning.to_dict()
    assert data["variable"] == "COLLEAGUE_TEMPERATURE"
    assert data["kind"] == "deprecated"
    assert ".colleague/models.json" in data["message"]


# ── the warning lands on TaskResult.warnings (acceptance 3) ────────────────


def test_stamp_run_metadata_folds_temperature_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_TEMPERATURE", "0.6")
    config = EngineConfig.resolve(model="m")
    result = TaskResult(task_id="x", status=OK, summary="s")
    _stamp_run_metadata(
        result, config=config, command_name=None, mode=None, continued_from=None, chain=None
    )
    assert len(config.temperature_deprecation_warnings) == 1
    expected = config.temperature_deprecation_warnings[0].to_dict()
    assert expected in result.warnings


def test_stamp_run_metadata_is_silent_when_unset() -> None:
    config = EngineConfig.resolve(model="m")
    result = TaskResult(task_id="x", status=OK, summary="s")
    _stamp_run_metadata(
        result, config=config, command_name=None, mode=None, continued_from=None, chain=None
    )
    assert result.warnings == []

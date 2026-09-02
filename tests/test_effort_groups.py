"""Task t10 — config show / session /effort render the 3 thinking-effort groups.

Covers c12, h12, h35. Three groups: ``seats`` (:data:`colleague.effort.
SEAT_TABLE`), ``associate.<seat>`` (:data:`colleague.efforttables.
ASSOCIATE_SEAT_TABLE`), and ``purposes`` (:data:`colleague.efforttables.
PURPOSE_TABLE`). ``colleague config show`` and the session ``/effort`` verb
both render all three groups with resolved rungs; an invalid value in ANY
group refuses at ``EngineConfig.resolve()`` time with
:func:`colleague.effort.validate_effort`'s message (parametrised per group);
``--json`` gains only new keys (the existing ``reasoning_effort*`` keys are
untouched).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import efforttables
from colleague.cli._commands import _effort_groups, _session_actions
from colleague.cli._commands.config import _config_show
from colleague.cli._commands.session import SessionIO, _Session
from colleague.cli._errors import CliError
from colleague.config import EngineConfig

_ALL_ENV = (
    "COLLEAGUE_REASONING_EFFORT",
    "COLLEAGUE_CORTEX_REASONING_EFFORT",
    "COLLEAGUE_ASSOCIATE_REASONING_EFFORT_SCOUT",
    "COLLEAGUE_WEB_SURVEY_REASONING_EFFORT",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _make_session(tmp_path: Path) -> _Session:
    return _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(model="cur"),
        json_mode=False,
        view="markdown",
        io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
        work_fn=lambda **k: None,
    )


# ---------------------------------------------------------------------------
# `config show` — 3 groups, resolved rungs.
# ---------------------------------------------------------------------------


def test_config_show_text_prints_three_group_titles() -> None:
    rendered = _config_show(".")
    text = rendered._text
    assert "seats:" in text
    assert "associate.<seat>:" in text
    assert "purposes:" in text


def test_config_show_text_names_every_seat_associate_seat_and_purpose() -> None:
    from colleague.effort import SEAT_TABLE

    text = _config_show(".")._text
    for seat in SEAT_TABLE:
        assert f"{seat}: " in text
    for sub_seat in efforttables.ASSOCIATE_SEAT_TABLE:
        assert f"associate.{sub_seat}: " in text
    for purpose in efforttables.PURPOSE_TABLE:
        assert f"{purpose}: " in text


def test_config_show_json_reasoning_effort_resolved_has_three_groups() -> None:
    rendered = _config_show(".")
    data = rendered
    resolved = data["reasoning_effort_resolved"]
    assert set(resolved) == {"seats", "associate", "purposes"}
    from colleague.effort import SEAT_TABLE

    assert set(resolved["seats"]) == set(SEAT_TABLE)
    assert set(resolved["associate"]) == {
        f"associate.{s}" for s in efforttables.ASSOCIATE_SEAT_TABLE
    }
    assert set(resolved["purposes"]) == set(efforttables.PURPOSE_TABLE)
    # table defaults, nothing overridden (v4, #475: all three at "low")
    assert resolved["seats"]["cortex"] == "off"
    assert resolved["associate"]["associate.scout"] == "low"
    assert resolved["purposes"]["web_survey"] == "low"


def test_config_show_json_additive_only_pre_existing_keys_still_present() -> None:
    """The pre-existing reasoning_effort/_seats/_purposes keys (raw override
    state) are untouched by the new resolved-groups key — additive only."""
    data = _config_show(".")
    assert "reasoning_effort" in data
    assert "reasoning_effort_seats" in data
    assert "reasoning_effort_purposes" in data
    assert data["reasoning_effort_seats"] == {}
    assert data["reasoning_effort_purposes"] == {}


def test_config_show_json_resolved_reflects_an_associate_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_REASONING_EFFORT_SCOUT", "high")
    resolved = _config_show(".")["reasoning_effort_resolved"]
    assert resolved["associate"]["associate.scout"] == "high"


def test_config_show_json_resolved_reflects_a_purpose_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_WEB_SURVEY_REASONING_EFFORT", "medium")
    resolved = _config_show(".")["reasoning_effort_resolved"]
    assert resolved["purposes"]["web_survey"] == "medium"


def test_config_show_json_resolved_kill_switch_all_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_REASONING_EFFORT", "default")
    resolved = _config_show(".")["reasoning_effort_resolved"]
    assert resolved["seats"]["cortex"] is None
    assert resolved["associate"]["associate.scout"] is None
    assert resolved["purposes"]["web_survey"] is None


# ---------------------------------------------------------------------------
# session `/effort` — 3 groups, no-arg listing + switch.
# ---------------------------------------------------------------------------


def test_session_effort_listing_names_associate_and_purpose_rows(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    out = _session_actions._act_effort(s, [])
    # v4 (#475): associate sub-seats and purposes all list at "low"
    assert "associate.scout low" in out
    assert "associate.distill low" in out
    assert "web_survey low" in out
    assert "plan low" in out


@pytest.mark.parametrize(
    "name,expect",
    [
        ("associate.scout", "associate.scout"),
        ("web_survey", "web_survey"),
    ],
)
def test_session_effort_switch_associate_and_purpose_names(
    tmp_path: Path, name: str, expect: str
) -> None:
    s = _make_session(tmp_path)
    out = _session_actions._act_effort(s, ["high", name])
    assert out == f"effort {expect} → high (session-only)"


def test_session_effort_switch_associate_seat_applies_to_config(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    _session_actions._act_effort(s, ["xhigh", "associate.scout"])
    assert s.config.reasoning_effort_seats.get("associate.scout") == "xhigh"


def test_session_effort_switch_purpose_applies_to_config(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    _session_actions._act_effort(s, ["medium", "code_survey"])
    assert s.config.reasoning_effort_purposes.get("code_survey") == "medium"


def test_session_effort_switch_unknown_name_raises_value_error(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    with pytest.raises(ValueError):
        _session_actions._act_effort(s, ["high", "not-a-real-name"])


def test_session_effort_switch_bad_rung_on_associate_name_raises(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    with pytest.raises(ValueError) as exc:
        _session_actions._act_effort(s, ["bogus", "associate.scout"])
    assert "off" in str(exc.value)  # the ladder is named
    assert s.config.reasoning_effort_seats == {}


def test_session_effort_switch_bad_rung_on_purpose_name_raises(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    with pytest.raises(ValueError) as exc:
        _session_actions._act_effort(s, ["bogus", "web_survey"])
    assert "off" in str(exc.value)
    assert s.config.reasoning_effort_purposes == {}


# ---------------------------------------------------------------------------
# _effort_groups module — direct unit coverage.
# ---------------------------------------------------------------------------


def test_valid_names_covers_all_three_groups_plus_all() -> None:
    names = _effort_groups.valid_names()
    assert "all" in names
    assert "cortex" in names
    assert "associate.scout" in names
    assert "web_survey" in names


def test_apply_group_effort_all_sets_global() -> None:
    cfg = EngineConfig.resolve(model="cur")
    _effort_groups.apply_group_effort(cfg, "medium", "all")
    assert cfg.reasoning_effort == "medium"


def test_apply_group_effort_unknown_name_lists_valid_names() -> None:
    cfg = EngineConfig.resolve(model="cur")
    with pytest.raises(ValueError) as exc:
        _effort_groups.apply_group_effort(cfg, "high", "bogus-name")
    assert "associate.scout" in str(exc.value)
    assert "web_survey" in str(exc.value)


# ---------------------------------------------------------------------------
# resolve()-time refusal, parametrised per group (validate_effort's message).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_key",
    [
        "COLLEAGUE_CORTEX_REASONING_EFFORT",  # seats
        "COLLEAGUE_ASSOCIATE_REASONING_EFFORT_SCOUT",  # associate.<seat>
        "COLLEAGUE_WEB_SURVEY_REASONING_EFFORT",  # purposes
    ],
)
def test_resolve_refuses_bad_value_per_group(monkeypatch: pytest.MonkeyPatch, env_key: str) -> None:
    monkeypatch.setenv(env_key, "not-a-rung")
    with pytest.raises(CliError) as exc_info:
        EngineConfig.resolve()
    message = str(exc_info.value)
    for rung in ("off", "low", "medium", "high", "xhigh", "default"):
        assert rung in message
    assert "not-a-rung" in message

"""Enumerated c19 pin-breaks + per-front degrade/JSON pins (presence-default, t13).

The presence-default-everywhere arc DELIBERATELY breaks the pre-arc "off-TTY /
piped is byte-identical" guarantee: presence is now the default on every front,
including non-interactive callers. This module is the single place that
ENUMERATES every broken byte-identical expectation and pins the compensating
guarantees, so the convention change is reviewable one by one, never silent.

ENUMERATED PIN-BREAKS (each updated in the SAME change with a stated reason):

1. `tests/test_session_presence.py::test_ack_speaks_off_tty_when_senses_armed`
   (was `test_ack_is_silent_when_lane_disabled_off_tty`) — an off-TTY session
   with senses ARMED now speaks the ack. Reason: c19 — presence is default on
   every front, no longer colour-TTY-only.
2. `tests/test_session_presence.py::test_update_fires_off_tty_when_senses_armed`
   (was `test_update_noop_when_lane_unarmed`) — proactive updates now fire
   off-TTY with senses armed. Same reason.
3. `tests/test_session_presence.py::test_off_tty_session_accumulates_history_when_senses_armed`
   (was `test_unarmed_session_accumulates_no_history`) — off-TTY sessions with
   senses armed now accumulate rolling history. Same reason.

No OTHER byte-identical test was broken by this arc (the full suite is green);
every front's UNARMED / --cortex-only path stays byte-identical, pinned per
front (test_session_presence / test_talk_presence / test_background_presence /
test_work_foreground_presence / test_resident_presence) and re-cross-checked
here. The one guarantee that must NEVER break — a structured `--json` stdout
stays machine-parseable — is pinned as a live e2e below.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main
from colleague.config import EngineConfig, SensesConfig, resolve_presence_rung
from colleague.contract import OK


# ── the JSON contract survives presence on every structured surface ───────────
def test_work_json_stdout_stays_parseable_with_senses_armed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    # Arm senses (the presence lane is default-on → rung 'loop'); a one-shot
    # `colleague work --json` must still emit ONLY the JSON result on stdout —
    # every senses beat goes to stderr, so an ask-colleague-style caller that
    # pipes stdout and json.loads() it is never corrupted (c19 / h16).
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "senses-model")
    monkeypatch.setenv("COLLEAGUE_SENSES_BASE_URL", "http://senses")

    rc = main(
        ["work", "leave a note", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    captured = capsys.readouterr()
    assert rc == 0
    # The load itself is the assertion — a single senses line leaking onto stdout
    # would make this raise.
    result = json.loads(captured.out)
    assert result["status"] == OK
    # And the presence beats DID render — just on stderr, never stdout.
    assert "senses:" not in captured.out


def test_work_json_byte_identical_when_senses_unarmed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # With no senses resolved the whole lane is a strict no-op: stdout is the
    # JSON result, and no `senses:` line appears anywhere (byte-identical).
    rc = main(
        ["work", "leave a note", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    assert result["status"] == OK
    assert "senses:" not in captured.out and "senses:" not in captured.err


# ── the off-switch is the same on every front (the compensating guarantee) ────
def _armed() -> EngineConfig:
    config = EngineConfig()
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def test_cortex_only_disarms_presence_on_every_front() -> None:
    # The single off switch (`--cortex-only`) resolves the whole lane to 'off'
    # regardless of front — the c19 pin-breaks never become 'forced'.
    armed = _armed()
    assert resolve_presence_rung(armed) == "loop"  # default-on when armed
    assert resolve_presence_rung(armed, cortex_only=True) == "off"  # the off switch


def test_senses_unarmed_is_off_everywhere() -> None:
    # Nothing to talk to → 'off' → byte-identical, on every front.
    assert resolve_presence_rung(EngineConfig()) == "off"


def test_env_and_config_off_switch_resolves_off(monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "off")
    assert resolve_presence_rung(_armed()) == "off"


def test_beats_opt_down_is_selectable(monkeypatch) -> None:
    # The ladder's middle rung (fixed-beat lane) is operator-selectable — the
    # degradation ladder is a real, resolvable choice, not just a fallback.
    monkeypatch.setenv("COLLEAGUE_PRESENCE", "beats")
    assert resolve_presence_rung(_armed()) == "beats"

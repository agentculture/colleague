"""Tests for the session ``/effort`` action (plan task t4).

``/effort`` with no argument prints one line per seat (cortex, worker,
deepthink, evaluator, senses, design) plus the acting role, using
``colleague.effort.effort_of`` / ``resolve_effort`` — what is actually sent,
including ``unset`` under the default kill-switch. ``/effort <rung> [seat]``
(default seat ``cortex``) validates via ``effort.validate_effort`` (a bad rung
surfaces as a ``ValueError`` for the slash dispatcher), mutates
``s.config.reasoning_effort_seats[seat]`` (or ``reasoning_effort`` for
``all``), and prints ``effort <seat> → <rung> (session-only)``; the next
request's ``chat_template_kwargs`` reflects it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from colleague.cli._commands import _session_actions
from colleague.cli._commands.session import (
    _CONFIG_ACTIONS,
    _HELP_TEXT,
    _SLASH_COMMANDS,
    SessionIO,
    _Session,
)
from colleague.config import EngineConfig
from colleague.engines.vllm_openai import VllmOpenAIEngine


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


def _payload_kwargs(config: EngineConfig) -> dict | None:
    """The next request's ``chat_template_kwargs`` for *config* (the vllm
    driver's own builder — what the backend would actually send)."""
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(config, [], [])
    return payload.get("chat_template_kwargs")


# ---------------------------------------------------------------------------
# AC1 — no-arg per-seat table
# ---------------------------------------------------------------------------


def test_effort_no_arg_lists_every_seat_and_acting_role(tmp_path: Path) -> None:
    """AC1: no-arg /effort prints one line per seat + the acting role, showing
    what is actually sent (the seat-table rung when nothing is set)."""
    s = _make_session(tmp_path)
    out = _session_actions._act_effort(s, [])
    for seat in ("cortex", "worker", "deepthink", "evaluator", "senses", "design"):
        assert f"{seat} " in out, f"seat {seat!r} missing from the table"
    assert "acting role" in out
    # The seat-table defaults are what is sent when nothing is set.
    assert "cortex medium" in out
    assert "senses off" in out
    assert "deepthink xhigh" in out
    # The acting role (cortex, worker unarmed) resolves to the same rung.
    assert "acting role (cortex) medium" in out


def test_effort_no_arg_unset_under_kill_switch(tmp_path: Path) -> None:
    """AC1: under the default kill-switch every seat reads ``unset`` — what is
    actually sent is nothing."""
    s = _make_session(tmp_path)
    s.config.reasoning_effort = "default"
    out = _session_actions._act_effort(s, [])
    assert "unset" in out
    # The kill-switch wins over the seat table: no seat shows its table rung.
    assert "cortex medium" not in out
    assert "senses off" not in out
    assert "acting role (cortex) unset" in out


def test_effort_no_arg_reflects_a_seat_override(tmp_path: Path) -> None:
    """AC1: a per-seat override shows the overridden rung, not the table default."""
    s = _make_session(tmp_path)
    s.config.reasoning_effort_seats = {"cortex": "high"}
    out = _session_actions._act_effort(s, [])
    assert "cortex high" in out
    assert "cortex medium" not in out
    # The acting role (cortex) reflects the override too.
    assert "acting role (cortex) high" in out


# ---------------------------------------------------------------------------
# AC2 — switch + request-dump assertion
# ---------------------------------------------------------------------------


def test_effort_switch_default_seat_cortex(tmp_path: Path) -> None:
    """AC2: /effort <rung> (no seat) targets cortex, mutates the seat override,
    and the next request's chat_template_kwargs reflects it."""
    s = _make_session(tmp_path)
    out = _session_actions._act_effort(s, ["high"])
    assert s.config.reasoning_effort_seats.get("cortex") == "high"
    assert out == "effort cortex → high (session-only)"
    # The acting seat (cortex) now sends the switched rung.
    assert _payload_kwargs(s.config) == {"reasoning_effort": "high"}


def test_effort_switch_named_seat(tmp_path: Path) -> None:
    """AC2: /effort <rung> <seat> mutates that seat's override."""
    s = _make_session(tmp_path)
    out = _session_actions._act_effort(s, ["low", "senses"])
    assert s.config.reasoning_effort_seats.get("senses") == "low"
    assert out == "effort senses → low (session-only)"


def test_effort_switch_all_sets_global(tmp_path: Path) -> None:
    """AC2: /effort <rung> all mutates the global knob (reasoning_effort)."""
    s = _make_session(tmp_path)
    out = _session_actions._act_effort(s, ["medium", "all"])
    assert s.config.reasoning_effort == "medium"
    assert out == "effort all → medium (session-only)"
    # The global override wins for the acting seat.
    assert _payload_kwargs(s.config) == {"reasoning_effort": "medium"}


def test_effort_switch_off_sends_enable_thinking_false(tmp_path: Path) -> None:
    """AC2: switching a seat to ``off`` renders the vLLM/Qwen3 toggle, not a
    reasoning_effort key."""
    s = _make_session(tmp_path)
    _session_actions._act_effort(s, ["off", "cortex"])
    assert _payload_kwargs(s.config) == {"enable_thinking": False}


def test_effort_switch_default_kill_switch_sends_nothing(tmp_path: Path) -> None:
    """AC2: switching to the ``default`` sentinel kill-switches the seat — the
    next request carries no chat_template_kwargs at all."""
    s = _make_session(tmp_path)
    out = _session_actions._act_effort(s, ["default", "cortex"])
    assert s.config.reasoning_effort_seats.get("cortex") == "default"
    assert out == "effort cortex → default (session-only)"
    assert _payload_kwargs(s.config) is None


def test_effort_bad_rung_raises_value_error(tmp_path: Path) -> None:
    """AC2: a bad rung raises ValueError (the slash dispatcher's error type)
    naming the ladder, and mutates nothing."""
    s = _make_session(tmp_path)
    with pytest.raises(ValueError) as exc:
        _session_actions._act_effort(s, ["bogus"])
    assert "bogus" in str(exc.value)
    assert "off" in str(exc.value)  # the ladder is named
    assert s.config.reasoning_effort_seats == {}
    assert s.config.reasoning_effort is None


# ---------------------------------------------------------------------------
# AC3 — catalog / help drift
# ---------------------------------------------------------------------------


def test_effort_registered_in_config_actions() -> None:
    assert "effort" in _CONFIG_ACTIONS
    assert _CONFIG_ACTIONS["effort"] is _session_actions._act_effort


def test_effort_in_catalog_and_help() -> None:
    names = {s.name for s in _SLASH_COMMANDS}
    assert "effort" in names
    assert "/effort" in _HELP_TEXT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

"""Tests for colleague.presence — cadence policy for senses proactive updates.

Arc: 'talking to colleague feels like talking to one person' (task t2).
"""

import ast

import pytest

from colleague.presence import UpdateCadence, cadence_from_env, should_update

# ── UpdateCadence defaults ─────────────────────────────────────────


class TestUpdateCadenceDefaults:
    """UpdateCadence dataclass defaults."""

    def test_default_values(self):
        c = UpdateCadence()
        assert c.every_steps == 8
        assert c.on_phase_change is True
        assert c.max_updates == 4

    def test_frozen(self):
        c = UpdateCadence()
        with pytest.raises(Exception):  # dataclasses frozen raises FrozenInstanceError
            c.every_steps = 1


# ── cadence_from_env ───────────────────────────────────────────────


class TestCadenceFromEnv:
    """cadence_from_env(env) → UpdateCadence."""

    def test_all_defaults(self):
        c = cadence_from_env({})
        assert c.every_steps == 8
        assert c.on_phase_change is True
        assert c.max_updates == 4

    def test_custom_steps(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_STEPS": "3"})
        assert c.every_steps == 3

    def test_phase_disabled(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_PHASE": "0"})
        assert c.on_phase_change is False

    def test_phase_enabled_anything_else(self):
        for val in ("1", "true", "yes", ""):
            c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_PHASE": val})
            assert c.on_phase_change is True

    def test_custom_cap(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_CAP": "10"})
        assert c.max_updates == 10

    def test_cap_zero_disables_updates(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_CAP": "0"})
        assert c.max_updates == 0

    def test_malformed_steps_falls_back(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_STEPS": "not_a_number"})
        assert c.every_steps == 8

    def test_negative_steps_falls_back(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_STEPS": "-1"})
        assert c.every_steps == 8

    def test_malformed_phase_keeps_enabled(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_PHASE": "garbage"})
        assert c.on_phase_change is True

    def test_malformed_cap_falls_back(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_CAP": "abc"})
        assert c.max_updates == 4

    def test_negative_cap_falls_back(self):
        c = cadence_from_env({"COLLEAGUE_SENSES_UPDATE_CAP": "-5"})
        assert c.max_updates == 4

    def test_all_custom(self):
        env = {
            "COLLEAGUE_SENSES_UPDATE_STEPS": "5",
            "COLLEAGUE_SENSES_UPDATE_PHASE": "0",
            "COLLEAGUE_SENSES_UPDATE_CAP": "2",
        }
        c = cadence_from_env(env)
        assert c.every_steps == 5
        assert c.on_phase_change is False
        assert c.max_updates == 2


# ── should_update ──────────────────────────────────────────────────


class TestShouldUpdate:
    """should_update(cadence, ...) → (bool, str)."""

    def test_fires_on_phase_change(self):
        c = UpdateCadence()
        ok, reason = should_update(
            c, step_count=5, last_update_step=0, phase_changed=True, updates_sent=0
        )
        assert ok is True
        assert reason == "phase-change"

    def test_does_not_fire_on_phase_change_when_disabled(self):
        c = UpdateCadence(on_phase_change=False)
        ok, reason = should_update(
            c, step_count=5, last_update_step=0, phase_changed=True, updates_sent=0
        )
        assert ok is False
        assert reason == ""

    def test_fires_on_every_n_boundary(self):
        c = UpdateCadence(every_steps=8, on_phase_change=False)
        ok, reason = should_update(
            c, step_count=8, last_update_step=0, phase_changed=False, updates_sent=0
        )
        assert ok is True
        assert reason == "every-n"

    def test_does_not_fire_before_every_n_boundary(self):
        c = UpdateCadence(every_steps=8, on_phase_change=False)
        ok, reason = should_update(
            c, step_count=7, last_update_step=0, phase_changed=False, updates_sent=0
        )
        assert ok is False
        assert reason == ""

    def test_cap_returns_false_cap(self):
        c = UpdateCadence(max_updates=2)
        # Two updates already sent; a phase-change fire would happen but cap blocks it
        ok, reason = should_update(
            c, step_count=10, last_update_step=0, phase_changed=True, updates_sent=2
        )
        assert ok is False
        assert reason == "cap"

    def test_cap_zero_blocks_every_fire(self):
        c = UpdateCadence(max_updates=0)
        ok, reason = should_update(
            c, step_count=8, last_update_step=0, phase_changed=False, updates_sent=0
        )
        assert ok is False
        assert reason == "cap"

    def test_cap_zero_blocks_phase_change(self):
        c = UpdateCadence(max_updates=0)
        ok, reason = should_update(
            c, step_count=1, last_update_step=0, phase_changed=True, updates_sent=0
        )
        assert ok is False
        assert reason == "cap"

    def test_no_fire_no_cap_signal(self):
        c = UpdateCadence(every_steps=8, on_phase_change=False, max_updates=0)
        # No fire condition met (step delta < every_steps, no phase change)
        ok, reason = should_update(
            c, step_count=3, last_update_step=0, phase_changed=False, updates_sent=0
        )
        assert ok is False
        assert reason == ""

    def test_updates_sent_below_cap_fires(self):
        c = UpdateCadence(max_updates=3)
        ok, reason = should_update(
            c, step_count=8, last_update_step=0, phase_changed=False, updates_sent=2
        )
        assert ok is True
        assert reason == "every-n"

    def test_phase_change_takes_priority_over_every_n(self):
        c = UpdateCadence(every_steps=8)
        # Both conditions met — phase-change should win
        ok, reason = should_update(
            c, step_count=8, last_update_step=0, phase_changed=True, updates_sent=0
        )
        assert ok is True
        assert reason == "phase-change"


# ── no-forbidden-imports ───────────────────────────────────────────


class TestNoForbiddenImports:
    """The module must not import time, threading, datetime, or subprocess."""

    def test_no_forbidden_imports(self):
        import pathlib

        mod_path = pathlib.Path(__file__).resolve().parent.parent / "colleague" / "presence.py"
        source = mod_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden = {"time", "threading", "datetime", "subprocess"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"Forbidden import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    assert top not in forbidden, f"Forbidden from-import: {node.module}"

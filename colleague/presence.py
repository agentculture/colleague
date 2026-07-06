"""Cadence policy for senses proactive updates.

Arc: 'talking to colleague feels like talking to one person' (task t2).
Clock-free, thread-free decision helper that determines when a proactive
status update should fire during a work loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple


@dataclass(frozen=True)
class UpdateCadence:
    """How often proactive updates fire during a work loop."""

    every_steps: int = 8
    on_phase_change: bool = True
    max_updates: int = 4


def cadence_from_env(env: Mapping[str, str]) -> UpdateCadence:
    """Build an :class:`UpdateCadence` from environment variables.

    Reads ``COLLEAGUE_SENSES_UPDATE_STEPS`` (positive int; absent or
    invalid falls back to 8), ``COLLEAGUE_SENSES_UPDATE_PHASE`` (the
    string ``'0'`` disables phase-change firing; anything else or absent
    leaves it enabled), and ``COLLEAGUE_SENSES_UPDATE_CAP`` (int >= 0; 0
    means updates disabled entirely; absent or invalid falls back to 4).
    Never raises on malformed values.
    """
    every_steps = 8
    raw_steps = env.get("COLLEAGUE_SENSES_UPDATE_STEPS")
    if raw_steps is not None:
        try:
            val = int(raw_steps)
            if val > 0:
                every_steps = val
        except (ValueError, OverflowError):
            pass

    on_phase_change = True
    raw_phase = env.get("COLLEAGUE_SENSES_UPDATE_PHASE")
    if raw_phase is not None and raw_phase == "0":
        on_phase_change = False

    max_updates = 4
    raw_cap = env.get("COLLEAGUE_SENSES_UPDATE_CAP")
    if raw_cap is not None:
        try:
            val = int(raw_cap)
            if val >= 0:
                max_updates = val
        except (ValueError, OverflowError):
            pass

    return UpdateCadence(
        every_steps=every_steps,
        on_phase_change=on_phase_change,
        max_updates=max_updates,
    )


def should_update(
    cadence: UpdateCadence,
    *,
    step_count: int,
    last_update_step: int,
    phase_changed: bool,
    updates_sent: int,
) -> Tuple[bool, str]:
    """Decide whether a proactive update fires at this progress boundary.

    Returns ``(True, reason)`` when an update should fire, ``(False, 'cap')``
    when a fire would have happened but the cap is reached, or ``(False, '')``
    when no fire condition is met.
    """
    # Determine whether a fire *would* happen and why.
    if phase_changed and cadence.on_phase_change:
        reason: str = "phase-change"
    elif step_count - last_update_step >= cadence.every_steps:
        reason = "every-n"
    else:
        return (False, "")

    # A fire would happen — check the cap.
    if updates_sent >= cadence.max_updates:
        return (False, "cap")

    return (True, reason)

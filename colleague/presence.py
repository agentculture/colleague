"""Cadence + clarify policy for the senses middle-manager lane.

Arc: 'talking to colleague feels like talking to one person' (tasks t2 + t7).
Clock-free, thread-free decision helpers: when a proactive status update
should fire during a work loop (t2), and when a low-confidence intake may ask
the operator a clarifying question before dispatching to cortex (t7). Pure
policy only — no I/O, no model calls, no clock.
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


@dataclass(frozen=True)
class ClarifyPolicy:
    """When a low-confidence intake may ask before dispatching (t7 / c19).

    ``confidence_floor`` — intake confidence below this MAY trigger a clarify
    question (senses' own judgment rides the packet: its confidence + its
    omissions). ``max_questions`` — the consecutive-question ceiling, a
    generous loop-proofing bound, not a UX cap (h8); ``0`` disables clarify
    entirely (always dispatch immediately).
    """

    confidence_floor: float = 0.45
    max_questions: int = 3


def clarify_from_env(env: Mapping[str, str]) -> ClarifyPolicy:
    """Build a :class:`ClarifyPolicy` from environment variables.

    Reads ``COLLEAGUE_SENSES_CLARIFY_CONFIDENCE`` (float in [0.0, 1.0]; absent
    or invalid falls back to 0.45) and ``COLLEAGUE_SENSES_CLARIFY_MAX``
    (int >= 0; 0 disables clarify entirely; absent or invalid falls back
    to 3). Never raises on malformed values.
    """
    confidence_floor = 0.45
    raw_floor = env.get("COLLEAGUE_SENSES_CLARIFY_CONFIDENCE")
    if raw_floor is not None:
        try:
            val = float(raw_floor)
            if 0.0 <= val <= 1.0:
                confidence_floor = val
        except (ValueError, OverflowError):
            pass

    max_questions = 3
    raw_max = env.get("COLLEAGUE_SENSES_CLARIFY_MAX")
    if raw_max is not None:
        try:
            ival = int(raw_max)
            if ival >= 0:
                max_questions = ival
        except (ValueError, OverflowError):
            pass

    return ClarifyPolicy(confidence_floor=confidence_floor, max_questions=max_questions)


def should_clarify(
    policy: ClarifyPolicy,
    *,
    confidence: float,
    has_omissions: bool,
    questions_asked: int,
) -> bool:
    """Decide whether senses may ask (another) clarifying question (t7).

    True only while ALL hold: clarify is enabled (``max_questions > 0``), the
    ceiling is not reached, the intake confidence sits below the floor, and
    the packet actually lists omissions — a question must be grounded in what
    intake itself said was left unspecified, never canned filler.
    """
    return (
        policy.max_questions > 0
        and questions_asked < policy.max_questions
        and confidence < policy.confidence_floor
        and has_omissions
    )


#: Normalized operator go-words: any of these dispatches IMMEDIATELY and
#: unconditionally — clarification can never withhold work (h8).
GO_WORDS = frozenset(
    {"go", "go ahead", "proceed", "dispatch", "just go", "run it", "ship it", "do it"}
)


def is_go_word(text: str) -> bool:
    """True iff *text* is an explicit operator go-word (case/punct-insensitive)."""
    return text.strip().strip(".!,").strip().lower() in GO_WORDS

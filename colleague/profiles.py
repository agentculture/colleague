"""Mode-profile catalog — the single source of truth for per-mode constraint
profiles (R1 of the work-modes spec).

Selecting a work mode (session mode, role, or ``ask-colleague`` verb) should
resolve a named bundle of compute/context knobs — step budget, context-budget
fraction, synthesis reserve steps, timeout, and fill-line threshold — instead
of every mode sharing one global knob set. This module is the pure catalog:
it holds the profile data and a lookup function only. Wiring the resolved
profile into ``EngineConfig.resolve`` / ``ContextControls`` (the new default
layer sitting between env vars and the built-in default) is a separate task
(t2); this module has no knowledge of that precedence chain.

Pure module: stdlib only, zero new dependencies, no import-time I/O, no
side effects. Does not import ``colleague.config`` or ``colleague.loop`` —
keeping the catalog free of the runtime config/precedence machinery it will
later feed (avoids import cycles and keeps this module trivially testable).

The exact per-mode numbers below are CONSERVATIVE DEFAULTS, not tuned
constants: they are deliberately parked as a documented follow-up ("live
tuning on a working served model") per the plan's risk r1, and may be
adjusted in a later PR without changing the shape of this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Profile data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeProfile:
    """A named bundle of compute/context constraint knobs for one work mode.

    Attributes
    ----------
    max_steps:
        Cap on the number of tool-loop steps for a work item in this mode.
    context_budget_fraction:
        Fraction (0, 1] of the resolved context budget (in tokens) this mode
        is allotted. ``1.0`` means "the full budget" — no scaling.
    synthesis_reserve_steps:
        Steps held back from the reading budget so the forced-synthesis /
        verdict turn isn't starved by context-reading (see #197).
    timeout:
        Per-request timeout in seconds.
    fillline_threshold:
        Fraction of the context budget at which the proactive capacity
        decision (compact | split | finish-with-handoff, #156) fires.
    """

    max_steps: int
    context_budget_fraction: float
    synthesis_reserve_steps: int
    timeout: float
    fillline_threshold: float


# ---------------------------------------------------------------------------
# Built-in catalog — one explicit entry per colleague.session_modes.MODES
# ---------------------------------------------------------------------------

#: The mode-profile catalog. Every entry in ``session_modes.MODES`` MUST have
#: an explicit key here (drift-tested) so a new mode can never ship without a
#: profile decision — even if that decision is "no profile" (``None``).
MODE_PROFILES: dict[str, Optional[ModeProfile]] = {
    # "auto" resolves to a concrete mode (via classify_intent / route_for)
    # before any work runs, so it never itself carries constraint knobs — an
    # explicit no-profile decision, not an oversight.
    "auto": None,
    # Exactly today's global built-in defaults (colleague.config.EngineConfig:
    # max_steps=40, context_budget_tokens unscaled (fraction=1.0), timeout=120.0,
    # synthesis_reserve_steps=0, fillline_threshold=0.8) — selecting work-mode
    # must be behavior-neutral (byte-identical to no mode at all, per the R1
    # honesty condition).
    "work": ModeProfile(
        max_steps=40,
        context_budget_fraction=1.0,
        synthesis_reserve_steps=0,
        timeout=120.0,
        fillline_threshold=0.8,
    ),
    # Read-only investigation: a smaller reading budget, a reserved tail for
    # the verdict turn, and a lower fill-line so compaction kicks in earlier
    # on a smaller effective window.
    "explore": ModeProfile(
        max_steps=30,
        context_budget_fraction=0.75,
        synthesis_reserve_steps=3,
        timeout=120.0,
        fillline_threshold=0.7,
    ),
    # A diverse second opinion on a diff — same shape as explore (read-only,
    # verdict-shaped) so it shares the same conservative profile.
    "review": ModeProfile(
        max_steps=30,
        context_budget_fraction=0.75,
        synthesis_reserve_steps=3,
        timeout=120.0,
        fillline_threshold=0.7,
    ),
    # Staged spec/plan/workforce planning: closer to work-mode's full budget
    # (planning calls are chunked already, see plan/cli_driver.py) but a
    # slightly tighter fill-line since a plan run makes many smaller calls.
    "plan": ModeProfile(
        max_steps=40,
        context_budget_fraction=0.9,
        synthesis_reserve_steps=0,
        timeout=120.0,
        fillline_threshold=0.8,
    ),
}


def resolve_profile(mode: Optional[str]) -> Optional[ModeProfile]:
    """Return the mode profile for *mode*, or ``None`` when absent.

    ``None`` is returned for ``None``, for an unknown mode name, and for
    ``"auto"`` (which resolves to a concrete mode before profile lookup
    matters — see the ``MODE_PROFILES["auto"]`` comment above). Pure lookup:
    no I/O, no environment reads, no side effects.
    """
    if mode is None:
        return None
    return MODE_PROFILES.get(mode)

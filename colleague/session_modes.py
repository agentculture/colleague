"""Session modes for colleague — the single source of truth.

Pure module: stdlib only, zero new dependencies, no import-time I/O, no side
effects. Does not import anything from colleague.cli or colleague.loop (avoids
cycles).

Modes represent the active session context and control how free-text input is
routed to verbs. The ordered cycle is the canonical definition of mode order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from colleague import profiles
from colleague.profiles import ModeProfile

#: The ordered cycle of session modes — the ONLY definition of mode order.
MODES: tuple[str, ...] = ("auto", "work", "plan", "explore", "review")

#: Default session mode.
DEFAULT_MODE: str = "auto"


def next_mode(current: str) -> str:
    """Return the next mode in MODES, wrapping 'review' -> 'auto'.

    If *current* is not a known mode, return DEFAULT_MODE.
    """
    try:
        idx = MODES.index(current)
        return MODES[(idx + 1) % len(MODES)]
    except ValueError:
        return DEFAULT_MODE


def resolve_mode(name: str) -> str:
    """Normalize/validate a mode name (case-insensitive, strip whitespace).

    Return the canonical lowercase mode if valid; otherwise raise ValueError
    whose message names the valid modes.
    """
    canonical = name.strip().lower()
    if canonical in MODES:
        return canonical
    valid = ", ".join(MODES)
    raise ValueError(f"unknown mode '{name.strip()}'; valid: {valid}")


def mode_label(mode: str) -> str:
    """Return a short human label for the mode.

    For v1 the label is the mode name itself.
    """
    return mode


def route_for(mode: str, text: str, classify) -> str:
    """Decide which verb a free-text input runs under the active mode.

    If *mode* is 'auto', delegate to *classify(text)* and return its result
    verbatim. Otherwise return the mode name without calling *classify*.
    """
    if mode == "auto":
        return classify(text)
    return mode


def mode_affordance_line(mode: str) -> str:
    """Return a one-line visible affordance for the cockpit.

    Names all modes in cycle order with the active one bracketed, ending with
    the hint 'shift-tab to cycle'.

    Example::

        'mode: [auto] work plan explore review  ·  shift-tab to cycle'
    """
    parts: list[str] = []
    for m in MODES:
        if m == mode:
            parts.append(f"[{m}]")
        else:
            parts.append(m)
    modes_str = " ".join(parts)
    return f"mode: {modes_str}  ·  shift-tab to cycle"


# ---------------------------------------------------------------------------
# Mode facts — three distinct facts: behavior, source, execution profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeFacts:
    """The three distinct mode facts for the cockpit.

    Attributes
    ----------
    behavior:
        The active mode name (e.g. "explore"); for auto, "auto".
    source:
        "auto" when the mode was auto-classified per input, "pinned" when
        the operator set it explicitly.
    profile_rows:
        Ordered (label, value) rows for the resolved execution profile.
        Empty when no profile is available (auto with no sample input).
    resolved_from:
        For auto: the concrete mode it would resolve to for a given input,
        or "" when not applicable (auto with no sample input).
    """

    behavior: str
    source: str
    profile_rows: tuple[tuple[str, str], ...]
    resolved_from: str


def _profile_rows(profile: Optional[ModeProfile]) -> tuple[tuple[str, str], ...]:
    """Render a ModeProfile as ordered (label, value) rows (empty when no profile)."""
    rows: list[tuple[str, str]] = []
    if profile is not None:
        rows = [
            ("steps", str(profile.max_steps)),
            ("timeout", f"{profile.timeout:g}s"),
            ("context budget", f"{int(profile.context_budget_fraction * 100)}%"),
            ("fill-line", f"{int(profile.fillline_threshold * 100)}%"),
            ("synthesis reserve", str(profile.synthesis_reserve_steps)),
        ]
    return tuple(rows)


def mode_facts(mode: str, *, resolved_from: str = "") -> ModeFacts:
    """Build the three facts for *mode*.

    - behavior = the mode name.
    - source = "auto" when mode == "auto", else "pinned".
    - profile_rows: derive from profiles.resolve_profile(effective_mode) where
      effective_mode is *resolved_from* if mode == "auto" and resolved_from
      is set, else *mode*. Render the ModeProfile as ordered (label, value)
      rows. When resolve_profile returns None, profile_rows = ().
    - resolved_from = the effective concrete mode for auto (the passed
      *resolved_from*), else "".
    """
    source = "auto" if mode == "auto" else "pinned"

    if mode == "auto" and resolved_from:
        effective = resolved_from
    else:
        effective = mode

    profile = profiles.resolve_profile(effective)
    rows = _profile_rows(profile)

    if mode == "auto":
        rf = resolved_from if resolved_from else ""
    else:
        rf = ""

    return ModeFacts(
        behavior=mode,
        source=source,
        profile_rows=rows,
        resolved_from=rf,
    )


def mode_facts_fragment(facts: ModeFacts) -> str:
    """One-line status fragment naming all three facts.

    Examples
    --------
    Pinned mode::

        'mode: explore (pinned) · steps 30 · timeout 120s · ctx 75% · fill 70%'

    Auto with resolved_from::

        'mode: auto→work (auto) · steps 40 · …'

    Auto with no resolved_from::

        'mode: auto (auto) · resolves per input'
    """
    if facts.resolved_from:
        behavior_label = f"{facts.behavior}→{facts.resolved_from}"
    else:
        behavior_label = facts.behavior

    prefix = f"mode: {behavior_label} ({facts.source})"

    if not facts.profile_rows:
        return f"{prefix} · resolves per input"

    # Build profile portion from rows
    row_parts: list[str] = []
    for label, value in facts.profile_rows:
        short = label
        if label == "steps":
            short = "steps"
        elif label == "timeout":
            short = "timeout"
        elif label == "context budget":
            short = "ctx"
        elif label == "fill-line":
            short = "fill"
        elif label == "synthesis reserve":
            short = "synthesis"
        row_parts.append(f"{short} {value}")

    return f"{prefix} · {' · '.join(row_parts)}"

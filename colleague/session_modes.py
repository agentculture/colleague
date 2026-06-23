"""Session modes for colleague — the single source of truth.

Pure module: stdlib only, zero new dependencies, no import-time I/O, no side
effects. Does not import anything from colleague.cli or colleague.loop (avoids
cycles).

Modes represent the active session context and control how free-text input is
routed to verbs. The ordered cycle is the canonical definition of mode order.
"""

from __future__ import annotations

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

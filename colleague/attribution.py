"""Attribution renderer: visually distinguish colleague's two lobes.

A pure helper the operator-facing surfaces use so senses' own lines and
cortex's repo work are unmistakable at a glance: senses output carries a
``"senses:"`` prefix, cortex operation shows as a ``"cortex ▸ working…"``
status line. Colour (a distinct ANSI SGR hue per lobe) is available on a
colour TTY but is never auto-detected here — the caller decides via the
explicit ``color`` parameter, and plain (no ANSI at all) is the default.

Stdlib only, zero deps, no I/O — every function here is pure and
deterministic: identical arguments always produce identical output.
"""

from __future__ import annotations

#: The label/status text and the ANSI SGR colour codes live in exactly one
#: place so the two lobes stay visually distinct without drifting apart.
SENSES_LABEL = "senses:"
CORTEX_STATUS_LABEL = "cortex ▸ working…"
WORKER_STATUS_LABEL = "worker ▸ working…"

#: Raw ANSI SGR escape codes — senses gets cyan, cortex gets magenta, distinct
#: hues so the two lobes are never confusable on a colour TTY.
_SENSES_SGR = "\x1b[36m"
_CORTEX_SGR = "\x1b[35m"
_SGR_RESET = "\x1b[0m"


def acting_seat_label(*, three_tier: bool = False) -> str:
    """Return the status label for the *acting* seat.

    Returns :data:`WORKER_STATUS_LABEL` when three-tier execution is armed
    (the worker is the bounded-tool-loop actor), :data:`CORTEX_STATUS_LABEL`
    otherwise (legacy two-tier mode).
    """
    return WORKER_STATUS_LABEL if three_tier else CORTEX_STATUS_LABEL


def senses_line(text: str, *, color: bool = False) -> str:
    """Render one senses output line: ``"senses: {text}"``.

    Plain (no ANSI at all) unless ``color=True``, in which case the whole
    line is wrapped in senses' colour code. The caller decides whether the
    target is a colour TTY — this function never inspects the environment.
    """
    line = f"{SENSES_LABEL} {text}" if text else SENSES_LABEL
    if not color:
        return line
    return f"{_SENSES_SGR}{line}{_SGR_RESET}"


def cortex_working_line(detail: str = "", *, color: bool = False, three_tier: bool = False) -> str:
    """Render one status line: ``"{seat} ▸ working… {detail}"``.

    ``detail`` is optional context (e.g. the current step) appended after the
    fixed status label; omitted when empty. Plain (no ANSI at all) unless
    ``color=True``, in which case the whole line is wrapped in the seat's
    colour code — a different hue from :func:`senses_line`.

    When ``three_tier=True`` the worker label is used (the worker is the
    bounded-tool-loop actor); otherwise the legacy cortex label is emitted.
    """
    label = acting_seat_label(three_tier=three_tier)
    line = f"{label} {detail}" if detail else label
    if not color:
        return line
    return f"{_CORTEX_SGR}{line}{_SGR_RESET}"

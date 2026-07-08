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

#: Raw ANSI SGR escape codes — senses gets cyan, cortex gets magenta, distinct
#: hues so the two lobes are never confusable on a colour TTY.
_SENSES_SGR = "\x1b[36m"
_CORTEX_SGR = "\x1b[35m"
_SGR_RESET = "\x1b[0m"


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


def cortex_working_line(detail: str = "", *, color: bool = False) -> str:
    """Render one cortex status line: ``"cortex ▸ working… {detail}"``.

    ``detail`` is optional context (e.g. the current step) appended after the
    fixed status label; omitted when empty. Plain (no ANSI at all) unless
    ``color=True``, in which case the whole line is wrapped in cortex's
    colour code — a different hue from :func:`senses_line`.
    """
    line = f"{CORTEX_STATUS_LABEL} {detail}" if detail else CORTEX_STATUS_LABEL
    if not color:
        return line
    return f"{_CORTEX_SGR}{line}{_SGR_RESET}"

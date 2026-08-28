"""colleague.resident.requestlines — the two mesh-request line conventions.

Split out of :mod:`colleague.resident.appserver` (which owns the dispatch, not
the grammar) — pure text parsing over ``str``: no asyncio, no
``agent_lifecycle``, no trust decision. The appserver re-exports both names, so
the conventions themselves are unchanged:

* ``attach: <path>`` — the media-reference convention (t12). The trust
  boundary a parsed candidate must clear lives in
  :func:`colleague.resident.trust.check_attachment_path`; this module owns only
  the token grammar and the cap.
* ``relay <task-id>: <text>`` — the relay-addressing convention (t8). What a
  relay may DO is decided in ``AppserverHarness._handle_relay``; this module
  only finds the line.
"""

from __future__ import annotations

import re
from typing import Optional

# t12: the mesh media-reference convention -- a line-anchored `attach: <path>`
# token, one per line. Capped so a request can't smuggle an unbounded number
# of filesystem probes through one message; extras beyond the cap are counted
# and reported, never silently dropped.
_MAX_ATTACHMENTS = 4
_ATTACH_LINE_RE = re.compile(r"^attach:\s*(\S.*)$")


def _extract_attach_lines(text: str) -> tuple[str, list[str], int]:
    """Split *text* into ``(cleaned_text, candidate_paths, dropped_count)``.

    Recognises the ``attach: <path>`` convention (see the appserver module docstring).
    A matched line is REMOVED from the returned text entirely. At most
    :data:`_MAX_ATTACHMENTS` candidates are kept, in order; any further
    matches are counted in *dropped_count* (never silently truncated without
    a trace -- the caller turns that count into a recorded note).

    A *text* with no ``attach:`` lines is returned completely unchanged
    (same object, even) -- a request with no media reference behaves
    byte-identically to before this feature existed.
    """
    lines = text.splitlines()
    if not any(_ATTACH_LINE_RE.match(line) for line in lines):
        return text, [], 0

    kept_lines: list[str] = []
    candidates: list[str] = []
    dropped = 0
    for line in lines:
        match = _ATTACH_LINE_RE.match(line)
        if not match:
            kept_lines.append(line)
            continue
        path = match.group(1).rstrip()
        if len(candidates) < _MAX_ATTACHMENTS:
            candidates.append(path)
        else:
            dropped += 1
    return "\n".join(kept_lines), candidates, dropped


# t8: the mesh relay-addressing convention -- a line-anchored `relay <task-id>:
# <text>` token (case-insensitive keyword; the task id is a single non-whitespace,
# non-colon token). See the appserver module docstring's "Trust-gated relay" section.
_RELAY_LINE_RE = re.compile(r"^relay\s+([^\s:]+):\s*(\S.*)$", re.IGNORECASE)


def _extract_relay_line(text: str) -> Optional[tuple[str, str]]:
    """Return ``(task_id, relay_text)`` for the FIRST ``relay <task-id>: <text>``
    line found in *text*, or ``None`` when no line matches the convention.

    Unlike :func:`_extract_attach_lines` (which strips matched lines and lets
    the REST of the message proceed as a normal work request), a matched relay
    line takes the message down an entirely different path (see
    :meth:`AppserverHarness._handle_relay`) — no work item is ever dispatched
    for it, so there is nothing to "clean" and return alongside it.
    """
    for line in text.splitlines():
        match = _RELAY_LINE_RE.match(line.strip())
        if match:
            return match.group(1), match.group(2).rstrip()
    return None


__all__ = [
    "_ATTACH_LINE_RE",
    "_MAX_ATTACHMENTS",
    "_RELAY_LINE_RE",
    "_extract_attach_lines",
    "_extract_relay_line",
]

"""Detection-only scan for markup-shaped tool calls in assistant prose (#360, t6).

A served model sometimes emits a tool call as literal *text* in the message
content instead of on the wire's tool-call channel::

    <tool_call>
    <function=web_survey>
    <parameter=query>...</parameter>
    </function>
    </tool_call>

The harness silently drops that text — which, from the outside, is
indistinguishable from "the model ignored the tools" (#360). This module makes
the failure countable: :func:`count` returns how many function-naming markup
blocks a turn's content carries, and the loop folds that onto
``WorkStats.counts['markup_tool_calls']`` (:mod:`colleague.runcounts`).

**Detection ONLY — never execution.** Nothing here converts markup into a
:class:`colleague.loop.ToolCall`, and no caller may: executing recovered markup
would change what a run *does* and confound every measured arm of this arc. The
one pre-existing recovery path (#248 mode B, ``loop._parse_literal_finish``)
stays exactly as it is; this scan neither feeds it nor is fed by it.

Two shapes are recognised, both **line-anchored** (a marker mid-sentence is
prose *about* markup — this repo's own docs discuss these tokens — not markup),
scanned with linear :meth:`str.find` only (no regex, SonarCloud S8786):

* ``function=<name>`` / ``<function=<name>`` at the start of a line — the
  Hermes/Qwen text shape #248 already recovers for ``finish``, generalised here
  to ANY function name;
* a line-anchored ``<tool_call`` block carrying a JSON ``"name": "<name>"`` —
  the same failure in the JSON dialect. A block that already matched the
  ``function=`` shape is not counted twice.
"""

from __future__ import annotations

_TOOL_CALL_OPEN = "<tool_call"
_TOOL_CALL_CLOSE = "</tool_call>"
_FUNCTION_MARKER = "function="
_NAME_KEY = '"name"'

#: Characters a function name may be built from (the scan stops at the first
#: other character — ``>``, whitespace, a quote…).
_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")


def _line_anchored(text: str, idx: int) -> bool:
    """True when the token at *idx* opens a line (optionally behind one ``<``)."""
    if idx == 0:
        return True
    prev = text[idx - 1]
    if prev == "\n":
        return True
    if prev == "<":
        return idx == 1 or text[idx - 2] == "\n"
    return False


def _read_name(text: str, start: int) -> str | None:
    """The identifier beginning at *start*, or ``None`` when there is none."""
    end = start
    while end < len(text) and text[end] in _NAME_CHARS:
        end += 1
    return text[start:end] or None


def _function_shape_names(content: str) -> list[str]:
    """Names from line-anchored ``function=<name>`` markup."""
    names: list[str] = []
    idx = content.find(_FUNCTION_MARKER)
    while idx != -1:
        if _line_anchored(content, idx):
            name = _read_name(content, idx + len(_FUNCTION_MARKER))
            if name:
                names.append(name)
        idx = content.find(_FUNCTION_MARKER, idx + 1)
    return names


def _tool_call_segments(content: str) -> list[str]:
    """Each line-anchored ``<tool_call`` block's text (to its close, or the next)."""
    segments: list[str] = []
    idx = content.find(_TOOL_CALL_OPEN)
    while idx != -1:
        nxt = content.find(_TOOL_CALL_OPEN, idx + 1)
        if _line_anchored(content, idx):
            close = content.find(_TOOL_CALL_CLOSE, idx)
            end = len(content)
            for candidate in (close, nxt):
                if candidate != -1:
                    end = min(end, candidate)
            segments.append(content[idx:end])
        idx = nxt
    return segments


def _json_shape_name(segment: str) -> str | None:
    """The ``"name": "<name>"`` value inside a ``<tool_call>`` block, if any."""
    key = segment.find(_NAME_KEY)
    if key == -1:
        return None
    colon = segment.find(":", key + len(_NAME_KEY))
    if colon == -1:
        return None
    open_quote = segment.find('"', colon + 1)
    if open_quote == -1:
        return None
    close_quote = segment.find('"', open_quote + 1)
    if close_quote == -1:
        return None
    return segment[open_quote + 1 : close_quote].strip() or None


def names_in(content: str | None) -> list[str]:
    """Every function name the content's tool-call markup declares, in order.

    Detection only — the caller counts these, and must never execute them.
    """
    if not content:
        return []
    names = _function_shape_names(content)
    for segment in _tool_call_segments(content):
        if _FUNCTION_MARKER in segment:
            continue  # already counted by the ``function=`` shape
        name = _json_shape_name(segment)
        if name:
            names.append(name)
    return names


def count(content: str | None) -> int:
    """How many markup-shaped tool calls *content* carries (0 for ordinary prose)."""
    return len(names_in(content))

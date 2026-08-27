"""Rule-based blanking of old tool results — a pure, stdlib-only pass.

adapted-from: qwen-code packages/core/src/services/microcompaction/microcompact.ts:14,40-64,
services/chatCompressionService.ts:109-124

qwen-code's microcompaction pass clears the *content* of old tool results
(keeping the most recent N) once a proportional token threshold is crossed, so
a long-running session doesn't keep paying to re-send megabytes of stale
``read_file``/``run_command`` output on every turn. This module ports the same
two ideas — a recent-N keep window (``microcompact.ts`` lines 40-64's
``COMPACTABLE_TOOLS``/``FILE_PATH_TOOLS`` sets, generalized here to every tool
since colleague's tool surface is small and fixed, ``colleague/tools.py``) and
the ``MICROCOMPACT_CLEARED_MESSAGE`` placeholder (``microcompact.ts:14``) named
with the tool + path so a model that needs the content again knows to re-read
it — plus the ``DEFAULT_PCT = 0.85`` proportional trigger
(``chatCompressionService.ts:109-124``) — onto colleague's OpenAI chat-message
shape.

Two public functions:

- :func:`microcompact` — blank the ``content`` of tool-role messages older
  than the most recent ``keep_recent``, leaving every assistant message (and
  its ``tool_calls``) untouched, and every ``tool`` message's ``role``/
  ``tool_call_id`` untouched — so wire validity (each ``tool_call`` id still
  paired with exactly one ``tool`` reply) is preserved by construction: no
  message is ever added or removed, only a ``tool`` message's ``content`` is
  swapped for a one-line marker.
- :func:`should_microcompact` — the proportional trigger: ``True`` once
  ``prompt_tokens`` reaches ``MICROCOMPACT_THRESHOLD_PCT`` (0.85) of
  ``budget``.

Deliberately NOT ported (out of scope for this pure primitive, t15's job): the
loop-wiring/fill-line ordering, the time-based idle trigger, media-part
handling, and the qwen-code compactable-tools allow-list (colleague's whole
tool surface is small enough — and every tool's output is equally
re-fetchable via the tool loop — that this port blanks any tool-role message,
not just an allow-listed subset).

Pure, no I/O: no shell-out, no network, no engine import. Stdlib only.
"""

from __future__ import annotations

import json
from typing import Any

#: Default recent-tool-message keep window (mirrors qwen-code's ``keepRecent``
#: default of 5, widened here since colleague's history holds full tool
#: results rather than qwen-code's already-slimmed input — t4's brief pins it
#: at 10).
DEFAULT_KEEP_RECENT = 10

#: Proportional auto-microcompaction threshold — mirrors qwen-code's
#: ``DEFAULT_PCT`` (chatCompressionService.ts:109).
MICROCOMPACT_THRESHOLD_PCT = 0.85

#: One-line marker template. Always names the tool; a path is appended only
#: when the triggering ``tool_calls`` entry's arguments carried one (mirrors
#: qwen-code's ``FILE_PATH_TOOLS`` path-naming, generalized to any tool whose
#: JSON arguments carry a ``path``/``file_path`` key) — naming the path is the
#: hard question colleague answered on c11: a model re-reading after
#: microcompaction needs to know WHERE, not just THAT something was cleared.
_MARKER_WITH_PATH = "[old {tool} result for {path} cleared — re-read if needed]"
_MARKER_NO_PATH = "[old {tool} result cleared — re-read if needed]"

#: Argument keys checked (in order) for a path to name in the marker.
#: ``path`` is colleague's own tool-schema key (``colleague/tools.py``);
#: ``file_path`` is kept for compatibility with the qwen-code naming this
#: module is adapted from.
_PATH_ARG_KEYS = ("path", "file_path")


def _parse_arguments(raw: Any) -> dict | None:
    """Best-effort parse of a ``function.arguments`` value into a dict.

    ``arguments`` is normally a JSON-encoded string (the OpenAI wire shape)
    but callers occasionally pass an already-decoded dict (e.g. in tests or a
    mock engine) — both are accepted. Anything else, or malformed JSON,
    yields ``None`` (the marker then falls back to naming just the tool).
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _extract_path(arguments: dict | None) -> str | None:
    if not arguments:
        return None
    for key in _PATH_ARG_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _build_tool_call_index(messages: list[dict]) -> dict[str, tuple[str, str | None]]:
    """Map every ``tool_calls[].id`` -> ``(tool_name, path_or_None)``.

    Scans ONLY ``assistant`` messages' ``tool_calls`` (the request side, where
    the arguments live — mirrors ``buildCallIdToFilePath`` in
    ``microcompact.ts``, which reads ``functionCall.args``, not the response).
    A malformed entry (missing id/name) is skipped rather than raising —
    microcompaction degrades to naming just "tool" for that id.
    """
    index: dict[str, tuple[str, str | None]] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            call_id = tool_call.get("id")
            if not call_id:
                continue
            function = tool_call.get("function") or {}
            name = function.get("name") or "tool"
            path = _extract_path(_parse_arguments(function.get("arguments")))
            index[call_id] = (name, path)
    return index


def _marker_for(
    tool_call_index: dict[str, tuple[str, str | None]], tool_call_id: str | None
) -> str:
    if tool_call_id and tool_call_id in tool_call_index:
        tool, path = tool_call_index[tool_call_id]
    else:
        tool, path = "tool", None
    if path:
        return _MARKER_WITH_PATH.format(tool=tool, path=path)
    return _MARKER_NO_PATH.format(tool=tool)


def microcompact(
    messages: list[dict], keep_recent: int = DEFAULT_KEEP_RECENT
) -> tuple[list[dict], int]:
    """Blank the content of tool-role messages older than the most recent N.

    ``messages`` is the OpenAI chat-format history (system/user/assistant/tool
    dicts); ``keep_recent`` (default :data:`DEFAULT_KEEP_RECENT`) is how many
    of the MOST RECENT ``tool``-role messages keep their real content — every
    earlier ``tool`` message has its ``content`` replaced with a one-line
    marker naming the tool (and its path, when the pairing ``tool_calls``
    entry's arguments carried one).

    Returns a NEW list (the input is never mutated) plus ``blanked_count``,
    the number of ``tool`` messages actually blanked. Every non-``tool``
    message (system/user/assistant, INCLUDING every ``tool_calls`` entry) is
    carried through unchanged — same object, not a copy — so
    ``assistant is result[i]`` holds and no tool_call is ever added, removed,
    or re-keyed. A ``tool`` message's ``role``/``tool_call_id`` are likewise
    preserved verbatim; only ``content`` changes. Because message COUNT and
    every id are invariant, wire validity (each ``tool_calls[].id`` paired
    with exactly one ``tool`` reply carrying that ``tool_call_id``) holds
    automatically before and after — this function cannot break it.

    ``keep_recent <= 0`` blanks every tool message; ``keep_recent`` at or
    above the total tool-message count is a no-op (nothing old enough to
    blank) and returns ``blanked_count == 0``.
    """
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if keep_recent > 0:
        protected = (
            set(tool_indices[-keep_recent:])
            if keep_recent < len(tool_indices)
            else set(tool_indices)
        )
    else:
        protected = set()

    tool_call_index = _build_tool_call_index(messages)

    result: list[dict] = []
    blanked_count = 0
    for i, message in enumerate(messages):
        if message.get("role") == "tool" and i not in protected:
            new_message = dict(message)
            new_message["content"] = _marker_for(tool_call_index, message.get("tool_call_id"))
            result.append(new_message)
            blanked_count += 1
        else:
            result.append(message)

    return result, blanked_count


def should_microcompact(prompt_tokens: int, budget: int) -> bool:
    """``True`` once *prompt_tokens* reaches :data:`MICROCOMPACT_THRESHOLD_PCT`
    (0.85) of *budget* — mirrors qwen-code's ``DEFAULT_PCT`` proportional
    auto-compaction trigger (``chatCompressionService.ts:109-124``), narrowed
    to the single proportional check (colleague has no absolute-ceiling term
    to combine it with here; that composition is the loop's job, t15).

    A non-positive ``budget`` can never be reached (division is avoided
    entirely) and returns ``False``.
    """
    if budget <= 0:
        return False
    return prompt_tokens / budget >= MICROCOMPACT_THRESHOLD_PCT

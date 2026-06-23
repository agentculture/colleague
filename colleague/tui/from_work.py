"""Bridge a work item's per-step output into TAUI :class:`WorkStep` events.

A work item reports progress two ways that must agree:

* **live** — the loop's progress callback ``(step_index, tool, target, ok)``,
  where ``target`` is the short hint computed by :func:`progress_target`; and
* **post-hoc** — the per-step trace ``<id>.trace.jsonl`` whose lines carry the
  full ``arguments`` dict.

Both are folded into the same cockpit by mapping each step to a
:class:`~colleague.tui.events.WorkStep`.  This module is the single source of
that mapping, so a step's ``summary`` is identical whether it was produced live
or reconstructed from a trace — which is what lets ``tui replay`` and
``tui replay --trace`` reproduce the live cockpit exactly.

Stdlib only (the zero-deps tui-core guard imports this module).
"""

from __future__ import annotations

from typing import Any

from colleague.tui.events import WorkStep

#: Argument keys, in priority order, that name a tool call's subject.
_TARGET_KEYS = ("path", "command", "name", "summary", "subcommand")
#: Maximum length of a step hint; longer values are truncated with an ellipsis.
_MAX_TARGET = 120


def progress_target(arguments: Any) -> str:
    """A short (``<= 120`` char) human hint for a tool call's subject.

    Looks for the first of ``path`` / ``command`` / ``name`` / ``summary`` /
    ``subcommand`` in *arguments*, takes its first line, and truncates to 120
    characters.  Falls back to ``cli`` (culture tool) or ``move`` (devague tool)
    when none of those keys are present.  Returns ``""`` when *arguments* is not
    a dict or carries none of those keys.

    This is the value the loop passes as the ``target`` of its progress callback;
    :func:`trace_to_work_steps` reuses it so a replayed step reads identically.
    """
    if not isinstance(arguments, dict):
        return ""
    for key in _TARGET_KEYS:
        value = arguments.get(key)
        if value:
            return _clip(str(value).splitlines()[0].strip())
    # Fallback for culture / devague loop tools.
    if "cli" in arguments and isinstance(arguments["cli"], str) and arguments["cli"]:
        parts: list[str] = [arguments["cli"]]
        args = arguments.get("args")
        if isinstance(args, list) and args:
            parts.extend(str(a) for a in args)
        return _clip(" ".join(parts))
    if "move" in arguments and isinstance(arguments["move"], str) and arguments["move"]:
        parts = [arguments["move"]]
        args = arguments.get("args")
        if isinstance(args, list) and args:
            parts.extend(str(a) for a in args)
        return _clip(" ".join(parts))
    return ""


def work_step(tool: str, summary: str, ok: bool = True) -> WorkStep:
    """Construct a :class:`WorkStep` from a live progress tuple's fields."""
    return WorkStep(tool=str(tool), summary=str(summary), ok=bool(ok))


def trace_to_work_steps(trace_lines: list[dict[str, Any]]) -> list[WorkStep]:
    """Map loop-trace lines (``<id>.trace.jsonl``) to :class:`WorkStep` events.

    Each line is ``{index, tool, arguments, result, ok}``.  The ``summary`` is the
    same hint the live callback would show (:func:`progress_target` of the
    ``arguments``), falling back to the first line of ``result`` when the
    arguments carry no recognised subject key — so a replayed step matches the
    live cockpit.  Lines that are not dicts, or lack a ``tool``, are skipped.
    """
    steps: list[WorkStep] = []
    for line in trace_lines:
        if not isinstance(line, dict):
            continue
        tool = line.get("tool")
        if not tool:
            continue
        summary = progress_target(line.get("arguments"))
        if not summary and line.get("result"):
            summary = _clip(str(line["result"]).splitlines()[0].strip())
        steps.append(work_step(str(tool), summary, bool(line.get("ok", True))))
    return steps


def _clip(text: str) -> str:
    """Return *text* unchanged if short, else truncated to 120 chars with ``...``."""
    return text if len(text) <= _MAX_TARGET else text[: _MAX_TARGET - 3] + "..."

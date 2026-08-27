"""Paged, grounded ``read_file`` rendering + the shared tool-output bound (plan t9).

adapted-from: qwen-code packages/core/src/tools/read-file.ts:102-158,
utils/fileUtils.ts:1440-1560 (offset/limit paging, the 1000-line / 25,000-char
caps and the ``Read lines X-Y of N`` trailer that tells the model to page on).
Copyright 2025 Google LLC, Copyright 2026 Qwen Team, Apache-2.0 — re-implemented
in stdlib Python (cite-don't-import).

Two entry points, both called from :mod:`colleague.tools`:

* :func:`render_read` — number the requested window of a file with its ORIGINAL
  1-based line numbers (the #240 grounding rule: split on bare ``"\\n"`` only),
  bounded by ``limit`` (default 1000 lines) and a char budget (default 25,000,
  ``COLLEAGUE_MAX_OUTPUT_CHARS`` / the executor's ``max_output_chars`` only ever
  a CEILING — decision c50), cutting on whole lines so a surviving prefix is
  always true to the file. A file that fits is returned byte-identical to the
  unpaged rendering; a cut or paged result ends with exactly
  ``Read lines X-Y of N`` and nothing else.
* :func:`bound_output` — every other tool result goes through
  :func:`colleague.truncation.truncate_output` (head+tail, spill to
  ``<root>/.colleague/tool-output/``) at its per-tool budget.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague import truncation

_LINE_NUMBER_WIDTH = 6
OFFSET_DESC = "Optional 1-based line to start from (page a long file)."
LIMIT_DESC = "Optional max number of lines to return (default 1000)."


def number_lines(text: str, start: int = 1) -> str:
    """``cat -n`` grounding (#240): bare-``\\n`` split, numbering from *start*."""
    if text == "":
        return ""
    body = text[:-1] if text.endswith("\n") else text
    return "\n".join(
        f"{i:{_LINE_NUMBER_WIDTH}d}\t{line}" for i, line in enumerate(body.split("\n"), start=start)
    )


def _int_arg(value: Any, name: str, minimum: int) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum - 1
    if parsed < minimum:
        from colleague.tools import ToolError  # local: tools imports this module

        raise ToolError(f"read_file: {name} must be an integer >= {minimum}, got {value!r}")
    return parsed


def _char_cap(ceiling: int | None) -> int:
    cap = truncation.resolve_max_chars("read_file")
    return cap if ceiling is None else min(cap, int(ceiling))


def render_read(
    text: str,
    offset: Any = None,
    limit: Any = None,
    *,
    ceiling: int | None = None,
) -> str:
    """Render the ``[offset, offset+limit)`` window of *text*, grounded and bounded."""
    start = _int_arg(offset, "offset", 1) or 1
    want = _int_arg(limit, "limit", 1) or truncation.resolve_max_lines()
    body = text[:-1] if text.endswith("\n") else text
    lines = body.split("\n") if text else []
    total = len(lines)
    if total == 0:
        return ""
    if start > total:
        return f"Read lines {start}-{total} of {total}"
    end = min(total, start - 1 + want)
    numbered = [f"{i:{_LINE_NUMBER_WIDTH}d}\t{lines[i - 1]}" for i in range(start, end + 1)]
    cap = _char_cap(ceiling)
    kept: list[str] = []
    size = -1
    for entry in numbered:
        if size + 1 + len(entry) > cap and kept:
            break
        kept.append(entry)
        size += 1 + len(entry)
    char_truncated = False
    if size > cap:  # a single line wider than the whole budget: keep its head
        kept[0] = kept[0][:cap]
        char_truncated = True
    shown_end = start + len(kept) - 1
    rendered = "\n".join(kept)
    # finding #441-9(readpage)/D: a char-truncated last line is still a
    # PARTIAL read even when its line number happens to equal the file's
    # final line and the window started at line 1 — omitting the trailer in
    # that case made editgate.record_read() treat unseen trailing text on
    # that line as fully shown, letting an edit touch text the model never
    # actually saw.
    if start == 1 and shown_end == total and not char_truncated:
        return rendered
    return f"{rendered}\nRead lines {start}-{shown_end} of {total}"


def bound_output(text: str, tool: str, ceiling: int, root: str | Path, executor=None) -> str:
    """Bound a non-read tool result at its per-tool budget, spilling the rest to disk.

    *executor* (t20): when given, a spill bumps its ``outputs_spilled`` tally —
    the exact counter :mod:`colleague.runcounts` folds onto the artifact.
    """
    max_chars = min(truncation.resolve_max_chars(tool or "read_file"), int(ceiling))
    spill_dir = Path(root) / ".colleague" / "tool-output"
    before = truncation.session_bytes_spilled()
    out = truncation.truncate_output(text, max_chars, truncation.resolve_max_lines(), spill_dir)
    if executor is not None and truncation.session_bytes_spilled() > before:
        executor.outputs_spilled = int(getattr(executor, "outputs_spilled", 0)) + 1
    return out

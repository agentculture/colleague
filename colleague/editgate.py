"""Edit gate (t13, plan adopt-from-qwen-code — c9/h7): the glue between
``ToolExecutor``'s ``read_file``/``edit_file``/``write_file`` and
:mod:`colleague.editmatch`.

Three pure-ish helpers, kept OUT of ``colleague/tools.py`` (the file-length
ratchet pins that module at its baseline):

* :func:`record_read` — after ``read_file`` renders, record exactly which
  lines were SHOWN on the executor's :class:`~colleague.editmatch.ReadSet`
  (a paged or truncated read only covers its ``Read lines X-Y of N`` span;
  a whole-file render is a full read).
* :func:`resolve_old_string` — the exact match first, then the deterministic
  tolerant tier (:func:`~colleague.editmatch.normalize_edit_strings`: smart
  quotes, per-line whitespace, CRLF). No LLM repair, ever. Returns the
  canonical on-disk slice so the replacement operates on exact bytes.
* :func:`require_prior_read` — the prior-read rule: an existing file may
  only be EDITED where it has been shown in THIS work item (every
  occurrence's span, for ``replace_all``). A file this executor wrote whole
  (``write_file``) counts as fully shown (:func:`record_written`).
  ``write_file`` itself stays ungated — overwriting is a whole-file act the
  model authors, and gating it broke the mock engine's rerun determinism.
  The refusal names the rule and says how to recover ("read the file (or
  that span) first") so a cheap model lands the retry in one step.
  ``COLLEAGUE_PRIOR_READ=0`` disables the rule (the escape knob for
  operators driving colleague as a plain editor).

adapted-from: qwen-code packages/core/src/tools/priorReadEnforcement.ts
(the rule) and utils/editHelper.ts:313-380 (the tolerant tier lives in
:mod:`colleague.editmatch`).
"""

from __future__ import annotations

import os
import re

from colleague import editmatch

#: ``read_file``'s paging trailer (``colleague/readpage.py``): present only when
#: the render did NOT show the whole file.
_TRAILER = re.compile(r"(?:^|\n)Read lines (\d+)-(\d+) of (\d+)$")

#: The one env knob; ``"0"`` disables the prior-read rule.
PRIOR_READ_ENV = "COLLEAGUE_PRIOR_READ"

RULE = "the prior-read rule"


def _enabled() -> bool:
    return os.environ.get(PRIOR_READ_ENV, "1").strip() != "0"


def new_read_set() -> editmatch.ReadSet:
    """The per-executor (= per work item) read set."""
    return editmatch.ReadSet()


def _total_lines(text: str) -> int:
    if not text:
        return 0
    body = text[:-1] if text.endswith("\n") else text
    return body.count("\n") + 1


def record_read(read_set: editmatch.ReadSet, key: str, text: str, rendered: str) -> None:
    """Record what ``read_file`` just SHOWED for ``key`` (the resolved path)."""
    total = _total_lines(text)
    match = _TRAILER.search(rendered)
    if match is None:
        read_set.record_full(key, total)
        return
    start, end = int(match.group(1)), int(match.group(2))
    if end >= start:
        read_set.record(key, start, end, total)


def record_written(read_set: editmatch.ReadSet, key: str, content: str) -> None:
    """A ``write_file`` by this executor authored the whole file — it counts as read."""
    read_set.record_full(key, _total_lines(content))


def occurrence_spans(text: str, needle: str) -> list[tuple[int, int]]:
    """1-indexed inclusive line spans of every non-overlapping ``needle`` in ``text``."""
    spans: list[tuple[int, int]] = []
    pos = 0
    height = needle.count("\n")
    while True:
        idx = text.find(needle, pos)
        if idx < 0:
            return spans
        start = text.count("\n", 0, idx) + 1
        spans.append((start, start + height))
        pos = idx + len(needle)


def resolve_old_string(text: str, old: str, rel: str) -> tuple[str, int]:
    """Exact match first, then the tolerant tier; ``(canonical_old, count)``.

    Raises ``ToolError`` (imported lazily — ``tools`` imports this module) when
    nothing matches, or when the RELAXED pass is ambiguous (the exact-path
    ambiguity is still the caller's — it knows about ``replace_all``).
    """
    from colleague.tools import ToolError  # circular at import time only

    count = text.count(old)
    if count:
        return old, count
    try:
        relaxed = editmatch.normalize_edit_strings(text, old, old)
    except editmatch.AmbiguousEditMatch as exc:
        raise ToolError(f"{exc} (in {rel})") from exc
    if relaxed is None:
        raise ToolError(
            f"old_string not found in {rel} — neither exactly nor after normalizing smart "
            "quotes, per-line whitespace and CRLF; re-read the file and copy the text verbatim"
        )
    canonical = relaxed[0]
    return canonical, text.count(canonical)


def _refuse(tool: str, rel: str, detail: str):
    from colleague.tools import ToolError

    return ToolError(
        f"{tool} refused for {rel}: read the file (or that span) first — {RULE}: an existing "
        f"file may only be changed where read_file showed it in this work item ({detail}); "
        f"{PRIOR_READ_ENV}=0 disables the rule"
    )


def require_prior_read(
    read_set: editmatch.ReadSet, key: str, rel: str, text: str, old: str
) -> None:
    """Every occurrence of ``old`` in ``text`` must lie within a shown span of ``key``."""
    if not _enabled():
        return
    for start, end in occurrence_spans(text, old):
        if not read_set.is_read_for_edit(key, start, end):
            raise _refuse("edit_file", rel, f"lines {start}-{end} were not shown")

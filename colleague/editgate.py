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
  that span) first") so a cheap model lands the retry in one step; on a
  continued run it also names which prior work item it resumed
  (``context_note``, t21 — the read set itself is NEVER persisted across a
  continuation, see :func:`continuation_id`).
  ``COLLEAGUE_PRIOR_READ=0`` disables the rule (the escape knob for
  operators driving colleague as a plain editor).

adapted-from: qwen-code packages/core/src/tools/priorReadEnforcement.ts
(the rule) and utils/editHelper.ts:313-380 (the tolerant tier lives in
:mod:`colleague.editmatch`).
"""

from __future__ import annotations

import os
import re
from typing import Optional

from colleague import editmatch

#: ``read_file``'s paging trailer (``colleague/readpage.py``): present only when
#: the render did NOT show the whole file.
_TRAILER = re.compile(r"(?:^|\n)Read lines (\d+)-(\d+) of (\d+)$")

#: The one env knob; ``"0"`` disables the prior-read rule.
PRIOR_READ_ENV = "COLLEAGUE_PRIOR_READ"

RULE = "the prior-read rule"

#: The continuation seed preamble's marker (:func:`continuation_preamble`) —
#: also what :func:`continuation_id` matches to read the id back out of a
#: continued run's ``task.instruction``, with no wiring between
#: ``continuation.py`` and the executor (t21).
_CONTINUATION_RE = re.compile(r"^You are CONTINUING work item (\S+) that stopped early\.")


def continuation_preamble(task_id: str) -> str:
    """The one-sentence continuation seed preamble (t21, plan t21): states the
    prior-read rule up front — files this executor edited in an EARLIER
    episode are NOT in this run's read set, so an edit still needs its own
    ``read_file`` first. :func:`colleague.continuation.resolve_continuation`
    prepends this to every seed body (prose or ledger)."""
    return (
        f"You are CONTINUING work item {task_id} that stopped early. This is a "
        f"continuation of {task_id}: files edited earlier are NOT considered read — "
        "read_file a file (or the span) before edit_file. Prior state:\n\n"
    )


def continuation_id(instruction: str) -> Optional[str]:
    """The continuation id embedded in *instruction*'s seed preamble (rendered
    by :func:`continuation_preamble`), or ``None`` for an ordinary work item.
    Lets the loop recognize a continuation from the task alone (set onto
    ``ToolExecutor.context_note``) with no wiring between ``continuation.py``
    and the executor."""
    match = _CONTINUATION_RE.match(instruction)
    return match.group(1) if match else None


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


def _refuse(tool: str, rel: str, detail: str, context_note: Optional[str] = None):
    from colleague.tools import ToolError

    # t21: an optional continuation id (ToolExecutor.context_note) names which
    # prior work item this refusal's run resumed — the read set itself is
    # never carried across the continuation, so the rule applies fresh.
    continuing = f" (continuing work item {context_note})" if context_note else ""
    return ToolError(
        f"{tool} refused for {rel}: read the file (or that span) first — {RULE}{continuing}: an "
        f"existing file may only be changed where read_file showed it in this work item "
        f"({detail}); {PRIOR_READ_ENV}=0 disables the rule"
    )


def require_prior_read(
    read_set: editmatch.ReadSet,
    key: str,
    rel: str,
    text: str,
    old: str,
    *,
    context_note: Optional[str] = None,
) -> None:
    """Every occurrence of ``old`` in ``text`` must lie within a shown span of
    ``key``. ``context_note`` (t21) is the executor's continuation id, when
    set — folded into the refusal so a continued run's message names which
    prior work item it resumed."""
    if not _enabled():
        return
    for start, end in occurrence_spans(text, old):
        if not read_set.is_read_for_edit(key, start, end):
            raise _refuse("edit_file", rel, f"lines {start}-{end} were not shown", context_note)

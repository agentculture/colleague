"""Tolerant edit-string matching + a prior-read set (t6, c9/h7).

adapted-from: qwen-code packages/core/src/utils/editHelper.ts:313-380,
tools/priorReadEnforcement.ts

Two independent, stdlib-only, pure-Python pieces ported from qwen-code's
edit-reconciliation helpers:

* ``normalize_edit_strings`` — qwen-code's ``normalizeEditStrings`` /
  ``findMatchedSlice`` (editHelper.ts:313-380) reconcile an LLM-proposed
  ``old_string`` against on-disk text through progressively relaxed
  comparison passes (smart quotes/dashes -> ASCII, per-line whitespace
  trim, CRLF/LF drift) until either the exact on-disk slice is located or
  the edit is declared unmatchable. This module keeps the same intent but
  a narrower contract: it is called ONLY as a fallback after colleague's
  existing exact ``str.count``/``str.replace`` path
  (``colleague/tools.py`` lines ~992-1060) has already failed to find
  ``old_string`` verbatim, so ``None`` here always means "fall through to
  the caller's own exact-match error handling" and never masks a genuine
  not-found.

* ``ReadSet`` — the *idea* behind qwen-code's ``priorReadEnforcement.ts``
  (a session cache that gates edit/write tools on "has this path been
  read since it last changed"). colleague has no on-disk read cache, so
  ``ReadSet`` is a small in-memory, per-work-item bookkeeping class: it
  records which line ranges of which paths were actually SHOWN to the
  model by a ``read_file`` call, and answers whether a given edit span
  was covered. A paged/truncated read only covers the lines it actually
  displayed — it does not imply the rest of the file was seen.

No LLM calls, no engine imports, no I/O: both pieces operate purely on
strings/ints supplied by the caller. Wiring either piece into
``colleague/tools.py``'s ``edit_file``/``read_file`` is a later task (t12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "AmbiguousEditMatch",
    "normalize_edit_strings",
    "ReadSet",
]


# --------------------------------------------------------------------------
# Character-level normalization (smart quotes/dashes/unicode spaces -> ASCII)
# --------------------------------------------------------------------------

# Mirrors qwen-code's UNICODE_EQUIVALENT_MAP (editHelper.ts) — the set of
# "looks the same, isn't the same byte" characters an LLM is prone to emit
# in place of the ASCII original: curly quotes, unicode dashes, and the
# assorted unicode space variants.
_UNICODE_EQUIVALENTS: dict[str, str] = {
    # Hyphen/dash variants -> ASCII hyphen-minus.
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    # Curly single quotes -> straight apostrophe.
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    # Curly double quotes -> straight double quote.
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    # Unicode space variants -> plain ASCII space.
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "　": " ",
}


def _normalize_chars(text: str) -> str:
    """Map each unicode look-alike character in ``text`` to its ASCII form."""
    if not text:
        return text
    return "".join(_UNICODE_EQUIVALENTS.get(ch, ch) for ch in text)


def _normalize_line(line: str) -> str:
    """The per-line comparison key: unicode-normalized, then fully trimmed.

    Colleague's relaxed pass trims BOTH leading and trailing whitespace per
    line (unlike qwen-code's ``normalizeLineForComparison``, which trims only
    trailing whitespace to preserve indentation-scope significance) — the
    acceptance contract for this task explicitly calls for indent-drifted
    ``old_string``s to land, so leading whitespace is relaxed too.
    """
    return _normalize_chars(line).strip()


def _strip_line_terminator(raw_line: str) -> str:
    """Remove a trailing ``\\r\\n``/``\\n``/``\\r`` from one ``splitlines(keepends=True)`` line."""
    if raw_line.endswith("\r\n"):
        return raw_line[:-2]
    if raw_line.endswith("\n") or raw_line.endswith("\r"):
        return raw_line[:-1]
    return raw_line


# --------------------------------------------------------------------------
# Ambiguity error
# --------------------------------------------------------------------------


class AmbiguousEditMatch(ValueError):
    """The relaxed comparison pass found more than one candidate match.

    Mirrors the naming style of colleague's existing exact-match ambiguity
    error in ``colleague/tools.py`` (``"old_string is not unique in {rel}
    ({count} matches)"``) so a caller wiring this in can compose one
    consistent message.
    """

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            f"old_string matches {count} places once smart quotes/whitespace/CRLF "
            "are normalized; add surrounding context to disambiguate, or set "
            "replace_all=true"
        )


# --------------------------------------------------------------------------
# normalize_edit_strings
# --------------------------------------------------------------------------


def normalize_edit_strings(text: str, old: str, new: str) -> Optional[tuple[str, str]]:
    """Find a relaxed match for ``old`` inside ``text`` and return its canonical slice.

    Returns ``None`` in exactly two cases — both mean "let the caller's
    existing exact-match path run unchanged":

    * ``old`` already occurs verbatim in ``text`` (the exact path already
      succeeds; relaxing further would only risk masking the caller's own
      ambiguity accounting), or
    * no relaxed match is found either (the edit is genuinely not present).

    When exactly one relaxed match is found, returns
    ``(canonical_old_slice, new)`` — the literal on-disk text the caller
    should now treat as ``old_string`` (so replacement operates on exact
    bytes), and ``new`` returned completely untouched (never rewritten;
    trailing whitespace in ``new`` is intentionally preserved, matching
    qwen-code's documented stance in ``editHelper.ts``).

    Raises ``AmbiguousEditMatch`` when the relaxed pass finds more than one
    candidate — an ambiguous edit must never be silently resolved.
    """
    if old == "":
        return None
    if old in text:
        return None

    matches = _find_relaxed_matches(text, old)
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousEditMatch(len(matches))

    return matches[0], new


def _find_relaxed_matches(text: str, old: str) -> list[str]:
    """Every canonical on-disk slice whose lines match ``old``'s lines once
    both are run through the relaxed per-line comparison (smart quotes ->
    ASCII, per-line leading/trailing whitespace trim). Line splitting via
    ``str.splitlines`` is itself CRLF/LF/CR agnostic, so an ``old_string``
    written with different line endings than the file still lines up.
    """
    ends_with_newline = old.endswith("\n") or old.endswith("\r")
    old_lines = old.splitlines()
    if not old_lines:
        return []
    pattern = [_normalize_line(line) for line in old_lines]
    pattern_len = len(pattern)

    raw_lines = text.splitlines(keepends=True)
    haystack = [_normalize_line(_strip_line_terminator(line)) for line in raw_lines]

    if pattern_len > len(haystack):
        return []

    slices: list[str] = []
    for start in range(0, len(haystack) - pattern_len + 1):
        if haystack[start : start + pattern_len] == pattern:
            slices.append(_reconstruct_slice(raw_lines, start, pattern_len, ends_with_newline))
    return slices


def _reconstruct_slice(
    raw_lines: list[str],
    start: int,
    length: int,
    ends_with_newline: bool,
) -> str:
    """Rebuild the literal on-disk text spanning ``raw_lines[start:start+length]``.

    When the matched ``old_string`` did not itself end in a newline, the
    final matched line's terminator (if any) is dropped, so the returned
    slice's newline-endedness matches what the caller asked to match — it
    would otherwise silently grow ``old_string`` by a trailing newline the
    caller never asked to delete.
    """
    if ends_with_newline:
        return "".join(raw_lines[start : start + length])
    body = "".join(raw_lines[start : start + length - 1])
    last = _strip_line_terminator(raw_lines[start + length - 1])
    return body + last


# --------------------------------------------------------------------------
# ReadSet
# --------------------------------------------------------------------------


@dataclass
class ReadSet:
    """Tracks which (path, line-range) spans have actually been shown to the
    model in this work item, so a caller can require a prior read before an
    edit — the *idea* behind qwen-code's ``priorReadEnforcement.ts``, adapted
    to colleague's stateless-per-call tools (no on-disk read cache; this is
    purely an in-memory bookkeeping object the tool executor would own for
    the lifetime of one work item).

    A read that only showed a portion of a file (offset/limit paging, or the
    executor's own truncation) only covers the lines it actually displayed —
    it never implies the rest of the file was seen.
    """

    _ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    _full: set[str] = field(default_factory=set)

    def record(
        self,
        path: str,
        start_line: int,
        end_line: int,
        total_lines: int,
        *,
        promote_full: bool = True,
    ) -> None:
        """Record that ``path`` lines ``[start_line, end_line]`` (1-indexed,
        inclusive) were shown. A range spanning the whole file (``start_line
        <= 1`` and ``end_line >= total_lines``) is recorded as a full read —
        UNLESS ``promote_full=False``.

        ``promote_full`` exists for a caller that knows its ``end_line`` is a
        LINE-NUMBER count only and cannot vouch that the line's full
        CONTENT was shown (finding #441-9/D — a char-truncated final line
        can coincidentally span ``[1, total_lines]`` at line granularity
        while showing only a prefix of that line's characters). Passing
        ``promote_full=False`` still records the exact ``[start_line,
        end_line]`` range for line-granularity checks, it just refuses to
        let that numeric coincidence grant blanket future authorization
        for the whole path — including lines added to the file AFTER this
        read, which a promoted-to-full record would otherwise cover.
        """
        if promote_full and start_line <= 1 and end_line >= total_lines:
            self._full.add(path)
        self._ranges.setdefault(path, []).append((start_line, end_line))

    def record_full(self, path: str, total_lines: int) -> None:
        """Record that the ENTIRE file at ``path`` (``total_lines`` lines) was shown."""
        self._full.add(path)
        self._ranges.setdefault(path, []).append((1, total_lines))

    def is_read_for_edit(self, path: str, span_start: int, span_end: int) -> bool:
        """Was ``path`` lines ``[span_start, span_end]`` (1-indexed, inclusive)
        covered by some prior read recorded on this set?

        A full read always covers any span. Otherwise, the span must fall
        entirely within a SINGLE previously recorded range — two disjoint
        partial reads that happen to bracket the span do not combine, matching
        the conservative "only what was actually shown" contract a paged or
        truncated read leaves behind.
        """
        if path in self._full:
            return True
        for start, end in self._ranges.get(path, ()):
            if start <= span_start and span_end <= end:
                return True
        return False

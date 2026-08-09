"""Distillation lesson schema + strict validator (#396 step 3 — answer-shaped).

Pure stdlib, no I/O, no subprocess, no network.

A distillation lesson is a JSON object with exactly three required keys:
``pattern``, ``constant``, and ``reason`` — each a non-empty string within
a bounded length.  Missing keys, extra keys, empty strings, over-length
strings, or non-JSON input all refuse the **whole** lesson — never stripping
invalid fields and keeping the rest.  This mirrors the lattice's unknown-key
stance (see :mod:`colleague.lattice`).

This is a **replacement**, not an addition: the prior three-key schema
(``cause``/``lesson``/``next_delta``) is gone outright.  There is no
dual-schema validator — a payload shaped like the old schema is simply an
unrecognized set of keys and refuses whole like any other malformed input.
Already-stored lessons recorded under the old schema are unaffected: they
recall as legacy free text (the record's ``text`` field), never re-validated
against this module.

Why the replacement: dogfooding evidence (issue #387) found lesson
*specificity* is the variable that determines whether self-learning changes
behavior at all.  A hand-seeded answer-shaped lesson produced a 5x effect; a
concrete "g3 latch" code-lesson meant that whole defect class never recurred.
Process-shaped narrative lessons ("write more tests", "review carefully")
produced an *identical* execution trace on rerun — i.e. no learning.  The new
schema structurally forces the answer shape:

- ``pattern`` — the recurring shape the lesson generalizes (what class of
  situation this applies to).
- ``constant`` — the specific repo anchor the lesson pins: an identifier, a
  value, a path, or an invariant.  This is what makes a lesson actionable
  rather than narrative, so :func:`validate_lesson` structurally rejects a
  ``constant`` that reads as generic prose (see
  :func:`_check_generic_constant`).
- ``reason`` — why the pattern holds (the causal link between the pattern and
  the constant).

Component target, artifact ids, evidence source, and provenance are
deliberately **not** fields on this payload — bolting them on as ad hoc keys
would break the refuse-whole exact-key contract and blur "what was learned"
with "how we know it".  They belong in the **record metadata** the caller
attaches when remembering the lesson (see ``colleague.distill.upsert_lesson``
/ ``colleague.memory.build_lesson_record``), or in a deliberately versioned
schema envelope layered *around* this payload.  :data:`LESSON_SCHEMA_VERSION`
names the payload shape a caller/consumer is targeting so a later envelope
(e.g. component attribution, plan t17) can version against it without ever
smuggling extra keys into the validated payload — the validated payload keys
stay exactly ``{pattern, constant, reason}``, always.

When validation fails the caller records the honest
``no-lesson-extracted`` marker instead of a partial or repaired lesson.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

#: Maximum allowed length for each lesson field (characters).
MAX_FIELD_LENGTH = 1000

#: The three required keys in a distillation lesson (answer-shaped, #396).
_REQUIRED_KEYS = frozenset({"pattern", "constant", "reason"})

#: The payload schema's version name. This module validates exactly ONE
#: payload shape at a time (no dual-schema validator) — a caller layering a
#: versioned envelope or record metadata AROUND this payload (component
#: target, artifact ids, evidence source, provenance) names this constant to
#: record which payload shape it targets. It is never itself a payload key.
LESSON_SCHEMA_VERSION = "answer-v1"


# ---------------------------------------------------------------------------
# LessonVerdict — structured acceptance / refusal result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LessonVerdict:
    """The outcome of validating one distillation lesson.

    Attributes
    ----------
    allowed:
        ``True`` when the lesson passes all schema checks.
    reason:
        A human-readable explanation, populated **only** when ``allowed``
        is ``False`` (an allowed verdict carries an empty reason).
    """

    allowed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# LessonValidationError — for programmatic misuse (not validation refusals)
# ---------------------------------------------------------------------------


class LessonValidationError(Exception):
    """Raised for programmatic misuse of the lessons API.

    Validation refusals return a :class:`LessonVerdict` with ``allowed=False``.
    This exception is reserved for internal invariants (e.g. a caller
    passing a non-dict where a dict is required).
    """


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_non_empty_string(value: object) -> bool:
    """Return ``True`` if *value* is a non-empty, non-whitespace string."""
    return isinstance(value, str) and bool(value.strip())


def _check_required_keys(lesson: dict[str, object]) -> list[str]:
    """Return any required keys missing from *lesson*."""
    return [k for k in _REQUIRED_KEYS if k not in lesson]


def _check_extra_keys(lesson: dict[str, object]) -> list[str]:
    """Return any keys on *lesson* that are not in the required set."""
    return [k for k in lesson if k not in _REQUIRED_KEYS]


def _check_empty_strings(lesson: dict[str, object]) -> list[str]:
    """Return keys whose values are empty or whitespace-only strings."""
    return [k for k in _REQUIRED_KEYS if not _is_non_empty_string(lesson.get(k))]


def _check_over_length(lesson: dict[str, object]) -> list[str]:
    """Return keys whose string values exceed :data:`MAX_FIELD_LENGTH`."""
    return [
        k
        for k in _REQUIRED_KEYS
        if isinstance(lesson.get(k), str) and len(lesson[k]) > MAX_FIELD_LENGTH
    ]


def _check_non_string_values(lesson: dict[str, object]) -> list[str]:
    """Return keys whose values are not strings."""
    return [k for k in _REQUIRED_KEYS if not isinstance(lesson.get(k), str)]


# ---------------------------------------------------------------------------
# The 'constant' anchor check — structurally rejects generic prose
# ---------------------------------------------------------------------------
#
# A 'constant' is the specific repo anchor a lesson pins: an identifier, a
# value, a path, or an invariant. Each of those shapes leaves a syntactic
# fingerprint real prose almost never has: a path separator, a dotted or
# underscored identifier, SCREAMING_CASE, CamelCase, a backticked code span,
# an issue/line reference, or a version/number anchor. If NONE of those
# fingerprints are present, the field reads as narrative ("write more tests
# and review carefully") rather than an anchor — refused whole.

_ANCHOR_PATTERN = re.compile(
    r"""
    [/\\][\w.\-]                                   # path separator
    | \b[A-Za-z_][A-Za-z0-9_]{1,}\.[A-Za-z_][A-Za-z0-9_]{1,}\b  # dotted.identifier
    | \b[A-Za-z_][A-Za-z0-9]*_[A-Za-z0-9_]*\b       # snake_case / SCREAMING_SNAKE
    | \b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b           # CamelCase / PascalCase
    | `[^`]+`                                       # backticked code span
    | \#\d+                                         # issue reference, e.g. #387
    | \b[A-Za-z_][A-Za-z0-9_]*\(\)                  # function/method call ref
    | \bv?\d+\.\d+(?:\.\d+)?\b                      # version number, e.g. v1.56.2
    | \bline\s*\d+\b                                # line reference
    | :\d+\b                                        # path:line reference
    """,
    re.VERBOSE,
)


def _is_generic_prose(value: str) -> bool:
    """Return ``True`` when *value* carries no repo-anchor fingerprint.

    A repo anchor (identifier, value, path, or invariant) leaves a syntactic
    trace an anchor regex can find. Its absence means the field is narrative
    prose rather than a specific pin.
    """
    return _ANCHOR_PATTERN.search(value) is None


def _check_generic_constant(lesson: dict[str, object]) -> bool:
    """Return ``True`` when ``constant`` is present as a string but reads as
    generic prose (no repo-anchor fingerprint).

    Callers only reach this check once ``constant`` is already known to be a
    non-empty string within :data:`MAX_FIELD_LENGTH` — earlier pipeline steps
    guarantee that.
    """
    constant = lesson.get("constant")
    return isinstance(constant, str) and _is_generic_prose(constant)


# ---------------------------------------------------------------------------
# Public validation entry-point
# ---------------------------------------------------------------------------


def _refuse_missing_keys(lesson: dict[str, object]) -> LessonVerdict | None:
    missing = _check_required_keys(lesson)
    if not missing:
        return None
    return LessonVerdict(False, f"no lesson extracted: missing required key(s) {missing!r}")


def _refuse_extra_keys(lesson: dict[str, object]) -> LessonVerdict | None:
    extra = _check_extra_keys(lesson)
    if not extra:
        return None
    return LessonVerdict(
        False,
        f"no lesson extracted: extra key(s) {extra!r} not allowed "
        "(only pattern, constant, reason)",
    )


def _refuse_non_string_values(lesson: dict[str, object]) -> LessonVerdict | None:
    non_string = _check_non_string_values(lesson)
    if not non_string:
        return None
    return LessonVerdict(
        False,
        f"no lesson extracted: key(s) {non_string!r} must be strings, "
        f"not {type(lesson[non_string[0]]).__name__}",
    )


def _refuse_empty_strings(lesson: dict[str, object]) -> LessonVerdict | None:
    empty = _check_empty_strings(lesson)
    if not empty:
        return None
    return LessonVerdict(
        False,
        f"no lesson extracted: key(s) {empty!r} must be non-empty (non-whitespace) strings",
    )


def _refuse_over_length(lesson: dict[str, object]) -> LessonVerdict | None:
    over = _check_over_length(lesson)
    if not over:
        return None
    return LessonVerdict(
        False,
        f"no lesson extracted: key(s) {over!r} exceed the {MAX_FIELD_LENGTH}-char length cap",
    )


def _refuse_generic_constant(lesson: dict[str, object]) -> LessonVerdict | None:
    if not _check_generic_constant(lesson):
        return None
    constant = lesson["constant"]
    preview = constant if len(constant) <= 80 else constant[:77] + "..."
    return LessonVerdict(
        False,
        "no lesson extracted: 'constant' must pin a specific repo anchor "
        f"(an identifier, value, path, or invariant), not generic prose: {preview!r}",
    )


def validate_lesson(lesson: object) -> LessonVerdict:
    """Validate a distillation lesson against the fixed answer-shaped schema.

    A valid lesson is a dict with exactly three keys — ``pattern``,
    ``constant``, and ``reason`` — each a non-empty string within
    :data:`MAX_FIELD_LENGTH` characters, where ``constant`` additionally
    carries a repo-anchor fingerprint (not generic prose). Missing keys,
    extra keys, empty strings, over-length strings, non-string values, a
    generic-prose ``constant``, or non-dict input all refuse the **whole**
    lesson.

    Returns a :class:`LessonVerdict` with ``allowed=True`` when the lesson
    passes all checks, or ``allowed=False`` with a ``reason`` string explaining
    the refusal.  **Never raises** — all validation paths return a LessonVerdict.

    When validation fails the caller records the honest
    ``no-lesson-extracted`` marker instead of a partial or repaired lesson.
    """
    if not isinstance(lesson, dict):
        return LessonVerdict(
            False,
            f"no lesson extracted: input is not a JSON object (got {type(lesson).__name__})",
        )

    # The check pipeline: first refusal wins. Lazy on purpose — a later
    # checker's message may assume the earlier checks passed.
    for refuse in (
        _refuse_missing_keys,
        _refuse_extra_keys,
        _refuse_non_string_values,
        _refuse_empty_strings,
        _refuse_over_length,
        _refuse_generic_constant,
    ):
        verdict = refuse(lesson)
        if verdict is not None:
            return verdict
    return LessonVerdict(True)


# ---------------------------------------------------------------------------
# Raw-text extraction — the distillation seam's parse half (t9)
# ---------------------------------------------------------------------------


def parse_lesson_json(text: object) -> dict | None:
    """Tolerantly extract the first balanced JSON object from raw model text.

    A served model wraps JSON in prose or a ``` fence; this walks the text for
    the first balanced ``{...}`` that parses as a JSON object and returns it
    as a dict. Anything else — no JSON, truncated JSON, a non-object payload,
    non-string input — returns ``None`` (the caller's ``validate_lesson``
    then refuses it as a whole). Pure stdlib, never raises.
    """
    if not isinstance(text, str):
        return None
    start = text.find("{")
    while start != -1:
        end = _balanced_object_end(text, start)
        if end is not None:
            obj = _try_load_object(text[start : end + 1])
            if obj is not None:
                return obj
        start = text.find("{", start + 1)
    return None


def _balanced_object_end(text: str, start: int) -> int | None:
    """The index of the ``}`` closing the object opened at *start*, or None."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _try_load_object(candidate: str) -> dict | None:
    """Parse *candidate* as JSON; a non-dict or invalid payload is ``None``."""
    try:
        obj = json.loads(candidate)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None

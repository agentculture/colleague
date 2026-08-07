"""Distillation lesson schema + strict validator (t2).

Pure stdlib, no I/O, no subprocess, no network.

A distillation lesson is a JSON object with exactly three required keys:
``cause``, ``lesson``, and ``next_delta`` — each a non-empty string within
a bounded length.  Missing keys, extra keys, empty strings, over-length
strings, or non-JSON input all refuse the **whole** lesson — never stripping
invalid fields and keeping the rest.  This mirrors the lattice's unknown-key
stance (see :mod:`colleague.lattice`).

When validation fails the caller records the honest
``no-lesson-extracted`` marker instead of a partial or repaired lesson.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

#: Maximum allowed length for each lesson field (characters).
MAX_FIELD_LENGTH = 1000

#: The three required keys in a distillation lesson.
_REQUIRED_KEYS = frozenset({"cause", "lesson", "next_delta"})


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
        f"no lesson extracted: extra key(s) {extra!r} not allowed (only cause, lesson, next_delta)",
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


def validate_lesson(lesson: object) -> LessonVerdict:
    """Validate a distillation lesson against the fixed schema.

    A valid lesson is a dict with exactly three keys — ``cause``, ``lesson``,
    and ``next_delta`` — each a non-empty string within :data:`MAX_FIELD_LENGTH`
    characters.  Missing keys, extra keys, empty strings, over-length strings,
    non-string values, or non-dict input all refuse the **whole** lesson.

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
                    try:
                        obj = json.loads(text[start : i + 1])
                    except ValueError:
                        break
                    return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None

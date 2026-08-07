"""Tests for colleague.lessons — the distillation lesson schema + strict validator.

Covers the lesson-validation in :mod:`colleague.lessons`:

* Valid lessons with all three required fields are accepted.
* Missing keys refuse the WHOLE lesson.
* Extra keys refuse the WHOLE lesson.
* Empty strings refuse the WHOLE lesson.
* Over-length strings refuse the WHOLE lesson.
* Non-JSON input refuses the WHOLE lesson.
* An invalid distillation yields the honest no-lesson-extracted marker,
  never a partial or repaired lesson — pinned by a garbage-completion test.
"""

from __future__ import annotations

import dataclasses
import sys

import pytest

from colleague.lessons import (
    LessonValidationError,
    LessonVerdict,
    validate_lesson,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: A minimal valid lesson dict.
_VALID_LESSON = {
    "cause": "the build failed on CI",
    "lesson": "run tests before pushing",
    "next_delta": "add a pre-push test gate",
}


# ===========================================================================
# AC1 — Valid lesson accepted
# ===========================================================================


def test_valid_lesson_accepted() -> None:
    """A well-formed lesson with all three required fields is accepted."""
    result = validate_lesson(_VALID_LESSON)
    assert result.allowed is True
    assert result.reason == ""


def test_valid_lesson_with_short_strings() -> None:
    """Short but non-empty strings are accepted."""
    result = validate_lesson(
        {
            "cause": "x",
            "lesson": "y",
            "next_delta": "z",
        }
    )
    assert result.allowed is True


def test_valid_lesson_with_max_length_strings() -> None:
    """Strings at the exact max length are accepted."""
    max_len = 1000
    result = validate_lesson(
        {
            "cause": "a" * max_len,
            "lesson": "b" * max_len,
            "next_delta": "c" * max_len,
        }
    )
    assert result.allowed is True


# ===========================================================================
# AC2 — Missing key refuses whole
# ===========================================================================


def test_missing_cause_refuses_whole() -> None:
    """A lesson missing 'cause' refuses the WHOLE lesson."""
    lesson = {"lesson": "y", "next_delta": "z"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "cause" in result.reason.lower() or "missing" in result.reason.lower()


def test_missing_lesson_refuses_whole() -> None:
    """A lesson missing 'lesson' refuses the WHOLE lesson."""
    lesson = {"cause": "x", "next_delta": "z"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "lesson" in result.reason.lower() or "missing" in result.reason.lower()


def test_missing_next_delta_refuses_whole() -> None:
    """A lesson missing 'next_delta' refuses the WHOLE lesson."""
    lesson = {"cause": "x", "lesson": "y"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "next_delta" in result.reason.lower() or "missing" in result.reason.lower()


def test_all_three_missing_refuses_whole() -> None:
    """A lesson with no keys at all refuses the WHOLE lesson."""
    result = validate_lesson({})
    assert result.allowed is False


# ===========================================================================
# AC3 — Extra key refuses whole
# ===========================================================================


def test_extra_key_refuses_whole() -> None:
    """A lesson with an extra key refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "extra_field": "not_allowed"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "extra" in result.reason.lower() or "unknown" in result.reason.lower()


def test_multiple_extra_keys_refuse_whole() -> None:
    """Multiple extra keys refuse the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "extra1": "a", "extra2": "b"}
    result = validate_lesson(lesson)
    assert result.allowed is False


# ===========================================================================
# AC4 — Empty string refuses whole
# ===========================================================================


def test_empty_cause_refuses_whole() -> None:
    """An empty 'cause' string refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "cause": ""}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "empty" in result.reason.lower() or "cause" in result.reason.lower()


def test_empty_lesson_refuses_whole() -> None:
    """An empty 'lesson' string refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "lesson": ""}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_empty_next_delta_refuses_whole() -> None:
    """An empty 'next_delta' string refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "next_delta": ""}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_whitespace_only_cause_refuses_whole() -> None:
    """A cause that is only whitespace refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "cause": "   "}
    result = validate_lesson(lesson)
    assert result.allowed is False


# ===========================================================================
# AC5 — Over-length string refuses whole
# ===========================================================================


def test_over_length_cause_refuses_whole() -> None:
    """A 'cause' exceeding the max length refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "cause": "a" * 1001}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "length" in result.reason.lower() or "exceed" in result.reason.lower()


def test_over_length_lesson_refuses_whole() -> None:
    """A 'lesson' exceeding the max length refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "lesson": "b" * 1001}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_over_length_next_delta_refuses_whole() -> None:
    """A 'next_delta' exceeding the max length refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "next_delta": "c" * 1001}
    result = validate_lesson(lesson)
    assert result.allowed is False


# ===========================================================================
# AC6 — Non-JSON / non-dict input refuses whole
# ===========================================================================


def test_non_dict_input_refuses_whole() -> None:
    """A non-dict input (e.g. a string) refuses the WHOLE lesson."""
    result = validate_lesson("not a dict")
    assert result.allowed is False


def test_list_input_refuses_whole() -> None:
    """A list input refuses the WHOLE lesson."""
    result = validate_lesson([_VALID_LESSON])
    assert result.allowed is False


def test_none_input_refuses_whole() -> None:
    """A None input refuses the WHOLE lesson."""
    result = validate_lesson(None)  # type: ignore[arg-type]
    assert result.allowed is False


def test_int_input_refuses_whole() -> None:
    """An int input refuses the WHOLE lesson."""
    result = validate_lesson(42)  # type: ignore[arg-type]
    assert result.allowed is False


# ===========================================================================
# AC7 — Non-string values refuse whole
# ===========================================================================


def test_non_string_cause_refuses_whole() -> None:
    """A non-string 'cause' value refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "cause": 123}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_non_string_lesson_refuses_whole() -> None:
    """A non-string 'lesson' value refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "lesson": ["list"]}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_non_string_next_delta_refuses_whole() -> None:
    """A non-string 'next_delta' value refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "next_delta": None}  # type: ignore[dict-item]
    result = validate_lesson(lesson)
    assert result.allowed is False


# ===========================================================================
# AC8 — Garbage completion yields honest no-lesson-extracted marker
# ===========================================================================


def test_garbage_completion_yields_no_lesson_marker() -> None:
    """A garbage completion (non-JSON) yields the honest no-lesson-extracted
    marker, never a partial or repaired lesson."""
    garbage = "this is not json at all {{{{garbage"
    result = validate_lesson(garbage)  # type: ignore[arg-type]
    assert result.allowed is False
    assert "no lesson" in result.reason.lower() or "extracted" in result.reason.lower()


def test_truncated_json_yields_no_lesson_marker() -> None:
    """A truncated JSON object yields the honest no-lesson-extracted marker."""
    truncated = '{"cause": "incomplete'
    result = validate_lesson(truncated)  # type: ignore[arg-type]
    assert result.allowed is False
    assert "no lesson" in result.reason.lower() or "extracted" in result.reason.lower()


def test_json_with_wrong_keys_yields_no_lesson_marker() -> None:
    """JSON that parses but has wrong keys yields the honest no-lesson-extracted marker."""
    wrong_keys = '{"foo": "bar", "baz": "qux"}'
    result = validate_lesson(wrong_keys)  # type: ignore[arg-type]
    assert result.allowed is False
    assert "no lesson" in result.reason.lower() or "extracted" in result.reason.lower()


def test_valid_json_but_empty_values_yields_no_lesson_marker() -> None:
    """JSON with empty string values yields the honest no-lesson-extracted marker."""
    empty_vals = '{"cause": "", "lesson": "", "next_delta": ""}'
    result = validate_lesson(empty_vals)  # type: ignore[arg-type]
    assert result.allowed is False
    assert "no lesson" in result.reason.lower() or "extracted" in result.reason.lower()


# ===========================================================================
# AC9 — Verdict is a frozen dataclass with allowed + reason
# ===========================================================================


def test_verdict_is_frozen_dataclass() -> None:
    """LessonVerdict is a frozen dataclass with allowed and reason fields."""
    v = LessonVerdict(True)
    assert v.allowed is True
    assert v.reason == ""
    # Frozen: cannot mutate.
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.allowed = False  # type: ignore[misc]


def test_verdict_with_reason() -> None:
    """A refusal verdict carries a non-empty reason."""
    v = LessonVerdict(False, "some reason")
    assert v.allowed is False
    assert v.reason == "some reason"


# ===========================================================================
# AC10 — validate_lesson never raises
# ===========================================================================


def test_validate_lesson_never_raises() -> None:
    """validate_lesson never raises, even with completely malformed input."""
    edge_cases = [
        None,  # type: ignore[arg-type]
        42,  # type: ignore[arg-type]
        [],
        {},
        "not json",
        {"cause": ""},
        {"cause": "x", "lesson": "y"},
        {"cause": "x", "lesson": "y", "next_delta": "z", "extra": "e"},
        {"cause": 123, "lesson": "y", "next_delta": "z"},
    ]
    for case in edge_cases:
        result = validate_lesson(case)  # type: ignore[arg-type]
        assert isinstance(result, LessonVerdict)
        assert isinstance(result.allowed, bool)
        assert isinstance(result.reason, str)


# ===========================================================================
# AC11 — Zero-deps guard: the module imports stdlib only
# ===========================================================================


def test_lessons_module_imports_stdlib_only() -> None:
    """Importing + exercising colleague.lessons introduces no third-party module."""
    before = set(sys.modules.keys())

    import colleague.lessons as _lessons  # noqa: F401

    # Exercise the real validation path.
    _lessons.validate_lesson(_VALID_LESSON)

    new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}
    third_party = []
    for name in sorted(new_top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_colleague = name.startswith("colleague")
        is_builtin = name.startswith("_")
        if not (is_stdlib or is_colleague or is_builtin):
            third_party.append(name)
    assert not third_party, f"colleague.lessons leaked third-party imports: {third_party}"


# ===========================================================================
# AC12 — LessonValidationError is a distinct exception type
# ===========================================================================


def test_lesson_validation_error_is_distinct() -> None:
    """LessonValidationError is a distinct exception, not a generic Exception."""
    assert issubclass(LessonValidationError, Exception)
    # It should be distinct from ValueError, etc.
    try:
        raise LessonValidationError("test")
    except LessonValidationError as e:
        assert str(e) == "test"


# ===========================================================================
# AC13 — Bounded lengths are documented and enforced
# ===========================================================================


def test_max_length_constant_exists() -> None:
    """The module exposes a MAX_FIELD_LENGTH constant for the bounded length."""
    from colleague.lessons import MAX_FIELD_LENGTH

    assert isinstance(MAX_FIELD_LENGTH, int)
    assert MAX_FIELD_LENGTH > 0


def test_max_length_is_enforced() -> None:
    """Strings at exactly MAX_FIELD_LENGTH are accepted; one over is refused."""
    from colleague.lessons import MAX_FIELD_LENGTH

    # At max: accepted.
    result = validate_lesson(
        {
            "cause": "a" * MAX_FIELD_LENGTH,
            "lesson": "b" * MAX_FIELD_LENGTH,
            "next_delta": "c" * MAX_FIELD_LENGTH,
        }
    )
    assert result.allowed is True

    # One over: refused.
    result = validate_lesson(
        {
            "cause": "a" * (MAX_FIELD_LENGTH + 1),
            "lesson": "b" * MAX_FIELD_LENGTH,
            "next_delta": "c" * MAX_FIELD_LENGTH,
        }
    )
    assert result.allowed is False

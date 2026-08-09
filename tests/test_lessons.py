"""Tests for colleague.lessons — the answer-shaped lesson schema + strict
validator (#396 step 3).

Covers the lesson-validation in :mod:`colleague.lessons`:

* Valid lessons with all three required fields (``pattern``, ``constant``,
  ``reason``) are accepted.
* Missing keys refuse the WHOLE lesson.
* Extra keys refuse the WHOLE lesson (including ad hoc metadata-shaped keys
  like ``component_target``/``artifact_id``/``evidence_source``/``provenance``
  — those belong in record metadata or a versioned envelope, never the
  validated payload).
* Empty strings refuse the WHOLE lesson.
* Over-length strings refuse the WHOLE lesson.
* A ``constant`` that reads as generic prose (no repo-anchor fingerprint)
  refuses the WHOLE lesson — this is what makes the schema answer-shaped
  rather than narrative (issue #387's falsifying evidence: process-shaped
  lessons produced an identical execution trace; answer-shaped ones changed
  behavior).
* Non-JSON input refuses the WHOLE lesson.
* The OLD three-key schema (``cause``/``lesson``/``next_delta``) is simply
  an unrecognized key set now — no dual-schema validator exists.
* An invalid distillation yields the honest no-lesson-extracted marker,
  never a partial or repaired lesson — pinned by a garbage-completion test.
"""

from __future__ import annotations

import dataclasses
import sys

import pytest

from colleague.lessons import (
    LESSON_SCHEMA_VERSION,
    LessonValidationError,
    LessonVerdict,
    validate_lesson,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: A minimal valid lesson dict — answer-shaped: pattern + constant + reason.
_VALID_LESSON = {
    "pattern": "a diff parser splits on the wrong header and drops nested paths",
    "constant": "colleague/correction.py:_parse_diff_output",
    "reason": "the original --- / +++ split truncated nested paths to a basename",
}

#: A g3-latch-style lesson (issue #387's proven-effective shape): concrete
#: pattern + a specific repo anchor + the causal reason.
_G3_LATCH_LESSON = {
    "pattern": "input plumbing silently drops a field when key names diverge",
    "constant": "colleague/correction.py:_parse_diff_output (g3 latch)",
    "reason": (
        "the original --- / +++ split truncated nested paths to a basename and "
        "flushed twice per file, silently dropping every file under a directory"
    ),
}

#: A process-narrative lesson: prose advice with no specific repo anchor.
_PROCESS_NARRATIVE_LESSON = {
    "pattern": "tests failed intermittently on this task",
    "constant": "review the code more carefully and add more tests before submitting again",
    "reason": "carelessness let bugs slip through the review",
}

#: The retired three-key schema — no dual-schema validator exists for this.
_OLD_SCHEMA_LESSON = {
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
    """Short but non-empty, anchored strings are accepted."""
    result = validate_lesson(
        {
            "pattern": "x",
            "constant": "a/b.py",
            "reason": "z",
        }
    )
    assert result.allowed is True


def test_valid_lesson_with_max_length_strings() -> None:
    """Strings at the exact max length are accepted."""
    max_len = 1000
    # constant must stay anchored even at max length — underscore-joined so
    # every char is part of one long identifier-shaped token.
    anchored_constant = ("a_" * (max_len // 2))[:max_len]
    result = validate_lesson(
        {
            "pattern": "a" * max_len,
            "constant": anchored_constant,
            "reason": "c" * max_len,
        }
    )
    assert result.allowed is True


def test_g3_latch_style_lesson_validates() -> None:
    """A g3-latch-style lesson (concrete pattern + constant + reason) validates.

    This is issue #387's proven-effective shape: a hand-seeded answer-shaped
    lesson produced a 5x effect, and a concrete "g3 latch" code-lesson meant
    that whole defect class never recurred.
    """
    result = validate_lesson(_G3_LATCH_LESSON)
    assert result.allowed is True
    assert result.reason == ""


# ===========================================================================
# AC2 — Missing key refuses whole
# ===========================================================================


def test_missing_pattern_refuses_whole() -> None:
    """A lesson missing 'pattern' refuses the WHOLE lesson."""
    lesson = {"constant": "a/b.py", "reason": "z"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "pattern" in result.reason.lower() or "missing" in result.reason.lower()


def test_missing_constant_refuses_whole() -> None:
    """A lesson missing 'constant' refuses the WHOLE lesson."""
    lesson = {"pattern": "x", "reason": "z"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "constant" in result.reason.lower() or "missing" in result.reason.lower()


def test_missing_reason_refuses_whole() -> None:
    """A lesson missing 'reason' refuses the WHOLE lesson."""
    lesson = {"pattern": "x", "constant": "a/b.py"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "reason" in result.reason.lower() or "missing" in result.reason.lower()


def test_all_three_missing_refuses_whole() -> None:
    """A lesson with no keys at all refuses the WHOLE lesson."""
    result = validate_lesson({})
    assert result.allowed is False


# ===========================================================================
# AC3 — Extra key refuses whole (including ad hoc metadata-shaped keys)
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


@pytest.mark.parametrize(
    "ad_hoc_key",
    ["component_target", "artifact_id", "evidence_source", "provenance"],
)
def test_ad_hoc_provenance_keys_refuse_whole(ad_hoc_key: str) -> None:
    """Component target, artifact ids, evidence source, and provenance are
    NOT payload keys — bolting them onto the validated payload refuses the
    WHOLE lesson. They belong in record metadata or a versioned schema
    envelope built around this payload, never ad hoc keys inside it."""
    lesson = {**_VALID_LESSON, ad_hoc_key: "some-value"}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "extra" in result.reason.lower()


# ===========================================================================
# AC4 — Empty string refuses whole
# ===========================================================================


def test_empty_pattern_refuses_whole() -> None:
    """An empty 'pattern' string refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "pattern": ""}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "empty" in result.reason.lower() or "pattern" in result.reason.lower()


def test_empty_constant_refuses_whole() -> None:
    """An empty 'constant' string refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "constant": ""}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_empty_reason_refuses_whole() -> None:
    """An empty 'reason' string refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "reason": ""}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_whitespace_only_pattern_refuses_whole() -> None:
    """A pattern that is only whitespace refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "pattern": "   "}
    result = validate_lesson(lesson)
    assert result.allowed is False


# ===========================================================================
# AC5 — Over-length string refuses whole
# ===========================================================================


def test_over_length_pattern_refuses_whole() -> None:
    """A 'pattern' exceeding the max length refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "pattern": "a" * 1001}
    result = validate_lesson(lesson)
    assert result.allowed is False
    assert "length" in result.reason.lower() or "exceed" in result.reason.lower()


def test_over_length_constant_refuses_whole() -> None:
    """A 'constant' exceeding the max length refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "constant": ("a_" * 501)[:1001]}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_over_length_reason_refuses_whole() -> None:
    """A 'reason' exceeding the max length refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "reason": "c" * 1001}
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


def test_non_string_pattern_refuses_whole() -> None:
    """A non-string 'pattern' value refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "pattern": 123}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_non_string_constant_refuses_whole() -> None:
    """A non-string 'constant' value refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "constant": ["list"]}
    result = validate_lesson(lesson)
    assert result.allowed is False


def test_non_string_reason_refuses_whole() -> None:
    """A non-string 'reason' value refuses the WHOLE lesson."""
    lesson = {**_VALID_LESSON, "reason": None}  # type: ignore[dict-item]
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
    truncated = '{"pattern": "incomplete'
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
    empty_vals = '{"pattern": "", "constant": "", "reason": ""}'
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
        {"pattern": ""},
        {"pattern": "x", "constant": "a/b.py"},
        {"pattern": "x", "constant": "a/b.py", "reason": "z", "extra": "e"},
        {"pattern": 123, "constant": "a/b.py", "reason": "z"},
        _OLD_SCHEMA_LESSON,
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

    anchored_constant = ("a_" * (MAX_FIELD_LENGTH // 2))[:MAX_FIELD_LENGTH]

    # At max: accepted.
    result = validate_lesson(
        {
            "pattern": "a" * MAX_FIELD_LENGTH,
            "constant": anchored_constant,
            "reason": "c" * MAX_FIELD_LENGTH,
        }
    )
    assert result.allowed is True

    # One over: refused.
    result = validate_lesson(
        {
            "pattern": "a" * (MAX_FIELD_LENGTH + 1),
            "constant": anchored_constant,
            "reason": "c" * MAX_FIELD_LENGTH,
        }
    )
    assert result.allowed is False


# ===========================================================================
# AC14 (#396) — 'constant' structurally rejects generic prose
# ===========================================================================


def test_process_narrative_lesson_without_constant_refused_whole() -> None:
    """A process-narrative lesson whose 'constant' is generic prose (no
    repo-anchor fingerprint) is refused whole with the honest
    no-lesson-extracted marker — this is the #387-falsifying-evidence case:
    process-shaped lessons produced no learning at all."""
    result = validate_lesson(_PROCESS_NARRATIVE_LESSON)
    assert result.allowed is False
    assert "no lesson" in result.reason.lower() or "extracted" in result.reason.lower()
    assert "prose" in result.reason.lower() or "constant" in result.reason.lower()


@pytest.mark.parametrize(
    "constant",
    [
        "colleague/lessons.py",
        "MAX_FIELD_LENGTH",
        "LessonVerdict",
        "`validate_lesson()`",
        "#387",
        "v1.56.2",
        "lessons.py:136",
        "chain.CONTINUABLE_REASONS",
    ],
)
def test_anchored_constant_shapes_all_validate(constant: str) -> None:
    """A representative set of repo-anchor shapes (path, SCREAMING_CASE,
    CamelCase, backticked code, issue ref, version, line ref, dotted
    identifier) all validate as a proper 'constant'."""
    lesson = {**_VALID_LESSON, "constant": constant}
    result = validate_lesson(lesson)
    assert result.allowed is True, result.reason


@pytest.mark.parametrize(
    "constant",
    [
        "always write more tests before submitting",
        "be more careful next time and double check the work",
        "make sure to review the change thoroughly",
    ],
)
def test_generic_prose_constant_shapes_all_refused(constant: str) -> None:
    """A representative set of narrative-prose 'constant' values (no anchor
    fingerprint) are all refused whole."""
    lesson = {**_VALID_LESSON, "constant": constant}
    result = validate_lesson(lesson)
    assert result.allowed is False


# ===========================================================================
# AC15 (#396) — no dual-schema validator; old 3-key schema is unrecognized
# ===========================================================================


def test_old_three_key_schema_refused_no_dual_schema() -> None:
    """The retired {cause, lesson, next_delta} schema is not a second
    recognized shape — it refuses whole as missing the new required keys
    (pattern/constant/reason) with extra unrecognized keys. There is no
    dual-schema validator: exactly one payload shape is ever accepted."""
    result = validate_lesson(_OLD_SCHEMA_LESSON)
    assert result.allowed is False


def test_lesson_schema_version_constant_exists() -> None:
    """The module names its payload shape via a version constant, so a
    caller building a versioned envelope or record metadata around this
    payload (component target, artifact ids, evidence source, provenance)
    can record which schema shape it targets without smuggling those keys
    into the validated payload itself."""
    assert isinstance(LESSON_SCHEMA_VERSION, str)
    assert LESSON_SCHEMA_VERSION

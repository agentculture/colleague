"""Tests for colleague/memory.py code-lesson record type + builders (plan t8).

Code-lesson records are a distinct record type from work-lesson records:
- type=code-lesson (vs type=work-lesson)
- id namespace that can never collide with work-lesson-<task_id> upserts
- fields: {area, convention, evidence, confidence}

Confidence is a bounded enum/float with an honest default of low.
Evidence is verbatim substance (a lint-fix line, a failing-test name, a diff hunk).

A store-less repo remains a zero-subprocess no-op (the triple gate is untouched —
the builder is a pure function, no subprocess).

Covers: c4, h4
"""

from __future__ import annotations

import enum

from colleague.memory import Confidence, build_code_lesson_record

# ---------------------------------------------------------------------------
# AC1 — build_code_lesson_record produces type=code-lesson records
# ---------------------------------------------------------------------------


class TestCodeLessonType:
    """build_code_lesson_record produces records with type=code-lesson."""

    def test_record_has_type_code_lesson(self) -> None:
        """The record's type field is 'code-lesson', not 'work-lesson'."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="memory wiring lives in the loop, not in a backend",
            evidence="colleague/loop.py:2246 _maybe_remember_lesson(ctx)",
        )
        assert record["type"] == "code-lesson"

    def test_record_type_is_not_work_lesson(self) -> None:
        """The record's type is distinct from work-lesson."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert record["type"] != "work-lesson"


# ---------------------------------------------------------------------------
# AC2 — ID namespace never collides with work-lesson-<task_id>
# ---------------------------------------------------------------------------


class TestCodeLessonIdNamespace:
    """code-lesson ids use a namespace that can never collide with
    work-lesson-<task_id> upserts."""

    def test_id_starts_with_code_lesson_prefix(self) -> None:
        """The id uses a 'code-lesson-' prefix, distinct from 'work-lesson-'."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert record["id"].startswith("code-lesson-")

    def test_id_never_collides_with_work_lesson_prefix(self) -> None:
        """A code-lesson id can never equal a work-lesson id."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        # work-lesson ids start with "work-lesson-"
        assert not record["id"].startswith("work-lesson-")

    def test_id_is_deterministic_for_same_inputs(self) -> None:
        """Two code-lesson records with the same inputs get the same id
        (idempotent upsert — same as work-lesson idempotency)."""
        record_a = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        record_b = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert record_a["id"] == record_b["id"]

    # ---------------------------------------------------------------------------


# AC3 — Fields: area, convention, evidence, confidence
# ---------------------------------------------------------------------------


class TestCodeLessonFields:
    """The record carries the required fields: area, convention, evidence,
    confidence."""

    def test_record_has_area_field(self) -> None:
        """The record carries an 'area' field with the provided value."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert "area" in record
        assert record["area"] == "colleague/loop.py"

    def test_record_has_convention_field(self) -> None:
        """The record carries a 'convention' field with the provided value."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert "convention" in record
        assert record["convention"] == "all-engines rule"

    def test_record_has_evidence_field(self) -> None:
        """The record carries an 'evidence' field with the provided value."""
        evidence = "colleague/loop.py:2246 _maybe_remember_lesson(ctx)"
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence=evidence,
        )
        assert "evidence" in record
        assert record["evidence"] == evidence

    def test_record_has_confidence_field(self) -> None:
        """The record carries a 'confidence' field."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert "confidence" in record

    def test_evidence_carries_verbatim_substance(self) -> None:
        """Evidence is stored verbatim — a lint-fix line, a failing-test name,
        or a diff hunk — not a summary."""
        evidence = "tests/test_loop.py::test_memory_disabled_is_strict_noop FAILED"
        record = build_code_lesson_record(
            area="tests/test_loop.py",
            convention="memory disabled is strict noop",
            evidence=evidence,
        )
        assert record["evidence"] == evidence

    def test_evidence_carries_diff_hunk(self) -> None:
        """Evidence can be a diff hunk — stored verbatim."""
        evidence = "@@ -10 +10 @@\n- old line\n+ new line"
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="indentation fix",
            evidence=evidence,
        )
        assert record["evidence"] == evidence


# ---------------------------------------------------------------------------
# AC4 — Confidence is a bounded enum/float, honest default low
# ---------------------------------------------------------------------------


class TestConfidence:
    """Confidence is a bounded enum/float with an honest default of low."""

    def test_confidence_is_enum(self) -> None:
        """Confidence is an enum type."""
        assert issubclass(Confidence, enum.Enum)

    def test_confidence_has_low_member(self) -> None:
        """Confidence has a 'low' member."""
        assert hasattr(Confidence, "low")

    def test_confidence_has_medium_member(self) -> None:
        """Confidence has a 'medium' member."""
        assert hasattr(Confidence, "medium")

    def test_confidence_has_high_member(self) -> None:
        """Confidence has a 'high' member."""
        assert hasattr(Confidence, "high")

    def test_confidence_values_are_bounded_floats(self) -> None:
        """Each Confidence member has a float value between 0.0 and 1.0."""
        for member in Confidence:
            assert isinstance(member.value, float)
            assert 0.0 <= member.value <= 1.0

    def test_confidence_low_is_less_than_medium(self) -> None:
        """Confidence.low < Confidence.medium."""
        assert Confidence.low.value < Confidence.medium.value

    def test_confidence_medium_is_less_than_high(self) -> None:
        """Confidence.medium < Confidence.high."""
        assert Confidence.medium.value < Confidence.high.value

    def test_default_confidence_is_low(self) -> None:
        """When no confidence is specified, the record defaults to low."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert record["confidence"] == Confidence.low.value

    def test_explicit_confidence_is_respected(self) -> None:
        """When confidence is explicitly set, it is used."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
            confidence=Confidence.high,
        )
        assert record["confidence"] == Confidence.high.value

    def test_confidence_low_value_is_honest(self) -> None:
        """The default low confidence value is small (honest default)."""
        assert Confidence.low.value <= 0.3


# ---------------------------------------------------------------------------
# AC5 — Record shape is a plain dict (serializable)
# ---------------------------------------------------------------------------


class TestCodeLessonRecordShape:
    """The record is a plain dict, serializable as JSON."""

    def test_record_is_dict(self) -> None:
        """The record is a plain dict."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert isinstance(record, dict)

    def test_record_has_required_keys(self) -> None:
        """The record has exactly the required keys: id, type, area,
        convention, evidence, confidence."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert "id" in record
        assert "type" in record
        assert "area" in record
        assert "convention" in record
        assert "evidence" in record
        assert "confidence" in record

    def test_record_is_json_serializable(self) -> None:
        """The record can be serialized as JSON."""
        import json

        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        # Should not raise
        json.dumps(record)

    def test_record_values_are_strings_or_floats(self) -> None:
        """All record values are JSON-safe types (str or float)."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        for key, value in record.items():
            assert isinstance(value, (str, float, int)), (
                f"Record key '{key}' has type {type(value).__name__}, " f"expected str or float"
            )


# ---------------------------------------------------------------------------
# AC6 — Builder is a pure function (no subprocess, no side effects)
# ---------------------------------------------------------------------------


class TestBuilderIsPure:
    """build_code_lesson_record is a pure function — no subprocess, no
    side effects. A store-less repo remains a zero-subprocess no-op."""

    def test_builder_needs_no_repo_path(self) -> None:
        """The builder takes no repo_path argument — it is a pure function."""
        import inspect

        sig = inspect.signature(build_code_lesson_record)
        params = list(sig.parameters.keys())
        assert "repo_path" not in params

    def test_builder_needs_no_eidetic_cli(self) -> None:
        """The builder does not call shutil.which or subprocess — it is
        a pure function that returns a dict."""
        from unittest.mock import patch

        with patch("colleague.memory.subprocess") as mock_subprocess:
            build_code_lesson_record(
                area="colleague/loop.py",
                convention="all-engines rule",
                evidence="colleague/loop.py:123",
            )
            # subprocess.run should never be called
            mock_subprocess.run.assert_not_called()

    def test_builder_is_deterministic(self) -> None:
        """The builder produces the same output for the same inputs."""
        record_a = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        record_b = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert record_a == record_b


# ---------------------------------------------------------------------------
# AC7 — Different areas/conventions produce different ids
# ---------------------------------------------------------------------------


class TestCodeLessonIdUniqueness:
    """Different code-lesson content produces different ids."""

    def test_different_area_produces_different_id(self) -> None:
        """Two records with different areas get different ids."""
        record_a = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        record_b = build_code_lesson_record(
            area="colleague/memory.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        assert record_a["id"] != record_b["id"]

    def test_different_convention_produces_different_id(self) -> None:
        """Two records with different conventions get different ids."""
        record_a = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        record_b = build_code_lesson_record(
            area="colleague/loop.py",
            convention="memory wiring in loop",
            evidence="colleague/loop.py:123",
        )
        assert record_a["id"] != record_b["id"]

    def test_different_evidence_produces_different_id(self) -> None:
        """Two records with different evidence get different ids."""
        record_a = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
        )
        record_b = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:456",
        )
        assert record_a["id"] != record_b["id"]


# ---------------------------------------------------------------------------
# AC8 — Confidence can be passed as enum or float
# ---------------------------------------------------------------------------


class TestConfidenceInput:
    """Confidence can be passed as a Confidence enum or a raw float."""

    def test_confidence_as_enum(self) -> None:
        """Confidence can be passed as a Confidence enum member."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
            confidence=Confidence.medium,
        )
        assert record["confidence"] == Confidence.medium.value

    def test_confidence_as_float(self) -> None:
        """Confidence can be passed as a raw float value."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
            confidence=0.75,
        )
        assert record["confidence"] == 0.75

    def test_confidence_as_int(self) -> None:
        """Confidence can be passed as an int (coerced to float)."""
        record = build_code_lesson_record(
            area="colleague/loop.py",
            convention="all-engines rule",
            evidence="colleague/loop.py:123",
            confidence=1,
        )
        assert record["confidence"] == 1.0


# ---------------------------------------------------------------------------
# AC9 — Module-level exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    """The module exports Confidence and build_code_lesson_record."""

    def test_confidence_is_exported(self) -> None:
        """Confidence is importable from colleague.memory."""
        from colleague.memory import Confidence as C

        assert C is Confidence

    def test_build_code_lesson_record_is_exported(self) -> None:
        """build_code_lesson_record is importable from colleague.memory."""
        from colleague.memory import build_code_lesson_record as bclr

        assert callable(bclr)

    def test_build_code_lesson_record_is_callable(self) -> None:
        """build_code_lesson_record is a callable function."""
        assert callable(build_code_lesson_record)

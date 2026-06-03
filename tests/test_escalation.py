"""Unit tests for colleague.escalation.build_continuation (t1, #106).

Written test-first: these tests define the contract BEFORE the implementation.
"""

from __future__ import annotations

from colleague.contract import DriveStats, TaskResult
from colleague.escalation import build_continuation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stats(**kwargs) -> DriveStats:
    defaults = dict(
        request="refactor the auth module",
        started_at="2026-06-03T10:00:00Z",
        duration_seconds=42.5,
        model_turns=8,
        step_count=15,
        tool_counts={"read_file": 5, "write_file": 4, "run_command": 6},
        files_changed=3,
        bytes_written=12800,
        reasoning_chars=9000,
        reasoning_bytes=9000,
        answer_chars=2500,
        answer_bytes=2500,
    )
    defaults.update(kwargs)
    return DriveStats(**defaults)


def _make_result(
    *, task_id: str = "abc123def456", stats: DriveStats | None = None, **kwargs
) -> TaskResult:
    if stats is None:
        stats = _make_stats()
    defaults = dict(
        task_id=task_id,
        status="error",
        summary="Refactored login and session modules; did not reach the token-refresh path.",
        changed_files=["auth/login.py", "auth/session.py", "tests/test_auth.py"],
        error="step budget exhausted",
    )
    defaults.update(kwargs)
    return TaskResult(stats=stats, **defaults)


# ---------------------------------------------------------------------------
# Section presence tests
# ---------------------------------------------------------------------------


class TestSectionPresence:
    """Every call must produce all five labelled sections."""

    def test_has_state_section(self) -> None:
        body = build_continuation(_make_result(), _make_stats())
        assert (
            "## Continuation State" in body
            or "## continuation/state" in body.lower()
            or "state" in body.lower()
        )

    def test_has_remaining_section(self) -> None:
        body = build_continuation(_make_result(), _make_stats())
        lower = body.lower()
        assert "remaining" in lower

    def test_has_whats_needed_section(self) -> None:
        body = build_continuation(_make_result(), _make_stats())
        lower = body.lower()
        assert "needed" in lower or "what's needed" in lower or "whats needed" in lower

    def test_has_suggested_split_section(self) -> None:
        body = build_continuation(_make_result(), _make_stats())
        lower = body.lower()
        assert "split" in lower

    def test_has_why_section(self) -> None:
        body = build_continuation(_make_result(), _make_stats())
        lower = body.lower()
        assert "why" in lower

    def test_all_five_sections_present_via_headings(self) -> None:
        """Verify all 5 sections appear as markdown headings."""
        body = build_continuation(_make_result(), _make_stats())
        # Count level-2 headings (##)
        headings = [line for line in body.splitlines() if line.startswith("##")]
        assert len(headings) >= 5, f"Expected >= 5 ## headings, got {len(headings)}: {headings}"


# ---------------------------------------------------------------------------
# Real drive-state embedding tests
# ---------------------------------------------------------------------------


class TestRealDriveState:
    """The body must embed concrete values from the inputs, not boilerplate."""

    def test_embeds_task_id(self) -> None:
        result = _make_result(task_id="deadbeef9999")
        body = build_continuation(result, result.stats)
        assert "deadbeef9999" in body

    def test_embeds_step_count(self) -> None:
        stats = _make_stats(step_count=27)
        body = build_continuation(_make_result(stats=stats), stats)
        assert "27" in body

    def test_embeds_model_turns(self) -> None:
        stats = _make_stats(model_turns=13)
        body = build_continuation(_make_result(stats=stats), stats)
        assert "13" in body

    def test_embeds_duration_seconds(self) -> None:
        stats = _make_stats(duration_seconds=99.75)
        body = build_continuation(_make_result(stats=stats), stats)
        # At minimum the integer part should appear
        assert "99" in body

    def test_embeds_summary_partial_work(self) -> None:
        result = _make_result(summary="Added index, updated schema, stopped at migration.")
        body = build_continuation(result, result.stats)
        assert "Added index" in body or "updated schema" in body or "migration" in body

    def test_embeds_changed_files(self) -> None:
        result = _make_result(changed_files=["src/foo.py", "src/bar.py"])
        body = build_continuation(result, result.stats)
        # At least one of the changed files should appear
        assert "src/foo.py" in body or "src/bar.py" in body

    def test_embeds_error_reason(self) -> None:
        result = _make_result(error="context window exhausted")
        body = build_continuation(result, result.stats)
        assert "context window exhausted" in body or "context" in body.lower()

    def test_embeds_files_changed_count(self) -> None:
        stats = _make_stats(files_changed=7)
        body = build_continuation(_make_result(stats=stats), stats)
        assert "7" in body

    def test_embeds_bytes_written(self) -> None:
        stats = _make_stats(bytes_written=65536)
        body = build_continuation(_make_result(stats=stats), stats)
        assert "65536" in body or "65,536" in body or "64" in body  # may format as KB

    def test_embeds_started_at(self) -> None:
        stats = _make_stats(started_at="2026-06-03T10:00:00Z")
        body = build_continuation(_make_result(stats=stats), stats)
        assert "2026-06-03" in body


# ---------------------------------------------------------------------------
# Purity / no side-effects tests
# ---------------------------------------------------------------------------


class TestPurity:
    """build_continuation must be a pure function — no I/O, no mutations."""

    def test_returns_string(self) -> None:
        body = build_continuation(_make_result(), _make_stats())
        assert isinstance(body, str)

    def test_non_empty_string(self) -> None:
        body = build_continuation(_make_result(), _make_stats())
        assert len(body) > 50

    def test_does_not_mutate_result(self) -> None:
        result = _make_result(task_id="stable123")
        original_id = result.task_id
        original_summary = result.summary
        build_continuation(result, result.stats)
        assert result.task_id == original_id
        assert result.summary == original_summary

    def test_does_not_mutate_stats(self) -> None:
        stats = _make_stats(step_count=10, model_turns=5)
        build_continuation(_make_result(stats=stats), stats)
        assert stats.step_count == 10
        assert stats.model_turns == 5

    def test_idempotent(self) -> None:
        result = _make_result()
        stats = _make_stats()
        body1 = build_continuation(result, stats)
        body2 = build_continuation(result, stats)
        assert body1 == body2

    def test_different_inputs_different_output(self) -> None:
        stats_a = _make_stats(step_count=5, model_turns=2, duration_seconds=10.0)
        stats_b = _make_stats(step_count=35, model_turns=20, duration_seconds=300.0)
        result_a = _make_result(task_id="aaa111", stats=stats_a)
        result_b = _make_result(task_id="bbb222", stats=stats_b)
        body_a = build_continuation(result_a, stats_a)
        body_b = build_continuation(result_b, stats_b)
        assert body_a != body_b


# ---------------------------------------------------------------------------
# Budget-hint tests
# ---------------------------------------------------------------------------


class TestBudgetHints:
    """The what's-needed section should reflect the actual failure mode."""

    def test_step_budget_exhaustion_hints_more_steps(self) -> None:
        stats = _make_stats(step_count=40)
        result = _make_result(error="step budget exhausted", stats=stats)
        body = build_continuation(result, stats)
        lower = body.lower()
        assert "step" in lower or "budget" in lower

    def test_context_exhaustion_hints_context(self) -> None:
        stats = _make_stats(step_count=5)
        result = _make_result(error="context window exhausted", stats=stats)
        body = build_continuation(result, stats)
        lower = body.lower()
        assert "context" in lower

    def test_timeout_hints_timeout(self) -> None:
        stats = _make_stats(duration_seconds=3600.0)
        result = _make_result(error="timeout", stats=stats)
        body = build_continuation(result, stats)
        lower = body.lower()
        assert "timeout" in lower or "time" in lower or "duration" in lower

    def test_none_error_still_produces_body(self) -> None:
        result = _make_result(error=None)
        body = build_continuation(result, result.stats)
        assert isinstance(body, str)
        assert len(body) > 50

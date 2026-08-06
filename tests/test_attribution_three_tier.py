"""Tests for seat-aware attribution in :mod:`colleague.attribution`.

Task t9: three-tier execution must not label the worker's work as 'cortex'.
Pinned literal strings — legacy renders are byte-identical to today's exact
output; three-tier renders produce the worker label with ZERO 'cortex' lines.
"""

from __future__ import annotations

from colleague.attribution import (
    CORTEX_STATUS_LABEL,
    WORKER_STATUS_LABEL,
    acting_seat_label,
    cortex_working_line,
    senses_line,
)

# ── pinned legacy constants ────────────────────────────────────────────────


def test_cortex_status_label_is_pinned() -> None:
    """CORTEX_STATUS_LABEL must not change — legacy callers depend on it."""
    assert CORTEX_STATUS_LABEL == "cortex ▸ working…"


def test_worker_status_label_is_pinned() -> None:
    """WORKER_STATUS_LABEL is the new three-tier worker label."""
    assert WORKER_STATUS_LABEL == "worker ▸ working…"


# ── acting_seat_label helper ───────────────────────────────────────────────


def test_acting_seat_label_legacy_returns_cortex() -> None:
    """Legacy (three_tier=False) returns the cortex label."""
    assert acting_seat_label(three_tier=False) == CORTEX_STATUS_LABEL


def test_acting_seat_label_three_tier_returns_worker() -> None:
    """Three-tier armed returns the worker label."""
    assert acting_seat_label(three_tier=True) == WORKER_STATUS_LABEL


# ── cortex_working_line — legacy byte-identical ────────────────────────────


def test_cortex_working_line_legacy_plain_is_byte_identical() -> None:
    """Legacy plain render is byte-identical to today's exact string."""
    out = cortex_working_line(three_tier=False)
    assert out == "cortex ▸ working…"
    assert "worker" not in out


def test_cortex_working_line_legacy_plain_with_detail_is_byte_identical() -> None:
    """Legacy plain render with detail is byte-identical."""
    out = cortex_working_line("editing colleague/loop.py", three_tier=False)
    assert out == "cortex ▸ working… editing colleague/loop.py"
    assert "worker" not in out


def test_cortex_working_line_legacy_color_is_byte_identical() -> None:
    """Legacy colour render carries the cortex label and magenta SGR."""
    out = cortex_working_line(three_tier=False, color=True)
    assert "cortex ▸ working…" in out
    assert "\x1b[35m" in out  # magenta
    assert "worker" not in out


def test_cortex_working_line_default_is_legacy() -> None:
    """Omitting three_tier defaults to legacy (cortex label)."""
    assert cortex_working_line() == cortex_working_line(three_tier=False)
    assert cortex_working_line("d") == cortex_working_line("d", three_tier=False)


# ── cortex_working_line — three-tier armed ─────────────────────────────────


def test_cortex_working_line_three_tier_plain_has_worker_label() -> None:
    """Three-tier plain render produces the worker label."""
    out = cortex_working_line(three_tier=True)
    assert out == "worker ▸ working…"
    assert "cortex ▸ working" not in out


def test_cortex_working_line_three_tier_plain_with_detail() -> None:
    """Three-tier plain render with detail carries the worker label."""
    out = cortex_working_line("editing colleague/loop.py", three_tier=True)
    assert out == "worker ▸ working… editing colleague/loop.py"
    assert "cortex ▸ working" not in out


def test_cortex_working_line_three_tier_color_has_worker_label() -> None:
    """Three-tier colour render carries the worker label."""
    out = cortex_working_line(three_tier=True, color=True)
    assert "worker ▸ working…" in out
    assert "cortex ▸ working" not in out


def test_cortex_working_line_three_tier_no_cortex_lines() -> None:
    """Three-tier render produces ZERO 'cortex ▸ working' lines."""
    for detail in ("", "step 1", "running tests"):
        plain = cortex_working_line(detail, three_tier=True, color=False)
        color = cortex_working_line(detail, three_tier=True, color=True)
        assert "cortex ▸ working" not in plain, f"detail={detail!r} plain"
        assert "cortex ▸ working" not in color, f"detail={detail!r} color"


# ── senses_line unchanged ──────────────────────────────────────────────────


def test_senses_line_unchanged() -> None:
    """senses_line is unaffected by three-tier changes."""
    assert senses_line("hello") == "senses: hello"

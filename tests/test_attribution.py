"""Tests for :mod:`colleague.attribution`.

Snapshot-style tests pinning both the plain (no-ANSI) and colour (ANSI SGR)
forms of the senses/cortex attribution lines, plus determinism.
"""

from __future__ import annotations

from colleague.attribution import cortex_working_line, senses_line


def _sgr_codes(text: str) -> set[str]:
    """Extract the set of raw ANSI SGR escape codes (e.g. ``"\\x1b[36m"``) in text."""
    codes: set[str] = set()
    index = 0
    while True:
        start = text.find("\x1b[", index)
        if start == -1:
            break
        end = text.find("m", start)
        if end == -1:
            break
        codes.add(text[start : end + 1])
        index = end + 1
    return codes


def test_senses_line_plain_has_label_and_no_ansi() -> None:
    out = senses_line("hello there", color=False)
    assert "senses:" in out
    assert "hello there" in out
    assert "\x1b" not in out


def test_cortex_working_line_plain_has_label_and_no_ansi() -> None:
    out = cortex_working_line(color=False)
    assert "cortex ▸ working" in out
    assert "\x1b" not in out


def test_cortex_working_line_plain_with_detail_has_no_ansi() -> None:
    out = cortex_working_line("editing colleague/loop.py", color=False)
    assert "cortex ▸ working" in out
    assert "editing colleague/loop.py" in out
    assert "\x1b" not in out


def test_senses_line_color_has_ansi_sgr_and_label() -> None:
    out = senses_line("hello there", color=True)
    assert "\x1b[" in out
    assert "senses:" in out
    assert "hello there" in out


def test_cortex_working_line_color_has_ansi_sgr_and_label() -> None:
    out = cortex_working_line(color=True)
    assert "\x1b[" in out
    assert "cortex ▸ working" in out


def test_senses_and_cortex_use_different_colour_codes() -> None:
    reset = "\x1b[0m"
    senses_codes = _sgr_codes(senses_line("x", color=True)) - {reset}
    cortex_codes = _sgr_codes(cortex_working_line("y", color=True)) - {reset}

    # Both must actually carry a colour code (beyond the shared reset), and
    # the colour codes themselves must not overlap — senses and cortex are
    # visually distinct hues.
    assert senses_codes
    assert cortex_codes
    assert senses_codes.isdisjoint(cortex_codes)


def test_senses_line_is_deterministic() -> None:
    assert senses_line("same text", color=True) == senses_line("same text", color=True)
    assert senses_line("same text", color=False) == senses_line("same text", color=False)


def test_cortex_working_line_is_deterministic() -> None:
    assert cortex_working_line("detail", color=True) == cortex_working_line("detail", color=True)
    assert cortex_working_line("detail", color=False) == cortex_working_line("detail", color=False)


def test_color_false_is_default() -> None:
    assert senses_line("hello") == senses_line("hello", color=False)
    assert cortex_working_line("d") == cortex_working_line("d", color=False)

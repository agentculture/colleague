"""Tests for shift-tab (CSI-Z) decoding and CYCLE_MODE sentinel in _session_input.

Covers the ESC[Z → SHIFT_TAB decode path, the reduce_key transition, and the
unique CYCLE_MODE sentinel object.  Mirrors the style of
tests/test_session_autocomplete.py (pipe-backed _read_escape, pure reduce_key
calls, sentinel identity checks).
"""

from __future__ import annotations

import os

from colleague.cli._commands._session_input import (
    CYCLE_MODE,
    _classify_key,
    _read_escape,
    reduce_key,
)

# ---------------------------------------------------------------------------
# A. _read_escape decoding: ESC[Z → SHIFT_TAB; ESC[Q → ESC; bare ESC → ESC
# ---------------------------------------------------------------------------


def test_read_escape_esc_z_yields_shift_tab() -> None:
    """ESC '[' 'Z' (CSI-Z) decodes to SHIFT_TAB."""
    r, w = os.pipe()
    os.write(w, b"[Z")
    assert _read_escape(r) == "SHIFT_TAB"
    os.close(r)
    os.close(w)


def test_read_escape_esc_unknown_byte_yields_esc() -> None:
    """ESC '[' followed by an unknown byte (e.g. 'Q') still resolves to ESC."""
    r, w = os.pipe()
    os.write(w, b"[Q")
    assert _read_escape(r) == "ESC"
    os.close(r)
    os.close(w)


def test_read_escape_bare_esc_yields_esc() -> None:
    """A bare ESC with no '[' (select times out) resolves to ESC."""
    r, w = os.pipe()
    try:
        assert _read_escape(r) == "ESC"
    finally:
        os.close(r)
        os.close(w)


# ---------------------------------------------------------------------------
# B. reduce_key('SHIFT_TAB', …) → action 'cycle_mode', buffer unchanged
# ---------------------------------------------------------------------------


def test_reduce_shift_tab_non_empty_buffer() -> None:
    """SHIFT_TAB on a non-empty buffer returns 'cycle_mode' and leaves buffer intact."""
    buf, sel, action = reduce_key("SHIFT_TAB", "/mo", 0, [])
    assert buf == "/mo"
    assert sel == 0
    assert action == "cycle_mode"


def test_reduce_shift_tab_empty_buffer() -> None:
    """SHIFT_TAB on an empty buffer returns 'cycle_mode' and leaves buffer intact."""
    buf, sel, action = reduce_key("SHIFT_TAB", "", 0, [])
    assert buf == ""
    assert sel == 0
    assert action == "cycle_mode"


def test_reduce_shift_tab_never_submit_or_quit() -> None:
    """SHIFT_TAB must never yield 'submit' or 'quit'."""
    _, _, action = reduce_key("SHIFT_TAB", "/mo", 0, [])
    assert action not in ("submit", "quit")


# ---------------------------------------------------------------------------
# C. CYCLE_MODE sentinel identity
# ---------------------------------------------------------------------------


def test_cycle_mode_is_unique_sentinel() -> None:
    """CYCLE_MODE is a unique object, not equal to any string or None."""
    assert CYCLE_MODE is CYCLE_MODE
    assert CYCLE_MODE is not None
    assert CYCLE_MODE != "cycle_mode"
    assert CYCLE_MODE != ""
    assert not isinstance(CYCLE_MODE, str)


# ---------------------------------------------------------------------------
# D. Regression: plain TAB still works as before
# ---------------------------------------------------------------------------


def test_reduce_tab_still_completes() -> None:
    """Plain TAB ('\t') still classifies as 'TAB' and completes via reduce_key."""
    from colleague.cli._commands.session import filter_slash

    matches = filter_slash("co")  # commands, config
    buf, sel, action = reduce_key("TAB", "/co", 1, matches)
    assert buf == "/config"
    assert sel == 0
    assert action == "redraw"


def test_classify_tab_still_yields_tab() -> None:
    """_classify_key('\\t', …) still returns 'TAB'."""
    assert _classify_key("\t", 0) == "TAB"

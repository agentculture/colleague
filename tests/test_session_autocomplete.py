"""Tests for the ``colleague session`` slash-command autocomplete popup.

The pure pieces (the autofilter, the popup widget, the raw-mode gate, the
catalog/help drift) are tested here without any real TTY. The raw per-keystroke
loop needs a terminal and is exercised by the PR's manual verification; its
fallback branch is tested deterministically with a non-TTY stream.
"""

from __future__ import annotations

import sys

from colleague.cli._commands._session_input import (
    read_line_with_popup,
    reduce_key,
    supports_raw_mode,
)
from colleague.cli._commands.session import (
    _CONFIG_ACTIONS,
    _HELP_TEXT,
    _INTROSPECT,
    _SLASH_COMMANDS,
    filter_slash,
)
from colleague.tui.widgets.slash_autocomplete import render_slash_autocomplete

# ---------------------------------------------------------------------------
# filter_slash — the autofilter core
# ---------------------------------------------------------------------------


def test_filter_empty_prefix_returns_all() -> None:
    """Just-opened popup (no chars after /) shows every command."""
    assert filter_slash("") == list(_SLASH_COMMANDS)


def test_filter_narrows_on_prefix() -> None:
    """'co' narrows to commands + config and drops the rest."""
    names = [s.name for s in filter_slash("co")]
    assert "commands" in names
    assert "config" in names
    assert "engine" not in names


def test_filter_is_case_insensitive() -> None:
    assert [s.name for s in filter_slash("CO")] == [s.name for s in filter_slash("co")]


def test_filter_no_match_is_empty_the_vanish_case() -> None:
    """A non-matching prefix yields [] — the popup disappears."""
    assert filter_slash("zzz") == []


def test_filter_restore_after_delete() -> None:
    """Deleting back to the bare '/' restores the full list (open→narrow→restore)."""
    assert filter_slash("e") != filter_slash("")  # narrowed
    assert filter_slash("") == list(_SLASH_COMMANDS)  # restored


# ---------------------------------------------------------------------------
# render_slash_autocomplete — the popup widget
# ---------------------------------------------------------------------------


def test_widget_empty_matches_renders_nothing() -> None:
    assert render_slash_autocomplete([], 0) == ""


def test_widget_renders_matches_with_exactly_one_highlight() -> None:
    matches = filter_slash("co")
    out = render_slash_autocomplete(matches, 0)
    assert out  # non-empty
    for spec in matches:
        assert spec.name in out
    assert out.count("\x1b[7m") == 1  # exactly one reverse-video (selected) row


def test_widget_clamps_selection() -> None:
    matches = filter_slash("co")
    # An out-of-range selection still renders one highlight (clamped).
    assert render_slash_autocomplete(matches, 99).count("\x1b[7m") == 1


def test_widget_truncates_rows_at_narrow_width() -> None:
    out = render_slash_autocomplete(filter_slash("co"), 0, width=14)
    assert "…" in out  # a narrow width forces row truncation


def test_widget_has_no_termios_import() -> None:
    import inspect
    import re

    import colleague.tui.widgets.slash_autocomplete as mod

    src = inspect.getsource(mod)
    assert not re.search(r"^\s*(import|from)\s+termios\b", src, re.MULTILINE)
    assert not re.search(r"^\s*(import|from)\s+tty\b", src, re.MULTILINE)


# ---------------------------------------------------------------------------
# catalog / help drift — single source of truth
# ---------------------------------------------------------------------------


def test_help_text_is_derived_from_catalog() -> None:
    for spec in _SLASH_COMMANDS:
        assert f"/{spec.name}" in _HELP_TEXT


def test_every_dispatch_verb_appears_in_catalog() -> None:
    names = {s.name for s in _SLASH_COMMANDS}
    for verb in list(_INTROSPECT) + list(_CONFIG_ACTIONS) + ["help", "quit"]:
        assert verb in names, f"slash verb '{verb}' missing from the catalog"
        assert f"/{verb}" in _HELP_TEXT


# ---------------------------------------------------------------------------
# raw-mode gate + fallback — agents/piped callers are unaffected
# ---------------------------------------------------------------------------


class _NonTTY:
    def isatty(self) -> bool:
        return False

    def read(self, _n: int) -> str:  # pragma: no cover - never reached in fallback
        return ""


class _FakeTTY:
    def isatty(self) -> bool:
        return True


def test_supports_raw_mode_false_for_non_tty() -> None:
    assert supports_raw_mode(_NonTTY()) is False


def test_supports_raw_mode_false_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert supports_raw_mode(_FakeTTY()) is False


def test_reader_uses_fallback_when_not_a_tty() -> None:
    """A non-TTY stream takes the fallback path and never enters raw mode."""
    used: list[bool] = []

    def _fb() -> str:
        used.append(True)
        return "typed line"

    result = read_line_with_popup(
        _SLASH_COMMANDS,
        lambda _b, _m, _s: "",
        filter_slash,
        stream=_NonTTY(),
        fallback=_fb,
    )
    assert result == "typed line"
    assert used == [True]


class _BadTTY:
    """isatty() lies True but fileno() fails — raw mode can't actually start."""

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        raise OSError("no fileno here")


def test_reader_falls_back_when_raw_mode_fails_at_runtime() -> None:
    """isatty() True but a termios/fileno op raises → fall back, don't crash."""
    used: list[bool] = []

    def _fb() -> str:
        used.append(True)
        return "fallback line"

    result = read_line_with_popup(
        _SLASH_COMMANDS,
        lambda _b, _m, _s: "",
        filter_slash,
        stream=_BadTTY(),
        fallback=_fb,
    )
    assert result == "fallback line"
    assert used == [True]


def test_getch_reassembles_multibyte_utf8() -> None:
    """A multi-byte keystroke (2- and 3-byte UTF-8) is not dropped."""
    import os

    from colleague.cli._commands._session_input import _getch

    for ch in ("é", "❯", "a"):  # 2-byte, 3-byte, 1-byte
        r, w = os.pipe()
        os.write(w, ch.encode("utf-8"))
        os.close(w)
        try:
            assert _getch(r) == ch
        finally:
            os.close(r)


def test_getch_returns_empty_on_eof() -> None:
    import os

    from colleague.cli._commands._session_input import _getch

    r, w = os.pipe()
    os.close(w)  # immediate EOF
    try:
        assert _getch(r) == ""
    finally:
        os.close(r)


def test_getch_truncated_multibyte_is_dropped_safely() -> None:
    """A lead byte with no continuation (truncated UTF-8) decodes to '' — no crash."""
    import os

    from colleague.cli._commands._session_input import _getch

    r, w = os.pipe()
    os.write(w, b"\xc3")  # 2-byte lead, no continuation
    os.close(w)
    try:
        assert _getch(r) == ""
    finally:
        os.close(r)


# ---------------------------------------------------------------------------
# _classify_key / _read_escape — raw keystroke normalisation
# ---------------------------------------------------------------------------


def test_classify_key_maps_control_and_printable() -> None:
    from colleague.cli._commands._session_input import _classify_key

    assert _classify_key("", 0) == "EOF"
    assert _classify_key("\x03", 0) == "CTRL_C"
    assert _classify_key("\x04", 0) == "CTRL_D"
    assert _classify_key("\r", 0) == "ENTER"
    assert _classify_key("\n", 0) == "ENTER"
    assert _classify_key("\t", 0) == "TAB"
    assert _classify_key("\x7f", 0) == "BACKSPACE"
    assert _classify_key("a", 0) == "a"
    assert _classify_key("\x01", 0) is None  # ignored control char


def test_read_escape_resolves_arrows_and_bare_esc() -> None:
    import os

    from colleague.cli._commands._session_input import _classify_key, _read_escape

    # Arrow up: "[A" after the ESC.
    r, w = os.pipe()
    os.write(w, b"[A")
    assert _read_escape(r) == "UP"
    os.close(r)
    os.close(w)

    # ESC dispatched through _classify_key with a down-arrow sequence.
    r, w = os.pipe()
    os.write(w, b"[B")
    assert _classify_key("\x1b", r) == "DOWN"
    os.close(r)
    os.close(w)

    # Bare ESC: nothing follows → select times out → "ESC" (w kept open).
    r, w = os.pipe()
    try:
        assert _read_escape(r) == "ESC"
    finally:
        os.close(r)
        os.close(w)

    # ESC followed by a non-'[' byte → "ESC".
    r, w = os.pipe()
    os.write(w, b"x")
    assert _read_escape(r) == "ESC"
    os.close(r)
    os.close(w)


# ---------------------------------------------------------------------------
# read_line_with_popup — builtin-input fallback when no fallback fn is given
# ---------------------------------------------------------------------------


def test_reader_uses_builtin_input_without_fallback(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_: "via input")
    result = read_line_with_popup(
        _SLASH_COMMANDS, lambda _b, _m, _s: "", filter_slash, stream=_NonTTY()
    )
    assert result == "via input"


def test_reader_returns_none_on_eof_without_fallback(monkeypatch) -> None:
    def _raise_eof(*_: object) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    result = read_line_with_popup(
        _SLASH_COMMANDS, lambda _b, _m, _s: "", filter_slash, stream=_NonTTY()
    )
    assert result is None


def test_supports_raw_mode_false_when_isatty_raises() -> None:
    class _Boom:
        def isatty(self) -> bool:
            raise RuntimeError("boom")

    assert supports_raw_mode(_Boom()) is False


# ---------------------------------------------------------------------------
# _read_live_ansi — the live-TTY entry: popup render closure + fallback path
# ---------------------------------------------------------------------------


def test_read_live_ansi_renders_popup_and_runs_fallback(tmp_path, monkeypatch) -> None:
    """Exercise the _render popup closure and the _fallback closure of the live read."""
    import colleague.cli._commands._session_input as si
    from colleague.cli._commands.session import _Session
    from colleague.config import EngineConfig

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
        json_mode=False,
        view="ansi",
        out=lambda *a, **k: None,
        err=lambda *a, **k: None,
        drive_fn=lambda **k: None,
    )

    captured: dict = {}
    monkeypatch.setattr("builtins.input", lambda *a: "fallback typed")

    def _fake_reader(specs, render, filter_fn, *, stream=None, out=None, fallback=None):
        captured["frame"] = render("/co", filter_fn("co", specs), 0)  # _render closure
        captured["fallback"] = fallback()  # _fallback closure
        return "/help"

    monkeypatch.setattr(si, "read_line_with_popup", _fake_reader)

    result = sess._read_live_ansi()
    assert result == "/help"
    assert "commands" in captured["frame"]  # the popup rendered for "/co"
    assert "\x1b[7m" in captured["frame"]  # a highlighted row was drawn
    assert captured["fallback"] == "fallback typed"


def test_read_live_ansi_fallback_returns_none_on_eof(tmp_path, monkeypatch) -> None:
    """The _fallback closure returns None when stdin hits EOF (Ctrl-D)."""
    import colleague.cli._commands._session_input as si
    from colleague.cli._commands.session import _Session
    from colleague.config import EngineConfig

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
        json_mode=False,
        view="ansi",
        out=lambda *a, **k: None,
        err=lambda *a, **k: None,
        drive_fn=lambda **k: None,
    )

    def _raise_eof(*_: object) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    captured: dict = {}

    def _fake_reader(specs, render, filter_fn, *, stream=None, out=None, fallback=None):
        captured["fallback"] = fallback()
        return None

    monkeypatch.setattr(si, "read_line_with_popup", _fake_reader)
    assert sess._read_live_ansi() is None
    assert captured["fallback"] is None


# The raw per-keystroke loop's I/O shell (``_raw_loop``) needs a real terminal;
# pytest's fd capture deadlocks a pty-backed test, so it is verified by the PR's
# manual pty smoke test. Its key-handling logic lives in the pure ``reduce_key``
# reducer below and IS unit-tested without a TTY.


# ---------------------------------------------------------------------------
# reduce_key — the pure key-handling transition (TTY-free)
# ---------------------------------------------------------------------------


def test_reduce_enter_submits_buffer() -> None:
    assert reduce_key("ENTER", "/help", 0, []) == ("/help", 0, "submit")


def test_reduce_eof_quits_even_mid_line() -> None:
    """True EOF must quit even with a partial buffer (else _raw_loop busy-loops)."""
    assert reduce_key("EOF", "/co", 0, [])[2] == "quit"


def test_reduce_ctrl_c_quits() -> None:
    assert reduce_key("CTRL_C", "", 0, [])[2] == "quit"


def test_reduce_ctrl_d_quits_only_on_empty_line() -> None:
    assert reduce_key("CTRL_D", "", 0, [])[2] == "quit"
    # Ctrl-D mid-line is ignored (redraw), buffer untouched.
    assert reduce_key("CTRL_D", "/co", 0, []) == ("/co", 0, "redraw")


def test_reduce_tab_completes_to_selected_match() -> None:
    matches = filter_slash("co")  # commands, config
    buf, _sel, action = reduce_key("TAB", "/co", 1, matches)
    assert buf == "/config"  # no arg_hint → no trailing space
    assert action == "redraw"


def test_reduce_tab_adds_trailing_space_when_arg_hint() -> None:
    matches = [s for s in _SLASH_COMMANDS if s.name == "engine"]  # arg_hint "<name>"
    buf, _sel, _action = reduce_key("TAB", "/engine", 0, matches)
    assert buf == "/engine "


def test_reduce_tab_without_matches_is_noop() -> None:
    assert reduce_key("TAB", "/zzz", 0, []) == ("/zzz", 0, "redraw")


def test_reduce_arrows_move_selection() -> None:
    assert reduce_key("DOWN", "/c", 0, filter_slash("c"))[1] == 1
    assert reduce_key("UP", "/c", 1, filter_slash("c"))[1] == 0


def test_reduce_esc_dismisses_by_clearing_buffer() -> None:
    assert reduce_key("ESC", "/co", 1, filter_slash("co")) == ("", 0, "redraw")


def test_reduce_backspace_deletes_last_char() -> None:
    assert reduce_key("BACKSPACE", "/co", 0, [])[0] == "/c"


def test_reduce_printable_char_is_appended() -> None:
    assert reduce_key("x", "/c", 0, [])[0] == "/cx"


def test_reduce_ignored_key_is_a_noop_redraw() -> None:
    assert reduce_key(None, "/c", 0, []) == ("/c", 0, "redraw")

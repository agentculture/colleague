"""Tests for the ``colleague session`` slash-command autocomplete popup.

The pure pieces (the autofilter, the popup widget, the raw-mode gate, the
catalog/help drift) are tested here without any real TTY. The raw per-keystroke
loop needs a terminal and is exercised by the PR's manual verification; its
fallback branch is tested deterministically with a non-TTY stream.
"""

from __future__ import annotations

import sys

from colleague.cli._commands._session_input import read_line_with_popup, supports_raw_mode
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


# The raw per-keystroke loop (``_raw_loop``) needs a real terminal; pytest's fd
# capture deadlocks a pty-backed test, so it is verified by the PR's manual pty
# smoke test (see docs/plans/...autocomplete-popup.md) rather than here.

"""Color/TTY gating helpers (A5): honor NO_COLOR + isatty, strip escapes."""

from __future__ import annotations

import io

from convertible.tui.colors import should_color, strip_ansi


class _Tty(io.StringIO):
    """A StringIO that claims to be (or not be) an interactive terminal."""

    def __init__(self, isatty: bool) -> None:
        super().__init__()
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


def test_should_color_true_only_on_tty_without_no_color(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert should_color(_Tty(isatty=True)) is True
    assert should_color(_Tty(isatty=False)) is False


def test_no_color_env_disables_even_on_a_tty(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert should_color(_Tty(isatty=True)) is False


def test_empty_no_color_does_not_disable(monkeypatch) -> None:
    # Per the common reading, an empty value is treated as unset.
    monkeypatch.setenv("NO_COLOR", "")
    assert should_color(_Tty(isatty=True)) is True


def test_should_color_handles_streams_without_isatty(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)

    class _NoIsatty:
        pass

    assert should_color(_NoIsatty()) is False  # type: ignore[arg-type]


def test_strip_ansi_removes_sgr_and_clear_sequences() -> None:
    colored = "\x1b[31mred\x1b[0m and \x1b[2J\x1b[Hcleared"
    assert strip_ansi(colored) == "red and cleared"
    assert "\x1b" not in strip_ansi(colored)


def test_strip_ansi_leaves_plain_text_untouched() -> None:
    assert strip_ansi("plain text") == "plain text"

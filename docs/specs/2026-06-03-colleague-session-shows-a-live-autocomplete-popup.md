# colleague session shows a live / autocomplete popup that opens on a colour TTY, autofilters slash commands as you type, and disappears when nothing matches

> colleague session shows a live / autocomplete popup that opens on a colour TTY, autofilters slash commands as you type, and disappears when nothing matches

## Audience

- humans driving 'colleague session' interactively on a colour TTY (not agents/piped callers)

## Before → After

- Before: the prompt is a whole-line input() call with no per-keystroke feedback; a human must already know the slash table or type /help to see it
- After: typing / opens a filtered menu of slash commands that narrows as you type, restores when characters are deleted, and vanishes when nothing matches; Tab/Enter completes the selection, arrows move it, Esc dismisses

## Why it matters

- slash-command discoverability without memorising the table — the palette teaches itself to humans

## Requirements

- the interactive reader degrades to plain input() whenever raw mode is unavailable: stdin is not a TTY, termios import fails, or the platform is Windows
  - honesty: with stdin not a colour TTY (piped/--json/--no-tui/Windows/termios-absent) the session takes the existing plain input() path and behaves byte-identically — the unchanged test_session.py suite proves it
- one structured slash-command catalog (a SlashSpec list) is the single source for both the /help text and the popup, so the two cannot drift
  - honesty: every verb in _INTROSPECT and _CONFIG_ACTIONS (plus help/quit) appears in the catalog and in the derived /help text — a drift test asserts this
- zero new runtime dependency: the reader uses only stdlib termios/tty/select and the popup widget emits pure ANSI; dependencies=[] still holds and the tui-core import guard stays green
  - honesty: the zero-deps guard (tests/test_zero_deps.py) and boundary guard (tests/test_boundary.py) pass: no urllib/socket/http/subprocess in tui-core and no forbidden imports introduced

## Honesty conditions

- on a colour TTY the popup is purely additive: the drive path (execute_drive) and result shape are unchanged, so the all-engines/h11 parity test still passes
- the feature targets only interactive human TTY use; agents and piped callers are explicitly unaffected because they take the fallback path
- each of the four behaviours (open on /, narrow on type, restore on delete, vanish on no-match) is exercised by a test over the pure filter and the widget render
- today's prompt is literally input(plain_prompt()) inside _read_live_ansi with no per-keystroke hook — verifiable in session.py
- a human can discover and run a slash command they did not previously know using only the popup
- no history/mouse/fuzzy-match code is added; the popup renders only on a colour TTY; no runtime dep and no socket/daemon are introduced
- the listed terminal interactions and the piped byte-identical behaviour are shown in the PR manual verification and the automated suite

## Success signals

- in a real terminal / shows the menu, 'co' narrows to commands+config, deleting back restores the full list, 'zzz' hides it; piped input stays byte-identical to today; all existing test_session.py passes unchanged

## Scope / boundaries

- not a full readline replacement (no history, no mouse, prefix-match only); live-TTY only; piped/--json/--no-tui/agent paths keep the exact line-based path; zero new runtime deps; foreground-only (no socket/daemon)

## Open / follow-up

- richer in-line editing beyond Tab/Enter/arrows/Esc/Backspace (e.g. Ctrl-A/Ctrl-E, word-delete, history) — v0 ships minimal editing only

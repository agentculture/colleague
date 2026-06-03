# Build Plan — colleague session shows a live / autocomplete popup that opens on a colour TTY, autofilters slash commands as you type, and disappears when nothing matches

slug: `colleague-session-shows-a-live-autocomplete-popup` · status: `exported` · from frame: `colleague-session-shows-a-live-autocomplete-popup`

> colleague session shows a live / autocomplete popup that opens on a colour TTY, autofilters slash commands as you type, and disappears when nothing matches

## Tasks

### t1 — Add a structured SlashSpec catalog in session.py and derive _HELP_TEXT from it (single source for help + popup)

- covers: c4, c9, h3, h7
- acceptance:
  - a SlashSpec(name,arg_hint,description) list enumerates every slash command and _HELP_TEXT is built from it
  - a drift test asserts every _INTROSPECT and _CONFIG_ACTIONS verb plus help/quit appears in the catalog and the derived help

### t2 — Add pure filter_slash(prefix, specs) over the catalog (the testable autofilter core)

- depends on: t1
- covers: c2, c3, h5, h6
- acceptance:
  - filter_slash returns the full list on empty prefix, case-insensitive startswith matches, and an empty list on no match (the vanish case)

### t3 — New pure-ANSI slash_autocomplete widget rendering filtered specs with a highlighted row

- depends on: t1
- covers: c1, c3, h6
- acceptance:
  - the widget renders filtered specs as a boxed ANSI menu with exactly one highlighted selected row and returns empty string on no matches
  - the widget imports no termios and the tui-core import guard (test_zero_deps) still passes

### t4 — New stdlib raw-mode reader read_line_with_popup in _session_input.py with graceful fallback

- covers: c8, c10, h2, h4, h9
- acceptance:
  - on a TTY it enters raw mode via termios/tty, reads per keystroke, returns the line on Enter and None on Ctrl-D
  - when stdin is not a TTY, termios is unavailable, or on Windows it signals the caller to use plain input() instead
  - it imports no urllib/socket/http/subprocess and adds no runtime dependency (test_zero_deps + test_boundary pass)

### t5 — Wire read_line_with_popup into _Session._read_live_ansi (interactive TTY path only)

- depends on: t1, t2, t3, t4
- covers: c1, c5, c6, c7, h1
- acceptance:
  - _read_live_ansi uses the reader with the catalog and a redraw callback that folds the filtered popup into the cockpit
  - the input_fn test seam, the Markdown/static view, and --json keep the existing _read_line path unchanged so execute_drive and result shape are untouched

### t6 — Add tests/test_session_autocomplete.py and keep test_session.py green

- depends on: t1, t2, t3, t4, t5
- covers: c7, h1, h2, h3, h6, h8, h10
- acceptance:
  - tests cover filter open/narrow/restore/vanish + case-insensitivity, widget render + empty, and reader fallback on a non-TTY stream (no raw-mode entry)
  - the full pytest suite passes including the unchanged test_session.py regression set

### t7 — Update docs: explain ('session',) entry and the Interactive-palette CLAUDE.md bullet

- depends on: t5
- covers: c4, c5, c6, h7, h8
- acceptance:
  - the explain session entry and the CLAUDE.md Interactive-palette bullet describe the live autocomplete and its TTY-only / zero-dep / foreground limits; doc-test-alignment passes

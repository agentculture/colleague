# Convertible ships a `tui` command whose every visual frame has an agent-readable semantic mirror (TAUI), so a coder agent can read, operate, snapshot, replay, and diagnose the terminal UI without OCR or terminal guessing.

> Convertible ships a `tui` command whose every visual frame has an agent-readable semantic mirror (TAUI — **T**extual **A**gentic **UI**), so a coder agent can read, operate, snapshot, replay, and diagnose the terminal UI without OCR or terminal guessing.

Source: [agentculture/convertible#69](https://github.com/agentculture/convertible/issues/69) (originally proposed as "TJSON"; renamed to **TAUI** — Textual Agentic UI — during this frame, see Decisions).

## Audience

- Coder agents (Codex, Claude Code, convertible's own engines) that must read, operate, and debug the TUI — and the humans who use it interactively.

## Before → After

- Before: Terminal UIs are opaque to agents: an agent can run a TUI but cannot reliably know what state it is in, what action is available, why a popup appeared, whether focus is correct, or whether the visual frame disagrees with app state.
- After: Every meaningful visual TUI frame has a structured TAUI mirror an agent can read, inspect by stable selector, operate (selector->event), snapshot, replay deterministically, and diagnose — no OCR, no terminal key-sequence guessing.

## Why it matters

- It moves the TUI from a blind spot inside the agent workflow into part of it: a human-seen bug becomes an agent-diagnosable snapshot, repairable via deterministic replay.

## Requirements

- The reducer is a pure function reduce(state, event) -> state: no I/O, no clock, no randomness. Determinism (incl. --animations=deterministic) comes from advancing the animation frame only via explicit injected 'tick' events, never by reading wall-clock time.
  - honesty: The animation frame counter is a field in State advanced only by a tick event; two replays of the same events.jsonl produce byte-identical ANSI.
- TAUI is serialize(state): a single derived mirror of canonical State, never hand-maintained beside the renderer. Stable selectors are dotted JSON-paths into that TAUI tree (e.g. popup.skill.boost.accept), so they cannot drift from state.
  - honesty: Renaming or moving a node in State changes both its render and its selector path in lockstep; there is no second selector table that can disagree.
- The base install stays zero-deps (dependencies = []): the tui core (state/reducer/taui/selectors/snapshot/replay/diagnose) never imports a rendering library; only the optional [tui] renderer wheel may. Guarded by test_zero_deps.
  - honesty: After installing only the base package (no extras), importing the convertible.tui core modules introduces no third-party module, asserted by test_zero_deps; the ANSI default renderer still works.
- No visual-only truth: every meaningful state lives in TAUI as data (e.g. status.severity), and colour/animation/theme only reflects it. An agent reads severity, never a colour.
  - honesty: For a state with status.severity='error', the TAUI carries severity='error' and a message string; the red background is derivable from severity, and removing colour loses no information an agent needs.
- diagnose is a pure stdlib cross-mirror differ: it folds events.jsonl through the reducer, compares against the captured .taui.json and greps the .ansi, and classifies the disagreement into the 7 bug classes (state/render/layout/focus/input-routing/theme/popup-lifecycle) — no LLM, no tokens.
  - honesty: Given a snapshot triple where TAUI says popup visible=true but the ANSI lacks the popup title, diagnose returns 'render bug' (not state/layout) using only stdlib string/JSON comparison.

## Honesty conditions

- A captured frame round-trips: state -> TAUI -> replay/render reproduces the same frame, and the TAUI mirror is complete enough that diagnose never needs OCR or terminal scraping.
- The TAUI payload is consumable by a coder agent with no convertible-specific client (plain JSON over stdout/file), and a human can run the same 'tui' and see the rendered frame.
- Each of read/inspect/operate/snapshot/replay/diagnose maps to a concrete 'tui' subcommand that works headless, with no real terminal attached.
- Without TAUI the same bug can only be reported by pasting ANSI/screenshots; with it the agent names the failing selector and bug class from structured data.
- A human-captured snapshot triple is sufficient input for an agent to diagnose and propose a fix offline, without reproducing the bug live.
- No code path in the tui feature opens a socket, forks a daemon, adds a base dependency, or calls a model; the live driver is a foreground process that exits on quit.
- A passing CI test feeds an events.jsonl to the reducer and asserts diagnose's bug-class output, running with no TTY and no network.

## Success signals

- A coder agent reconstructs TUI state from an events.jsonl via the pure reducer and classifies a TUI bug from the snapshot triple, with no real terminal attached and no model call.

## Scope / boundaries

- Not a daemon/server, not a new parallel runtime (foreground TTY like session), not a base TUI-library dependency, and not an LLM-based diagnose. The live TTY driver is the thinnest, last slice.

## Decisions

- The CLI verb is 'tui' (not 'cockpit').
- The renderer is a wheel like engines: a hand-rolled stdlib ANSI renderer ships zero-deps as the default; Rich/Textual is an opt-in [tui] extra plus a separately-installable renderer wheel discovered via a 'convertible.renderers' entry-point group.
- Naming: the agent-readable semantic mirror is **TAUI** (Textual Agentic UI), renamed from the issue's "TJSON". The name doubles as the feature's identity (a Textual UI for humans that is Agentic/agent-readable). Snapshot mirror files use the `.taui.json` extension; the snapshot triple is `<name>.taui.json` + `<name>.ansi` + `<name>.events.jsonl`.

## Open / follow-up

- The Rich/Textual renderer wheel and the 'convertible.renderers' entry-point group ship after the stdlib-ANSI MVP; v0 ships only the default ANSI renderer.
- Whether the existing 'convertible session' line-palette folds into 'tui' (tui as the full-screen session) or stays a separate verb — decide during planning.
- The live TTY driver's raw-mode input handling (termios/tty) is the one impure seam; its keymap->event routing test strategy is TBD (the driver is intentionally the last, thinnest slice).

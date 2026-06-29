# colleague TUI — human-experience evaluation

A frame-by-frame evaluation of what colleague's terminal UI *feels like* for a
human, driven from deterministic simulations of the real render code.

## How this was produced

colleague's TUI renders through **pure, deterministic** functions over a
`CockpitState` — `render` (`colleague/tui/render/ansi.py`), `reduce`
(`colleague/tui/reducer.py`), `render_slash_autocomplete`
(`colleague/tui/widgets/slash_autocomplete.py`), and the session frame
composition (`colleague/cli/_commands/session.py:268`). The harness
`tools/tui_sim/` scripts realistic human flows through those *real* seams and
records each as an asciinema **v2 `.cast`** (the replayable "video") plus a
SGR-stripped `.txt` storyboard and a snapshot quad. Regenerate with:

```bash
python -m tools.tui_sim --out tools/tui_sim/recordings
```

Five scenarios cover the three surfaces and a full end-to-end ride:
`first-contact` (palette + slash autocomplete), `drive-cockpit` (live drive),
`skill-suggested` and `failed-step` (popups), and `full-ride` (all of it).

**Honest method note.** Per the chosen approach this is `.cast`-only — no pixel
rasterization — so the evaluation below is frame-level reasoning over the
deterministic ANSI frames and the cast pacing, not a pixel screenshot review.
To *see* the recordings, `asciinema play tools/tui_sim/recordings/full-ride.cast`,
or turn one into a GIF with `agg full-ride.cast full-ride.gif` (`cargo install agg`).

**Automated cross-check.** `agentfront.taui.diagnose` (the 7-class cross-mirror
checker) runs clean on every snapshot — RENDER / LAYOUT / FOCUS / INPUT_ROUTING /
THEME / POPUP_LIFECYCLE all pass. So the findings below are *interaction /
affordance* issues, which those 7 classes deliberately don't cover (itself a small
gap — see P1).

## What works well

- **Deterministic, pure rendering.** Same state → same frame, no clock or
  randomness. This is what let the entire simulation exist with zero new
  dependencies, and it makes the UI trivially testable.
- **The slash autocomplete is the strongest moment.** Typing `/` opens a filtered
  popup of every command; each keystroke narrows it live; the selected row is
  marked with `›`; a non-matching prefix makes it vanish (`first-contact.txt`
  frames 2→6). Discoverability on first contact is genuinely good.
- **Clear "working" feedback.** The prompt spinner cycles `|` `/` `-` `\` as a
  drive runs (`drive-cockpit.txt`, prompt line across frames), so the human can
  tell the agent is busy.
- **Legible tool-by-tool progress.** Drive steps fold into the conversation as
  `[read_file] colleague/loop.py`, `[write_file] …`, `[run_command] pytest …`,
  `[finish] …` — a human can follow exactly what the agent did.
- **Information-dense status line.** `engine mock · model … · local` tells you the
  three things you most need before you commit to a drive.
- **Clean box alignment.** At width 100 the three box styles (`┌ Commands`,
  `╔ Session`, popup boxes) align and visually separate the surfaces.

## Findings (prioritized)

### P1 — Popup buttons are inert, and their advertised keys do something else

The skill and error popups render action buttons with keybindings —
`[Activate boost]` (enter), `[Dismiss]` (esc), `[Details]` (d)
(`skill-suggested.txt` frame 7; `failed-step.md`). **No human input surface wires
those keys to those actions**, and the advertised keys are actively repurposed:

- In `session` (the readline cockpit), `reduce_key`
  (`colleague/cli/_commands/_session_input.py:178,197`) handles only
  submit/complete/navigate/backspace. **Enter always submits** — and an empty
  buffer submits `""`, which `session.run` treats as a quit token
  (`colleague/cli/_commands/session.py:291`). So a user who follows the boost
  popup's "Activate boost (enter)" **quits the session**. **Esc** only clears the
  slash buffer (`_key_esc`, line 197); it never emits a `Dismiss`, so the error
  popup's own "Dismiss (esc)" button **cannot remove the popup**.
- In `tui live` (the raw driver), `key_to_event`
  (`colleague/tui/render/driver.py:71`) maps **Esc → quit** and every other key to
  a `KeyPress`, which the reducer ignores (`colleague/tui/reducer.py:51`). So the
  buttons are non-functional there too; pressing "Dismiss (esc)" quits the driver.

Only the agent-facing `tui action --select <selector>` path actually triggers a
popup action. For a *human*, the buttons are decoration at best and a quit-trap at
worst. This is also why `diagnose` is happy: INPUT_ROUTING only checks that each
action's *selector resolves in the tree*, not that any keybinding reaches it.

**Suggested fixes (pick one):**

1. Render popups as purely informational inside the human surfaces — drop the
   button row (or mark it "(via `tui action`)") so no false affordance is shown.
2. Wire popup keys into `reduce_key` / the driver: when a popup is visible,
   enter/esc/d emit accept / `Dismiss` / details instead of submit / quit / no-op.
3. Minimum safety net: while a popup is visible, stop treating empty-Enter as a
   session quit.

### P2 — The status bar never reflects drive state or failure

A failed `run_command` opens an error popup but leaves `status.severity = "info"`
(`failed-step.md:38`) — the top bar stays its calm "info" colour through a
failure. `session._status()` hardcodes `severity="info"`
(`colleague/cli/_commands/session.py:214`) and the reducer's `_reduce_drive_step`
opens the popup without touching status (`colleague/tui/reducer.py:123`). The one
high-signal, always-visible line on screen is blind to the most important event.

**Fix:** set `severity="error"` on a failed step (or while an error popup is
visible), and consider `success`/`warn` on finish. The status bar already
colour-codes severity (`colleague/tui/widgets/status_bar.py`), so this is wiring,
not new rendering.

### P2 — The conversation panel has no viewport cap

`render_conversation` (`colleague/tui/widgets/conversation.py:58`) emits one box
row per logical line with no height bound, and the cockpit `render()` does no
total-height windowing. A long drive grows the Session box until the status bar
and command palette scroll off the top and the prompt is pushed down — on an
80×24 terminal the cockpit overflows after roughly 15–18 conversation lines (the
`/help` frame alone already reaches 28 lines: `first-contact.txt` frame 7). Live
redraw clears and repaints the whole frame each step, so the overflow is silent —
the top just disappears.

**Fix:** window the conversation to the last *N* lines (or to remaining terminal
height), with a `… (k earlier lines)` elision marker.

### P3 — Two parallel command namespaces are on screen at once

The numbered `Commands` palette (templates, e.g. `doc-review`) and the
`/`-triggered `Slash commands` popup coexist (`first-contact.txt` frame 2). A
newcomer faces three input modes simultaneously — type a number, type a template
name, or type a slash command — plus free text. The prompt hint enumerates them,
but the two competing boxes still ask "which list am I supposed to use?" Consider
subordinating one (e.g. collapse the templates palette to a count once a drive is
underway, or fold templates into the slash popup).

### P3 — Non-blocking suggestions render *below* the prompt

The boost popup is appended after the `colleague ❯` line (`skill-suggested.txt`
frame 7), i.e. below where the cursor and the user's attention are. As a
non-blocking nudge that's a defensible choice, but it detaches the suggestion from
the conversation it refers to and is easy to miss. If popups become interactive
(P1), reconsider placing them adjacent to the prompt or the relevant step.

### P3 — `/help` duplicates the autocomplete popup

Submitting `/help` prints the same 13-command list the autocomplete popup just
showed (`first-contact.txt` frame 2 vs frame 7). Harmless, but with a live popup
the textual `/help` is largely redundant for discovery.

## Bottom line

The foundation is strong: pure deterministic rendering, a genuinely good slash
autocomplete, clear progress feedback, and clean layout. The gap is **affordance
honesty** — the cockpit renders interactive-looking popup buttons that no human
keybinding actually drives (P1), and the always-visible status line ignores drive
failures (P2). Fixing those two would close most of the distance between "looks
interactive" and "is interactive." The recordings under
[`tools/tui_sim/recordings/`](../tools/tui_sim/recordings/) reproduce every
observation above and regenerate deterministically.

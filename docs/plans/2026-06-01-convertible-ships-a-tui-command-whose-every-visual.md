# Build Plan — Convertible ships a `tui` command whose every visual frame has an agent-readable semantic mirror (TAUI), so a coder agent can read, operate, snapshot, replay, and diagnose the terminal UI without OCR or terminal guessing.

slug: `convertible-ships-a-tui-command-whose-every-visual` · status: `exported` · from frame: `convertible-ships-a-tui-command-whose-every-visual`

> Convertible ships a `tui` command whose every visual frame has an agent-readable semantic mirror (TAUI — Textual Agentic UI), so a coder agent can read, operate, snapshot, replay, and diagnose the terminal UI without OCR or terminal guessing. Source: [agentculture/convertible#69](https://github.com/agentculture/convertible/issues/69) (originally "TJSON").

## Tasks

### t1 — convertible/tui/state.py: canonical CockpitState dataclass + to_dict/from_dict

- covers: c11
- acceptance:
  - CockpitState.to_dict()/from_dict() round-trip to an identical object
  - State holds screen, mode, focused, zones, panels, popups, background (with an integer animation 'frame' field), status (severity+message strings as data), drive, and problems

### t2 — convertible/tui/events.py: Event union + JSONL (de)serialize helpers

- covers: c10
- acceptance:
  - Each event type (user_input, key, tick, skill_suggested, dismiss, drive_step) round-trips through to_dict/from_dict and one-event-per-line JSONL

### t3 — convertible/tui/reducer.py: pure reduce(state, event) -> state

- depends on: t1, t2
- covers: c10, h2
- acceptance:
  - reduce() imports no os/time/random and reads no clock (purity asserted by test)
  - reduce(state, tick) advances only background.frame by a fixed delta; reduce(state, skill_suggested(boost)) opens popup.skill.boost; reduce(state, dismiss) closes it

### t4 — convertible/tui/taui.py: serialize(state) -> TAUI mirror dict + SCHEMA_VERSION

- depends on: t1
- covers: c3, c11, h7, c13
- acceptance:
  - serialize(state) returns a plain json.dumps-able dict; every popup/panel/action node carries a stable 'id'; status.severity+message present as data
  - the dict is consumable with no convertible import (pure JSON), and carries taui_version

### t5 — convertible/tui/render/ansi.py + widgets/ (status_bar, skill_panel, conversation, prompt_input, popup_layer): render(state)->str

- depends on: t1
- covers: c13, h5
- acceptance:
  - render(state) returns an ANSI string; a visible popup's title appears in the text; status.severity='error' renders red SGR codes yet the message text is still present (colour is reflection, not the only carrier)

### t6 — convertible/tui/selectors.py: resolve a dotted-path selector into the TAUI tree -> node/Action + selector->event

- depends on: t4
- covers: c11, h3
- acceptance:
  - resolve(taui, 'popup.skill.boost.accept') returns the action node; an unknown selector raises a clean error; a selector path is computed from the tree (moving a node changes its path) — there is no second selector table

### t7 — convertible/tui/snapshot.py: write/read the snapshot triple (<name>.taui.json + .ansi + .events.jsonl)

- depends on: t2, t4, t5
- covers: h1, h10
- acceptance:
  - snapshot.write(name, state, events) produces exactly the 3 files; read() reconstructs taui+ansi+events; the triple alone is sufficient input (no live process needed)

### t8 — convertible/tui/replay.py: fold an events.jsonl through reduce() -> state, deterministically

- depends on: t2, t3, t5
- covers: h1, h2, c7
- acceptance:
  - replay(events) reconstructs the final state; replaying the same events.jsonl twice yields byte-identical ANSI (deterministic, no clock)

### t9 — convertible/tui/diagnose.py: pure stdlib cross-mirror differ -> classify the 7 bug classes

- depends on: t3, t4, t7, t8
- covers: c14, h6, c4, h9, c5, c7, h12
- acceptance:
  - given a triple where TAUI says popup visible=true but the ANSI lacks the title, diagnose returns 'render bug' (not state/layout)
  - diagnose classifies all 7 classes (state/render/layout/focus/input-routing/theme/popup-lifecycle), imports no model/network module, and a CI test exercises events->reducer->diagnose with no TTY

### t10 — convertible/cli/_commands/tui.py + register in cli/__init__.py + explain catalog entry + scenario test: headless subcommands (render --state, state, snapshot, replay, inspect --select, action --select, test --scenario, diagnose, overview)

- depends on: t3, t4, t5, t6, t7, t8, t9
- covers: c1, c2, c3, h8
- acceptance:
  - every listed subcommand runs headless (no TTY) with --json, errors via CliError, and 'tui overview' + an explain catalog entry exist
  - a scenario YAML (scenarios/boost-popup.yaml) drives skill_suggested->popup and a test asserts the resulting TAUI + ANSI expectations

### t11 — pyproject.toml: optional [tui] extra (Rich/Textual) + 'convertible.renderers' entry-point group (ansi default registered); update tests/test_zero_deps.py + docs/features/tui.md

- depends on: t1, t2, t3, t4, t5, t6, t7, t8, t9
- covers: c6, h11, c12, h4
- acceptance:
  - base install keeps dependencies = []; importing the convertible.tui core (state/events/reducer/taui/selectors/snapshot/replay/diagnose) introduces no third-party module, asserted by test_zero_deps; the default ANSI renderer still works
  - the [tui] extra and convertible.renderers entry-point group are declared; no tui code path opens a socket, forks a daemon, or calls a model

### t12 — convertible/tui/render/driver.py: live foreground TTY loop (termios raw mode) + wire 'tui' (no subcommand) default func in cli/_commands/tui.py

- depends on: t10
- covers: h11
- acceptance:
  - running 'tui' starts a foreground loop that reads keys, routes them via selectors->events->reduce, repaints the ANSI frame, and exits cleanly on quit (no daemon, no socket); the driver is the only impure seam

## Risks

- [unknown_nonblocking] Live TTY driver raw-mode input handling (termios/tty): keymap->event routing test strategy is TBD; the driver is intentionally the last/thinnest slice. (task t12)
- [follow_up] Rich/Textual renderer wheel + populated convertible.renderers group ship after the stdlib-ANSI MVP; v0 ships only the default ANSI renderer.
- [follow_up] Whether 'convertible session' folds into 'tui' (tui as full-screen session) or stays a separate verb — decide post-MVP.

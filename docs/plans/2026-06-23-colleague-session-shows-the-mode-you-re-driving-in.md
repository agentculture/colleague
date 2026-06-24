# Build Plan — colleague session shows the mode you're driving in: shift-tab cycles auto → work → plan → explore → review, the active mode is visible in the cockpit (and the TAUI mirror), and your next free-text input routes by it.

slug: `colleague-session-shows-the-mode-you-re-driving-in` · status: `exported` · from frame: `colleague-session-shows-the-mode-you-re-driving-in`

> colleague session shows the mode you're driving in: shift-tab cycles auto → work → plan → explore → review, the active mode is visible in the cockpit (and the TAUI mirror), and your next free-text input routes by it.

## Tasks

### t1 — Mode catalog + pure helpers in a new colleague/session_modes.py: the single source for mode order, labels, cycling, validation, the routing decision, and the flat-ANSI affordance string.

- covers: c8, h2, c12, h6
- acceptance:
  - MODES is an ordered tuple ('auto','work','plan','explore','review'); next_mode() wraps review->auto and is the ONLY definition of cycle order
  - resolve_mode('plan')=='plan'; resolve_mode('bogus') raises a clean error naming the valid modes (no traceback)
  - route_for('auto', text, classify) returns exactly classify(text) (work|plan); route_for('explore',...) returns 'explore' WITHOUT calling classify
  - mode_affordance_line(mode) renders the labelled cycle with a 'shift-tab to cycle' hint, marking the active mode
  - a drift test asserts session_modes is the single source — no other module hardcodes the mode list/labels/order; module is pure stdlib, zero new deps, no import-time I/O

### t2 — Decode shift-tab in the raw-mode reader (colleague/cli/_commands/_session_input.py): ESC[Z -> a SHIFT_TAB token that cycles the mode without submitting or mutating the typed buffer.

- covers: c10, h4
- acceptance:
  - _read_escape decodes ESC[Z to a 'SHIFT_TAB' token; an unknown ESC[<x> still resolves to 'ESC'; a bare ESC still resolves to 'ESC'
  - reduce_key('SHIFT_TAB',...) returns the buffer UNCHANGED with a 'cycle_mode' action, never 'submit'/'quit'; reduce_key stays a pure function
  - _raw_loop returns a distinct CYCLE_MODE sentinel (not a string line) on shift-tab, writing no newline and not clearing the buffer
  - every existing _session_input key test stays green; plain TAB still completes a slash command (new SHIFT_TAB + unknown-escape cases added)

### t3 — Wire mode into colleague/cli/_commands/session.py: store the active mode, cycle on the reader's shift-tab sentinel, set CockpitState.mode for all tiers, add the /mode slash, and route free-text by mode.

- depends on: t1, t2
- covers: c1, h1, c4, h10, c6, h12, c9, h3, c11, h5
- acceptance:
  - session stores mode (default 'auto'); a shift-tab CYCLE_MODE sentinel advances it via session_modes.next_mode and re-renders WITHOUT submitting input
  - CockpitState.mode is set to the live mode each render so tui state JSON, render --format markdown, and flat-ANSI all show the SAME mode string (never the static 'planning'); flat-ANSI shows the mode + 'shift-tab to cycle' affordance
  - /mode with no arg cycles (or shows) current; /mode plan sets plan; /mode bogus prints error+hint listing valid modes and changes nothing; /mode is in the SlashSpec catalog and appears in /help
  - free-text routing calls session_modes.route_for(mode,text,classify_intent): auto reproduces today's ->work:/->plan: dispatch byte-for-byte; a pinned mode runs the matching verb and still logs the route
  - a bare number or known template name selects a work template regardless of the active mode (a palette pick is never reclassified)

### t4 — Add read-only explore/review dispatch to colleague/cli/_commands/session.py: explore via the explorer role, review via the reviewer role over the committed <base>...HEAD diff; no handoff.

- depends on: t3
- covers: c13, h7
- acceptance:
  - explore mode dispatches a read-only run using the explorer role; review mode uses the reviewer role over the committed <base>...HEAD diff via the session's current base
  - the read-only role withholds write_file/edit_file/run_command so a session explore/review leaves git status byte-identical even if the model attempts a write; no commit/branch/PR handoff is invoked
  - a test asserts the working tree + checked-out branch are unchanged after a mock explore and a mock review run
  - DECISION recorded: session explore/review run in-place under the read-only role (not a throwaway worktree) — the role's structural no-write makes in-place tree-safe (resolves the parked v1 unknown)

### t5 — Boundary/audience guard tests + docs: prove the non-goals hold and document the five modes.

- depends on: t3, t4
- covers: c2, h8, c3, h9, c5, h11, c7, h13
- acceptance:
  - a regression test proves auto-mode dispatch is byte-identical to today's classifier routing AND that colleague/session_intent.py (the classifier) is unchanged by this feature
  - the zero-deps guard (tests/test_zero_deps.py) and the e2e mock shape test (tests/test_e2e_mock.py) stay green — no new runtime dependency, TaskResult shape unchanged
  - a headless test proves an agent reads the mode from TAUI JSON and sets it via /mode with stdin NOT a TTY (both audiences served)
  - docs/features/session-modes.md + the CLAUDE.md 'Interactive palette' bullet describe the five modes, shift-tab, /mode, and read-only explore/review; the work/plan subcommands are documented as unchanged (non-goal)

## Risks

- [unknown_nonblocking] Some terminals emit a shift-tab sequence other than ESC[Z (e.g. legacy/non-xterm); those won't cycle via the key and degrade to /mode. v1 decodes ESC[Z only; the sequence set is not enumerated. (task t2)
- [follow_up] Parked frame unknown RESOLVED in t4: session explore/review run in-place under the read-only role, not a throwaway worktree. Follow-up: if a future read role ever needs a write-capable tool (e.g. run_command to execute tests), revisit worktree isolation like the ask-colleague verbs use. (task t4)

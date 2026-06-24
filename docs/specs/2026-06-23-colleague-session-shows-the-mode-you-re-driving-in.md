# colleague session shows the mode you're driving in: shift-tab cycles auto → work → plan → explore → review, the active mode is visible in the cockpit (and the TAUI mirror), and your next free-text input routes by it.

> colleague session shows the mode you're driving in: shift-tab cycles auto → work → plan → explore → review, the active mode is visible in the cockpit (and the TAUI mirror), and your next free-text input routes by it.

## Audience

- Two audiences: the operator driving 'colleague session' interactively at a colour TTY, and agents/pipelines that read the cockpit's TAUI/Markdown mirror or drive the session non-interactively (piped, --json, --no-tui).

## Before → After

- Before: Today the session classifies each free-text input implicitly via classify_intent (work vs plan) with no visible, operator-controllable mode; explore and review are unreachable from the session (only via the ask-colleague skill); CockpitState.mode is a dead field that always serializes 'planning' and is never set or used; shift-tab is not decoded by the raw-mode reader.
- After: The operator sees the active mode in the cockpit and presses shift-tab to cycle auto → work → plan → explore → review; the next free-text input routes by the active mode; agents read the live mode from the TAUI mirror and can set it with the /mode slash command on any path (TTY or not).

## Why it matters

- Explicit, visible mode control replaces an implicit guess: the operator pins the route instead of relying on the classifier (a misroute is visible today but still a misroute), and the two read-only safe verbs (explore, review) finally reach the interactive surface — one keystroke instead of dropping to the ask-colleague skill.

## Requirements

- R1 — one ordered mode catalog (single source of truth) defines the cycle order auto→work→plan→explore→review→auto, the display label per mode, and the routing each mode performs; shift-tab, /mode, and the visible label all read from it (drift-tested like the SlashSpec catalog).
  - honesty: Exactly one catalog lists the modes, their order, labels, and routing; shift-tab, /mode, the visible label, and /help all derive from it; a drift test fails if any consumer hardcodes a divergent list.
- R2 — the live mode is written onto CockpitState.mode so all three render tiers (TAUI JSON, Markdown, flat-ANSI) surface the same current-mode string; the dead default 'planning' is replaced by the real session mode, and the flat-ANSI interactive view shows the mode prominently with a 'shift-tab to cycle' affordance.
  - honesty: A snapshot of the same live session in all three tiers (tui state JSON, render --format markdown, flat-ANSI) shows the identical current-mode string; CockpitState.mode is no longer a static 'planning' when a session is live.
- R3 — the raw-mode reader decodes shift-tab (ESC[Z) into a new SHIFT_TAB key token that cycles the mode and redraws WITHOUT submitting or mutating the typed buffer; reduce_key stays a pure, unit-tested transition and every other key path (incl. plain Tab, arrows, bare ESC, unknown escape sequences) is byte-identical.
  - honesty: After a shift-tab keypress the typed buffer is unchanged and no line is submitted; reduce_key stays pure and unit-tested; plain Tab still completes a slash command and a bare/unknown ESC still resolves to ESC — proven by existing key tests staying green plus a new SHIFT_TAB case.
- R4 — a /mode slash command is the keyboard-free equivalent: '/mode' cycles (or shows current), '/mode <name>' sets it explicitly, '/mode <invalid>' fails with a hint listing valid modes (no crash); it works on the non-TTY path and appears in /help, sourced from the same catalog as R1.
  - honesty: '/mode' with no arg cycles or shows current; '/mode plan' sets plan; '/mode bogus' exits non-zero with a hint listing valid modes and changes nothing; the command is in /help and works when stdin is not a TTY.
- R5 — free-text routing honors the active mode: auto = today's classify_intent decision (byte-identical, same →work:/→plan: log); work/plan pin the route (skip the classifier, still log the dispatch); explore/review run the read-only path. A bare number or known template name is always a 'work' selection regardless of mode (a palette pick is never reclassified).
  - honesty: In auto mode the dispatch is byte-identical to today (same classify_intent call + same →work:/→plan: log); in a pinned mode the matching verb runs with a routing line still logged; a bare number or known template name selects a work template regardless of mode.
- R6 — explore and review run read-only and provably never mutate the operator's tree or branch: they reuse the existing read-only role machinery (explorer/reviewer roles withhold write_file/edit_file/run_command) so a session explore/review leaves 'git status' unchanged, with no commit/branch/PR handoff; review reads the committed <base>...HEAD diff using the session's current base.
  - honesty: A session explore or review run leaves 'git status' byte-identical (no new commit/branch/PR); the read-only role structurally withholds write_file/edit_file/run_command so even a hallucinated write is refused; review's context is the committed <base>...HEAD diff via the session base.

## Honesty conditions

- Pressing shift-tab in an interactive session deterministically advances the mode through the full cycle and wraps back to auto; the visible label and the TAUI 'mode' field both reflect the new mode immediately.
- Both audiences are really served: the interactive operator sees the mode in the flat-ANSI cockpit, and an agent/pipeline reads the same mode from the TAUI JSON and sets it via /mode with no TTY.
- The described gaps are factually present in current code: classify_intent routes free text with no operator-visible mode, the session exposes no explore/review verb, CockpitState.mode defaults to 'planning' and is never assigned, and the raw reader does not decode shift-tab.
- Each capability is demonstrable: cycling reaches all five modes and wraps, the next input routes by the active mode, and the mode is both readable (TAUI) and settable (/mode) on a non-TTY path.
- The value holds: a pinned mode removes a misroute the classifier would otherwise make, and explore/review become reachable in one keystroke instead of leaving the session for the ask-colleague skill.
- The signal is test-observable: an interactive cycle advances the label, a piped '/mode plan' sets the TAUI mode, and a never-touched session is byte-identical to today's routing and artifacts.
- The non-goals are enforceable: no work/plan subcommand change, no new dep/socket/daemon (the zero-deps guard stays green), classifier code unchanged, and the shift-tab key path gated to the live-ANSI reader only.

## Success signals

- In an interactive session, shift-tab visibly advances the mode label and the next free-text input runs the matching verb; in a piped/--json session, '/mode plan' sets it and the TAUI 'mode' field reflects it; a session that never touches mode stays in 'auto' and behaves byte-identically to today (same classify_intent routing, same artifacts).

## Scope / boundaries

- Non-goals: modes do NOT change the 'colleague work' / 'colleague plan' subcommands (modes are a session-only affordance); no new daemon/socket/runtime-dep (stdlib only); the classifier itself is unchanged (auto mode still calls classify_intent verbatim); no automatic task→backend routing; the shift-tab KEY works only on the live-ANSI interactive path — non-TTY sessions use /mode.

## Assumptions

- A1 — shift-tab arrives as the CSI-Z escape sequence (ESC[Z) on the xterm-family terminals colleague targets; a terminal that sends a different sequence simply won't cycle via the key, degrading to an ignored/!known escape (no crash) with /mode still available.

## Decisions

- D1 — the mode set is auto / work / plan / explore / review (operator-confirmed via the design question); 'auto' is a first-class member of the cycle, not the absence of a mode, and is the default at session start.
- D2 — the non-TTY affordance is a /mode slash command (operator-confirmed via the design question); shift-tab remains the interactive shortcut, /mode is the equivalent everywhere.

# colleague's cockpit now reads like a real coder-agent cockpit in both states: idle answers identity → permissions → workspace → capacity → next action, and a running work item visibly changes the screen — live phase, step progress, current operation, and a mutation ledger (files changed · commands run · commits · publish state) — while mode language is unambiguous (behavior mode vs auto resolution vs execution profile).

> colleague's cockpit now reads like a real coder-agent cockpit in both states: idle answers identity → permissions → workspace → capacity → next action, and a running work item visibly changes the screen — live phase, step progress, current operation, and a mutation ledger (files changed · commands run · commits · publish state) — while mode language is unambiguous (behavior mode vs auto resolution vs execution profile).

## Audience

- operators driving 'colleague session' interactively on a terminal, plus agents reading the same cockpit through the Markdown / TAUI-JSON mirror tiers

## Before → After

- Before: the mid-run cockpit looks like the idle cockpit: a vague 'thinking…' line, a stale Safest-next suggestion, templates eating vertical space, transcript and tool events interleaved in one Conversation feed, and 'mode' meaning three different things (behavior, auto resolution, capacity profile)
- After: idle and running are visibly distinct layouts; at a glance the operator can tell whether the agent is waiting on the model, reading, editing, or running a command, and can always see what has already been changed (files, commands, commits, publish state)

## Why it matters

- a coder agent whose run_command is ungated must earn trust by construction: the cockpit must always answer 'what is it doing right now' and 'what has it already changed' — issue #285's five-questions design principle (identity, permissions, workspace, current activity, mutations)

## Requirements

- mode disambiguation: the cockpit presents the three mode concepts as distinct labeled facts — behavior (work/plan/explore/review), source (auto-classified vs pinned), and execution profile (steps/timeout/budget/fill-line) — instead of three uses of the word 'mode'
  - honesty: the three facts (behavior, source, profile) are rendered from the existing single-source catalogs (session_modes.MODES, profiles.MODE_PROFILES) and a drift test pins them — no second mode vocabulary is introduced
- idle layout: 'Work templates' is reframed as suggested work, the Safest-next line is promoted from status text to a first-class next-action block, the Run policy panel gets a stronger honest visual grammar (aligned label · state · consequence), and neutral-empty facts (e.g. capacity signal none-yet) drop warning styling
  - honesty: the idle frame renders the next-action block as a panel (not just status text), and no neutral-empty fact carries a warning glyph or warn severity — verified by a rendered-frame test
- running layout: while a work item runs the cockpit visibly changes state — a live status surface composes phase · step N/max · current operation · event-stamped elapsed; an Active-run block shows the goal, changes-so-far, and last action; the templates panel collapses; the idle suggestion is replaced, returning at finish
  - honesty: a test proves the running frame differs from the idle frame (templates hidden, Active-run present, status shows step N/max) and that the finish path restores the idle layout including a refreshed suggestion
- mutation ledger: mid-run counters (files touched, commands run) derived from progress-sink events, and a post-run session ledger sourced authoritatively from TaskResult.stats + the handoff outcome (commits, branch, PR), surviving into the idle cockpit as the last-run record
  - honesty: the post-run ledger equals TaskResult.stats verbatim (files_changed, per-tool counts) — mid-run counters are labeled as observed-so-far and never claim more than sink events prove (no fabricated commit counts)
- conversation/activity split: user and agent text render as a readable transcript while tool steps render as a separate auditable run-activity ledger — achieved colleague-side by composing around the imported reducer (keep reduce() for step_count/popups), never by duplicating it; tui replay/snapshot stay byte-unchanged
  - honesty: user/agent text and tool steps render in separate blocks in the live session, while agentfront's reducer, tui replay, and snapshot outputs stay byte-identical (the split composes around reduce(), it never re-implements it)
- /help regrouping: the SlashSpec catalog gains groups that map to the operator's mental model (runtime / workspace / git-publish / inspect / session), with the existing drift test still pinning that every dispatch verb appears
  - honesty: the existing /help drift test still passes with the new groups: every dispatch verb appears exactly once, and the popup + /help + slash panels all derive from the one SlashSpec catalog
- icons option: an icons=emoji|ascii|none setting applied to colleague-composed labels only (policy/context/capacity/ledger panel labels); the renderer-owned state glyph and popup icons stay upstream and are covered by a filed agentfront ask, not colleague code
  - honesty: with icons=ascii or none, no emoji from colleague-composed labels reaches the frame; the upstream state glyph is documented as out of colleague's control and the agentfront ask is actually filed before the spec claims it
- both live cockpits stay consistent: the session cockpit and the standalone 'colleague work --tui' cockpit share the new fold helpers (the fold_phase precedent) so running-state treatment cannot drift between them
  - honesty: the session _WorkSink and _tui_sink.CockpitProgressSink call the same shared helpers for phase folding, activity recording, and ledger counting — a test imports both and pins the shared code path
- every tier stays consistent for free: the new panels ride the generic panel walk so the flat-ANSI live view, the Markdown render, and the TAUI JSON mirror all carry them with zero per-renderer code, guarded by drift tests
  - honesty: no new code is added under any render path: the Markdown and TAUI-JSON tiers show the new panels purely via the generic walk, proven by asserting the mirror dict carries them

## Honesty conditions

- the announcement is provable from a captured snapshot pair: an idle frame and a mid-run frame from the same session render the claimed differences (distinct layouts, live status, ledger, disambiguated mode facts)
- both audiences are served by the same state: an operator's flat-ANSI frame and the agent-facing Markdown/TAUI mirror carry identical new facts (no TTY-only information)
- the before-state is evidenced in current main, not strawmanned: reduce() interleaves tool labels into conversation, _suggested_action persists during runs, the empty capacity signal carries a warning glyph, and 'mode' appears with three meanings across status/capacity surfaces
- at-a-glance answers derive only from real progress-sink events and TaskResult data — the cockpit never invents a phase, count, or activity it did not observe
- trust is earned by honest rendering: no label claims a gate, sandbox, or confirmation the harness does not enforce, and mutation counts never under-report what the sink observed
- the diff touches no agentfront source and adds no colleague-side renderer: colleague/tui keeps exactly its two surviving modules (from_work.py, render/driver.py) plus any new pure state/fold helpers — no module shadows an agentfront.taui module
- the acceptance criteria are executable as tests: running-frame ≠ idle-frame assertions, post-run ledger == TaskResult.stats, and the five #285 questions answerable from a single rendered frame in each state

## Success signals

- acceptance per #285: a user can tell at a glance whether the agent is waiting/reading/editing/running and what it has changed; a running frame is provably different from an idle frame (templates collapsed, Active-run block present) and the post-run ledger matches TaskResult.stats exactly

## Scope / boundaries

- colleague-side content changes only: panels, labels, statuses, status-line text, and panel visibility built over the imported agentfront.taui 0.20.0 generic panel walk — no TAUIState schema change, no renderer fork, no second ANSI path; genuine schema/renderer needs (state glyph, icons switch in the renderer, WorkItem max_steps/elapsed fields) become filed upstream agentfront asks, not colleague code (the #256/agentfront#48 precedent)

## Non-goals

- no ticking elapsed clock: the session is deliberately thread-free and the UI thread blocks inside the model completion, so elapsed/phase data is stamped at progress-sink event boundaries only — recorded honestly, never simulated
- no invented safety gates: the Run policy panel keeps honest labels — it must not claim a 'requires confirmation' escalation boundary that the harness does not enforce (the only real outward gate is push/PR off + approvals.json when present)

## Decisions

- issue #285's concrete layouts are a suggestion, not a contract: the user delegated design judgment, and deliberate adaptations (event-stamped elapsed, icons scoping, no invented confirmation gates) are recorded in the frame rather than silently applied

## Open / follow-up

- upstream agentfront asks to file: an icons=emoji|ascii|none switch + state-glyph vocabulary at the renderer level, and WorkItem schema fields (max_steps, started_at) so step N/max and elapsed become structural instead of status-text — colleague rides status text until then

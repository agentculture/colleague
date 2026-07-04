# Cockpit UX — a real coder-agent cockpit in both states (#285)

`colleague session`'s cockpit now reads like a real coder-agent cockpit in
**both** states. Idle, it answers five questions in order — **identity →
permissions → workspace → capacity → next action**. Running, it **visibly
changes the screen** — a live status line, an Active-run panel, collapsed
templates, and a mutation ledger — instead of looking the same as idle with a
spinning glyph. And the word "mode" stops meaning three things at once.

Spec + plan: `docs/specs/2026-07-03-colleague-s-cockpit-now-reads-like-a-real-coder-ag.md`
and `docs/plans/2026-07-03-colleague-s-cockpit-now-reads-like-a-real-coder-ag.md`.
Committed snapshot evidence: [`cockpit-ux/idle.md`](cockpit-ux/idle.md) and
[`cockpit-ux/running.md`](cockpit-ux/running.md).

## The before-state (what #285 fixed)

Pointers are to the pre-#285 code on `colleague/cli/_commands/session.py`:

- **The suggested next move was sticky status-text**, buried in the Session
  panel's `content_summary` (`_suggested_action` → `_with_suggestion`), not a
  first-class fact. An operator scanning the frame had to read prose to find
  "what now?".
- **Neutral facts wore warning styling.** The Capacity panel's signal row
  always carried the `⚠️` glyph, even when the value was the neutral `"none
  yet"` (`_capacity_panel`) — a warning where nothing was wrong.
- **"Mode" meant three things in one conflated line.** `_mode_profile_status`
  blurred the *behavior* mode (work/plan/explore/review), whether it was
  *auto-resolved or pinned*, and the *execution profile* (steps/timeout/budget)
  into a single string.
- **The Run policy panel risked over-claiming.** The issue text suggested a
  `requires confirmation: push, PR, external write…` line — a confirmation
  boundary the harness does **not** enforce.
- **The running state didn't visibly change the screen.** The work-templates
  panel stayed shown, there was no Active-run panel, and the status line didn't
  report live phase/step/current-op/elapsed or a mutation ledger — a long turn
  looked identical to idle.

## What it does now

### Idle — five questions, one frame

- **Next panel** (`_next_panel`, id `next`) — the safest/most-useful next move
  promoted from status-text into a first-class panel + item.
- **Run policy** (`_policy_panel`) — an aligned **`label · state · consequence`**
  grammar: `run_command · ungated · any shell command runs`;
  `file edits · read + write within repo · the loop can create/modify any repo
  file`; `push + PR · off · commits locally only — nothing leaves this machine`.
  Honest labels only (see the adaptations below).
- **Context** (`_context_panel`) — repo · branch · working-tree state · AGENTS
  layers · skills · telemetry · feedback.
- **Capacity** (`_capacity_panel`) — context budget + the **three distinct mode
  facts** (`colleague.session_modes.mode_facts`): behavior (`cap.mode`), source
  (auto vs pinned, on the same row), and execution profile (`cap.mode_profile`,
  a separate row) — plus a **neutral-empty** capacity signal (the `⚠` glyph
  only for a real warning).

### Running — the screen changes

`_dispatch_work` arms a run view before the loop and restores the idle layout
after (on the success **and** the error path):

- the **templates panel collapses** (`visible=False`);
- an **Active-run panel** (`_active_run_panel`, id `active_run`) replaces the
  idle Next block — goal · changes-so-far · last action, folded live from the
  sink events;
- the **status line** composes `phase · step N/max · current op · elapsed`
  (`colleague.cockpit_run.status_line`);
- on finish, a **Last-run ledger** panel (`_last_run_panel`, id `last_run`) is
  reconciled verbatim from `TaskResult.stats` + handoff (files · commands ·
  commits · publish state).

### The shared pure core

`colleague/cockpit_run.py` is a pure, deterministic, I/O-free, clock-free
run-state + ledger module (`fold` / `RunState` / `observed_ledger` / `reconcile`
/ `status_line`). **Both** live cockpits use it identically — the session's
`_WorkSink` and the standalone `colleague work --tui` `CockpitProgressSink`
(`colleague/cli/_commands/_tui_sink.py`) — so their running status lines agree
by construction. `colleague/icons.py` resolves an `emoji | ascii | none`
vocabulary applied to colleague-composed labels.

## Deliberate adaptations of the issue text (with rationale)

Each is an intentional, recorded departure — never a silent one:

- **No ticking elapsed clock.** The session is thread-free and the UI thread
  blocks inside the model completion, so `status_line`'s `elapsed_seconds` is
  **event-stamped at sink boundaries** (`_WorkSink._started` + a `time.monotonic`
  diff per step), never a clock thread. `cockpit_run` itself reads no clock.
- **No invented confirmation gates.** The issue's suggested `requires
  confirmation: push, PR, external write` line was **pushed back** — the harness
  enforces no such boundary. Policy labels claim only what is enforced: push/PR
  on/off, and the `approvals.json` checksum/token gate when a policy is present.
  The tool is never described as "sandboxed".
- **Mid-run ledger omits commits (parked v3 resolved).** Heuristic `git commit`
  detection from sink events is dishonest, so `observed_ledger` sets
  `commits=None` mid-run; only the post-run `reconcile(TaskResult)` shows
  commits, derived from the authoritative handoff record.
- **Icons scope is colleague-composed labels only.** `colleague/icons.py`
  switches the glyphs in labels colleague builds; the **renderer-owned** glyphs
  (moon-phase state animation, idle severity glyph, popup glyphs) live inside
  `agentfront.taui` and can't be switched consumer-side without forking (the
  #249 rule) — filed upstream as **agentfront#50**.
- **The #233 legible action feed is preserved.** The plan said "restore
  `state.conversation` after `reduce()`" to separate the transcript from the
  tool ledger. Taken literally that removed the `[tool] target` feed lines and
  regressed the shipped #233 ×N-collapse feed (caught by
  `tests/test_agent_native_e2e.py`). The resolution: **keep the tool feed in the
  conversation** (that IS #233) and deliver the "separate blocks" via the
  **structured Active-run + Last-run ledger panels** — a distinct block alongside
  the feed, not a removal of it.
- **Last-run ledger shipped; cumulative session totals parked (v4).** Idle shows
  the just-finished work item's authoritative ledger; per-session cumulative
  totals are a documented follow-up.

## Upstream boundary — filed, not forked

Colleague stays **consumer-side only** (no fork/shadow of an `agentfront.taui`
renderer — the #249 rule). Two renderer/schema needs are filed upstream and
referenced from the consuming code:

- **agentfront#50** — a renderer-level icon vocabulary switch (`emoji|ascii|none`)
  so the renderer-owned glyphs become switchable. Referenced in
  `colleague/icons.py`.
- **agentfront#51** — `WorkItem.max_steps` + `WorkItem.started_at` so
  `step N/max` and elapsed become structural (today caller-injected).
  Referenced in `colleague/cockpit_run.py` `status_line`.
- **agentfront#48** — the sibling ask (capacity/phase/goal on `TAUIState`),
  the #256 precedent.

## Honest limits

- The per-frame elapsed is event-stamped, so it advances only when a sink event
  fires — a long single completion shows the elapsed as of its last boundary,
  not a live-ticking second count (by design; see agentfront#51 for the
  structural start-stamp).
- The mid-run ledger counts observed sink events (a file appears once even if
  edited twice; `read_file` is not a change). The post-run `reconcile` is the
  authoritative record.
- A live-TTY visual pass (colours, alignment, wide/narrow terminals) on the real
  rig is a post-merge follow-up — automated frame tests pin content and
  structure, not aesthetics.

## Where it lives

| Piece | Module |
|-------|--------|
| Pure run-state + ledger | `colleague/cockpit_run.py` |
| Icons vocabulary | `colleague/icons.py` |
| Mode facts | `colleague/session_modes.py` (`mode_facts`, `mode_facts_fragment`) |
| Idle layout + running switch | `colleague/cli/_commands/session.py` |
| `work --tui` running state | `colleague/cli/_commands/_tui_sink.py` (`CockpitProgressSink`) |
| Executable acceptance proof | `tests/test_cockpit_ux_285.py` |
| Structural boundary proofs | `tests/test_boundary.py` |
| Snapshot evidence | `docs/features/cockpit-ux/{idle,running}.md` |

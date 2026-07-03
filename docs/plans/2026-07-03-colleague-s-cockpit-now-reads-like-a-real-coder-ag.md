# Build Plan — colleague's cockpit now reads like a real coder-agent cockpit in both states: idle answers identity → permissions → workspace → capacity → next action, and a running work item visibly changes the screen — live phase, step progress, current operation, and a mutation ledger (files changed · commands run · commits · publish state) — while mode language is unambiguous (behavior mode vs auto resolution vs execution profile).

slug: `colleague-s-cockpit-now-reads-like-a-real-coder-ag` · status: `exported` · from frame: `colleague-s-cockpit-now-reads-like-a-real-coder-ag`

> colleague's cockpit now reads like a real coder-agent cockpit in both states: idle answers identity → permissions → workspace → capacity → next action, and a running work item visibly changes the screen — live phase, step progress, current operation, and a mutation ledger (files changed · commands run · commits · publish state) — while mode language is unambiguous (behavior mode vs auto resolution vs execution profile).

## Tasks

### t1 — t1 Pure run-state + ledger module (colleague/cockpit_run.py): fold (tool, target, ok) sink events into an activity list (capped), files-touched set, command count, last action, phase text, and a status composer 'phase · step N/max · current op · elapsed' with caller-injected timestamps (event-stamped, never a clock thread); post-run reconcile(TaskResult) returns the authoritative ledger from stats + handoff; mid-run ledger deliberately OMITS commits (resolves parked v3 — heuristic git-commit detection is dishonest, only the post-run handoff record shows commits)

- covers: c4, h14, c13, h4
- acceptance:
  - pure and deterministic: no I/O, no threads, no clock reads inside fold functions (timestamps injected); unit-tested
  - reconcile(result) equals TaskResult.stats verbatim for files_changed and per-tool counts; mid-run counters labeled observed-so-far; commits absent from the mid-run ledger
  - not under colleague/tui/ (keeps the #249 two-survivors boundary test intact); imports nothing from agentfront render paths

### t2 — t2 Icons vocabulary module (colleague/icons.py): icons=emoji|ascii|none resolved flag > COLLEAGUE_ICONS env > .colleague/config.json > default emoji; a mapping applied to colleague-composed panel labels at build time (policy/context/capacity/mode/ledger/activity)

- covers: c16
- acceptance:
  - with ascii or none resolved, no emoji appears in any colleague-composed label (regex-asserted over built panels); default emoji is byte-identical to today
  - resolution follows the existing EngineConfig precedence conventions and is a strict no-op when unset

### t3 — t3 Mode-facts helpers (extend colleague/session_modes.py, pure): compose the three distinct facts — behavior (active mode), source (auto-classified vs pinned), execution profile (steps/timeout/budget/fill-line from profiles.resolve_profile) — as structured rows + a status-line fragment; drift-tested against MODES and MODE_PROFILES so no second vocabulary exists

- covers: c10, h1
- acceptance:
  - rows/fragment derive only from session_modes.MODES + profiles.MODE_PROFILES; a drift test fails if a mode is added to either catalog without the facts covering it
  - auto renders as source=auto with the resolved-per-input explanation; a pinned mode renders source=pinned

### t5 — File the upstream agentfront asks and record the boundary: one issue for a renderer-level icons/state-glyph switch (emoji|ascii|none incl. moon-phase frames + popup glyphs), one for WorkItem schema fields (max_steps, started_at) so step N/max + elapsed become structural; link both from code comments at the consuming sites

- covers: h7
- acceptance:
  - both issues exist on agentculture/agentfront with reproduction/context and are referenced by URL in colleague code comments + the feature doc
  - colleague ships no workaround that forks or shadows an agentfront renderer meanwhile

### t6 — session.py idle-layout rework (hot-file chain 1/3): consume the mode-facts helpers for disambiguated mode rows; retitle 'Work templates' to suggested work; promote the Safest-next line into a first-class Next panel (id + items, not status text); restructure Run policy items into the aligned label · state · consequence grammar with honest wording only (no invented confirmation gates); neutral-empty capacity signal (no warning glyph/severity for none-yet); apply the icons vocabulary to all composed labels

- depends on: t2, t3
- covers: c11, h2, c5, h15
- acceptance:
  - idle frame renders the Next block as a panel and the disambiguated mode facts; asserted by a rendered-frame test (flat ANSI) plus the mirror dict
  - no neutral-empty fact carries a warning glyph or warn severity; policy labels claim only enforced gates (push/PR, approvals.json when present)
  - existing session tests stay green; --json and non-TTY paths byte-identical except the reworded panels

### t7 — session.py running-state switch (hot-file chain 2/3): _dispatch_work arms a run view built on the pure run-state module — Active-run panel (goal, changes-so-far from fold events, last action), templates panel collapses (visible=False), idle suggestion replaced; _WorkSink folds real steps into the run-activity surface and restores state.conversation after reduce() so transcript and tool ledger render as separate blocks; status line composes phase · step N/max · current op · event-stamped elapsed; finish restores the idle layout with a refreshed suggestion and a last-run ledger panel reconciled from TaskResult.stats + handoff (idle shows the last-run record; cumulative session totals parked as follow-up — resolves parked v4)

- depends on: t1, t6
- covers: c12, h3, c14, c13
- acceptance:
  - a test proves running frame differs from idle (templates hidden, Active-run present, status shows step N/max) and finish restores idle incl. refreshed suggestion
  - user/agent text and tool steps render in separate blocks; reduce() is composed around, never re-implemented (step_count/popups still advance through it)
  - post-run ledger equals TaskResult.stats verbatim; the #206 invariant holds (phase notices never advance step_count or add feed lines)

### t8 — _tui_sink.py: CockpitProgressSink adopts the same shared run-state helpers (activity fold, ledger counting, status composition) so the standalone 'colleague work --tui' cockpit gets the identical running-state treatment; tui replay/snapshot and the events sink stay byte-unchanged

- depends on: t1
- covers: c17, h8
- acceptance:
  - a test imports both _WorkSink and CockpitProgressSink and pins they call the shared helpers (no duplicated fold logic)
  - tui replay, tui snapshot, and the JSONL events stream are byte-identical to before (step-only, no phase/activity leakage)

### t9 — session.py /help regrouping (hot-file chain 3/3): SlashSpec groups become runtime / workspace / git-publish / inspect / session (engine+model+mode → runtime; base+attach+learn-from → workspace; pr → git-publish); SLASH_GROUPS ordering + /help + popup + slash panels all still derive from the one catalog

- depends on: t7
- covers: c15, h6
- acceptance:
  - the /help drift test still passes: every dispatch verb appears exactly once under exactly one group; /pr renders under a publish-boundary heading
  - help verbose/compact and the autocomplete popup honor the new groups with no second catalog introduced

### t10 — Proof suite + captured snapshots: assert the mirror dict and Markdown tier carry every new panel (zero per-renderer code); capture an idle + mid-run snapshot pair via the existing snapshot machinery as the announcement evidence; extend the #249 boundary test so new pure modules never shadow agentfront.taui and no agentfront source is touched; pin replay/snapshot byte-identity for the conversation/activity split; make the #285 acceptance executable (five questions answerable from one rendered frame per state)

- depends on: t7, t8, t9
- covers: c1, h11, c2, h12, c6, h10, c9, h16, c18, h9, h5
- acceptance:
  - tests assert new panels appear in the TAUI mirror + Markdown render via the generic walk only; running-frame vs idle-frame assertions pass
  - an idle and a mid-run snapshot pair is committed (or generated in-test) showing distinct layouts, live status, ledger, and disambiguated mode facts
  - boundary tests prove no colleague module shadows agentfront.taui and colleague/tui keeps only its two survivors + none of the new helpers

### t11 — Docs + release: feature doc docs/features/cockpit-ux.md recording the before-state evidence (interleaved feed, sticky suggestion, warning-styled neutral facts, triple mode meaning), the adaptations from issue #285 (event-stamped elapsed, icons scoping, omitted mid-run commits, no invented gates), and the upstream-boundary asks; CLAUDE.md architecture bullet; CHANGELOG + version bump

- depends on: t10
- covers: c3, h13
- acceptance:
  - feature doc names the before-state with pointers to pre-change code and lists every deliberate adaptation from the issue text with its rationale
  - CLAUDE.md bullet + CHANGELOG entry land; version bumped per the version-check CI gate

## Risks

- [unknown_nonblocking] final wording and visual grammar of each label/block settled at implementation against rendered frames (spec v2)
- [follow_up] cumulative session totals (vs the shipped last-run ledger record) parked as a follow-up (spec v4 resolved to last-run in t7)
- [unknown_nonblocking] a live-TTY visual pass on the real rig (colours, alignment, wide/narrow terminals) after merge — automated frame tests cannot judge aesthetics

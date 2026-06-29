# Build Plan — Colleague renders its cockpit from agentfront's TAUI instead of a hand-rolled colleague/tui — and agentfront's TAUI grew the work-loop richness (animated work-steps, conversation folding, the snapshot/diagnose/replay quad) that made colleague's worth keeping

slug: `colleague-renders-its-cockpit-from-agentfront-s-ta` · status: `exported` · from frame: `colleague-renders-its-cockpit-from-agentfront-s-ta`

> Colleague renders its cockpit from agentfront's TAUI instead of a hand-rolled colleague/tui — and agentfront's TAUI grew the work-loop richness (animated work-steps, conversation folding, the snapshot/diagnose/replay quad) that made colleague's worth keeping

## Tasks

### t1 — Pin the agentfront floor to the release closing agentfront#43 and verify the uplift landed

- covers: c2, c3, c8, c10, c12, c15, h5, h8, h9
- acceptance:
  - pyproject.toml pins agentfront to the release that closes agentfront#43, with a comment naming the issue
  - a new test imports agentfront.taui and asserts SCHEMA_VERSION equals 0.2, the Background field and WorkStep and SkillSuggested events are present, and snapshot, replay and the structured diagnose are importable
  - test_zero_deps still passes (agentfront is the only base dep) and agentfront's 12 parity smoke tests are re-verified as closed

### t2 — Re-point the from_work adapter to agentfront.taui WorkStep events

- depends on: t1
- covers: c14
- acceptance:
  - colleague/tui/from_work.py imports WorkStep and event types from agentfront.taui and emits agentfront WorkStep events; progress_target and trace_to_work_steps keep identical behavior (existing from_work tests stay green)

### t3 — Re-point cockpit.py domain panels to agentfront.taui Panel/PanelItem

- depends on: t1
- covers: c14
- acceptance:
  - colleague/cockpit.py builds the repo-context and run-policy panels using agentfront.taui Panel and PanelItem; build_repo_context_panel output is unchanged

### t4 — Re-wire the tui CLI verbs to agentfront.taui (verb surface unchanged)

- depends on: t1
- covers: c6, c11
- acceptance:
  - every colleague tui verb (state, render, inspect, action, replay, snapshot, test, diagnose, overview, live) dispatches to agentfront.taui; verb names, flags and exit codes are unchanged (a CLI surface test pins it)

### t5 — Re-wire the work-loop progress sink to agentfront.taui

- depends on: t1
- covers: c11
- acceptance:
  - CockpitProgressSink and FrameWriter fold agentfront.taui WorkStep events and render through agentfront renderers; the per-step live rendering is observably unchanged

### t6 — Re-wire the session cockpit and rewrite in-place mutations to functional frozen updates

- depends on: t1
- covers: c9, h2
- acceptance:
  - colleague/cli/_commands/session.py updates state via agentfront frozen dataclasses using dataclasses.replace, with no in-place mutation of state.mode or sess.state
  - the session test suite stays green and the cockpit behavior (mode display, work-step feed, slash panels) is observably unchanged

### t7 — Delete the duplicated generic colleague/tui modules and add the no-import boundary test

- depends on: t2, t3, t4, t5, t6
- covers: c4, h10, c11, h4, h14
- acceptance:
  - the generic colleague/tui modules (state, events, taui, reducer, replay, snapshot, diagnose, selectors, colors, render/*, widgets/*) are deleted; only the from_work adapter remains under colleague/tui
  - a boundary test asserts no colleague module imports colleague.tui.* except the adapter, which imports agentfront.taui for all generic behavior

### t8 — Golden-file, faithfulness, and suite-green proof of identical rendering

- depends on: t7
- covers: c1, c5, c7, h1, h3, h4, h7, h11, h12, h13, h15
- acceptance:
  - golden-file tests assert colleague tui state, render, snapshot, diagnose and replay produce byte-identical output to a captured pre-migration baseline
  - tui diagnose JSON-to-Markdown faithfulness passes; the full tui and session suites are green; reducer behavior (step_count increment, conversation folding, moon-phase animation) reproduces identically through agentfront

### t9 — Docs, version bump, and zero-vendored-source check

- depends on: t7
- covers: c16, h16
- acceptance:
  - CLAUDE.md Cockpit views section and a feature doc describe the cockpit rendering from agentfront.taui; a CHANGELOG entry and a version bump are added
  - no agentfront TAUI source is vendored into colleague — the dependency is the released agentfront package only (the PR touches only colleague files)

## Risks

- [follow_up] Execution is gated on agentfront shipping the release that closes agentfront#43 (the 12-gap uplift); build waves must not start until t1 can pin a real release
- [unknown_nonblocking] agentfront frozen dataclasses on the hot session render path — measure dataclasses.replace churn if the session cockpit feels slow (task t6)
- [unknown_nonblocking] colleague must verify agentfront's moon-phase animation and conversation collapse-repeat folding reproduce colleague's exact sequences (full uplift moved them up); a golden test pins it (task t8)

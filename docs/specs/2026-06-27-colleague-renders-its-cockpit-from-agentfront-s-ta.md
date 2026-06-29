# Colleague renders its cockpit from agentfront's TAUI instead of a hand-rolled colleague/tui — and agentfront's TAUI grew the work-loop richness (animated work-steps, conversation folding, the snapshot/diagnose/replay quad) that made colleague's worth keeping

> Colleague renders its cockpit from agentfront's TAUI instead of a hand-rolled colleague/tui — and agentfront's TAUI grew the work-loop richness (animated work-steps, conversation folding, the snapshot/diagnose/replay quad) that made colleague's worth keeping

## Audience

- agentfront (the library plus its future TAUI consumers) and colleague as the first consumer; the agents and operators who watch colleague live cockpit

## Before → After

- Before: colleague hand-maintains a complete v0.2 colleague/tui (Background animation, WorkStep and SkillSuggested events, a 7-class diagnose, the snapshot quad, replay, the from_work loop bridge); agentfront ships a v0.1 baseline TAUI (registry-derived, frozen, 4-check diagnose, Tick and UserInput as no-ops). The two are parallel implementations that will drift — the 12 documented parity gaps are the drift surface
- After: colleague cockpit tiers (TAUI JSON, ANSI, Markdown, the snapshot quad, diagnose, replay, the live session cockpit) all render from agentfront.taui; the duplicated generic plumbing is deleted from colleague/tui; colleague keeps only a thin domain adapter (the work-loop bridge plus its repo-context and run-policy panels); agentfront TAUI absorbed the generic work-loop richness it lacked

## Why it matters

- import, do not duplicate — one TAUI standard across the org instead of a colleague-private fork; colleague pioneering richness becomes a reusable agentfront capability every future consumer gets for free; the 12 parity gaps stop being a drift liability

## Requirements

- agentfront.taui grows the generic work-loop richness colleague needs: a Background field (theme/animation/frame/semantic), WorkStep and SkillSuggested events, and a reducer that advances animation on Tick and appends to a conversation panel on UserInput (closing parity gaps 1, 3, 4, 10) — all stdlib-only and frozen-or-pure
  - honesty: every new agentfront.taui field/event stays stdlib-only; agentfront test_taui_no_dep stays green; colleague existing reducer behavior (step_count increment on a work step, conversation folding, moon-phase animation) reproduces identically through the imported reducer or the thin adapter
- frozen-vs-mutable is reconciled (gap 11): agentfront keeps frozen=True dataclasses and colleague rewrites its in-place CockpitState mutations to functional updates (dataclasses.replace), so one immutable state model serves both
  - honesty: colleague session cockpit, which mutates CockpitState in place today (self.state.mode assignment, sess.state reduce reassignment, _refresh_status), is rewritten to functional updates with no observable behavior change; the session test suite stays green
- schema versions align (gap 9): agentfront SCHEMA_VERSION advances to 0.2 as it absorbs the richer fields, so a single TAUI mirror shape serves agentfront and colleague
  - honesty: a TAUI mirror produced by agentfront round-trips through colleague consumers and back; colleague tui diagnose JSON-to-Markdown faithfulness still passes; no consumer asserts the old 0.2-only or 0.1-only version in a way that breaks
- colleague imports agentfront.taui and deletes the duplicated generic modules; the colleague tui CLI verbs and the session cockpit re-wire to the imported package; resolve() signature, zone resolution, and available_actions composition are reconciled (gaps 5, 6, 8, 12)
  - honesty: after deletion no colleague module imports colleague.tui.* (a boundary/grep test enforces it); the colleague tui state/render/snapshot/diagnose/replay verbs produce byte-identical output to today (a golden-file test pins it); the zero-deps allow-list test still passes (agentfront only, no second base dep)
- the migration is gated on an agentfront release that closes the gaps (an upstream agentfront issue, the analog of agentfront#38); colleague bumps its agentfront floor and the parity test flips from gaps-documented to gaps-closed and stays green
  - honesty: colleague does not migrate before the agentfront release ships; the agentfront floor bump is recorded in pyproject.toml with a comment naming the gap-closing issue; agentfront test_taui_colleague_parity flips to assert gaps closed and stays green in CI
- Under full uplift the colleague adapter shrinks to only the genuinely TaskResult-coupled bits: the from_work tool-loop bridge mapping colleague steps to agentfront WorkStep events, plus the repo-context and run-policy domain panels. Generic concepts (moon-phase work animation, conversation collapse-repeat folding) move UP into agentfront, not the adapter
  - honesty: the colleague adapter contains no rendering, state, reducer, mirror, diagnose, snapshot, or replay code — only TaskResult-to-event mapping and domain-panel construction; a boundary test proves the adapter imports agentfront.taui for all generic behavior
- agentfront upstreams the snapshot quad (taui.json/ansi/events.jsonl/md), replay, and the 7-class structured diagnose as generic agentfront surfaces (closing gap 7 plus adding the quad), so colleague deletes its copies rather than keeping them — agentfront-side work
  - honesty: agentfront snapshot/replay/diagnose are generic (not colleague-named) and stdlib-only; colleague tui snapshot/diagnose/replay verbs produce byte-identical output through the imported surfaces (a golden-file test pins it)
- Division of labor: the agentfront-side uplift (richer state/events/reducer, schema 0.2, snapshot/replay/7-class diagnose) is delivered BY agentfront, handed over via a /communicate brief filed as a tracked agentfront issue; colleague implements ONLY the consumer side (import, delete duplicated source, re-wire tui verbs and session cockpit, bump the floor, flip the parity test) and its PR touches no agentfront source
  - honesty: the colleague PR diff contains zero agentfront source changes; the agentfront work is tracked in a separate agentfront issue created via the communicate skill; colleague CI does not depend on unreleased agentfront code (migration waits for the agentfront release that closes the gaps)

## Honesty conditions

- after migration colleague cockpit renders from agentfront.taui with no regression a user notices — the live session cockpit, the ANSI frame, the Markdown view, and the JSON mirror all still work
- the new agentfront fields/events are generic and not colleague-named, so a second agentfront app could consume the same TAUI richness — reuse is real, not aspirational
- the 12 parity gaps are re-verified against agentfront test_taui_colleague_parity at migration time (agentfront TAUI may evolve), so the divergence inventory is current, not stale
- no duplicated generic TAUI plumbing remains in colleague after migration; what stays in colleague/tui is only the domain adapter, proven by a no-duplication check
- the agentfront-side richness is exercised by colleague AND covered by agentfront own tests, so the shared capability cannot silently rot
- the migration adds no third-party dep to either repo and does not change the documented tui verb surface; stdlib-only boundary tests stay green on both sides
- each success signal is measurable and tested — green suites, a parity-test flip, a deleted-source LOC delta, an aligned schema version — not asserted by vibe

## Success signals

- colleague existing tui and session test suites stay green against the imported package; a parity test proves colleague cockpit renders identically pre and post migration; the duplicated colleague/tui generic source is deleted (a net-LOC win, unlike cli-on-agentfront transitional plus-LOC); agentfront TAUI schema advances and the 12 parity gaps close (the parity test flips)

## Scope / boundaries

- Not a production live-TTY framework (stdlib-only stays — no curses, textual, rich); not a second base dep; not a change to the agent-facing TAUI JSON contract faithfulness; colleague domain cockpit content (repo-context and run-policy panels) stays colleague-owned; the colleague tui verb surface (state/render/snapshot/diagnose/replay/live) keeps its observable contract

## Non-goals

- colleague implementing the agentfront-side TAUI uplift itself is out of scope; that work is delegated upstream to agentfront via /communicate

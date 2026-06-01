# convertible tui renders the cockpit as Markdown — a third view beside the JSON mirror and the live screen — and a cross-mirror check proves the Markdown and the JSON never disagree

> convertible tui renders the cockpit as Markdown — a third view beside the JSON mirror and the live screen — and a cross-mirror check proves the Markdown and the JSON never disagree

## Audience

- Agents and humans who need to read a convertible drive's cockpit state OUTSIDE a live terminal — pasted into a PR, a log, a doc, or a chat — plus the test suite that guards rendering.

## Before → After

- Before: Today tui offers only the JSON mirror (machine-readable, not skimmable) and the ANSI live screen (needs a real TTY, full of escape codes). There is no portable, human-skimmable, paste-anywhere rendering, and nothing verifies a render faithfully reflects the mirror except the ANSI-only RENDER detector inside diagnose.
- After: From any CockpitState/TAUI snapshot you can produce a readable Markdown view of the cockpit, and a cross-mirror check flags any place the Markdown and the JSON mirror disagree (zero findings when they're faithful).

## Why it matters

- The whole TAUI premise is that every view derives from one CockpitState and therefore cannot drift. A Markdown view extends that guarantee to the format humans actually skim, and an explicit JSON<->Markdown alignment check turns 'cannot drift' from a design claim into a tested invariant.
- For an AGENT, Markdown is a better readable view of the cockpit than raw JSON — the agent's equivalent of a human glancing at the live screen. JSON stays the programmatic/script contract AND the source of truth the Markdown is checked against. Markdown = agent-facing live-equivalent read; JSON = for scripts.

## Honesty conditions

- Markdown and ANSI render from the SAME CockpitState through one render entry point; generalizing diagnose's RENDER detector to Markdown changes NO ANSI behavior (existing diagnose tests stay green).
- The Markdown view is reachable HEADLESSLY (no TTY): 'tui render --format markdown --state <file>' prints Markdown to stdout — so a PR/log/doc/chat consumer and the test suite all produce it the same way.
- 'tui render --format markdown' produces Markdown from any loaded CockpitState/TAUI snapshot, and 'tui diagnose' returns a non-empty finding set IFF the Markdown disagrees with the mirror, empty IFF faithful.
- Verifiable by inspection of main@HEAD: no convertible command emits Markdown, and diagnose's signature takes only (taui, ansi, events) — its RENDER detector inspects the ANSI frame only.
- Markdown and JSON are both pure functions of the same CockpitState (no independent data source), so any disagreement diagnose reports is a render-fidelity bug, never a data-source divergence.
- There is a round-trip test (render one fixture state to JSON + Markdown, run diagnose, assert zero findings) AND a mutation test (a Markdown frame missing a visible popup's message yields a RENDER finding).
- The Markdown render is structured for reading (headings/sections/lists that mirror the cockpit zones), and it contains every fact the JSON mirror marks visible — so an agent reading ONLY the Markdown misses nothing the JSON would have told it.
- No code path accepts Markdown as input to build a CockpitState: the markdown render signature is state->str only, and there is no markdown loader anywhere in the tui package.

## Success signals

- Rendering the same state to JSON and to Markdown and running the alignment check yields zero findings; a deliberately broken Markdown render (drops a visible popup) is caught with a clear finding; the new path is offered identically for every engine (chassis-owned).

## Scope / boundaries

- Render is strictly one-way: state -> Markdown only. convertible never parses Markdown back into a CockpitState.

## Non-goals

- No live/interactive Markdown TTY driver. Markdown is produced from a state SNAPSHOT exactly like 'tui render' does for ANSI; 'tui live' stays ANSI.
- Markdown is additive — the ANSI frame and the JSON mirror are unchanged; nothing is replaced or removed.

## Assumptions

- The Markdown renderer is stdlib-only — no [tui] extra, no new runtime dependency (consistent with convertible's zero-deps rule). The [tui] extra remains only for the live interactive driver.

## Decisions

- Surface: 'tui render --format ansi|markdown' (ansi default). Markdown is a render target of the existing render verb, not a new verb; --json still wraps the chosen format.
- Alignment: GENERALIZE diagnose so its RENDER faithfulness detector runs against the Markdown frame too. The snapshot triple (taui/ansi/events) gains an optional markdown member (-> quad). No new differ engine; reuse the 7-bug-class model.

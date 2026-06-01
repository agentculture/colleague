# Build Plan — convertible tui renders the cockpit as Markdown — a third view beside the JSON mirror and the live screen — and a cross-mirror check proves the Markdown and the JSON never disagree

slug: `convertible-tui-renders-the-cockpit-as-markdown-a` · status: `exported` · from frame: `convertible-tui-renders-the-cockpit-as-markdown-a`

> convertible tui renders the cockpit as Markdown — a third view beside the JSON mirror and the live screen — and a cross-mirror check proves the Markdown and the JSON never disagree

## Tasks

### t1 — Markdown renderer: add convertible/tui/render/markdown.py with render_markdown(state)->str — pure stdlib, structured headings/sections/lists mirroring the cockpit zones (status, skills, conversation, prompt, popups), reading-complete vs the TAUI mirror

- covers: c1, c3, c7, c8, h3, h4
- acceptance:
  - render_markdown(state) returns a Markdown string for any CockpitState; the only signature is state->str — there is no markdown loader/parse path anywhere in the tui package
  - Every popup/panel/status/drive fact the TAUI mirror marks visible appears in the Markdown output (reading-complete vs the mirror); render is pure and deterministic (same state -> same Markdown), stdlib-only

### t2 — Snapshot quad: extend convertible/tui/snapshot.py so Snapshot carries a markdown field, write_snapshot writes a 4th file name.md = render_markdown(state), and read_snapshot populates it; legacy triples without a .md read gracefully

- depends on: t1
- covers: c3
- acceptance:
  - write_snapshot writes name.md = render_markdown(state) and read_snapshot round-trips Snapshot.markdown == render_markdown(state); reading a legacy triple with no .md does not crash

### t3 — Generalize diagnose: convertible/tui/diagnose.py diagnose() gains an optional markdown frame; the RENDER faithfulness check runs against it (visible popup message/title absent from Markdown -> RENDER finding); diagnose_snapshot forwards Snapshot.markdown; ANSI behavior unchanged when markdown is absent

- depends on: t1, t2
- covers: c5, c6, h1, h2, h6, h8
- acceptance:
  - With no markdown argument, diagnose output is identical to pre-change behavior and all existing test_tui_diagnose tests pass (no ANSI regression)
  - Round-trip test: render one fixture state to taui+ansi+markdown, run diagnose, assert zero findings. Mutation test: a Markdown frame with a visible popup message removed yields a RENDER finding
  - diagnose_snapshot forwards Snapshot.markdown so tui diagnose --dir/--name checks the quad; diagnose returns a non-empty finding set IFF the Markdown disagrees with the mirror, empty IFF faithful

### t4 — CLI tui render --format: convertible/cli/_commands/tui.py render verb gains --format ansi|markdown (ansi default), dispatching to render or render_markdown; --json wraps the chosen format; the Markdown view is reachable headlessly with no TTY

- depends on: t1
- covers: c2, h5
- acceptance:
  - tui render --state f --format markdown prints Markdown to stdout with no TTY; default and --format ansi print the unchanged ANSI frame; an invalid --format value raises CliError with no traceback
  - tui render --format markdown --json emits a JSON object wrapping the markdown string (parallel to the ansi --json shape)

### t5 — Docs and explain: update convertible/explain/catalog.py _TUI entry for --format and the JSON/Markdown alignment via diagnose, add a CHANGELOG.md entry, and note Markdown as the third cockpit view in CLAUDE.md

- depends on: t3, t4
- covers: c4, h7
- acceptance:
  - convertible explain tui render documents --format ansi|markdown and the alignment-via-diagnose story; CHANGELOG and CLAUDE.md describe Markdown as the third view and the accurate ANSI-only before-state
  - Docs state the before-state accurately (h7): pre-change no convertible command emitted Markdown and diagnose inspected the ANSI frame only

## Risks

- [follow_up] Explicit 'tui diagnose --markdown <file>' for non-snapshot alignment checks is deferred; v0 surfaces the JSON<->Markdown check via snapshot-dir mode (tui diagnose --dir/--name) + diagnose_snapshot reading the quad's .md
- [unknown_nonblocking] Legacy snapshots written before the quad have no .md file; read_snapshot must default markdown gracefully (documented), not raise (task t2)
- [follow_up] Version bump + PR creation is the main-agent integration step after the waves merge (per repo convention + version-check CI), not a fanned-out task

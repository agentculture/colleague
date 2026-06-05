# TUI / TAUI: the agent-readable cockpit mirror

> A pure-reducer, stdlib-only cockpit UI whose semantic state is a JSON mirror
> an agent reads directly — no screen-scraping, no LLM, no network.

TAUI (**Textual Agentic UI**) is the **semantic mirror** of the live cockpit
state. Where a human reads the rendered screen, an agent reads the TAUI JSON —
a serialised, stable, selector-addressed tree that captures exactly what is
visible, what actions are available, and what the model just said. The design
goal: an agent can fully understand and drive the UI from the TAUI alone,
without a screen reader, without an LLM call, and without any `colleague`
import on the reader's side.

## Architecture: pure reducer

The TUI is a **pure-reducer pipeline** — no global state, no I/O inside the
core:

```text
Event  →  reduce(state, event)  →  CockpitState  →  serialize()  =  TAUI JSON
                                                  →  render()     =  ANSI string
```

Every component in the pipeline is a pure function (same input → same output).
The reducer (`colleague/tui/reducer.py`) never reads the clock, opens a file,
or calls the model. State changes only through events.

### Events

Events are a discriminated union (`colleague/tui/events.py`) covering user
interaction (`UserInput`, `Key`), model progress (`DriveStep`), UI lifecycle
(`Tick`, `Dismiss`), and suggestions (`SkillSuggested`). Each event carries a
string `type` discriminator and round-trips through JSON cleanly — the JSONL
event log is a full replay record.

### State

`CockpitState` (`colleague/tui/state.py`) is a plain `dataclasses` tree:
status bar, skills panel, conversation panel, prompt input, popup overlay, and
background spinner state. Every field has a default; a fresh state is always
valid. `state.to_dict()` / `CockpitState.from_dict()` round-trip losslessly
through `json.dumps` — same convention as `colleague.contract`.

## The TAUI mirror

`colleague/tui/taui.py` produces the agent-readable dict from a
`CockpitState`. Key invariants:

- Every popup and panel carries a stable `id`.
- Every action carries a **selector** — a dotted path into the UI tree
  (`"popup.confirm.button.ok"`). Selectors are *derived from* the same state,
  so they cannot drift from the actual tree.
- `available_actions` is the flat, agent-readable "what can I do right now?"
  list: all visible-popup actions plus the standing prompt input entry.
- `taui_version` is always present and pinned to a schema constant.
- `json.dumps(serialize(state))` always succeeds on a valid `CockpitState`.

## Dotted-path selectors

`colleague/tui/selectors.py` walks the TAUI mirror and exposes:

- `selectors(mirror)` — every addressable dotted path in the tree.
- `resolve(mirror, selector)` — the node (dict or scalar) at a path, or
  `SelectorError` if absent.
- `selector_to_event(mirror, selector)` — the `Event` that clicking/choosing a
  selector would fire.

Selectors are derived from the tree, not from a separate registry — renaming a
node changes its selector automatically.

## Snapshot triple

`colleague/tui/snapshot.py` captures a complete TUI moment as three
complementary files written to a caller-supplied directory:

| File | Contents |
|------|----------|
| `<name>.taui.json` | The semantic mirror — agent-readable dict. |
| `<name>.ansi` | The visual frame — ANSI-coloured string. |
| `<name>.events.jsonl` | The event trail — one JSON event per line. |

The three files are self-sufficient: a debugger or agent can reconstruct what
the UI looked like, what the model saw, and what happened — without a live
process or any additional context.

```python
from colleague.tui.snapshot import write_snapshot, read_snapshot

paths = write_snapshot(directory, "bug-x", state, events)
snap  = read_snapshot(directory, "bug-x")
# snap.taui   == serialize(state)
# snap.ansi   == render(state)
# snap.events == original event objects
```

Scenarios (the structured test inputs) are stored as JSON, not YAML — PyYAML
would break the zero-deps guard.

## Deterministic replay

`colleague/tui/replay.py` folds a list of events through the pure reducer,
starting from an initial state (or a fresh `CockpitState` when `None`):

```python
from colleague.tui.replay import replay, replay_from_jsonl

final_state = replay(events)
final_state = replay_from_jsonl(jsonl_text)   # parse + fold in one call
```

Because the reducer is pure, replaying the same event log always produces the
same final state — useful for regression tests and offline debugging.

## Diagnose: 7-bug-class cross-mirror differ

`colleague/tui/diagnose.py` classifies disagreements between the three views
of a snapshot — **without any LLM, model, or network call**:

| Bug class | What it means |
|-----------|---------------|
| `STATE` | An event occurred but the TAUI mirror never updated. |
| `RENDER` | The mirror is correct but the ANSI frame is wrong or missing. |
| `LAYOUT` | A node exists and is visible, but its owning zone is hidden. |
| `FOCUS` | `taui.focused` names a selector that does not resolve in the tree. |
| `INPUT_ROUTING` | A `Key` event was dispatched but no widget handled it. |
| `ACTION_DRIFT` | An action selector in `available_actions` does not resolve. |
| `SCHEMA` | A required TAUI field (`taui_version`, `available_actions`, …) is absent. |

The disagreement is *derivable* from the captured state alone — no live process
needed.

## Headless subcommands

The TUI feature exposes headless CLI subcommands under `colleague tui` for
scripted and agent use (no TTY required):

| Subcommand | What it does |
|-----------|--------------|
| `tui render <snapshot>` | Re-render a snapshot's state to ANSI (stdout). |
| `tui replay <events.jsonl>` | Fold an events log and emit the final TAUI JSON. |
| `tui replay --trace <id>.trace.jsonl` | Fold a real drive's loop-step trace (#74 A4). |
| `tui diagnose <snapshot>` | Run the 7-bug-class differ and report findings. |
| `tui selectors <snapshot>` | List every addressable selector in the TAUI mirror. |

All subcommands support `--json`; failures raise `CliError` (no tracebacks leak)
— standard agent-first CLI conventions.

## Renderer-is-a-plugin

The TUI renderer follows the same extension seam as backends:

```toml
[project.entry-points."colleague.renderers"]
ansi = "colleague.tui.render.ansi:render"
```

An external package that installs a `colleague.renderers` entry-point
(e.g. `rich = "mypackage.render_rich:render"`) will be discovered at runtime
without any core change — the same mechanism `colleague backends list` uses for
backends.

The built-in `ansi` renderer (`colleague/tui/render.ansi`) is **hand-rolled
ANSI SGR** — no third-party rendering library, no network, no subprocess. It
works out of the box with zero extras installed.

Rich and Textual are an **opt-in `[tui]` extra** for future richer renderer
plugins. They are never base dependencies:

```bash
pip install 'colleague[tui]'     # or: uv sync --extra tui
```

Installing the extra does not activate the richer renderer automatically — it
only makes the packages available for an external renderer plugin that declares
them. The `ansi` renderer remains the built-in default regardless.

## Zero-deps guarantee

The TUI core is import-clean: `rich`, `textual`, `urllib`, `socket`, `http`, and
`subprocess` are absent from every `colleague/tui/` source file. This is
enforced by `tests/test_zero_deps.py`:

- `test_tui_core_no_third_party_imports` — imports all nine TUI core modules at
  runtime and asserts no third-party top-level module is introduced (same
  mechanism as the OTel guard).
- `test_tui_core_no_forbidden_stdlib_imports` — scans the source of every
  `colleague/tui/*.py` and asserts no `rich`, `textual`, `urllib`, `socket`,
  `http`, or `subprocess` import appears.

## Live drive integration (#74)

A real `drive` feeds the cockpit, not just authored/snapshot state:

- **Live cockpit (A1)** — `colleague drive` renders the cockpit on stderr as it
  runs (conversation per step; an `error` popup when a tool step fails). Auto-on an
  interactive TTY; `--tui` / `--no-tui` force it. Off a TTY it falls back to the
  plain `step N: <tool> [ok|err]` lines, byte-identical. Escapes are stripped when
  `NO_COLOR` is set or the stream isn't a TTY.
- **Live event stream (A3)** — `drive --tui-events <path>` appends one `DriveStep`
  JSONL line per step as the drive runs (the same format `replay`/`snapshot`
  consume). A stream written into the driven repo is treated as harness telemetry,
  never swept into the drive branch.
- **Replay a real drive (A4)** — `tui replay --trace <id>.trace.jsonl` folds a
  finished drive's loop-step trace into the cockpit. Live and replayed steps read
  identically — both go through one converter (`colleague/tui/from_drive.py`)
  and the same pure reducer, so a failed step opens the same popup live and on
  replay.

## Honest limits

- The **interactive `session` cockpit (#74 A2)** is the remaining follow-up:
  `session` still uses its readline numbered palette, not the live cockpit (a
  drive *inside* a session keeps the plain `step N:` lines). The pure reducer,
  TAUI mirror, snapshot, replay, diagnose, the live TTY view (`tui live`), and
  the live-drive integration above are all complete.
- The **Rich/Textual renderer plugin** is a post-MVP follow-up. The entry-point
  seam is registered and the `[tui]` extra packages the deps, but no
  Rich/Textual renderer ships in core today — the stdlib ANSI renderer is the
  default and only plugin.

## Key files

- `colleague/tui/state.py` — `CockpitState` and its nested dataclasses.
- `colleague/tui/events.py` — discriminated event union with JSONL helpers.
- `colleague/tui/reducer.py` — pure `reduce(state, event) -> CockpitState`.
- `colleague/tui/taui.py` — `serialize(state) -> dict` (the TAUI mirror).
- `colleague/tui/selectors.py` — dotted-path resolution over the TAUI mirror.
- `colleague/tui/snapshot.py` — snapshot triple write + read.
- `colleague/tui/replay.py` — deterministic event-log replay.
- `colleague/tui/diagnose.py` — 7-bug-class cross-mirror differ.
- `colleague/tui/render/ansi.py` — stdlib ANSI renderer (the default plugin).

## See also

- [artifact.md](artifact.md) — the per-drive JSON artifact TAUI complements.
- [telemetry.md](telemetry.md) — Telemetry (OTel) follows the same opt-in extra +
  lazy-import pattern as the `[tui]` extra.
- [engines.md](engines.md) — the `colleague.engines` entry-point group that
  `colleague.renderers` mirrors.

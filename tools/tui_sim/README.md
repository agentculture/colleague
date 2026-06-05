# tools/tui_sim — simulate the colleague TUI as asciinema recordings

Dev-only tooling (not shipped in the wheel). It scripts realistic human flows
through colleague's **real, pure** TUI render functions and records each as an
asciinema `.cast` "video", a readable storyboard, and a snapshot quad.

## Run

```bash
python -m tools.tui_sim --out tools/tui_sim/recordings
```

Re-running is **deterministic** — byte-identical output, so the recordings are
safe to commit and a guard test (`tests/test_tui_sim.py`) can pin them.

## What it writes (per scenario, into `recordings/`)

| file | what |
| --- | --- |
| `<name>.cast` | asciinema **v2** recording — the replayable video |
| `<name>.txt` | SGR-stripped storyboard — every frame, labelled (review/diff) |
| `<name>.{taui.json,ansi,events.jsonl,md}` | snapshot quad of the key moment |

Plus `recordings/index.md` (manifest + diagnose summary).

## Play / share

```bash
asciinema play tools/tui_sim/recordings/full-ride.cast
# optional GIF for sharing (needs: cargo install agg)
agg tools/tui_sim/recordings/full-ride.cast full-ride.gif
```

(`.cast`-only by design — zero install. The `agg` step is offered, not required.)

## Scenarios

- `first-contact` — palette + slash autocomplete (Surface 1)
- `drive-cockpit` — live drive: tool steps + spinner (Surface 2)
- `skill-suggested` — the `boost` popup (Surface 3)
- `failed-step` — the error popup on a failed tool step (Surface 3)
- `full-ride` — palette → config → drive → popup → quit (everything)

## How it stays faithful

Every frame comes from the same functions the live TUI uses:
`colleague.tui.render.ansi.render`, `colleague.tui.reducer.reduce`,
`render_slash_autocomplete`, and the session composition mirrored from
`session.py:_read_live_ansi._render`. The palette state is taken from a real
`_Session` instance, so the command list / status line never drift from the
shipped screen. Zero third-party imports — a `.cast` is just JSON.

The human-experience findings drawn from these recordings live in
[`docs/tui-experience-evaluation.md`](../../docs/tui-experience-evaluation.md).

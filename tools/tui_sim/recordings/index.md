# colleague TUI simulations

Deterministic recordings of the colleague TUI, generated from the *real*
render seams by `python -m tools.tui_sim`. Regenerate with:

```bash
python -m tools.tui_sim --out tools/tui_sim/recordings
```

Play a recording (needs [asciinema](https://asciinema.org/)):

```bash
asciinema play tools/tui_sim/recordings/full-ride.cast
# optional: turn it into a shareable GIF with agg (cargo install agg)
agg tools/tui_sim/recordings/full-ride.cast full-ride.gif
```

The `.txt` storyboards are the SGR-stripped frames (read them directly);
the snapshot quad (`.taui.json` / `.ansi` / `.events.jsonl` / `.md`) captures
each event-driven scenario's key moment.

| scenario | what it shows | frames | ~duration | diagnose |
| --- | --- | ---: | ---: | --- |
| `first-contact` | First contact — palette + slash autocomplete | 7 | 4.5s | clean |
| `drive-cockpit` | Drive cockpit — tool steps + spinner | 16 | 8.9s | clean |
| `skill-suggested` | Skill suggested — the boost popup | 11 | 6.5s | clean |
| `failed-step` | Failed step — the error popup | 7 | 5.4s | clean |
| `full-ride` | Full ride — palette -> config -> drive -> popup -> quit | 30 | 16.8s | clean |

All snapshots pass `colleague.tui.diagnose` cross-mirror checks (zero findings).


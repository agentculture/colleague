"""``python -m tools.tui_sim`` — generate every TUI simulation artifact.

For each scenario this writes, into ``--out`` (default
``tools/tui_sim/recordings``):

* ``<name>.cast``  — the asciinema v2 recording (the replayable "video");
* ``<name>.txt``   — the SGR-stripped storyboard (review/diff-friendly);
* the snapshot quad ``<name>.{taui.json,ansi,events.jsonl,md}`` for the scenario's
  key moment (event-driven scenarios), via :func:`colleague.tui.snapshot.write_snapshot`.

It then runs :func:`colleague.tui.diagnose.diagnose` over each snapshot (the 7-class
cross-mirror checker) and writes a ``index.md`` manifest summarising frame counts,
durations, play instructions, and any diagnose findings.

Deterministic: re-running produces byte-identical output (``git status`` clean).
Stdlib only; imports colleague's pure render seams.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from colleague.tui.diagnose import diagnose
from colleague.tui.render.ansi import render
from colleague.tui.render.markdown import render_markdown
from colleague.tui.snapshot import write_snapshot
from colleague.tui.taui import serialize

from .scenarios import Scenario, build_all

#: Default target repo = this colleague checkout (tools/tui_sim/__main__.py -> root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUT = _REPO_ROOT / "tools" / "tui_sim" / "recordings"


def _diagnose_scenario(scenario: Scenario) -> List[str]:
    """Return diagnose finding messages for *scenario* (empty list == clean).

    ``events`` is passed as ``None`` on purpose: scenarios start from a *composed*
    base (the session palette + a drive overlay), not a fresh ``CockpitState``, so
    the STATE replay-equivalence and POPUP_LIFECYCLE dismissed-vs-visible checks
    (both of which assume a fresh, full-trail capture) would raise expected false
    positives. Every render/layout/focus/routing/theme detector still runs against
    the captured TAUI + ANSI + Markdown frames — which is exactly the cross-mirror
    faithfulness we want to assert.
    """
    if scenario.snapshot is None:
        return []
    state, _events = scenario.snapshot
    taui = serialize(state)
    diag = diagnose(taui, render(state), events=None, markdown=render_markdown(state))
    return [f"{f.bug_class}@{f.selector}: {f.message}" for f in diag.findings]


def _write_scenario(scenario: Scenario, out: Path) -> dict:
    """Write the cast + storyboard (+ snapshot quad) for *scenario*; return a summary."""
    fs = scenario.filmstrip
    (out / f"{scenario.name}.cast").write_text(fs.cast(), encoding="utf-8")
    (out / f"{scenario.name}.txt").write_text(fs.storyboard_txt(), encoding="utf-8")

    has_quad = False
    if scenario.snapshot is not None:
        state, events = scenario.snapshot
        write_snapshot(out, scenario.name, state, events)
        has_quad = True

    return {
        "name": scenario.name,
        "title": scenario.title,
        "frames": len(fs.frames),
        "duration_ms": fs.duration_ms,
        "quad": has_quad,
        "findings": _diagnose_scenario(scenario),
    }


def _render_index(summaries: List[dict]) -> str:
    lines: List[str] = [
        "# colleague TUI simulations",
        "",
        "Deterministic recordings of the colleague TUI, generated from the *real*",
        "render seams by `python -m tools.tui_sim`. Regenerate with:",
        "",
        "```bash",
        "python -m tools.tui_sim --out tools/tui_sim/recordings",
        "```",
        "",
        "Play a recording (needs [asciinema](https://asciinema.org/)):",
        "",
        "```bash",
        "asciinema play tools/tui_sim/recordings/full-ride.cast",
        "# optional: turn it into a shareable GIF with agg (cargo install agg)",
        "agg tools/tui_sim/recordings/full-ride.cast full-ride.gif",
        "```",
        "",
        "The `.txt` storyboards are the SGR-stripped frames (read them directly);",
        "the snapshot quad (`.taui.json` / `.ansi` / `.events.jsonl` / `.md`) captures",
        "each event-driven scenario's key moment.",
        "",
        "| scenario | what it shows | frames | ~duration | diagnose |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for s in summaries:
        dur = f"{s['duration_ms'] / 1000:.1f}s"
        verdict = "clean" if not s["findings"] else f"{len(s['findings'])} finding(s)"
        lines.append(f"| `{s['name']}` | {s['title']} | {s['frames']} | {dur} | {verdict} |")
    lines.append("")

    any_findings = any(s["findings"] for s in summaries)
    if any_findings:
        lines.append("## diagnose findings")
        lines.append("")
        for s in summaries:
            if s["findings"]:
                lines.append(f"### `{s['name']}`")
                for msg in s["findings"]:
                    lines.append(f"- {msg}")
                lines.append("")
    else:
        lines.append(
            "All snapshots pass `colleague.tui.diagnose` cross-mirror checks (zero findings)."
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.tui_sim", description=__doc__)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Output directory.")
    parser.add_argument("--repo", type=Path, default=_REPO_ROOT, help="Repo for the palette.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the per-scenario log.")
    args = parser.parse_args(argv)

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    summaries: List[dict] = []
    for scenario in build_all(args.repo):
        summary = _write_scenario(scenario, out)
        summaries.append(summary)
        if not args.quiet:
            verdict = (
                "clean" if not summary["findings"] else f"{len(summary['findings'])} finding(s)"
            )
            print(
                f"  {scenario.name:<16} {summary['frames']:>3} frames "
                f"{summary['duration_ms'] / 1000:>5.1f}s  diagnose: {verdict}"
            )

    (out / "index.md").write_text(_render_index(summaries), encoding="utf-8")
    if not args.quiet:
        print(f"wrote {len(summaries)} scenarios + index.md to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

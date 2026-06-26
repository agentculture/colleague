"""``colleague quickstart`` — a guided first-run walkthrough for new users.

The flat ``--help`` lists every verb but answers no "where do I start?". This
verb *is* that answer: a short, ordered path from "is it set up?" to "run a first
work item and read the result". Read-only — it prints guidance, runs nothing.

Deterministic by design: the steps are a static, ordered catalog so the output is
stable (the agent-first rubric + tests can pin it) and a wheel install with no
provider configured still gets a useful answer.
"""

from __future__ import annotations

import argparse

from colleague.cli._output import emit_result, rendered

#: (title, example command, why) — the ordered first-run path. One source of
#: truth for both the markdown and the --json rendering.
_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "Check your setup",
        "colleague doctor",
        "Confirms a backend is reachable and your config is ready. "
        "Add --probe to actually ping the provider.",
    ),
    (
        "See the available minds",
        "colleague backends list",
        "Lists the model backends colleague can drive (e.g. mock, vllm-openai).",
    ),
    (
        "Run a zero-cost first work item",
        'colleague work "summarize the README" --engine mock --no-pr',
        "The mock backend returns a scripted result without calling a model — a "
        "free dry run of the whole loop. Drop --engine to use your real backend.",
    ),
    (
        "Read the run report",
        "colleague feedback show last",
        "Every work item writes a JSON artifact (with cost stats) under .colleague/. "
        'Grade it: colleague feedback record last --rating 4 --notes "...".',
    ),
    (
        "Go deeper",
        "colleague explain work",
        "Markdown docs for any verb. Or run bare `colleague` at a terminal to open "
        "the interactive session palette.",
    ),
)


def _as_markdown() -> str:
    lines = [
        "# colleague quickstart",
        "",
        "colleague hands a scoped repo task to a model backend, drives it through a "
        "bounded tool-loop, and returns a JSON run report. The shortest path from "
        "zero to your first work item:",
        "",
    ]
    for i, (title, cmd, why) in enumerate(_STEPS, start=1):
        lines.append(f"{i}. **{title}**")
        lines.append(f"   `{cmd}`")
        lines.append(f"   {why}")
        lines.append("")
    lines.append(
        "Tip: `colleague --help` lists every verb; `colleague explain` is the full catalog."
    )
    return "\n".join(lines)


# --- registry tool function -------------------------------------------------
# Named params (no argparse Namespace), return rendered(structured, text).


def _quickstart() -> object:
    return rendered(
        {"steps": [{"title": t, "command": c, "why": w} for t, c, w in _STEPS]},
        _as_markdown(),
    )


def register_into(app) -> None:
    """Register the quickstart verb onto the agentfront App registry."""
    app.tool(
        _quickstart,
        name="quickstart",
        description="Guided first-run walkthrough for new users (start here).",
        doc="# quickstart\nA guided first-run walkthrough: the shortest path "
        "from 'is it set up?' to reading a first run report.",
    )


# --- legacy argparse path (pre-flip) ----------------------------------------
# Thin adapter delegating to the registry tool function so the live argparse
# CLI stays byte-identical until the entry is flipped to the rendered CLI.


def cmd_quickstart(args: argparse.Namespace) -> int:
    emit_result(_quickstart(), json_mode=bool(getattr(args, "json", False)))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "quickstart",
        help="Guided first-run walkthrough for new users (start here).",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_quickstart)

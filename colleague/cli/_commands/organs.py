"""``colleague organs`` — inspect the AI-coworker organism (colleague#291, S10).

``organs list`` renders the SAME curated table + resolver as the ``doctor``
organs check-group (:mod:`colleague.oilcheck.organs`'s :func:`resolve_organs`)
as a second view: for every organ, its ``seam`` (how colleague talks to it
today, or would once its planned integration lands), its ``contract`` (a
pointer to the organ's own published contract artifact — see
``docs/organs.md``), and its ``present`` / ``version`` / ``armed`` state.
Read-only, zero network, zero subprocess — one shared resolver, two renderings
(``doctor`` for a pass/fail health rubric, ``organs list`` for the full table).

``organs overview`` describes the noun (satisfying the agent-first rubric: any
noun with action-verbs must also expose ``overview``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.oilcheck.organs import resolve_organs


def _organs_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Lists the curated organ table: lobes, eidetic, coherence, sloth, "
                "data-refinery, agtag, devex, devague",
                "For each: seam (how colleague talks to it), contract doc, present, "
                "version, armed",
                "The SAME resolver `colleague doctor` uses for its organs check-group "
                "(one resolver, two views)",
                "Read-only, zero network, zero subprocess — presence is a PATH lookup, "
                "version is importlib.metadata, armed is colleague's own config",
            ],
        },
        {
            "title": "Curated, not a plugin registry",
            "items": [
                "The organ table is hand-maintained (colleague/oilcheck/organs.py), not "
                "dynamically discovered",
                "A missing organ is never unhealthy in `colleague doctor` — it is an "
                "advisory warning with a `uv tool install <distribution>` hint",
                "coherence / sloth / data-refinery are listed even though colleague does "
                "not consume them yet (planned specs — see docs/organs.md)",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "organs list [--repo PATH] [--json] — list every organ's resolved state",
                "organs overview — describe the organs surface (this command)",
            ],
        },
    ]


def _organs_overview() -> object:
    sections = _organs_sections()
    return rendered(
        {"subject": "colleague organs", "sections": sections},
        render_text("colleague organs", sections),
    )


def _organs_list(repo: str = ".") -> object:
    """Registry tool: the resolved organ table as ``rendered(dict, text)``.

    ``repo`` is derived by agentfront into ``--repo`` from this signature; it
    threads through to the SAME no-network resolver
    (:func:`colleague.oilcheck.organs.resolve_organs`) ``colleague doctor``
    uses, so the two views can never disagree.
    """
    repo_path = Path(repo).expanduser()
    entries = resolve_organs(str(repo_path))
    lines = []
    for entry in entries:
        state = "present" if entry["present"] else "MISSING"
        lines.append(
            f"{entry['organ']}\t[{state}]\tversion={entry['version']}\t"
            f"armed={entry['armed']}\tseam: {entry['seam']}\tcontract: {entry['contract']}"
        )
    return rendered({"organs": entries}, "\n".join(lines))


def register_into(app) -> None:
    """Register the organism-visibility inspection verbs on the App registry."""
    g = app.group("organs")
    g.tool(
        _organs_list,
        name="list",
        description="List the resolved organ table (presence/version/armed/seam/contract).",
        doc="# organs list [--repo PATH]\nList every curated organ's resolved state: "
        "seam, contract doc, present, version, armed. The same resolver "
        "`colleague doctor` uses for its organs check-group.",
    )
    g.tool(
        _organs_overview,
        name="overview",
        description="Describe the organs surface.",
        doc="# organs overview\nDescribe the organism-visibility surface: what an organ "
        "is, the curated (not dynamically discovered) table, and the verbs.",
    )


def cmd_organs_overview(args: argparse.Namespace) -> int:
    emit_result(_organs_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_organs_list(args: argparse.Namespace) -> int:
    emit_result(
        _organs_list(getattr(args, "repo", ".")),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_organs_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "organs",
        help="Inspect the AI-coworker organism (see 'colleague organs overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="organs_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List the resolved organ table.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_organs_list)

    ov = noun_sub.add_parser("overview", help="Describe the organs surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_organs_overview)

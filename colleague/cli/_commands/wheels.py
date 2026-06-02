"""``colleague wheels`` — discover installed engine plugins.

``wheels list`` enumerates the engines discovered via the ``colleague.engines``
entry-point group; ``wheels overview`` describes the noun (and satisfies the
agent-first rubric: any noun with action-verbs must also expose ``overview``).

("Wheel" is the internal term for a replaceable engine plugin; the user-facing
surface stays engine-centric and serious — see issue #1's UX note.)
"""

from __future__ import annotations

import argparse

from colleague import registry
from colleague.cli._commands.overview import emit_overview
from colleague.cli._output import JSON_HELP, emit_result


def wheels_sections() -> list[dict[str, object]]:
    catalog = registry.catalog()
    engines = [f"{w.name} — {w.target}" for w in catalog] or ["(no engine wheels installed)"]
    return [
        {"title": "Discovered engines", "items": engines},
        {
            "title": "Verbs",
            "items": [
                "wheels list — list discovered engine wheels",
                "wheels overview — describe the garage (this command)",
            ],
        },
    ]


def cmd_wheels_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague wheels",
        wheels_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_wheels_list(args: argparse.Namespace) -> int:
    catalog = registry.catalog()
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result(
            {"engines": [{"name": w.name, "target": w.target} for w in catalog]},
            json_mode=True,
        )
    elif not catalog:
        emit_result("(no engine wheels installed)", json_mode=False)
    else:
        emit_result("\n".join(f"{w.name}\t{w.target}" for w in catalog), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_wheels_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "wheels",
        help="Discover installed engine wheels (see 'colleague wheels overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="wheels_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List discovered engine wheels.")
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_wheels_list)

    ov = noun_sub.add_parser("overview", help="Describe the wheels garage.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_wheels_overview)

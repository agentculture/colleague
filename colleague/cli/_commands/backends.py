"""``colleague backends`` — discover installed backend plugins (the minds).

``backends list`` enumerates the backends discovered via the ``colleague.engines``
entry-point group; ``backends overview`` describes the noun (and satisfies the
agent-first rubric: any noun with action-verbs must also expose ``overview``).

``wheels`` is retained as a **deprecated alias** of ``backends`` — the old
convertible-era car-themed name — for back-compatibility. Both names dispatch to
the same handlers; prefer ``backends``. Its ``--help`` row is labelled deprecated
so the surface nudges toward ``backends`` without breaking the old name.
"""

from __future__ import annotations

import argparse

from colleague import registry
from colleague.cli._commands.overview import emit_overview
from colleague.cli._output import JSON_HELP, emit_result


def backends_sections() -> list[dict[str, object]]:
    catalog = registry.catalog()
    engines = [f"{b.name} — {b.target}" for b in catalog] or ["(no backend plugins installed)"]
    return [
        {"title": "Discovered backends", "items": engines},
        {
            "title": "Verbs",
            "items": [
                "backends list — list discovered backend plugins",
                "backends overview — describe the registry of installed plugins (this command)",
            ],
        },
    ]


def cmd_backends_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague backends",
        backends_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_backends_list(args: argparse.Namespace) -> int:
    catalog = registry.catalog()
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result(
            {"engines": [{"name": b.name, "target": b.target} for b in catalog]},
            json_mode=True,
        )
    elif not catalog:
        emit_result("(no backend plugins installed)", json_mode=False)
    else:
        # Header row so a reader knows what the two tab-separated columns mean
        # (the backend name vs. its target class path). --json above is unchanged.
        rows = [f"{b.name}\t{b.target}" for b in catalog]
        emit_result("\n".join(["NAME\tTARGET", *rows]), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_backends_overview(args)


def _register_noun(sub: argparse._SubParsersAction, name: str, *, help_text: str) -> None:
    """Register a backend-discovery noun (``backends`` or its ``wheels`` alias).

    Both nouns share the same handlers; the alias differs only by its ``--help``
    label, which marks it deprecated.
    """
    p = sub.add_parser(name, help=help_text)
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest=f"{name}_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List discovered backend plugins.")
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_backends_list)

    ov = noun_sub.add_parser("overview", help="Describe the installed-plugins registry.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_backends_overview)


def register(sub: argparse._SubParsersAction) -> None:
    _register_noun(
        sub,
        "backends",
        help_text="Discover installed backend plugins (see 'colleague backends overview').",
    )
    # Deprecated alias of `backends` (the old car-themed name), kept for
    # back-compatibility. Labelled in --help so the surface nudges toward `backends`.
    _register_noun(sub, "wheels", help_text="Deprecated alias of 'colleague backends'.")

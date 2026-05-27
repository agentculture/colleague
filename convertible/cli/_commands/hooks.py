"""``convertible hooks`` — inspect configured lifecycle hooks.

``hooks list`` enumerates hook entries loaded from ``.convertible/hooks.json``
for the target repo; ``hooks overview`` describes the noun (satisfying the
agent-first rubric: any noun with action-verbs must also expose ``overview``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convertible import hooks as _hooks
from convertible.cli._commands.overview import emit_overview
from convertible.cli._output import emit_result


def _hooks_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Loads hook configuration from .convertible/hooks.json",
                "Hooks fire at lifecycle events: task_start, pre_tool, post_tool, finish",
                "Each entry maps an event + optional matcher regex to a shell command",
            ],
        },
        {
            "title": "Hook decisions",
            "items": [
                "allow — permit the tool call (default on exit 0 / empty stdout)",
                "deny — block the tool call (non-zero exit or {decision:deny})",
                "rewrite — replace tool arguments ({decision:rewrite, arguments:{}})",
                "observe — pass-through with optional additionalContext",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "hooks list [--repo PATH] — list configured hook entries",
                "hooks overview — describe the hooks surface (this command)",
            ],
        },
    ]


def cmd_hooks_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "convertible hooks",
        _hooks_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_hooks_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    json_mode = bool(getattr(args, "json", False))

    hook_config = _hooks.load_hooks(repo)

    # Public accessor — never reach into the config's private mapping.
    all_entries = hook_config.all_entries()

    if json_mode:
        items = [
            {"event": e.event, "matcher": e.matcher, "command": e.command} for e in all_entries
        ]
        emit_result({"hooks": items}, json_mode=True)
    elif not all_entries:
        emit_result("(no hooks configured)", json_mode=False)
    else:
        lines = []
        for entry in all_entries:
            if entry.matcher:
                lines.append(f"{entry.event}\t{entry.matcher}\t{entry.command}")
            else:
                lines.append(f"{entry.event}\t(any)\t{entry.command}")
        emit_result("\n".join(lines), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_hooks_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "hooks",
        help="Inspect configured lifecycle hooks (see 'convertible hooks overview').",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="hooks_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List configured hook entries.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument("--json", action="store_true", help="Emit structured JSON.")
    lst.set_defaults(func=cmd_hooks_list)

    ov = noun_sub.add_parser("overview", help="Describe the hooks surface.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_hooks_overview)

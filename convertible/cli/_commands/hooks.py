"""``convertible hooks`` — inspect configured lifecycle hooks.

``hooks list`` enumerates hook entries loaded from ``.convertible/hooks.json``
for the target repo; ``hooks overview`` describes the noun (satisfying the
agent-first rubric: any noun with action-verbs must also expose ``overview``).

When ``--model <m>`` is given, per-model entries from
``.convertible/<m>/hooks.json`` are composed ahead of (and tagged
``per-model``), and base entries are tagged ``base``.  The ``<m>`` token is
passed through :func:`convertible.layers.sanitize_model` before the path is
built (e.g. ``Qwen/Qwen3-32B`` -> ``Qwen-Qwen3-32B``), so a model id containing
``/`` resolves to one safe directory, never a nested path.  Without ``--model``
the output is byte-identical to the pre-model baseline — no ``scope`` key
is injected.
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
                "Per-model overlays at .convertible/<model>/hooks.json (the model "
                "id sanitized to a filename-safe token) are composed ahead of (and "
                "take priority over) base entries when --model is given",
            ],
        },
        {
            "title": "Per-model overlay (--model)",
            "items": [
                "Pass --model <name> to include per-model hook entries",
                "Per-model entries (from .convertible/<model>/hooks.json, where the "
                "model id is sanitized, e.g. Qwen/Qwen3-32B -> Qwen-Qwen3-32B) are "
                "listed first with scope=per-model; base entries follow with scope=base",
                "Per-model-first precedence: the loop's first-deny/rewrite-wins "
                "semantics give per-model hooks priority over base hooks",
                "Without --model the output is identical to the base-only baseline",
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
                "hooks list [--repo PATH] [--model NAME] — list configured hook entries",
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
    model: str | None = getattr(args, "model", None) or None

    if model is None:
        # No --model: base-only load; output is byte-identical to the pre-model
        # baseline — no scope key injected.
        hook_config = _hooks.load_hooks(repo)
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

    # --model given: load base and composed configs, derive scope by comparing
    # lengths per event.  Per-model entries are the ones prepended ahead of base —
    # for each event, the first (len(composed[event]) - len(base[event])) entries
    # in the composed list are per-model; the rest are base.
    base_config = _hooks.load_hooks(repo)
    composed_config = _hooks.load_hooks(repo, model=model)

    base_entries = base_config.all_entries()
    composed_entries = composed_config.all_entries()

    # Build a per-event length map for the base so we can determine the cutoff.
    # _hooks.HookConfig.all_entries() visits events in stable order:
    #   task_start, pre_tool, post_tool, finish.

    # Collect base counts per event (using all_entries, which we can reconstruct
    # from the stable ordering).
    base_counts: dict[str, int] = {}
    for entry in base_entries:
        base_counts[entry.event] = base_counts.get(entry.event, 0) + 1

    # Composed counts per event (same idiom as base_counts), precomputed once so
    # scope assignment stays O(n) instead of rescanning composed_entries per entry.
    composed_counts: dict[str, int] = {}
    for entry in composed_entries:
        composed_counts[entry.event] = composed_counts.get(entry.event, 0) + 1

    # Walk the composed entries and assign scopes.
    # Within each event, composed entries are: [per-model..., base...].
    # Track how many per-event entries we've seen to identify the boundary.
    per_event_seen: dict[str, int] = {}
    scoped: list[tuple[_hooks.HookEntry, str]] = []
    for entry in composed_entries:
        ev = entry.event
        idx = per_event_seen.get(ev, 0)
        model_count = composed_counts.get(ev, 0) - base_counts.get(ev, 0)
        scope = "per-model" if idx < model_count else "base"
        scoped.append((entry, scope))
        per_event_seen[ev] = idx + 1

    if json_mode:
        items = [
            {
                "event": e.event,
                "matcher": e.matcher,
                "command": e.command,
                "scope": scope,
            }
            for e, scope in scoped
        ]
        emit_result({"hooks": items}, json_mode=True)
    elif not scoped:
        emit_result("(no hooks configured)", json_mode=False)
    else:
        lines = []
        for entry, scope in scoped:
            matcher_str = entry.matcher if entry.matcher else "(any)"
            lines.append(f"[{scope}]\t{entry.event}\t{matcher_str}\t{entry.command}")
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
    lst.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "Include per-model overlay entries from "
            ".convertible/<model>/hooks.json (the <model> token is sanitized, "
            "e.g. Qwen/Qwen3-32B -> Qwen-Qwen3-32B). "
            "Per-model entries are listed first (scope=per-model); "
            "base entries follow (scope=base)."
        ),
    )
    lst.add_argument("--json", action="store_true", help="Emit structured JSON.")
    lst.set_defaults(func=cmd_hooks_list)

    ov = noun_sub.add_parser("overview", help="Describe the hooks surface.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_hooks_overview)

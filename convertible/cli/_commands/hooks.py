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
from convertible.cli._output import JSON_HELP, emit_result


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


def _count_by_event(entries: list[_hooks.HookEntry]) -> dict[str, int]:
    """Per-event entry counts."""
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.event] = counts.get(entry.event, 0) + 1
    return counts


def _resolve_scoped_entries(
    repo: Path, model: str | None
) -> list[tuple[_hooks.HookEntry, str | None]]:
    """Entries to display, each paired with its scope.

    Without a model the scope is ``None`` (base-only; no scope is surfaced).
    With a model, base + per-model overlays are composed and each entry is tagged
    ``per-model`` or ``base``: per-model entries are prepended ahead of base ones
    per event, so for each event the first ``composed - base`` entries are the
    per-model overlay and the remainder are base.
    """
    if model is None:
        return [(entry, None) for entry in _hooks.load_hooks(repo).all_entries()]

    base_entries = _hooks.load_hooks(repo).all_entries()
    composed_entries = _hooks.load_hooks(repo, model=model).all_entries()
    base_counts = _count_by_event(base_entries)
    composed_counts = _count_by_event(composed_entries)

    per_event_seen: dict[str, int] = {}
    scoped: list[tuple[_hooks.HookEntry, str | None]] = []
    for entry in composed_entries:
        ev = entry.event
        idx = per_event_seen.get(ev, 0)
        model_count = composed_counts.get(ev, 0) - base_counts.get(ev, 0)
        scoped.append((entry, "per-model" if idx < model_count else "base"))
        per_event_seen[ev] = idx + 1
    return scoped


def _emit_hook_entries(
    scoped: list[tuple[_hooks.HookEntry, str | None]], *, json_mode: bool
) -> None:
    """Render scoped entries; a ``None`` scope is omitted (base-only mode)."""
    if json_mode:
        items: list[dict[str, str]] = []
        for entry, scope in scoped:
            item = {"event": entry.event, "matcher": entry.matcher, "command": entry.command}
            if scope is not None:
                item["scope"] = scope
            items.append(item)
        emit_result({"hooks": items}, json_mode=True)
        return
    if not scoped:
        emit_result("(no hooks configured)", json_mode=False)
        return
    lines = []
    for entry, scope in scoped:
        matcher_str = entry.matcher if entry.matcher else "(any)"
        prefix = f"[{scope}]\t" if scope is not None else ""
        lines.append(f"{prefix}{entry.event}\t{matcher_str}\t{entry.command}")
    emit_result("\n".join(lines), json_mode=False)


def cmd_hooks_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    json_mode = bool(getattr(args, "json", False))
    model: str | None = getattr(args, "model", None) or None

    scoped = _resolve_scoped_entries(repo, model)
    _emit_hook_entries(scoped, json_mode=json_mode)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_hooks_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "hooks",
        help="Inspect configured lifecycle hooks (see 'convertible hooks overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
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
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_hooks_list)

    ov = noun_sub.add_parser("overview", help="Describe the hooks surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_hooks_overview)

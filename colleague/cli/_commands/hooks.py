"""``colleague hooks`` — inspect and approve configured lifecycle hooks.

``hooks list`` enumerates hook entries loaded from ``.colleague/hooks.json``
for the target repo; ``hooks approve`` records a checksum approval for a hook
script file into ``<repo>/.colleague/approvals.json``; ``hooks overview``
describes the noun (satisfying the agent-first rubric: any noun with
action-verbs must also expose ``overview``).

When ``--model <m>`` is given, per-model entries from
``.colleague/<m>/hooks.json`` are composed ahead of (and tagged
``per-model``), and base entries are tagged ``base``.  The ``<m>`` token is
passed through :func:`colleague.layers.sanitize_model` before the path is
built (e.g. ``Qwen/Qwen3-32B`` -> ``Qwen-Qwen3-32B``), so a model id containing
``/`` resolves to one safe directory, never a nested path.  Without ``--model``
the output is byte-identical to the pre-model baseline — no ``scope`` key
is injected.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague import hooks as _hooks
from colleague.cli import _approvals
from colleague.cli._commands.overview import render_text
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.policy import SUPPORTED_CHECKSUM_ALGOS, file_checksum, load_policy, verify_checksum


def _hooks_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Loads hook configuration from .colleague/hooks.json",
                "Hooks fire at lifecycle events: task_start, pre_tool, post_tool, finish",
                "Each entry maps an event + optional matcher regex to a shell command",
                "Per-model overlays at .colleague/<model>/hooks.json (the model "
                "id sanitized to a filename-safe token) are composed ahead of (and "
                "take priority over) base entries when --model is given",
                "Approval gate: operator can approve hook scripts by checksum (approvals.json)",
            ],
        },
        {
            "title": "Per-model overlay (--model)",
            "items": [
                "Pass --model <name> to include per-model hook entries",
                "Per-model entries (from .colleague/<model>/hooks.json, where the "
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
                "hooks list [--repo PATH] [--model NAME] — list configured hook entries + status",
                "hooks approve <name> [--repo PATH] [--algo sha256|md5] — record script approval",
                "hooks overview — describe the hooks surface (this command)",
            ],
        },
    ]


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


def _file_status(policy, rel: str, candidate: Path) -> str:
    """Approval status of one referenced hook file under an active hooks section."""
    approval = policy.file_approval("hooks", rel)
    if approval is None:
        return "unapproved"
    return "approved" if verify_checksum(candidate, approval) else "drifted"


def _hook_approval_status(command: str, repo: Path, model: str | None = None) -> str:
    """Approval status of a hook command, reflecting the *merged* policy.

    Uses :func:`colleague.policy.load_policy` (repo-over-user + per-model
    overlay) — the same source enforcement uses — and derives keys via
    :func:`colleague.hooks.referenced_repo_files`, so the displayed status
    agrees with what the gate actually does. Returns:

    - ``ungated``     — no hooks section in the merged policy;
    - ``exempt``      — section present but the command references no repo file
      (a pure inline hook needs no content-approval; enforcement allows it);
    - ``approved`` / ``drifted`` / ``unapproved`` — aggregated worst-case across
      the command's referenced files (drifted beats unapproved beats approved).
    """
    policy = load_policy(repo, model=model)
    if not policy.section_present("hooks"):
        return "ungated"
    refs = _hooks.referenced_repo_files(command, repo)
    if not refs:
        return "exempt"
    statuses = {_file_status(policy, rel, candidate) for rel, candidate in refs}
    for worst in ("drifted", "unapproved", "approved"):
        if worst in statuses:
            return worst
    return "approved"


def _run_command_line(run_cmd_policy: dict, *, colon: bool) -> str:
    """One-line summary of the run_command allow/deny policy for text output."""
    allow = run_cmd_policy.get("allow", [])
    deny = run_cmd_policy.get("deny", [])
    sep = ":" if colon else ""
    return f"run_command{sep} allow={allow} deny={deny}"


def _hook_json_item(
    entry: _hooks.HookEntry, scope: str | None, repo: Path, model: str | None
) -> dict[str, str]:
    """One hook entry as a JSON dict (with approval status; scope only when set)."""
    item: dict[str, str] = {
        "event": entry.event,
        "matcher": entry.matcher,
        "command": entry.command,
        "approval_status": _hook_approval_status(entry.command, repo, model),
    }
    if scope is not None:
        item["scope"] = scope
    return item


def _hook_text_line(
    entry: _hooks.HookEntry, scope: str | None, repo: Path, model: str | None
) -> str:
    """One hook entry as a tab-separated text line (with approval status)."""
    matcher_str = entry.matcher if entry.matcher else "(any)"
    prefix = f"[{scope}]\t" if scope is not None else ""
    status = _hook_approval_status(entry.command, repo, model)
    return f"{prefix}{entry.event}\t{matcher_str}\t{entry.command}\t[{status}]"


# --- registry tool functions (rendered) + thin legacy adapters --------------


def _hooks_overview() -> object:
    sections = _hooks_sections()
    return rendered(
        {"subject": "colleague hooks", "sections": sections},
        render_text("colleague hooks", sections),
    )


def _hooks_list(repo: str = ".", model: str = "") -> object:
    """Registry tool: configured hook entries + approval status + run_command policy.

    Builds the SAME ``{"hooks": [...], "run_command_policy"?: ...}`` payload and
    the SAME text lines the legacy ``hooks list`` emitted, from one
    ``rendered(payload, text)`` value. ``repo`` / ``model`` derive into
    ``--repo`` / ``--model``; an empty ``model`` is the base-only baseline (no
    ``scope`` key), byte-identical to before.
    """
    repo_path = Path(repo).expanduser()
    model_arg = model or None
    scoped = _resolve_scoped_entries(repo_path, model_arg)
    run_cmd_policy = load_policy(repo_path, model=model_arg).run_command_config()

    payload: dict = {"hooks": [_hook_json_item(e, s, repo_path, model_arg) for e, s in scoped]}
    if run_cmd_policy is not None:
        payload["run_command_policy"] = run_cmd_policy

    if not scoped:
        lines = ["(no hooks configured)"]
        if run_cmd_policy is not None:
            lines.append(_run_command_line(run_cmd_policy, colon=True))
    else:
        lines = [_hook_text_line(e, s, repo_path, model_arg) for e, s in scoped]
        if run_cmd_policy is not None:
            lines.append(_run_command_line(run_cmd_policy, colon=False))
    return rendered(payload, "\n".join(lines))


def _hooks_approve(name: str, repo: str = ".", algo: str = "sha256") -> object:
    """Registry tool: record a checksum approval for a hook script file.

    ``name`` (no default) derives into a positional arg. ``--algo`` is a
    value-carrying flag (consumed via the ``algo`` signature param), so it
    cannot take an explicit ``Flag(choices=…)`` without colliding with its
    signature-derived ``--algo``; it is therefore validated explicitly and
    early below, raising a clean choices-shaped ``CliError``.
    """
    repo_path = Path(repo).expanduser()
    algo = algo or "sha256"
    if algo not in SUPPORTED_CHECKSUM_ALGOS:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"invalid --algo {algo!r}",
            remediation=f"choose one of: {', '.join(SUPPORTED_CHECKSUM_ALGOS)}",
        )
    # Normalize to the canonical repo-relative key — the SAME key hook
    # enforcement derives from a command referencing this file (so
    # 'hooks approve ./x.sh' and a hook running 'bash ./x.sh' agree on 'x.sh').
    key = _hooks.canonical_hook_key(repo_path, name)
    if key is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"hook script path escapes the repo root: {name}",
            remediation="approve a script that lives inside the repository tree",
        )
    script_path = repo_path.resolve() / key
    if not script_path.is_file():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"hook script file not found: {script_path}",
            remediation=(
                "ensure the file exists at the given repo-relative path; "
                "hooks are keyed by the repo-relative path of their script file"
            ),
        )
    try:
        checksum = file_checksum(script_path, algo)
    except (OSError, ValueError) as exc:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"could not checksum {script_path}: {exc}",
            remediation="ensure the file exists and is readable",
        ) from exc
    _approvals.write_approval(repo_path, "hooks", key, checksum)
    result = {"name": key, "category": "hooks", "checksum": checksum, "path": str(script_path)}
    return rendered(result, f"approved hooks/{key}  {checksum}")


def register_into(app) -> None:
    """Register the lifecycle-hook inspection + approval verbs on the App registry."""
    g = app.group("hooks")
    g.tool(
        _hooks_list,
        name="list",
        description="List configured hook entries.",
        doc="# hooks list [--repo PATH] [--model NAME]\nList the lifecycle hook "
        "entries from .colleague/hooks.json (with per-model overlay when --model is "
        "given), each with its approval status, plus the run_command policy.",
    )
    g.tool(
        _hooks_approve,
        name="approve",
        description="Record a checksum approval for a hook script file.",
        doc="# hooks approve <name> [--repo PATH] [--algo sha256|md5]\nRecord a "
        "checksum approval for a hook script file (keyed by its repo-relative path) "
        "into .colleague/approvals.json.",
    )
    g.tool(
        _hooks_overview,
        name="overview",
        description="Describe the hooks surface.",
        doc="# hooks overview\nDescribe the lifecycle-hook surface: events, the "
        "per-model overlay, hook decisions, the approval gate, and the verbs.",
    )


def cmd_hooks_overview(args: argparse.Namespace) -> int:
    emit_result(_hooks_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_hooks_list(args: argparse.Namespace) -> int:
    emit_result(
        _hooks_list(getattr(args, "repo", "."), getattr(args, "model", None) or ""),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_hooks_approve(args: argparse.Namespace) -> int:
    emit_result(
        _hooks_approve(args.name, getattr(args, "repo", "."), getattr(args, "algo", "sha256")),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_hooks_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "hooks",
        help="Inspect configured lifecycle hooks (see 'colleague hooks overview').",
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
            ".colleague/<model>/hooks.json (the <model> token is sanitized, "
            "e.g. Qwen/Qwen3-32B -> Qwen-Qwen3-32B). "
            "Per-model entries are listed first (scope=per-model); "
            "base entries follow (scope=base)."
        ),
    )
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_hooks_list)

    apr = noun_sub.add_parser("approve", help="Record a checksum approval for a hook script file.")
    apr.add_argument(
        "name",
        help="Repo-relative path to the hook script file (used as the approval key).",
    )
    apr.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    apr.add_argument(
        "--algo",
        default="sha256",
        choices=["sha256", "md5"],
        help="Checksum algorithm (default: sha256).",
    )
    apr.add_argument("--json", action="store_true", help=JSON_HELP)
    apr.set_defaults(func=cmd_hooks_approve)

    ov = noun_sub.add_parser("overview", help="Describe the hooks surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_hooks_overview)

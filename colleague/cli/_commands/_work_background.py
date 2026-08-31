"""Background one-shot detach for ``colleague work`` (child argv + spawn).

Split out of ``colleague/cli/_commands/work.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t16). ``colleague.background`` is imported
here AND re-exported by ``work.py``, so ``work_mod.background`` still resolves
to the same module object the suite patches.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from colleague import background
from colleague.cli._output import emit_result

# The forwardable ``work`` flags a background child inherits verbatim, in CLI
# order: ``(args attr, flag, kind)`` where kind "value" carries an argument and
# "bool" is a bare switch. max_steps / mode / tui / tui-events / json have
# non-uniform shapes and stay explicit in _background_child_argv.
_CHILD_FLAG_TABLE: tuple[tuple[str, str, str], ...] = (
    ("engine", "--engine", "value"),
    ("no_pr", "--no-pr", "bool"),
    ("allow_dirty", "--allow-dirty", "bool"),
    ("until_done", "--until-done", "bool"),
    ("no_lint", "--no-lint", "bool"),
    ("no_coherence", "--no-coherence", "bool"),
    ("no_affected_tests", "--no-affected-tests", "bool"),
    ("test", "--test", "value"),
    ("base", "--base", "value"),
    ("base_url", "--base-url", "value"),
    ("model", "--model", "value"),
    ("effort", "--effort", "value"),
    ("role", "--role", "value"),
    ("api_key", "--api-key", "value"),
)


def _child_tail_argv(args: argparse.Namespace) -> list[str]:
    """Non-uniform ``work`` child flags, in CLI order.

    These flags don't fit the ``_CHILD_FLAG_TABLE`` value/bool pattern — a
    tri-state (``--tui``/``--no-tui``) or a repeatable one (``--attach``) —
    so they're built here. Extracted from :func:`_background_child_argv` so
    that function stays under SonarCloud's cognitive-complexity threshold
    (S3776).
    """
    tail: list[str] = []
    if getattr(args, "max_steps", None) is not None:
        tail += ["--max-steps", str(args.max_steps)]
    # --max-episodes carries a value where 0 (explicit unlimited) is falsy, so
    # it rides here with the max_steps `is not None` idiom, not the flag table.
    if getattr(args, "max_episodes", None) is not None:
        tail += ["--max-episodes", str(args.max_episodes)]
    if getattr(args, "mode", None):
        tail += ["--mode", args.mode]
    tui = getattr(args, "tui", None)
    if tui is True:
        tail.append("--tui")
    elif tui is False:
        tail.append("--no-tui")
    if getattr(args, "tui_events", None):
        tail += ["--tui-events", args.tui_events]
    if getattr(args, "json", False):
        tail.append("--json")
    # Forward each --attach value (repeatable), resolved to an ABSOLUTE path here
    # in the parent: the child may run with a different cwd, and
    # media.validate_attachment() resolves a relative path against cwd, so a
    # relative --attach would silently miss (or hit the wrong file) in the
    # detached child. Without this the attachment was dropped entirely (Qodo).
    for attach_path in getattr(args, "attach", None) or []:
        tail += ["--attach", str(Path(attach_path).resolve())]
    return tail


def _background_child_argv(args: argparse.Namespace, repo: Path) -> list[str]:
    """Rebuild ``work``'s CLI argv for the detached background child (t12).

    The same invocation the parent received, minus ``--background`` (so the
    child runs the ordinary foreground path instead of forking again) and with
    ``--watch`` force-added (auto-arming the flight control plane — the
    detached run's only pilot interface, per spec R4). Built from the parsed
    ``args`` Namespace rather than raw ``sys.argv`` so it is correct whether
    ``work`` was invoked directly or reached via the legacy ``drive`` alias,
    and ``--repo`` always carries the fully resolved absolute path (not
    whatever relative string the caller typed) so the child is unambiguous
    about which repo it targets. Each ``--attach`` value is likewise forwarded
    as a resolved absolute path (not the table-driven flags below — repeatable,
    non-uniform shape) so a relative attachment path still resolves correctly
    against the child's own cwd.
    """
    argv: list[str] = ["work"]
    command_name = getattr(args, "command_name", None)
    if command_name:
        argv += ["--command", command_name]
    argv += list(getattr(args, "instruction", None) or [])
    argv += ["--repo", str(repo)]
    # Table-driven forwarding (order preserved from the CLI surface): "value"
    # appends flag + str(value) when truthy, "bool" appends the bare flag.
    for attr, flag, kind in _CHILD_FLAG_TABLE:
        value = getattr(args, attr, None)
        if kind == "bool":
            if value:
                argv.append(flag)
        elif value:
            argv += [flag, str(value)]
    # Non-uniform tail flags (tri-state --tui, repeatable --attach, etc.) live
    # in a helper so this function stays under the S3776 complexity threshold.
    argv += _child_tail_argv(args)
    # Force-arm the flight control plane: a detached run has no other pilot
    # interface, so --watch is not optional here (spec R4 — the flight feed +
    # 'colleague flight status/guide/stop' is the ONLY way to observe/steer it).
    argv.append("--watch")
    return argv


def _render_background(payload: dict) -> str:
    lines = [
        f"background: {payload['id']}",
        f"pid: {payload['pid']}",
        f"log_dir: {payload['log_dir']}",
        f"flight: {payload['flight'] or '(none)'}",
    ]
    if payload.get("flight"):
        lines.append(f"pilot: colleague flight status {payload['flight']} --repo <repo>")
    return "\n".join(lines)


def _cmd_work_background(args: argparse.Namespace, repo: Path, json_mode: bool) -> int:
    """Detach this work item as a background one-shot child (t12, spec R4 / h10).

    Pre-mints the handle id here (parent side), builds the child's argv (the
    same invocation minus ``--background``, with ``--watch`` force-added), and
    hands off to :func:`colleague.background.spawn_background` — a one-shot
    ``subprocess.Popen(start_new_session=True)`` re-invoking ``python -m
    colleague`` so the child always runs the exact package currently
    executing, never a stale PATH install. Returns immediately with the
    machine-readable start payload; the child runs the ordinary foreground
    work path (:func:`cmd_work` again, this time without ``--background``)
    start to finish entirely on its own — no polling, no daemon.
    """
    handle_id = background.new_handle_id()
    child_argv = _background_child_argv(args, repo)
    handle = background.spawn_background(
        repo,
        [sys.executable, "-m", "colleague", *child_argv],
        handle_id=handle_id,
        flight_id=handle_id,
    )
    payload = handle.to_dict()
    emit_result(payload if json_mode else _render_background(payload), json_mode=json_mode)
    return 0

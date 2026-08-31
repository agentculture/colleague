"""``colleague work``'s argparse surface (flags + help text).

Split out of ``colleague/cli/_commands/work.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t16). ``_add_work_parser``/``register``/
``register_into`` stay in ``work.py`` — they bind ``cmd_work``.
"""

from __future__ import annotations

import argparse

from colleague.cli._commands._listing import register_listing_flags


def _configure_work_parser(p: argparse.ArgumentParser) -> None:
    """Add ``work``'s positional + flags to an already-created parser.

    Shared by the legacy :func:`_add_work_parser` (the pre-flip argparse path)
    and the agentfront host-command ``configure`` hook (:func:`register_into`),
    so the two registration doors build a byte-identical surface. It does NOT
    call ``set_defaults(func=...)``: the legacy path sets ``func=cmd_work`` after
    calling this; the host-command path lets agentfront set ``func=`` to the
    handler it was registered with (also ``cmd_work``).
    """
    # #268 ask 4: the timeout surface is documented where the operator looks for
    # it — `colleague work --help` — not only in the error string after a loss.
    p.epilog = (
        "env knobs: COLLEAGUE_TIMEOUT — seconds per model turn (default 120; a "
        "mid-flight turn timeout or armed backpressure raises it once, bounded "
        "x2, before the flight is failed); COLLEAGUE_CONTEXT_BUDGET — tokens "
        "per turn window (default 48000, sized to the reference rig's served "
        "64K window). `colleague doctor` reports the effective values."
    )
    # ``instruction`` is now zero-or-more positional tokens (nargs="*") so
    # ``--command`` can be the sole input without argparse raising an error.
    p.add_argument(
        "instruction",
        nargs="*",
        help=(
            "A goal or instruction to pursue autonomously.  "
            "Mutually exclusive with --command.  "
            "When --command is used, any positional tokens are passed as template arguments."
        ),
    )
    p.add_argument(
        "--command",
        dest="command_name",
        metavar="NAME",
        default=None,
        help="Expand a saved command template and run it (mutually exclusive with instruction).",
    )
    p.add_argument(
        "--continue",
        "-c",
        dest="continue_ref",
        metavar="ID|last",
        default=None,
        help=(
            "Resume a cut work item (#167): seed this run from its persisted "
            "artifact's continuation record. 'last' resolves the most recent "
            "work item; a completed (ok) item is refused. Positional text "
            "becomes extra guidance appended after the seed."
        ),
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help="Backend plugin to use (default: COLLEAGUE_ENGINE or vllm-openai).",
    )
    p.add_argument("--no-pr", action="store_true", help="Commit locally; do not push or open a PR.")
    p.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Run even when the working tree has uncommitted tracked changes "
            "(they get committed onto the work branch). Default: refuse, to "
            "protect in-progress work (#149)."
        ),
    )
    p.add_argument(
        "--no-lint",
        action="store_true",
        help=(
            "Skip the pre-finish lint gate (by default the repo's configured "
            "linters are run + auto-fixed before handoff; this opts out). Also "
            'via COLLEAGUE_LINT=0 or .colleague/config.json {"lint": false}.'
        ),
    )
    p.add_argument(
        "--no-coherence",
        action="store_true",
        help=(
            "Skip the coherence pre-finish gate (by default changed .md files "
            "are scored via the coherence CLI, advisory/warn-only; this opts "
            'out). Also via COLLEAGUE_COHERENCE=0 or config.json {"coherence": false}.'
        ),
    )
    p.add_argument(
        "--no-affected-tests",
        action="store_true",
        dest="no_affected_tests",
        help=(
            "Skip the pre-finish affected-tests gate (by default the tests that "
            "transitively import the changed module(s) are run before handoff; "
            "this opts out). Also via COLLEAGUE_AFFECTED_TESTS=0 or "
            '.colleague/config.json {"affected_tests": false}.'
        ),
    )
    p.add_argument(
        "--test",
        metavar="PYTEST_ARGS",
        help=(
            "Run this explicit pytest selection as the affected-tests gate "
            "instead of the auto reverse-import selection."
        ),
    )
    p.add_argument("--base", default="main", help="Base branch for the PR (default: main).")
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    register_listing_flags(p)
    p.add_argument(
        "--role",
        default=None,
        help="Run the work item as a typed subagent role (e.g. explorer, reviewer, writer).",
    )
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument("--max-steps", type=int, default=None, help="Override the loop step budget.")
    p.add_argument(
        "--until-done",
        action="store_true",
        dest="until_done",
        help=(
            "Chain bounded episodes until the task finishes ok (or the chain halts: "
            "a non-continuable exit, no progress, or the episode cap). Each episode "
            "is an ordinary work item with its own artifact; push/PR happens ONCE, "
            "at chain end. Also via COLLEAGUE_UNTIL_DONE=1 or .colleague/config.json "
            '{"until_done": true}.'
        ),
    )
    p.add_argument(
        "--max-episodes",
        type=int,
        default=None,
        dest="max_episodes",
        help=(
            "Episode cap for an armed --until-done chain (default 5; 0 = unlimited). "
            'Also via COLLEAGUE_MAX_EPISODES or .colleague/config.json {"max_episodes": N}.'
        ),
    )
    p.add_argument(
        "--cortex-only",
        action="store_true",
        help=(
            "Bypass the senses front door for this run (suppresses the senses media "
            "bridge). A strict no-op when no senses model is resolved. (cortex/senses arc)"
        ),
    )
    p.add_argument(
        "--mode",
        default=None,
        help=(
            "Constraint-profile mode (auto|work|plan|explore|review): applies the "
            "mode's step/context/reserve/timeout/fill-line profile as DEFAULTS — "
            "explicit flags and COLLEAGUE_* env vars still win. Profiles only; the "
            "tool surface is selected by --role."
        ),
    )
    p.add_argument(
        "--tui",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Render a live cockpit (with popups) on stderr during the work item. "
            "Default: auto — on when stderr is an interactive TTY. "
            "Use --no-tui to force the plain 'step N:' lines."
        ),
    )
    p.add_argument(
        "--tui-events",
        metavar="PATH",
        default=None,
        help="Append a live WorkStep JSONL stream to PATH (replay with 'tui replay').",
    )
    p.add_argument("--json", action="store_true", help="Emit the result as structured JSON.")
    p.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Arm a flight-control plane so a pilot can watch/guide/stop "
            "this work item (see 'colleague flight'). Armed by default (#307); "
            "this flag is the explicit alias."
        ),
    )
    p.add_argument(
        "--no-watch",
        action="store_true",
        help=(
            "Do NOT arm the flight-control plane (opt out of the #307 default). "
            "Also settable via COLLEAGUE_WATCH=0 or .colleague/config.json "
            '{"watch": false}.'
        ),
    )
    p.add_argument(
        "--background",
        action="store_true",
        help=(
            "Detach this work item as a one-shot background child (no daemon, "
            "no polling) and return immediately with a JSON start payload "
            "{background, id, pid, log_dir, flight}. Auto-arms --watch so the "
            "detached run is pilotable via 'colleague flight'; a crashed "
            "background run's residue is reaped by 'colleague clean'."
        ),
    )
    p.add_argument(
        "--attach",
        action="append",
        metavar="PATH",
        default=None,
        help=(
            "Attach a media file (image or audio) to the work item. "
            "May be repeated. The file is validated (must exist, known extension) "
            "and passed to the backend as an attachment."
        ),
    )


_WORK_HELP = (
    "Work toward a goal: act autonomously on a request or instruction "
    "through a coder backend, then hand off the result."
)

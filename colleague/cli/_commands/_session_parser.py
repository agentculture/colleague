"""``colleague session``'s argparse surface — help text + flag configuration.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17). Zero ``_Session`` coupling: it only
adds flags to an already-created parser. ``session.py`` re-exports
``_SESSION_HELP`` / ``_SESSION_DESCRIPTION`` / ``_configure_session_parser``,
which its ``register`` (legacy subparser) and ``register_into`` (agentfront
host command) doors both use, and which ``tests/test_session_speak.py`` calls
as ``session_mod._configure_session_parser``.
"""

from __future__ import annotations

import argparse

_SESSION_HELP = (
    "Agent-native interactive cockpit: type a free-text goal and it routes "
    "to work or plan on colleague's own backend — no subcommand needed."
)
_SESSION_DESCRIPTION = (
    "Open the interactive cockpit — the conversational, agent-native entry "
    "point to colleague.  Type a free-text goal and intent routing maps it "
    "to 'work' (the default) or 'plan' automatically; a '→ work:' / '→ plan:' "
    "line confirms the dispatch.  A number or template name runs a work template "
    "directly (never re-classified).  A line starting with '/' is a slash command "
    "(introspection + live config).  The session runs on colleague's OWN served "
    "backend by default (--engine > COLLEAGUE_SESSION_ENGINE > COLLEAGUE_ENGINE > "
    "vllm-openai).  Commit-local by default; /pr or --pr opts into push+PR."
)


def _configure_session_parser(p: argparse.ArgumentParser) -> None:
    """Add ``session``'s flags to an already-created parser.

    Shared by the legacy :func:`register` and the agentfront host-command
    ``configure`` hook (:func:`register_into`). ``session`` is a host command
    (an interactive raw-mode cockpit agentfront's rendered tools can't express);
    this builds an identical flag surface for both doors. The long ``--help``
    description is set on *p* directly so the host-command path (whose
    ``add_parser`` takes only ``help=``) keeps it too. ``func`` is left for the
    caller / agentfront to set to :func:`cmd_session`.
    """
    p.description = _SESSION_DESCRIPTION
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help=(
            "Backend plugin to use.  Precedence: explicit --engine > "
            "COLLEAGUE_SESSION_ENGINE (session-only override) > COLLEAGUE_ENGINE > "
            "vllm-openai (colleague's own served backend)."
        ),
    )
    p.add_argument(
        "--pr",
        action="store_true",
        help="Push and open a PR after each work item (default: commit locally only, no PR).",
    )
    p.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Run work items even when the working tree has uncommitted tracked "
            "changes (they get committed onto the work branch). Default: refuse, "
            "to protect in-progress work (#149)."
        ),
    )
    p.add_argument("--base", default="main", help="Base branch for the PR (default: main).")
    p.add_argument(
        "--cortex-only",
        action="store_true",
        help=(
            "Bypass the senses front door for this session: run cortex-only (no "
            "senses intake or speak-back shaping, no senses media bridge). The "
            "artifact records mode=cortex-only. Byte-identical when no senses "
            "model is resolved. (cortex/senses arc)"
        ),
    )
    p.add_argument(
        "--debug-senses",
        action="store_true",
        help="Print the senses ContextPacket to stderr after each intake (cortex/senses arc).",
    )
    p.add_argument(
        "--voice",
        action="store_true",
        help=(
            "Opt in to the realtime voice lane: while a work item runs, talk to "
            "senses by voice (server-VAD turns) and hear its reply spoken. Needs a "
            "colour TTY + senses armed + a resolved realtime endpoint; /voice "
            "toggles it live. The mic is NEVER hot without this flag or /voice "
            "(c27); realtime unavailable is one honest notice. (realtime-speech arc)"
        ),
    )
    p.add_argument(
        "--speak",
        action="store_true",
        help=(
            "Opt in to the speak-only lane: senses' reply plays as audio after "
            "each turn while you only type — no mic, no realtime session (c7 "
            "stands: this NEVER arms the mic or stt). Needs a resolved tts "
            "endpoint; /speak toggles it live. Default OFF. (speak-only lane, "
            "task t8)"
        ),
    )
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    p.add_argument("--model", default=None, help="Override the engine model name.")
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument("--max-steps", type=int, default=None, help="Override the loop step budget.")
    p.add_argument(
        "--until-done",
        action="store_true",
        dest="until_done",
        help=(
            "Arm episode chaining for EVERY work item this session dispatches: "
            "chain bounded episodes until the task finishes ok (or the chain "
            "halts: a non-continuable exit, no progress, or the episode cap) — "
            "the same semantics as 'work --until-done'; push/PR happens ONCE, at "
            "chain end. Also via COLLEAGUE_UNTIL_DONE=1 or .colleague/config.json "
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
        "--tui",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Render the dynamic ANSI cockpit (default: auto — on a colour TTY). "
            "Use --no-tui for the static Markdown view."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit one JSON TaskResult per work item to stdout; render the cockpit as "
            "chrome to stderr. (The TAUI JSON mirror lives under 'tui state'.)"
        ),
    )

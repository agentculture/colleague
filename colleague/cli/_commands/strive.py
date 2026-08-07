"""``colleague strive`` — bounded-attempt hypothesis-driven iteration (plan t13).

Drives a bounded number of attempts toward a goal, recording schema-enforced
hypothesis ledger entries and detecting novelty stalls. The retry policy lives
in this module, not in ``chain.py``.

Verbs: ``strive <goal> --attempts N --measure <cmd>`` (run),
``strive overview``. Results to stdout, diagnostics to stderr; every verb
supports ``--json``. Failures raise :class:`colleague.cli._errors.CliError`.

Covers: c6, h6, c8, h8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from colleague.cli._commands.overview import emit_overview
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result, rendered
from colleague.config import EngineConfig, resolve_engine
from colleague.contract import Task


def _strive_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Drives bounded attempts toward a goal via hypothesis-ledger iteration",
                "Each attempt declares a delta BEFORE execution — no fabricated progress",
                "Schema-enforced ledger records persist to .colleague/strive/<goal>.json",
                "K consecutive refuted-recombinations = recorded novelty stall",
                "chain.CONTINUABLE_REASONS stays {budget-exhausted}; strive has its own retry policy",
            ],
        },
        {
            "title": "Usage",
            "items": [
                'strive "<goal>" --attempts N --measure "<cmd>" [--engine E] [--json]',
                "strive overview — describe the strive surface",
            ],
        },
    ]


def _render_result(result: dict) -> str:
    lines = [
        f"goal: {result['goal']}",
        f"attempts run: {result['attempts_run']}",
        f"ledger entries: {len(result['ledger_entries'])}",
    ]
    if result.get("novelty_stall"):
        stall = result["novelty_stall"]
        lines.append(f"novelty stall: attempts {stall['start_attempt']}-{stall['end_attempt']}")
        lines.append(f"  repeated hypothesis: {stall['repeated_hypothesis']}")
    return "\n".join(lines)


def _strive_run(
    goal: str,
    attempts: int,
    measure_cmd: str,
    engine: str | None = None,
) -> dict:
    """Run strive for *goal* with *attempts* bounded attempts."""
    from colleague import registry
    from colleague.strive import drive_strive

    if engine is None:
        engine = resolve_engine(None)

    try:
        eng = registry.load(engine)
    except Exception as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"cannot load engine {engine}: {exc}",
            "see 'colleague backends list'",
        ) from exc

    config = EngineConfig.resolve()

    def _dispatch(goal: str, attempt: int, delta: str, hypothesis: str) -> None:
        """Dispatch one attempt via the work-dispatch seam.

        For strive, the dispatch is a simple callable that records the attempt.
        The delta and hypothesis are declared before execution.
        """
        emit_diagnostic(f"attempt {attempt}: delta={delta!r}, hypothesis={hypothesis!r}")

    result = drive_strive(
        goal=goal,
        attempts=attempts,
        measure_cmd=measure_cmd,
        dispatch=_dispatch,
    )
    return result


def cmd_strive_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague strive", _strive_sections(), json_mode=bool(getattr(args, "json", False))
    )
    return 0


def cmd_strive_run(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))

    goal = args.goal
    attempts = args.attempts
    measure_cmd = args.measure

    if attempts < 1:
        raise CliError(
            EXIT_USER_ERROR,
            f"--attempts must be >= 1, got {attempts}",
            "pass --attempts N where N >= 1",
        )

    if not measure_cmd:
        raise CliError(
            EXIT_USER_ERROR,
            "--measure is required",
            'pass --measure "<shell-command>" to evaluate each attempt',
        )

    engine = resolve_engine(getattr(args, "engine", None))

    result = _strive_run(
        goal=goal,
        attempts=attempts,
        measure_cmd=measure_cmd,
        engine=engine,
    )

    emit_result(
        result if json_mode else _render_result(result),
        json_mode=json_mode,
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_strive_overview(args)


_STRIVE_HELP = "Bounded-attempt hypothesis-driven iteration (see 'colleague strive overview')."


def register(sub: argparse._SubParsersAction) -> None:
    """Register the strive verb onto the argparse subparsers."""
    p = sub.add_parser(
        "strive",
        help=_STRIVE_HELP,
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(json=False)
    p.set_defaults(func=_no_verb)

    noun_sub = p.add_subparsers(dest="strive_command", parser_class=type(p))

    run = noun_sub.add_parser("run", help="Run bounded strive attempts toward a goal.")
    run.add_argument("goal", help="The goal to strive toward (e.g. 'make it faster').")
    run.add_argument(
        "--attempts",
        type=int,
        default=3,
        help="Maximum number of attempts (default: 3).",
    )
    run.add_argument(
        "--measure",
        required=True,
        help='Shell command to evaluate each attempt (e.g. "bash bench.sh").',
    )
    run.add_argument(
        "--engine",
        default=None,
        help="Backend engine to use (default: resolved from config).",
    )
    run.add_argument("--json", action="store_true", help=JSON_HELP)
    run.set_defaults(json=False)
    run.set_defaults(func=cmd_strive_run)

    overview = noun_sub.add_parser("overview", help="Describe the strive surface.")
    overview.add_argument("--json", action="store_true", help=JSON_HELP)
    overview.set_defaults(json=False)
    overview.set_defaults(func=cmd_strive_overview)


def register_into(app) -> None:
    """Register the strive verb onto the agentfront App registry."""
    app.tool(
        lambda goal, attempts=3, measure_cmd=None: _strive_run(goal, attempts, measure_cmd),
        name="strive",
        description="Bounded-attempt hypothesis-driven iteration toward a goal.",
        doc="# strive\nBounded-attempt hypothesis-driven iteration: drives attempts "
        "toward a goal with schema-enforced hypothesis ledger records.",
    )

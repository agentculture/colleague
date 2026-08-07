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

from colleague.cli._commands.overview import emit_overview
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result
from colleague.config import resolve_engine


def _strive_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Drives bounded attempts toward a goal via hypothesis-ledger iteration",
                "Each attempt declares a delta BEFORE execution — no fabricated progress",
                "Schema-enforced ledger records persist to .colleague/strive/<goal-hash>.json",
                "K consecutive refuted-recombinations = recorded novelty stall",
                "chain.CONTINUABLE_REASONS stays {budget-exhausted}; retry policy lives here",
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
    repo: str = ".",
) -> dict:
    """Run strive for *goal* with *attempts* bounded attempts.

    The acting leg is REAL (t16): every attempt dispatches one work episode
    via ``Engine.work`` inside a single per-run episode worktree (branch
    ``sub/strive-<goal-slug>``), so attempts accumulate in one workspace and
    the measure command scores exactly the tree the attempts produced — never
    the operator tree. The worktree is removed at the end; the branch (with a
    final WIP commit when the attempts changed anything) survives for
    inspection.
    """
    from colleague import registry, worktrees
    from colleague.config import EngineConfig
    from colleague.contract import Task
    from colleague.slug import slugify
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

    config = EngineConfig().resolve(repo_path=repo)
    child_id = f"strive-{slugify(goal, max_len=32)}"
    try:
        wt_path = worktrees.worktree_add(repo, child_id)
    except Exception as exc:
        raise CliError(
            EXIT_USER_ERROR,
            f"cannot create the strive episode worktree: {exc}",
            "strive needs a git repo (pass --repo)",
        ) from exc

    def _dispatch(goal: str, attempt: int, delta: str, hypothesis: str) -> None:
        """Run one REAL work episode for this attempt, in the episode worktree."""
        emit_diagnostic(f"attempt {attempt}: delta={delta!r}, hypothesis={hypothesis!r}")
        text = f"Strive attempt {attempt} toward the goal: {goal}."
        if delta:
            text += f" Declared delta for this attempt: {delta}."
        else:
            text += " No applicable prior lesson; this is a fresh hypothesis."
        if hypothesis:
            text += f" Hypothesis under test: {hypothesis}."
        task = Task.new(wt_path, text)
        eng.work(task, config)

    try:
        result = drive_strive(
            goal=goal,
            attempts=attempts,
            measure_cmd=measure_cmd,
            dispatch=_dispatch,
            worktree_path=wt_path,
        )
    finally:
        # Preserve whatever the attempts produced on the branch, then reap the
        # worktree — the branch is the durable episode record. Best-effort,
        # but never silent: a failed preserve/reap lands on stderr.
        try:
            worktrees.commit_all(wt_path, f"strive: attempts toward {goal!r}")
        except Exception as exc:
            emit_diagnostic(f"strive: preserving the episode branch failed: {exc}")
        try:
            worktrees.worktree_remove(repo, child_id, delete_branch=False)
        except Exception as exc:
            emit_diagnostic(f"strive: reaping the episode worktree failed: {exc}")
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
        repo=getattr(args, "repo", ".") or ".",
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
    run.add_argument(
        "--repo",
        default=".",
        help="Repository the strive episodes run against (default: cwd).",
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
        lambda goal, attempts=3, measure_cmd=None, repo=".": _strive_run(
            goal, attempts, measure_cmd, repo=repo
        ),
        name="strive",
        description="Bounded-attempt hypothesis-driven iteration toward a goal.",
        doc="# strive\nBounded-attempt hypothesis-driven iteration: drives attempts "
        "toward a goal with schema-enforced hypothesis ledger records.",
    )

"""``colleague experiment`` — detached ``sloth`` training runs (colleague#291 S5).

A host command (like ``flight``/``clean``): the ``experiment start`` verb
must return the moment the detached ``sloth train`` child is launched (never
waiting on it), and every verb ships custom exit codes (0/1/2) rather than the
uniform-tool-success shape a rendered ``app.tool`` provides. Thin presentation
layer over :mod:`colleague.experiment` — this module never touches
``subprocess`` itself (``tests/test_boundary.py``).

Results go to stdout, diagnostics/errors to stderr; every verb supports
``--json``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NoReturn

import colleague.experiment as experiment_mod
from colleague.cli._commands.overview import emit_overview
from colleague.cli._errors import CliError
from colleague.cli._output import JSON_HELP, emit_result

_EXP_ID_HELP = "Experiment id (printed by 'colleague experiment start')."


def _add_repo(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")


def _reraise_as_cli_error(exc: experiment_mod.ExperimentError) -> NoReturn:
    raise CliError(exc.code, exc.message, exc.remediation) from exc


# ---------------------------------------------------------------------------
# experiment overview
# ---------------------------------------------------------------------------


def _experiment_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Drives unsloth-cli's `sloth` CLI: validate a dataset, then detach "
                "`sloth train` with a machine-readable job handle",
                "Status is queryable mid-run; on completion, summarize + optionally "
                "remember the result to eidetic memory",
                "Job-shaped, never a scheduler: one detached child per experiment, "
                "no daemon, no polling loop of colleague's own",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "experiment start --config <toml> [--repo P] — validate then detach "
                "`sloth train`",
                "experiment status <id> [--repo P] — pid liveness + log tail + "
                "best-effort sloth registry correlation",
                "experiment list [--repo P] — every detached experiment, newest-first",
                "experiment summarize <id> [--remember] [--repo P] — join sloth's "
                "training_metadata.json + trainer_state.json; optionally remember it",
                "experiment overview — this description",
            ],
        },
        {
            "title": "Storage",
            "items": [
                "<repo>/.colleague/experiments/<id>/start.json — the start payload",
                "<repo>/.colleague/experiments/<id>/train.log — combined stdout+stderr "
                "of the detached `sloth train` child",
            ],
        },
        {
            "title": "Grading",
            "items": [
                "An experiment id is a valid feedback task_id: "
                "`colleague feedback record <exp-id> --rating N`",
            ],
        },
    ]


def cmd_experiment_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague experiment",
        _experiment_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


# ---------------------------------------------------------------------------
# experiment start
# ---------------------------------------------------------------------------


def cmd_experiment_start(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    try:
        handle = experiment_mod.start_experiment(
            repo, args.config, runs_root=getattr(args, "runs_root", None)
        )
    except experiment_mod.ExperimentError as exc:
        _reraise_as_cli_error(exc)

    payload = handle.to_dict()
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        lines = [
            f"experiment: {payload['id']}",
            f"pid: {payload['pid']}",
            f"config: {payload['config']}",
            f"output_dir: {payload['output_dir']}",
            f"log_dir: {payload['log_dir']}",
            f"started: {payload['started']}",
        ]
        if "runs_root" in payload:
            lines.append(f"runs_root: {payload['runs_root']}")
        emit_result("\n".join(lines), json_mode=False)
    return 0


# ---------------------------------------------------------------------------
# experiment status
# ---------------------------------------------------------------------------


def cmd_experiment_status(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    try:
        status = experiment_mod.experiment_status(repo, args.id)
    except experiment_mod.ExperimentError as exc:
        _reraise_as_cli_error(exc)

    if json_mode:
        emit_result(status, json_mode=True)
    else:
        lines = [
            f"id: {status['id']}",
            f"pid: {status['pid']}",
            f"alive: {status['alive']}",
            f"started: {status['started']}",
        ]
        sloth_run = status.get("sloth_run")
        if sloth_run:
            lines.append(f"sloth_run.status: {sloth_run.get('status')}")
            lines.append(f"sloth_run.run_id: {sloth_run.get('run_id')}")
        else:
            lines.append("sloth_run: (not yet registered / sloth unreachable)")
        log_tail = status.get("log_tail") or []
        if log_tail:
            lines.append("log_tail:")
            lines += [f"  {line}" for line in log_tail]
        emit_result("\n".join(lines), json_mode=False)
    return 0


# ---------------------------------------------------------------------------
# experiment list
# ---------------------------------------------------------------------------


def cmd_experiment_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    entries = experiment_mod.list_experiments(repo)

    if json_mode:
        emit_result(entries, json_mode=True)
        return 0

    if not entries:
        emit_result(f"no experiments found under {repo}/.colleague/experiments/", json_mode=False)
        return 0

    header = f"{'id':<28} {'pid':<8} {'alive':<6} started"
    lines = [header, "-" * len(header)]
    for entry in entries:
        lines.append(
            f"{str(entry.get('id', '?')):<28} {str(entry.get('pid', '?')):<8} "
            f"{str(entry.get('alive', '?')):<6} {entry.get('started', '?')}"
        )
    emit_result("\n".join(lines), json_mode=False)
    return 0


# ---------------------------------------------------------------------------
# experiment summarize
# ---------------------------------------------------------------------------


def cmd_experiment_summarize(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    remember = bool(getattr(args, "remember", False))
    try:
        summary = experiment_mod.summarize_experiment(repo, args.id, remember=remember)
    except experiment_mod.ExperimentError as exc:
        _reraise_as_cli_error(exc)

    if json_mode:
        emit_result(summary, json_mode=True)
        return 0

    lines = [f"output_dir: {summary.get('output_dir')}"]
    metadata = summary.get("metadata")
    if metadata:
        lines.append(f"model:      {metadata.get('model')}")
        lines.append(f"method:     {metadata.get('method')}")
        lines.append(f"dataset:    {metadata.get('dataset')}")
    training = summary.get("training")
    if training:
        lines.append(f"checkpoint:  {training.get('checkpoint')}")
        lines.append(f"final_step:  {training.get('final_step')}")
        lines.append(f"final_loss:  {training.get('final_loss')}")
    for note in summary.get("notes") or []:
        lines.append(f"note: {note}")
    lines.append(f"remembered: {summary.get('remembered')}")
    emit_result("\n".join(lines), json_mode=False)
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

_EXPERIMENT_HELP = (
    "Detached sloth training runs: start/status/list/summarize "
    "(see 'colleague experiment overview')."
)


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_experiment_overview(args)


def _configure_experiment_parser(p: argparse.ArgumentParser) -> None:
    """Add ``experiment``'s ``--json`` + sub-verbs to an already-created parser.

    Shared by the legacy :func:`register` and the host-command ``configure``
    hook. ``experiment`` is a host command, NOT a rendered tool group:
    ``experiment start`` detaches a long-running child and must return custom
    exit codes (0/1/2) sloth-style, which a single-return ``rendered`` tool
    cannot express — mirrors ``colleague/cli/_commands/flight.py``.
    """
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(json=False)
    noun_sub = p.add_subparsers(dest="experiment_command", parser_class=type(p))

    st = noun_sub.add_parser(
        "start", help="Validate a dataset, then detach `sloth train --config <toml>`."
    )
    st.add_argument("--config", required=True, metavar="TOML", help="Path to the sloth run.toml.")
    _add_repo(st)
    st.add_argument(
        "--runs-root",
        dest="runs_root",
        default=None,
        metavar="DIR",
        help="Override the run registry root (default: the output dir's parent).",
    )
    st.add_argument("--json", action="store_true", help=JSON_HELP)
    st.set_defaults(func=cmd_experiment_start)

    stat = noun_sub.add_parser("status", help="Query a detached experiment's live status.")
    stat.add_argument("id", help=_EXP_ID_HELP)
    _add_repo(stat)
    stat.add_argument("--json", action="store_true", help=JSON_HELP)
    stat.set_defaults(func=cmd_experiment_status)

    ls = noun_sub.add_parser("list", help="List every detached experiment, newest-first.")
    _add_repo(ls)
    ls.add_argument("--json", action="store_true", help=JSON_HELP)
    ls.set_defaults(func=cmd_experiment_list)

    su = noun_sub.add_parser(
        "summarize", help="Summarize a recorded experiment; optionally remember it."
    )
    su.add_argument("id", help=_EXP_ID_HELP)
    su.add_argument(
        "--remember",
        action="store_true",
        help="Upsert a compact summary into eidetic memory.",
    )
    _add_repo(su)
    su.add_argument("--json", action="store_true", help=JSON_HELP)
    su.set_defaults(func=cmd_experiment_summarize)

    ov = noun_sub.add_parser("overview", help="Describe the experiment surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_experiment_overview)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("experiment", help=_EXPERIMENT_HELP)
    _configure_experiment_parser(p)
    p.set_defaults(func=_no_verb)


def register_into(app) -> None:
    """Register the ``experiment`` noun-group as an agentfront host command.

    See :func:`_configure_experiment_parser` for why ``experiment`` is a host
    command (the detach-and-return-immediately ``start`` verb + custom exit
    codes). Reuses the existing ``cmd_experiment_*`` handlers verbatim; bare
    ``experiment`` falls through to :func:`_no_verb` (overview).
    """
    app.add_command(
        "experiment", _no_verb, help=_EXPERIMENT_HELP, configure=_configure_experiment_parser
    )

"""``colleague feedback`` — grade a drive after the fact (the ROI loop).

Drive statistics (in the artifact) say what a drive *cost*; feedback says how
*good* it was. ``feedback record`` writes a single 1–5 rating + notes for a drive
(by task-id, or the literal ``last`` for the most recent drive in the repo);
``feedback show`` reads it back; ``feedback overview`` describes the noun
(agent-first rubric: any noun with action-verbs also exposes ``overview``).

Results go to stdout, diagnostics to stderr; every verb supports ``--json``.
Storage is a stdlib JSON file beside the drive artifact — see
:mod:`colleague.feedback`. An ungraded drive is reported as a clean
"no feedback yet" state, never an error.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague import feedback as fb
from colleague.artifact import read_request
from colleague.cli._commands.overview import emit_overview
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result
from colleague.feedback import Feedback, FeedbackError
from colleague.identity import resolve_identity


def _feedback_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Grade a drive after the fact: a 1-5 quality rating + free-text notes",
                "Stats say what a drive cost; feedback says how good it was (ROI)",
                "One record per drive (re-grading overwrites); stored beside the artifact",
                "Reference a drive by its task-id, or 'last' for the most recent drive",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "feedback record <id|last> --rating N [--notes ...] [--by ...] [--repo P]",
                "feedback show <id|last> [--repo P] [--json] — read a drive's feedback",
                "feedback list [--repo P] [--json] — every drive by request + grade",
                "feedback overview — describe the feedback surface (this command)",
            ],
        },
        {
            "title": "Storage",
            "items": [
                "<repo>/.colleague/<task_id>.feedback.json — the single record",
                "<repo>/.colleague/last_drive — pointer resolving 'last'",
                "An ungraded drive reads back as 'no feedback yet' (not an error)",
            ],
        },
    ]


def _render(record: Feedback) -> str:
    return "\n".join(
        [
            f"task:   {record.task_id}",
            f"rating: {record.rating}/{fb.MAX_RATING}",
            f"by:     {record.by or '(unknown)'}",
            f"at:     {record.at}",
            f"notes:  {record.notes}",
        ]
    )


def _resolve(repo: Path, ref: str) -> str:
    try:
        task_id = fb.resolve_task_id(repo, ref)
    except FeedbackError as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), "run a drive first, or pass an explicit task-id"
        ) from exc
    # Transparency: when the caller asked for the ambiguous `last`, surface which
    # drive it landed on (id + request) on stderr — so a mis-resolve (e.g. a
    # later read-only probe) is never silent. Results stay clean on stdout/--json.
    if ref == "last":
        request = read_request(repo, task_id)
        detail = f' — "{request}"' if request else ""
        emit_diagnostic(f"feedback: 'last' resolved to {task_id}{detail}")
    return task_id


def cmd_feedback_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague feedback",
        _feedback_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_feedback_record(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    task_id = _resolve(repo, args.ref)
    resolved = resolve_identity(repo)
    by = args.by or resolved or ""
    # Don't attribute a grade to a silent ``(unknown)``: when neither an explicit
    # ``--by`` nor a repo identity resolves, say so (stderr, never the result) and
    # point at the two fixes. Contextual ``feedback:`` prefix — ``hint:`` is
    # reserved for the ``error:``/``hint:`` rubric pair. The record still writes.
    if not args.by and resolved is None:
        emit_diagnostic(
            "feedback: no identity resolved for this repo; recording 'by' as "
            "(unknown). Pass --by NAME, or add a culture.yaml nick or "
            '.colleague/identity.json "as".'
        )
    try:
        record = fb.write_feedback(repo, task_id, rating=args.rating, notes=args.notes or "", by=by)
    except FeedbackError as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), f"--rating must be {fb.MIN_RATING}-{fb.MAX_RATING}"
        ) from exc

    if json_mode:
        emit_result(record.to_dict(), json_mode=True)
    else:
        emit_result(_render(record), json_mode=False)
    return 0


def cmd_feedback_show(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    task_id = _resolve(repo, args.ref)
    try:
        record = fb.read_feedback(repo, task_id)
    except FeedbackError as exc:
        raise CliError(EXIT_USER_ERROR, str(exc), "the feedback file may be corrupt") from exc

    # Ungraded is a clean state, not an error — both paths exit 0 via a single
    # return (a lone invariant return keeps the handler off SonarCloud S3516).
    if record is None:
        payload: dict = {"task_id": task_id, "feedback": None}
        text = f"no feedback yet for {task_id}"
    else:
        payload = record.to_dict()
        text = _render(record)
    emit_result(payload if json_mode else text, json_mode=json_mode)
    return 0


def _truncate(text: str, width: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _render_listing(rows: list[fb.DriveSummary]) -> str:
    if not rows:
        return "no drives recorded yet"
    header = f"{'ID':<14}{'WHEN':<18}{'STATUS':<8}{'GRADE':<7}REQUEST"
    lines = [header]
    for row in rows:
        when = row.started_at[:16].replace("T", " ") if row.started_at else ""
        grade = f"{row.rating}/{fb.MAX_RATING}" if row.rating is not None else "--"
        lines.append(
            f"{_truncate(row.task_id, 13):<14}{when:<18}{_truncate(row.status, 7):<8}"
            f"{grade:<7}{_truncate(row.request, 48)}"
        )
    return "\n".join(lines)


def cmd_feedback_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    rows = fb.list_drives(repo)
    if json_mode:
        emit_result([r.to_dict() for r in rows], json_mode=True)
    else:
        emit_result(_render_listing(rows), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_feedback_overview(args)


def _add_repo(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "feedback",
        help="Grade a drive after the fact (see 'colleague feedback overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="feedback_command", parser_class=type(p))

    rec = noun_sub.add_parser("record", help="Record a 1-5 rating + notes for a drive.")
    rec.add_argument("ref", help="Drive task-id, or 'last' for the most recent drive.")
    rec.add_argument(
        "--rating",
        type=int,
        required=True,
        help=f"Quality rating ({fb.MIN_RATING}-{fb.MAX_RATING}).",
    )
    rec.add_argument("--notes", default="", help="Free-text feedback notes.")
    rec.add_argument("--by", default="", help="Who is grading (default: resolved identity).")
    _add_repo(rec)
    rec.add_argument("--json", action="store_true", help=JSON_HELP)
    rec.set_defaults(func=cmd_feedback_record)

    sh = noun_sub.add_parser("show", help="Show a drive's feedback record.")
    sh.add_argument("ref", help="Drive task-id, or 'last' for the most recent drive.")
    _add_repo(sh)
    sh.add_argument("--json", action="store_true", help=JSON_HELP)
    sh.set_defaults(func=cmd_feedback_show)

    ls = noun_sub.add_parser("list", help="List recorded drives by request + grade.")
    _add_repo(ls)
    ls.add_argument("--json", action="store_true", help=JSON_HELP)
    ls.set_defaults(func=cmd_feedback_list)

    ov = noun_sub.add_parser("overview", help="Describe the feedback surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_feedback_overview)

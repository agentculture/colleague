"""``colleague feedback`` — grade a work item after the fact (the ROI loop).

Work statistics (in the artifact) say what a work item *cost*; feedback says how
*good* it was. ``feedback record`` writes a single 1–5 rating + notes for a work
item (by task-id, or the literal ``last`` for the most recent work item in the
repo); ``feedback show`` reads it back; ``feedback overview`` describes the noun
(agent-first rubric: any noun with action-verbs also exposes ``overview``).

Results go to stdout, diagnostics to stderr; every verb supports ``--json``.
Storage is a stdlib JSON file beside the work-item artifact — see
:mod:`colleague.feedback`. An ungraded work item is reported as a clean
"no feedback yet" state, never an error.

**This is the reference verb for the "CLI rendered from imported agentfront"
migration.** The verb logic lives in named-parameter functions (``_overview`` /
``_record`` / ``_show`` / ``_list_items``) that return a
:func:`~colleague.cli._output.rendered` value — a dict/list that the
agentfront-rendered CLI emits as JSON under ``--json`` and as pretty text
otherwise, from one return value (a tool function cannot receive ``json_mode``).
``register_into(app)`` registers them as a nested ``feedback`` group on the App
registry (so they appear on the CLI, the MCP catalog, and ``learn`` alike). The
old ``cmd_feedback_*(args)`` handlers are kept as thin adapters that delegate to
the same functions (so the pre-flip argparse path stays byte-identical) until
the live entry is flipped to the rendered CLI; ``register(sub)`` stays until then.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentfront._registry import Flag

from colleague import feedback as fb
from colleague.artifact import read_request
from colleague.cli._commands.overview import render_text
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result, rendered
from colleague.feedback import Feedback, FeedbackError
from colleague.identity import resolve_identity


def _feedback_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Grade a work item after the fact: a 1-5 quality rating + free-text notes",
                "Stats say what a work item cost; feedback says how good it was (ROI)",
                "One record per work item (re-grading overwrites); stored beside the artifact",
                "Reference a work item by its task-id, or 'last' for the most recent work item",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "feedback record <id|last> --rating N [--notes ...] [--by ...] "
                "[--author operator|cortex] [--repo P]",
                "feedback show <id|last> [--author operator|cortex] [--repo P] [--json] — "
                "read a work item's feedback",
                "feedback list [--repo P] [--json] — every work item by request + grade",
                "feedback export [--min-rating N] [--since ISO-DATE] [--format jsonl] "
                "[--repo P] — one JSONL line per GRADED work item (the ROI ledger)",
                "feedback overview — describe the feedback surface (this command)",
            ],
        },
        {
            "title": "Storage",
            "items": [
                "<repo>/.colleague/<task_id>.feedback.json — the operator record (default author)",
                "<repo>/.colleague/<task_id>.<author>.feedback.json — a non-default author's "
                "record (e.g. cortex), coexisting beside the operator's rather than "
                "overwriting it",
                "<repo>/.colleague/last_work — pointer resolving 'last'",
                "An ungraded work item reads back as 'no feedback yet' (not an error)",
            ],
        },
    ]


def _render(record: Feedback) -> str:
    return "\n".join(
        [
            f"task:   {record.task_id}",
            f"rating: {record.rating}/{fb.MAX_RATING}",
            f"author: {record.author}",
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
            EXIT_USER_ERROR, str(exc), "run a work item first, or pass an explicit task-id"
        ) from exc
    # Transparency: when the caller asked for the ambiguous `last`, surface which
    # drive it landed on (id + request) on stderr — so a mis-resolve (e.g. a
    # later read-only probe) is never silent. Results stay clean on stdout/--json.
    if ref == "last":
        request = read_request(repo, task_id)
        detail = f' — "{request}"' if request else ""
        emit_diagnostic(f"feedback: 'last' resolved to {task_id}{detail}")
    return task_id


def _truncate(text: str, width: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _render_listing(rows: list[fb.WorkSummary]) -> str:
    if not rows:
        return "no work items recorded yet"
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


# --- registry tool functions ------------------------------------------------
# Named params (no argparse Namespace), return rendered(structured, text), raise
# CliError on failure. agentfront's dispatch derives the CLI args from the
# signature and emits the return value (--json -> JSON, else the pretty text).


def _overview() -> object:
    sections = _feedback_sections()
    return rendered(
        {"subject": "colleague feedback", "sections": sections},
        render_text("colleague feedback", sections),
    )


def _feedback_error_hint(exc: FeedbackError) -> str:
    """A detail hint for a :class:`FeedbackError`, discriminating rating- vs
    author-shaped failures (both surface through the same try/except)."""
    if "author" in str(exc):
        return f"--author must be one of {', '.join(fb.ALLOWED_AUTHORS)}"
    return f"--rating must be {fb.MIN_RATING}-{fb.MAX_RATING}"


def _record(
    ref: str,
    rating: int = 0,
    notes: str = "",
    by: str = "",
    repo: str = ".",
    author: str = fb.DEFAULT_AUTHOR,
) -> object:
    # `rating` defaults to 0 (out of the valid 1-5 range), so omitting --rating
    # surfaces the same "rating must be 1-5" FeedbackError as an explicit 0 —
    # the argparse `required=True` of the legacy path becomes a value check here.
    repo_path = Path(repo).expanduser()
    task_id = _resolve(repo_path, ref)
    resolved = resolve_identity(repo_path)
    by_val = by or resolved or ""
    # Don't attribute a grade to a silent anonymous author: when neither an
    # explicit ``--by`` nor a repo identity resolves, say so (stderr, never the
    # result) and point at the two fixes. ``by`` is stored as ``""`` (text mode
    # renders that as ``(unknown)``). NOTE: `by` is WHO within an author (e.g.
    # "ori"); `author` is the grade's PROVENANCE (operator|cortex, c17/h14) —
    # the two are independent.
    if not by and resolved is None:
        emit_diagnostic(
            "feedback: no identity resolved for this repo; the grade's 'by' will "
            "be empty. Pass --by NAME, or add a culture.yaml nick or "
            '.colleague/identity.json "as".'
        )
    # Chain-aware grading (indefinite-run c30): when the graded work item is the
    # tail of a ``continued_from`` chain, one record call stamps EVERY episode
    # (grade_chain walks the lineage with a visited-set; cycle/missing-artifact
    # terminate cleanly). A lineage-less work item keeps today's single-record
    # path and persisted shape byte-identical. ``author`` applies to every
    # episode, same as ``rating``/``notes``/``by``.
    try:
        if _continued_from(repo_path, task_id) is not None:
            records = fb.grade_chain(
                repo_path, task_id, rating=rating, notes=notes or "", by=by_val, author=author
            )
            payload = records[0].to_dict()
            payload["chain_episodes"] = [r.task_id for r in records]
            text = (
                _render(records[0])
                + f"\n(chain: graded {len(records)} episodes: "
                + " <- ".join(r.task_id for r in records)
                + ")"
            )
            return rendered(payload, text)
        record = fb.write_feedback(
            repo_path, task_id, rating=rating, notes=notes or "", by=by_val, author=author
        )
    except FeedbackError as exc:
        raise CliError(EXIT_USER_ERROR, str(exc), _feedback_error_hint(exc)) from exc
    return rendered(record.to_dict(), _render(record))


def _continued_from(repo_path: Path, task_id: str) -> str | None:
    """The ``continued_from`` id off ``task_id``'s artifact, or ``None``.

    Best-effort: a missing/corrupt artifact or an absent/blank field all read as
    "not a chain tail" — the single-record grading path handles those exactly as
    before this feature.
    """
    from colleague.artifact import find_artifact

    path = find_artifact(repo_path, task_id)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    parent = data.get("continued_from") if isinstance(data, dict) else None
    if isinstance(parent, str) and parent:
        return parent
    return None


def _show(ref: str, repo: str = ".", author: str = fb.DEFAULT_AUTHOR) -> object:
    repo_path = Path(repo).expanduser()
    task_id = _resolve(repo_path, ref)
    try:
        record = fb.read_feedback(repo_path, task_id, author=author)
    except FeedbackError as exc:
        hint = (
            f"--author must be one of {', '.join(fb.ALLOWED_AUTHORS)}"
            if "invalid author" in str(exc)
            else "the feedback file may be corrupt"
        )
        raise CliError(EXIT_USER_ERROR, str(exc), hint) from exc
    # Ungraded is a clean state, not an error — both paths exit 0.
    if record is None:
        return rendered({"task_id": task_id, "feedback": None}, f"no feedback yet for {task_id}")
    return rendered(record.to_dict(), _render(record))


def _list_items(repo: str = ".") -> object:
    repo_path = Path(repo).expanduser()
    rows = fb.list_work_items(repo_path)
    return rendered([r.to_dict() for r in rows], _render_listing(rows))


_SUPPORTED_EXPORT_FORMATS = ("jsonl",)


def _export(
    min_rating: int = 0,
    since: str = "",
    format: str = "jsonl",
    repo: str = ".",
) -> object:
    """Export every GRADED work item as one JSONL line each (the ROI ledger).

    Ungraded work items are excluded entirely — see docs/contract.md's
    "feedback export" section for the exact line shape. Text mode (the
    default) IS the JSONL: one compact JSON object per line, newline
    terminated, nothing else on stdout. ``--json`` renders the same rows as
    a single JSON array for parity with the other list-shaped verbs.
    """
    if format not in _SUPPORTED_EXPORT_FORMATS:
        raise CliError(
            EXIT_USER_ERROR,
            f"unsupported --format {format!r}",
            f"only {_SUPPORTED_EXPORT_FORMATS[0]!r} is supported in v1 (also the default)",
        )
    since_arg = since or None
    if since_arg is not None and fb.parse_since(since_arg) is None:
        raise CliError(
            EXIT_USER_ERROR,
            f"invalid --since value {since!r}: expected an ISO-8601 date or datetime",
            "e.g. --since 2026-07-01 or --since 2026-07-01T00:00:00+00:00",
        )
    repo_path = Path(repo).expanduser()
    rows = fb.export_work_items(repo_path, min_rating=min_rating or None, since=since_arg)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    text = ("\n".join(lines) + "\n") if lines else ""
    return rendered(rows, text)


def register_into(app) -> None:
    """Register the feedback noun group onto the agentfront App registry."""
    g = app.group("feedback")
    g.tool(
        _overview,
        name="overview",
        description="Describe the feedback surface.",
        doc="# feedback overview\nDescribe the feedback surface (the ROI loop): "
        "what it does, the verbs, and where records are stored.",
    )
    g.tool(
        _record,
        name="record",
        description="Record a 1-5 rating + notes for a work item.",
        doc="# feedback record <id|last> --rating N [--notes ...] [--by ...] "
        "[--author operator|cortex] [--repo P]\n"
        "Record a single 1-5 quality rating (+ notes) for a finished work item. "
        "Re-grading the SAME author overwrites; a DIFFERENT author's record for the "
        "same work item lands beside it instead (c17/h14). Reference by task-id or 'last'.",
    )
    g.tool(
        _show,
        name="show",
        description="Show a work item's feedback record.",
        doc="# feedback show <id|last> [--author operator|cortex] [--repo P] [--json]\n"
        "Read back a work item's feedback for the given author (default operator). "
        "An ungraded work item reads as 'no feedback yet' (not an error).",
    )
    g.tool(
        _list_items,
        name="list",
        description="List recorded work items by request + grade.",
        doc="# feedback list [--repo P] [--json]\n"
        "List every recorded work item, newest first, by request + status + grade.",
    )
    g.tool(
        _export,
        name="export",
        description="Export graded work items as JSONL (the ROI ledger).",
        doc="# feedback export [--min-rating N] [--since ISO-DATE] [--format jsonl] "
        "[--repo P]\nOne JSON line per GRADED work item, newest first; an ungraded "
        "work item is excluded entirely. See docs/contract.md for the exact line "
        "shape. An empty/all-ungraded store exits 0 with no output lines.",
        # `min_rating` needs an explicit Flag so the CLI-facing option is the
        # hyphenated `--min-rating` (a Python identifier can't contain a hyphen);
        # `--since`/`--format` derive directly from their param names.
        flags=(
            Flag(
                names=("--min-rating",),
                type=int,
                dest="min_rating",
                default=0,
                help="Only include work items rated at least N (1-5).",
            ),
        ),
    )


# --- legacy argparse path (pre-flip) ----------------------------------------
# Thin adapters delegating to the registry tool functions so the live argparse
# CLI stays byte-identical until the entry is flipped to the rendered CLI (t8).


def cmd_feedback_overview(args: argparse.Namespace) -> int:
    emit_result(_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_feedback_record(args: argparse.Namespace) -> int:
    emit_result(
        _record(
            args.ref,
            args.rating,
            args.notes,
            args.by,
            args.repo,
            getattr(args, "author", fb.DEFAULT_AUTHOR),
        ),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_feedback_show(args: argparse.Namespace) -> int:
    emit_result(
        _show(args.ref, args.repo, getattr(args, "author", fb.DEFAULT_AUTHOR)),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_feedback_list(args: argparse.Namespace) -> int:
    emit_result(_list_items(args.repo), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_feedback_export(args: argparse.Namespace) -> int:
    emit_result(
        _export(args.min_rating, args.since, args.format, args.repo),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_feedback_overview(args)


def _add_repo(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "feedback",
        help="Grade a work item after the fact (see 'colleague feedback overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="feedback_command", parser_class=type(p))

    rec = noun_sub.add_parser("record", help="Record a 1-5 rating + notes for a work item.")
    rec.add_argument("ref", help="Work-item task-id, or 'last' for the most recent work item.")
    rec.add_argument(
        "--rating",
        type=int,
        required=True,
        help=f"Quality rating ({fb.MIN_RATING}-{fb.MAX_RATING}).",
    )
    rec.add_argument("--notes", default="", help="Free-text feedback notes.")
    rec.add_argument("--by", default="", help="Who is grading (default: resolved identity).")
    rec.add_argument(
        "--author",
        default=fb.DEFAULT_AUTHOR,
        help=f"Grade provenance ({'|'.join(fb.ALLOWED_AUTHORS)}; default: {fb.DEFAULT_AUTHOR}). "
        "A different author's record for the same work item coexists rather than overwrites.",
    )
    _add_repo(rec)
    rec.add_argument("--json", action="store_true", help=JSON_HELP)
    rec.set_defaults(func=cmd_feedback_record)

    sh = noun_sub.add_parser("show", help="Show a work item's feedback record.")
    sh.add_argument("ref", help="Work-item task-id, or 'last' for the most recent work item.")
    sh.add_argument(
        "--author",
        default=fb.DEFAULT_AUTHOR,
        help=f"Grade provenance to read ({'|'.join(fb.ALLOWED_AUTHORS)}; default: "
        f"{fb.DEFAULT_AUTHOR}).",
    )
    _add_repo(sh)
    sh.add_argument("--json", action="store_true", help=JSON_HELP)
    sh.set_defaults(func=cmd_feedback_show)

    ls = noun_sub.add_parser("list", help="List recorded work items by request + grade.")
    _add_repo(ls)
    ls.add_argument("--json", action="store_true", help=JSON_HELP)
    ls.set_defaults(func=cmd_feedback_list)

    ex = noun_sub.add_parser("export", help="Export graded work items as JSONL (the ROI ledger).")
    ex.add_argument(
        "--min-rating",
        dest="min_rating",
        type=int,
        default=0,
        help="Only include work items rated at least N (1-5).",
    )
    ex.add_argument(
        "--since", default="", help="Only include work items on/after this ISO-8601 date."
    )
    ex.add_argument(
        "--format",
        dest="format",
        default="jsonl",
        help="Export line format (only 'jsonl' is supported in v1).",
    )
    _add_repo(ex)
    ex.add_argument("--json", action="store_true", help=JSON_HELP)
    ex.set_defaults(func=cmd_feedback_export)

    ov = noun_sub.add_parser("overview", help="Describe the feedback surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_feedback_overview)

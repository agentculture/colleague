"""``colleague flight`` — pilot a running work item.

The flight noun lets the dispatching agent (Claude or a colleague work-loop)
pilot a running work item: watch its live feed (status), redirect it (guide),
or call it back (stop). Control is cooperative — directives are applied at the
running loop's next turn boundary.

Results go to stdout, diagnostics to stderr; every verb supports ``--json``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import List, Tuple

import colleague.flight as flight
from colleague.cli._commands.overview import emit_overview
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_result

_TASK_ID_HELP = "Task id of the flight (printed by 'colleague work --watch')."


def _checked_task_id(args: argparse.Namespace) -> tuple[Path, str]:
    """Resolve (repo, task_id) and reject an unsafe task id (path traversal)."""
    repo = Path(args.repo).expanduser()
    task_id = args.task_id
    if not flight.is_safe_task_id(task_id):
        raise CliError(EXIT_USER_ERROR, f"invalid flight task id: {task_id!r}")
    return repo, task_id


def _flight_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Pilot a running work item: watch its live feed, redirect it, or stop it",
                "Control is cooperative — applied at the running loop's next turn boundary",
                "Dispatching-agent audience: Claude or a colleague work-loop",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "flight status <task_id> [--repo P] — read the latest feed record",
                "flight guide <task_id> <message> [--repo P] — send guidance to the running loop",
                "flight stop <task_id> [--repo P] — signal the running loop to stop",
                "flight list [--repo P] — list active flight task ids",
                "flight overview — describe the flight surface",
            ],
        },
        {
            "title": "Storage",
            "items": [
                "<repo>/.colleague/flight/<task_id>.feed.jsonl — live feed (JSONL)",
                "<repo>/.colleague/flight/<task_id>.control.json — stop + guidance directives",
            ],
        },
    ]


def cmd_flight_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague flight",
        _flight_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _iter_new_feed_records(path: Path, start_line: int) -> Tuple[List[dict], int]:
    """Return newly parseable records appended since *start_line*, and the new line count.

    Skips blank and corrupt middle lines. A torn/partial trailing line is
    *not* advanced so the next poll re-reads it once the write completes.
    The caller owns the file-read; this function is deterministic (no sleeping,
    no unbounded loop) so it is directly testable.
    """
    if not path.exists():
        return [], start_line
    lines = path.read_text().splitlines()
    records: List[dict] = []
    idx = start_line
    slice_lines = lines[start_line:]
    for i, line in enumerate(slice_lines):
        if not line.strip():
            idx += 1
            continue
        try:
            records.append(json.loads(line))
            idx += 1
        except ValueError:
            if i == len(slice_lines) - 1:
                # Last line: likely torn mid-write; break WITHOUT advancing
                # so the next poll re-reads and emits it once complete.
                break
            # Not the last line: complete-but-corrupt; advance and continue
            # (do NOT break, otherwise a corrupt middle line would wedge the
            # stream in an infinite loop).
            idx += 1
    return records, idx


def _format_record(record: dict, json_mode: bool) -> str:
    """Format a single feed record for output."""
    if json_mode:
        return json.dumps(record, ensure_ascii=False)
    parts = []
    if "step_index" in record:
        parts.append(f"step={record['step_index']}")
    if "tool" in record:
        parts.append(f"tool={record['tool']}")
    if "intent" in record:
        parts.append(f"intent={record['intent']}")
    return " | ".join(parts) if parts else str(record)


def cmd_flight_status(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    follow = bool(getattr(args, "follow", False))

    repo, task_id = _checked_task_id(args)
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        raise CliError(EXIT_USER_ERROR, f"no active flight {task_id}")

    if follow:
        _cmd_flight_status_follow(fp, json_mode)
        return 0

    # One-shot: find the last PARSEABLE non-empty line. An armed flight
    # legitimately has an empty feed before its first turn boundary, and a
    # crash can leave a partial trailing line — neither is an error, so
    # json.loads is guarded.
    record = None
    for line in reversed(fp.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            break
        except ValueError:  # skip a torn/partial trailing line
            continue
    # No record yet (just armed) is a valid state, not "no active flight".
    payload = record if record is not None else {"flight": task_id, "records": 0}
    emit_result(payload, json_mode=json_mode)
    return 0


def _cmd_flight_status_follow(fp: Path, json_mode: bool) -> None:
    """Streaming follow loop: poll for new records until the feed is reaped.

    Terminates cleanly on file removal (flight finished) or KeyboardInterrupt.
    """
    line_pos = 0
    try:
        while True:
            if not fp.exists():
                return
            records, line_pos = _iter_new_feed_records(fp, line_pos)
            for record in records:
                print(_format_record(record, json_mode))
            time.sleep(1.0)
    except KeyboardInterrupt:
        return


def cmd_flight_guide(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo, task_id = _checked_task_id(args)
    message = args.message
    flight.append_guidance(repo, task_id, message)
    payload = {"flight": task_id, "guided": message}
    emit_result(payload, json_mode=json_mode)
    return 0


def cmd_flight_stop(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo, task_id = _checked_task_id(args)
    flight.write_stop(repo, task_id)
    payload = {"flight": task_id, "stopped": True}
    emit_result(payload, json_mode=json_mode)
    return 0


def cmd_flight_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    repo = Path(args.repo).expanduser()
    files = flight.list_flight_files(repo)
    task_ids = sorted(
        f.name[: -len(".feed.jsonl")] for f in files if f.name.endswith(".feed.jsonl")
    )
    payload = {"flights": task_ids}
    emit_result(payload, json_mode=json_mode)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_flight_overview(args)


def _add_repo(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "flight",
        help="Pilot a running work item (see 'colleague flight overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="flight_command", parser_class=type(p))

    st = noun_sub.add_parser("status", help="Read the latest feed record for a flight.")
    st.add_argument("task_id", help=_TASK_ID_HELP)
    _add_repo(st)
    st.add_argument("--json", action="store_true", help=JSON_HELP)
    st.add_argument("--follow", action="store_true", help="Stream feed records as they arrive.")
    st.set_defaults(func=cmd_flight_status)

    gu = noun_sub.add_parser("guide", help="Send guidance to a running flight.")
    gu.add_argument("task_id", help=_TASK_ID_HELP)
    gu.add_argument("message", help="Guidance message for the running loop.")
    _add_repo(gu)
    gu.add_argument("--json", action="store_true", help=JSON_HELP)
    gu.set_defaults(func=cmd_flight_guide)

    sp = noun_sub.add_parser("stop", help="Signal a running flight to stop.")
    sp.add_argument("task_id", help=_TASK_ID_HELP)
    _add_repo(sp)
    sp.add_argument("--json", action="store_true", help=JSON_HELP)
    sp.set_defaults(func=cmd_flight_stop)

    ls = noun_sub.add_parser("list", help="List active flight task ids.")
    _add_repo(ls)
    ls.add_argument("--json", action="store_true", help=JSON_HELP)
    ls.set_defaults(func=cmd_flight_list)

    ov = noun_sub.add_parser("overview", help="Describe the flight surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_flight_overview)

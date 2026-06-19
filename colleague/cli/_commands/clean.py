"""``colleague clean`` — reap what a crashed work item left behind (#162).

A crashed / interrupted ``work --apply`` can leave a dangling ``colleague/<id>``
branch ref pointing at half-written (0-byte) loose objects, which wedges
``git fetch`` / ``git pull`` in the user's repo, plus orphaned 0-byte
``.colleague/`` run artifacts. ``clean`` reaps both — scoped **strictly** to
``colleague/*`` refs and ``.colleague/`` artifacts — restoring the repo with a
single documented command.

By default it reaps only the **corrupt** refs (the fetch breaker) and 0-byte
artifacts; ``--merged`` and ``--older-than`` opt into broader reaping. It is
**conservative with ``.git/objects``**: it *reports* leftover 0-byte loose
objects and suggests ``git prune`` but never deletes them itself.

Thin presentation layer: the git-touching reap logic lives in
:mod:`colleague.handoff` (the sanctioned subprocess consumer) and the
artifact reap in :mod:`colleague.artifact`; this module only orchestrates and
renders. It imports no ``subprocess`` (``tests/test_boundary.py``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague import artifact, flight, handoff, worktrees
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_result

_REAPED = {"reaped", "would-reap", "cleared", "would-clear"}


def cmd_clean(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser()
    if not handoff.is_git_repo(repo):
        raise CliError(
            EXIT_USER_ERROR,
            f"--repo is not a git repository: {repo}",
            "point --repo at a git work tree",
        )
    dry_run = bool(getattr(args, "dry_run", False))
    json_mode = bool(getattr(args, "json", False))

    older_than = getattr(args, "older_than", None)
    # A negative threshold would make `age_days >= older_than` true for every
    # branch — silently reaping all live colleague/* branches. Reject it as a
    # user-input error rather than honor a nonsensical "older than -5 days".
    if older_than is not None and older_than < 0:
        raise CliError(
            EXIT_USER_ERROR,
            f"--older-than must be a non-negative number of days, got {older_than}",
            "pass a positive DAYS value (e.g. --older-than 14)",
        )

    # Reap orphaned isolation worktrees (#222) BEFORE the branch reap: a crashed /
    # SIGKILLed isolated run leaves a .colleague/worktrees/iso-<id> worktree with its
    # colleague/<id> branch checked out, which blocks the branch reap until the
    # worktree is gone. Scoped strictly to iso-* (never a sub/* child or an unrelated
    # worktree); --dry-run reports without removing. The git-touching reap lives in
    # worktrees.py (the sanctioned subprocess consumer), so clean.py stays subprocess-free.
    iso_worktrees = worktrees.reap_orphaned_iso_worktrees(str(repo), dry_run=dry_run)
    branches = handoff.reap_colleague_branches(
        repo,
        dry_run=dry_run,
        include_merged=bool(getattr(args, "merged", False)),
        older_than_days=older_than,
        base_branch=args.base,
    )
    artifacts = artifact.reap_artifacts(repo, dry_run=dry_run)
    # Reap stale flight residue but SPARE a flight that is still running — a
    # recently-written feed/control marks a likely-active flight (no daemon, so
    # mtime is the signal). reap_orphans treats the recent ids as "active".
    active_flights = flight.recent_flight_task_ids(repo)
    flights = [str(p) for p in flight.reap_orphans(repo, active_flights, dry_run=dry_run)]
    empty_objects = handoff.empty_loose_objects(repo)

    report = {
        "repo": str(repo),
        "dry_run": dry_run,
        "iso_worktrees": iso_worktrees,
        "branches": branches,
        "artifacts": artifacts,
        "flights": flights,
        "empty_loose_objects": empty_objects,
    }
    emit_result(report if json_mode else _render(report), json_mode=json_mode)
    return 0


def _render(report: dict) -> str:
    dry = report["dry_run"]
    verb = "would reap" if dry else "reaped"
    reaped_branches = [b for b in report["branches"] if b["action"] in _REAPED]
    kept = [b for b in report["branches"] if b["action"] == "kept"]
    reaped_arts = [a for a in report["artifacts"] if a["action"] in _REAPED]

    header = "colleague clean (dry-run)" if dry else "colleague clean"
    lines = [f"{header} — {report['repo']}"]

    iso_worktrees = report.get("iso_worktrees", [])
    if iso_worktrees:
        lines.append(f"isolation worktrees ({verb}):")
        lines += [f"  - {w}" for w in iso_worktrees]
    if reaped_branches:
        lines.append(f"branches ({verb}):")
        lines += [f"  - {b['ref']} [{b['classification']}]" for b in reaped_branches]
    if reaped_arts:
        lines.append(f"artifacts ({verb}):")
        lines += [f"  - {a['artifact']}" for a in reaped_arts]
    reaped_flights = report.get("flights", [])
    if reaped_flights:
        lines.append(f"flight files ({verb}):")
        lines += [f"  - {f}" for f in reaped_flights]
    if not reaped_branches and not reaped_arts and not reaped_flights and not iso_worktrees:
        lines.append(
            "nothing to reap — no stale colleague/* branches, orphaned .colleague/ "
            "artifacts, or isolation worktrees"
        )
    if kept:
        lines.append(
            f"kept {len(kept)} healthy colleague/* branch(es) "
            "(pass --merged / --older-than DAYS to reap more)"
        )

    empties = report["empty_loose_objects"]
    if empties:
        lines.append("")
        lines.append(
            f"note: {len(empties)} 0-byte loose object(s) remain under .git/objects "
            "(now unreferenced)."
        )
        lines.append(
            "      run 'git prune' to remove them — colleague leaves .git/objects untouched."
        )

    return "\n".join(lines)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "clean",
        help=(
            "Reap stale/corrupt colleague/* branches + orphaned .colleague/ "
            "artifacts left by a crashed work item (see 'colleague explain clean')."
        ),
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be reaped without changing anything.",
    )
    p.add_argument(
        "--merged",
        action="store_true",
        help="Also reap colleague/* branches already merged into --base.",
    )
    p.add_argument(
        "--older-than",
        type=int,
        default=None,
        metavar="DAYS",
        help="Also reap colleague/* branches whose tip commit is older than DAYS.",
    )
    p.add_argument(
        "--base",
        default="main",
        help="Base branch for the merged check (default: main).",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=cmd_clean)

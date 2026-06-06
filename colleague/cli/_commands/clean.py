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

from colleague import artifact, handoff
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

    branches = handoff.reap_colleague_branches(
        repo,
        dry_run=dry_run,
        include_merged=bool(getattr(args, "merged", False)),
        older_than_days=getattr(args, "older_than", None),
        base_branch=args.base,
    )
    artifacts = artifact.reap_artifacts(repo, dry_run=dry_run)
    empty_objects = handoff.empty_loose_objects(repo)

    report = {
        "repo": str(repo),
        "dry_run": dry_run,
        "branches": branches,
        "artifacts": artifacts,
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

    if reaped_branches:
        lines.append(f"branches ({verb}):")
        lines += [f"  - {b['ref']} [{b['classification']}]" for b in reaped_branches]
    if reaped_arts:
        lines.append(f"artifacts ({verb}):")
        lines += [f"  - {a['artifact']}" for a in reaped_arts]
    if not reaped_branches and not reaped_arts:
        lines.append(
            "nothing to reap — no stale colleague/* branches or orphaned .colleague/ artifacts"
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

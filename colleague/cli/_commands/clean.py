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

Also reaps a crashed ``work --background`` one-shot's residue (t12): a
``kill -9``'d detached child leaves its ``.colleague/background/<id>/`` log
dir behind with no supervisor to clean it up; liveness is checked by holder
PID (:func:`colleague.background.reap_background`), so a genuinely
still-running background child is never touched.

Also reaps stale ``colleague experiment`` residue (colleague#291 S5, task
t23): a dead-pid ``.colleague/experiments/<id>/`` dir is reaped only once it
has ALSO aged past a day (:func:`colleague.experiment.reap_experiments`) —
stricter than the background reap because an experiment's start payload +
log ARE its durable record (no separate artifact), so reaping the instant the
pid exits would delete a finished-but-not-yet-summarized experiment. A
genuinely live experiment is never touched.

Also reaps finished-task ledgers (#411 t19): an agents-mode run ledgers at
the OPERATOR repo (``.colleague/ledger/<id>.jsonl``), outside any throwaway
worktree, so the file outlives the run. :func:`colleague.handoff.
reap_finished_ledgers` removes it only once the task's artifact is final
(ok / incomplete / error) or the task is orphaned (dead liveness marker, or
an iso worktree this same ``clean`` just reaped); a live task's ledger
(active flight id / alive liveness marker) is never removed, and a ledger
with no artifact and no liveness opinion is kept.

Thin presentation layer: the git-touching reap logic lives in
:mod:`colleague.handoff` (the sanctioned subprocess consumer), the artifact
reap in :mod:`colleague.artifact`, the background reap in
:mod:`colleague.background`, and the experiment reap in
:mod:`colleague.experiment`; this module only orchestrates and renders. It
imports no ``subprocess`` (``tests/test_boundary.py``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague import artifact, background, experiment, flight, handoff, truncation, worktrees
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

    # A flight whose feed/control was written recently is a likely-active run (no
    # daemon, so mtime is the liveness signal). Computed up front so BOTH the iso
    # worktree reap and the flight reap can spare an in-flight run.
    active_flights = flight.recent_flight_task_ids(repo)
    # Reap orphaned iso-* worktrees (#222) BEFORE the branch reap (a crashed run's
    # checked-out colleague/<id> branch blocks it); scoped to iso-*, sparing an
    # active flight (#228); the git reap lives in worktrees.py (subprocess consumer).
    iso_worktrees = worktrees.reap_orphaned_iso_worktrees(
        str(repo), active_task_ids=active_flights, dry_run=dry_run
    )
    branches = handoff.reap_colleague_branches(
        repo,
        dry_run=dry_run,
        include_merged=bool(getattr(args, "merged", False)),
        older_than_days=older_than,
        base_branch=args.base,
    )
    artifacts = artifact.reap_artifacts(repo, dry_run=dry_run)
    tool_output = truncation.reap_spill_dir(repo, dry_run=dry_run)  # t20: spilled outputs
    # Reap stale flight residue, SPARING a still-running flight (same active-id set).
    flights = [str(p) for p in flight.reap_orphans(repo, active_flights, dry_run=dry_run)]
    # Reap background one-shot residue (t12): a kill -9'd `work --background` child's
    # .colleague/background/<id>/ dir; liveness = holder PID (os.kill(pid, 0)), so a
    # still-running child is never reaped out from under it.
    backgrounds = background.reap_background(repo, dry_run=dry_run)
    # Reap stale `colleague experiment` residue (colleague#291 S5, t23): a
    # dead-pid experiment dir is reaped only once it's ALSO aged past a day
    # (see colleague/experiment.py's reap_experiments docstring for why this
    # differs from the background reap's immediate-on-death rule) — a
    # genuinely live experiment is never touched.
    experiments = experiment.reap_experiments(repo, dry_run=dry_run)
    # Reap finished-task ledgers (#411 t19) AFTER the iso-worktree reap: the
    # ids of the iso worktrees reaped above are orphaned by construction (and
    # that reap already cleared their dead markers), so they bridge into the
    # ledger reap; a task whose artifact is final is reaped on its own evidence;
    # the same active-flight set + an ALIVE marker spare a live task's ledger.
    ledgers = handoff.reap_finished_ledgers(
        repo,
        active_task_ids=active_flights,
        orphaned_task_ids={Path(w).name[len("iso-") :] for w in iso_worktrees},
        dry_run=dry_run,
    )
    empty_objects = handoff.empty_loose_objects(repo)

    report = {
        "repo": str(repo),
        "dry_run": dry_run,
        "iso_worktrees": iso_worktrees,
        "branches": branches,
        "artifacts": artifacts,
        "tool_output": tool_output,
        "flights": flights,
        "background": backgrounds,
        "experiments": experiments,
        "ledgers": ledgers,
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
    spill = report.get("tool_output") or {}
    if spill.get("files"):
        lines.append(
            f"tool-output spill ({verb}): {spill['files']} file(s), {spill['bytes_freed']} B"
        )
    reaped_flights = report.get("flights", [])
    if reaped_flights:
        lines.append(f"flight files ({verb}):")
        lines += [f"  - {f}" for f in reaped_flights]
    reaped_backgrounds = [b for b in report.get("background", []) if b["action"] in _REAPED]
    if reaped_backgrounds:
        lines.append(f"background runs ({verb}):")
        lines += [f"  - {b['background']}" for b in reaped_backgrounds]
    reaped_experiments = [e for e in report.get("experiments", []) if e["action"] in _REAPED]
    if reaped_experiments:
        lines.append(f"experiments ({verb}):")
        lines += [f"  - {e['experiment']}" for e in reaped_experiments]
    reaped_ledgers = report.get("ledgers", [])
    if reaped_ledgers:
        lines.append(f"ledgers ({verb}):")
        lines += [f"  - {led}" for led in reaped_ledgers]
    if (
        not reaped_branches
        and not reaped_arts
        and not reaped_flights
        and not reaped_backgrounds
        and not reaped_experiments
        and not iso_worktrees
        and not reaped_ledgers
        and not spill.get("files")
    ):
        lines.append(
            "nothing to reap — no stale colleague/* branches, orphaned .colleague/ "
            "artifacts, isolation worktrees, dead background runs, dead experiments, "
            "or finished-task ledgers"
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


_CLEAN_HELP = (
    "Reap stale/corrupt colleague/* branches + orphaned .colleague/ "
    "artifacts left by a crashed work item (see 'colleague explain clean')."
)


def _configure_clean_parser(p: argparse.ArgumentParser) -> None:
    """Add ``clean``'s flags to an already-created parser.

    Shared by the legacy :func:`register` and the host-command ``configure`` hook.
    ``clean`` is a host command, not a rendered tool: its flag surface
    (``--dry-run`` / ``--older-than DAYS`` with ``None`` = "no age filter") does
    not map cleanly to signature-derived flags — agentfront would render
    ``--dry_run`` / ``--older_than`` and could not express the ``None`` default.
    Reusing the argparse surface verbatim keeps the flags byte-identical.
    ``func`` is left for the caller / agentfront to set to :func:`cmd_clean`.
    """
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


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("clean", help=_CLEAN_HELP)
    _configure_clean_parser(p)
    p.set_defaults(func=cmd_clean)


def register_into(app) -> None:
    """Register ``clean`` as an agentfront host command.

    See :func:`_configure_clean_parser` for why ``clean`` is a host command (its
    ``--dry-run`` / ``--older-than`` flag surface doesn't map cleanly to
    signature-derived flags). Reuses :func:`cmd_clean`'s ``(args) -> int`` handler
    verbatim.
    """
    app.add_command("clean", cmd_clean, help=_CLEAN_HELP, configure=_configure_clean_parser)

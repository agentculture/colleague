"""handoff_ledger — finished-task ledger reap (split from colleague.handoff).

Split out of :mod:`colleague.handoff` (hard-1000-line-file-limit, t8): the
``.colleague/ledger/<id>.jsonl`` finished/orphaned reap logic (#411 t19) —
no git/subprocess involved, per its own module comment below.
:mod:`colleague.handoff` re-exports every name so existing importers resolve
unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Finished-task ledger reap (#411 t19) — ``.colleague/ledger/<id>.jsonl``.
#
# The agents-mode task ledger lives under the OPERATOR repo (``task.
# flight_repo_path or task.repo_path`` — the flight-plane precedent), never
# inside a throwaway worktree, so it survives the worktree's teardown and
# accumulates. ``colleague clean`` reaps a ledger ONLY once its task is
# provably over: the task's artifact exists with a terminal status (``ok`` /
# ``incomplete`` / ``error`` — the whole closed status set), OR the task is
# orphaned (its iso liveness marker names a dead pid, or the caller just reaped
# its iso worktree). A live task — named in ``active_task_ids`` (the recent
# flight ids) or holding an ALIVE liveness marker — is NEVER touched, and a
# ledger with no artifact and no liveness opinion (an in-place run never stamps
# a marker) is kept: absence of evidence is not evidence of death.
#
# No git/subprocess involved; it sits here because ``clean`` gathers every reap
# from this module (the sanctioned "reap scope" home, see above).
# ---------------------------------------------------------------------------

#: Mirrors ``colleague.agents.state.ledger._LEDGER_SUBDIR`` (pinned by
#: ``tests/test_ledger_reap.py`` against ``ledger_path``).
_LEDGER_SUBDIR = Path(".colleague") / "ledger"

#: An artifact carrying this status is FINAL (the run completed); ``incomplete`` /
#: ``error`` artifacts are RESUMABLE (``work --continue``) and their ledger is the
#: continuation seed (#411 c35) — the reap keeps those.
_TERMINAL_STATUSES = frozenset({"ok"})
_RESUMABLE_STATUSES = frozenset({"incomplete", "error"})


def ledger_dir(repo_path: str | Path) -> Path:
    """``<repo>/.colleague/ledger`` — where agents-mode task ledgers live."""
    return Path(repo_path) / _LEDGER_SUBDIR


def _artifact_status(repo: Path, task_id: str) -> str | None:
    """``task_id``'s artifact status, or ``None`` when it is absent/unparseable.

    A 0-byte / unparseable artifact (a truncated write) has no status — the
    artifact reap handles that file; this helper stays conservative.
    """
    from colleague.artifact import find_artifact  # local: keeps module import order flat

    path = find_artifact(repo, task_id)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    status = data.get("status") if isinstance(data, dict) else None
    return status if isinstance(status, str) else None


def _artifact_is_final(repo: Path, task_id: str) -> bool:
    """True when ``task_id``'s artifact exists, parses, and says the run COMPLETED (``ok``)."""
    return _artifact_status(repo, task_id) in _TERMINAL_STATUSES


def _artifact_is_resumable(repo: Path, task_id: str) -> bool:
    """True when the artifact says ``incomplete`` / ``error`` — a ``work --continue`` seed."""
    return _artifact_status(repo, task_id) in _RESUMABLE_STATUSES


def _liveness_opinion(repo: Path, task_id: str) -> bool | None:
    """``True`` = marker names a live pid, ``False`` = a dead one, ``None`` = no
    (parseable) marker — no opinion either way."""
    from colleague.worktrees import iso_liveness_path, iso_worktree_is_live

    marker = iso_liveness_path(str(repo), task_id)
    try:
        int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return iso_worktree_is_live(str(repo), task_id)


def _ledger_is_reapable(repo: Path, task_id: str, *, active: set, orphaned: set) -> bool:
    """The reap predicate: NOT live, NOT resumable, and (final OR orphaned)."""
    if not task_id or task_id in active:
        return False
    alive = _liveness_opinion(repo, task_id)
    if alive is True or _artifact_is_resumable(repo, task_id):
        return False
    return task_id in orphaned or alive is False or _artifact_is_final(repo, task_id)


def reap_finished_ledgers(
    repo_path: str | Path,
    *,
    active_task_ids: "frozenset[str] | set[str] | tuple[str, ...]" = (),
    orphaned_task_ids: "frozenset[str] | set[str] | tuple[str, ...]" = (),
    dry_run: bool = False,
) -> list[str]:
    """Remove finished/orphaned task ledgers under ``.colleague/ledger/``; return their paths.

    A ``<id>.jsonl`` directly under the ledger dir is reaped when — and only
    when — its task is NOT live, NOT resumable, and is either **final** (its
    artifact parses with status ``ok``, :func:`_artifact_is_final`) or
    **orphaned** (``id`` in ``orphaned_task_ids`` — e.g. the iso worktrees
    ``clean`` just reaped — or its liveness marker names a dead pid). **Live**
    wins over everything: an ``id`` in ``active_task_ids`` or an ALIVE marker
    keeps the ledger. **Resumable** wins next: an ``incomplete`` / ``error``
    artifact means ``work --continue`` can still seed from this ledger (#411
    c35), so it is kept even when orphaned. A ledger with no artifact and no
    marker is kept (a run may still be going). Anything that is not ``*.jsonl``
    directly in the dir is never touched. ``dry_run=True`` reports without
    removing; an unlink failure is skipped (not reported, never raised).
    Missing dir = ``[]``.
    """
    repo = Path(repo_path)
    ldir = ledger_dir(repo)
    if not ldir.is_dir():
        return []
    active = set(active_task_ids)
    orphaned = set(orphaned_task_ids)
    reaped: list[str] = []
    for path in sorted(ldir.glob("*.jsonl")):
        if not path.is_file():
            continue
        task_id = path.name[: -len(".jsonl")]
        if not _ledger_is_reapable(repo, task_id, active=active, orphaned=orphaned):
            continue
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
        reaped.append(str(path))
    return reaped

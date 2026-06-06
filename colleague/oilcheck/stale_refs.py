"""Stale-ref check-group — flag a repo a crashed work item left wedged (#162).

A crashed / interrupted ``work --apply`` can leave a dangling ``colleague/<id>``
branch ref pointing at a missing/0-byte object, which breaks ``git fetch``. This
group surfaces such corrupt ``colleague/*`` refs in the current repo and points
at ``colleague clean`` to reap them.

It is **advisory** (``warning`` severity): a wedged repo never flips ``doctor``
unhealthy — it is a self-heal hint, not a config-readiness gate. The git read is
delegated to :func:`colleague.handoff.list_colleague_branches` (the sanctioned
subprocess consumer), so this module imports no ``subprocess``. Read-only and
never raises — a non-git cwd is a passing no-op.
"""

from __future__ import annotations

from pathlib import Path

from colleague.oilcheck import make_check


def _check_stale_refs() -> dict:
    """Warn (advisory) when the current repo has corrupt ``colleague/*`` refs."""
    try:
        from colleague import handoff

        repo = Path.cwd()
        if not handoff.is_git_repo(repo):
            return make_check(
                "colleague_stale_refs",
                True,
                "info",
                "not a git repo — no colleague/* refs to check",
            )
        corrupt = [b for b in handoff.list_colleague_branches(repo) if b["corrupt"]]
        if not corrupt:
            return make_check(
                "colleague_stale_refs",
                True,
                "info",
                "no stale/corrupt colleague/* refs",
            )
        names = ", ".join(b["ref"] for b in corrupt)
        return make_check(
            "colleague_stale_refs",
            False,
            "warning",
            f"{len(corrupt)} corrupt colleague/* ref(s) — these break git fetch: {names}",
            remediation="run `colleague clean` to reap them (advisory — not a config gate)",
        )
    except Exception as exc:  # noqa: BLE001
        # Contract: never raise — surface an unexpected probe error as a warning
        # so one broken group can't take down the whole report.
        return make_check(
            "colleague_stale_refs",
            False,
            "warning",
            f"colleague/* ref probe failed: {exc}",
            remediation="check git is on PATH and the repo is readable",
        )


def checks() -> list[dict]:
    """Return the stale-ref checks (read-only; never raises)."""
    return [_check_stale_refs()]

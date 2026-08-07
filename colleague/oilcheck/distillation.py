"""Distillation alive-counter check-group — armed-is-not-alive made operator-visible (t11, c28).

Surfaces the distillation alive-counter from recent artifact outcome markers
(``.distill.json`` files next to work-item artifacts in ``.colleague/``).

``distillation_alive`` (info | warning, always emitted)
    Scans ``.colleague/`` (and legacy ``.convertible/``) for ``*.distill.json``
    outcome markers. Counts:

    * **attempts** — every marker with a recognisable ``status`` field
      (``pending``, ``done``, ``dead``) counts as a distillation attempt.
    * **validated** — only markers with ``status == "done"`` AND a non-empty
      ``lesson`` dict count as validated (a lesson that survived validation
      and was remembered).

    When ``attempts > 0`` and ``validated == 0``, emits a ``warning`` — the
    distillation pipeline is armed but not alive (distillation children are
    being launched but none are producing validated lessons). When
    ``validated > 0``, emits ``info/passed`` (distillation is alive).

    The message shows both counts: e.g. "distillation: 3 attempts, 1 validated".

Read-only: reads ``.colleague/`` and ``.convertible/`` directories and parses
``.distill.json`` files. No writes, no network, no subprocess. Never raises.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague.oilcheck import make_check


def _scan_distill_markers(repo_path: str | Path) -> tuple[int, int]:
    """Scan artifact dirs for distill.json markers; return (attempts, validated).

    Searches both ``.colleague/`` and ``.convertible/`` (legacy). A marker is
    counted as an *attempt* when it has a recognisable ``status`` field. It is
    counted as *validated* when ``status == "done"`` AND a non-empty ``lesson``
    dict is present.

    Corrupt or unreadable markers are silently skipped.
    """
    repo = Path(repo_path)
    attempts = 0
    validated = 0

    for dirname in (".colleague", ".convertible"):
        adir = repo / dirname
        if not adir.is_dir():
            continue
        try:
            for marker in adir.glob("*.distill.json"):
                attempts, validated = _count_marker(marker, attempts, validated)
        except OSError:
            pass  # unreadable dir — skip silently

    return attempts, validated


def _count_marker(marker: Path, attempts: int, validated: int) -> tuple[int, int]:
    """Parse one distill.json marker; return updated (attempts, validated).

    A marker counts as an attempt when it has a recognisable ``status`` field.
    It counts as validated when ``status == "done"`` AND ``lesson`` is present
    and non-empty.
    """
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return attempts, validated  # corrupt — skip

    if not isinstance(data, dict):
        return attempts, validated

    status = data.get("status")
    if not isinstance(status, str) or not status:
        return attempts, validated  # no recognisable status — skip

    # Has a recognisable status → counts as an attempt
    attempts += 1

    # Only "done" with a lesson counts as validated
    if status == "done":
        lesson = data.get("lesson")
        if isinstance(lesson, dict) and lesson:
            validated += 1

    return attempts, validated


def checks(repo_path: str | Path = ".") -> list[dict]:
    """Return the distillation alive-counter check (read-only; never raises).

    Parameters
    ----------
    repo_path:
        The repo root whose ``.colleague/`` directory to scan.
    """
    try:
        attempts, validated = _scan_distill_markers(repo_path)

        if attempts == 0:
            return [
                make_check(
                    "distillation_alive",
                    True,
                    "info",
                    "no distillation activity",
                )
            ]

        if validated == 0:
            return [
                make_check(
                    "distillation_alive",
                    False,
                    "warning",
                    f"distillation: {attempts} attempt(s), 0 validated — armed but not alive",
                    remediation=(
                        "check distillation child logs in .colleague/background/; "
                        "verify the distillation author model is reachable; "
                        "see `colleague distill` for manual distillation"
                    ),
                )
            ]

        return [
            make_check(
                "distillation_alive",
                True,
                "info",
                f"distillation: {attempts} attempt(s), {validated} validated",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        # Contract: never raise — surface an unexpected probe error as a warning.
        return [
            make_check(
                "distillation_alive",
                False,
                "warning",
                f"distillation probe failed: {exc}",
                remediation="check .colleague/ is readable",
            )
        ]

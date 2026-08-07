"""Correction-diff capture module — plan task t7, covers c5/h5/h28.

Resolves the squash merge commit from a PR URL via ``gh pr view --json``,
then computes per-file hunks between the work-tip and the merge commit,
scoped to the task's changed files.

Design principles:
- **No daemon, no polling.** One-shot subprocess calls only.
- **Honest degradation.** ANY missing fact (tip SHA, merge commit,
  changed_files) yields a no-diff record naming the missing fact — never
  a diff against a guessed base.
- **Subprocess confinement.** Uses ``subprocess.run`` for ``gh`` and ``git``
  calls; listed in ``tests/test_boundary.py`` ``_SUBPROCESS_ALLOWED``.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 — drives gh + git CLI; sanctioned consumer
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------------
# Missing-fact enum
# ---------------------------------------------------------------------------


class MissingFact(Enum):
    """The facts required for a correction diff, each a first-class missing reason."""

    TIP_SHA = "tip_sha"
    MERGE_SHA = "merge_sha"
    CHANGED_FILES = "changed_files"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffHunk:
    """One file's correction hunk — the verbatim git diff output for that file.

    Attributes
    ----------
    file_path:
        The repo-relative path of the file this hunk covers.
    text:
        The verbatim ``git diff`` output for this file (one or more hunks).
    """

    file_path: str
    text: str


@dataclass
class CorrectionRecord:
    """The outcome of a correction-diff capture attempt.

    When ``ok`` is ``True``, ``hunks`` contains per-file ``DiffHunk`` objects
    scoped to the requested ``changed_files``.  When ``ok`` is ``False``,
    ``missing`` names the facts that were absent and ``note`` explains why.

    Attributes
    ----------
    ok:
        ``True`` when the diff was computed successfully.
    missing:
        The missing facts that prevented a diff (empty when ``ok`` is ``True``).
    hunks:
        Per-file hunks keyed by repo-relative path (empty when ``ok`` is ``False``).
    note:
        A human-readable explanation when ``ok`` is ``False``.
    """

    ok: bool
    missing: list[MissingFact] = field(default_factory=list)
    hunks: dict[str, DiffHunk] = field(default_factory=dict)
    note: str = ""


#: Back-compat alias — some callers may reference the older name.
CorrectionDiff = CorrectionRecord


@dataclass
class CodeLesson:
    """A code-lesson record built from a correction diff hunk.

    The evidence field carries the hunk text **verbatim** — the raw diff is
    the substance.  Interpretation fields (``area``, ``convention``) are
    marked ``origin=model`` because they are model-derived analysis, not
    observed fact.

    Attributes
    ----------
    file_path:
        The file this lesson applies to.
    evidence:
        The verbatim hunk text from the correction diff.
    area:
        The code area or concern this lesson addresses (model interpretation).
    convention:
        The convention or pattern the lesson captures (model interpretation).
    origin:
        Always ``"model"`` — interpretation fields are model-derived.
    confidence:
        Confidence level; defaults to ``"low"`` for correction-derived lessons.
    """

    file_path: str
    evidence: str
    area: str = ""
    convention: str = ""
    origin: str = "model"
    confidence: str = "low"


# ---------------------------------------------------------------------------
# Merge-commit resolution
# ---------------------------------------------------------------------------


def resolve_merge_commit(repo: Path | str, pr_url: str | None) -> str | None:
    """Resolve the squash merge commit SHA from a PR URL.

    Calls ``gh pr view <pr_url> --json mergeCommit`` and extracts the
    ``oid`` field.  Returns ``None`` when:

    - ``pr_url`` is ``None`` (no PR to resolve).
    - ``gh`` is not available on PATH.
    - The ``gh`` command fails (non-zero exit, network error, etc.).
    - The JSON response has no ``mergeCommit.oid`` field.

    This is a one-shot call — no polling, no daemon.
    """
    if not pr_url:
        return None

    if shutil.which("gh") is None:
        return None

    try:
        proc = subprocess.run(  # nosec B603 B607 — fixed 'gh' argv, no shell
            ["gh", "pr", "view", pr_url, "--json", "mergeCommit"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None

        data = json.loads(proc.stdout)
        merge = data.get("mergeCommit")
        if not isinstance(merge, dict):
            return None
        oid = merge.get("oid")
        return oid if isinstance(oid, str) and oid else None
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Diff capture
# ---------------------------------------------------------------------------


def _git_diff_scoped(
    repo: Path | str, tip_sha: str, merge_sha: str, changed_files: list[str]
) -> dict[str, str] | None:
    """Run ``git diff <tip>..<merge> -- <files>`` and return per-file diff text.

    Returns ``None`` when git can't compute the diff (bad SHAs, unreachable
    commits, etc.).  On success, returns a dict mapping each requested file
    to its diff text (only files that actually changed are included).
    """
    if not changed_files:
        return None

    try:
        proc = subprocess.run(  # nosec B603 B607 — fixed 'git' argv, no shell
            ["git", "diff", f"{tip_sha}..{merge_sha}", "--"] + changed_files,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None

        return _parse_diff_output(proc.stdout, changed_files)
    except (subprocess.SubprocessError, OSError):
        return None


def _parse_diff_output(diff_text: str, requested_files: list[str]) -> dict[str, str]:
    """Parse unified diff output into per-file hunks.

    Splits the diff on ``--- a/`` / ``+++ b/`` boundaries to isolate each
    file's hunk text.  Only files in ``requested_files`` are included.
    """
    result: dict[str, str] = {}
    if not diff_text.strip():
        return result

    # Parse unified diff: each file section starts with "--- a/<path>" / "+++ b/<path>"
    # We track file boundaries and collect hunks per file.
    lines = diff_text.splitlines(keepends=True)
    current_file: str | None = None
    current_hunk: list[str] = []

    def _flush() -> None:
        nonlocal current_file, current_hunk
        if current_file and current_hunk and current_file in requested_files:
            result[current_file] = "".join(current_hunk)
        current_file = None
        current_hunk = []

    for line in lines:
        stripped = line.rstrip("\n")
        # Detect file header: "--- a/path" or "+++ b/path"
        if stripped.startswith("--- a/") or stripped.startswith("+++ b/"):
            # If we were tracking a file, flush it
            if current_file is not None:
                _flush()
            # Extract the path (after "--- a/" or "+++ b/")
            path = stripped.split("/", 2)[-1] if "/" in stripped[6:] else stripped[6:]
            current_file = path
            current_hunk = [line]
        elif current_file is not None:
            current_hunk.append(line)
        # Lines before any file header (e.g. binary file notices) are ignored

    # Flush the last file
    if current_file is not None:
        _flush()

    return result


def capture_correction_diff(
    repo: Path | str,
    tip_sha: str | None,
    merge_sha: str | None,
    changed_files: list[str] | None,
) -> CorrectionRecord:
    """Capture the correction diff between a work-tip and its merge commit.

    Computes ``git diff <tip_sha>..<merge_sha> -- <changed_files>`` and returns
    per-file hunks scoped to exactly the requested files.

    **ANY missing fact yields an honest no-diff record** naming the missing
    fact — never a diff against a guessed base.

    Parameters
    ----------
    repo:
        The repository path.
    tip_sha:
        The work branch's tip commit SHA (before merge).
    merge_sha:
        The squash merge commit SHA.
    changed_files:
        The list of repo-relative file paths to scope the diff to.

    Returns
    -------
    CorrectionRecord
        With ``ok=True`` and per-file hunks when all facts are present and
        the diff succeeds; ``ok=False`` with ``missing`` facts named otherwise.
    """
    repo_path = Path(repo)
    missing: list[MissingFact] = []

    # Check each required fact
    if not tip_sha:
        missing.append(MissingFact.TIP_SHA)
    if not merge_sha:
        missing.append(MissingFact.MERGE_SHA)
    if not changed_files:
        missing.append(MissingFact.CHANGED_FILES)

    if missing:
        names = ", ".join(f.value for f in missing)
        return CorrectionRecord(
            ok=False,
            missing=missing,
            hunks={},
            note=f"correction diff unavailable: missing {names}",
        )

    # All facts present — attempt the diff
    diff_map = _git_diff_scoped(repo_path, tip_sha, merge_sha, changed_files)

    if diff_map is None:
        return CorrectionRecord(
            ok=False,
            missing=[],
            hunks={},
            note="correction diff unavailable: git diff failed (bad SHAs or unreachable commits)",
        )

    # Build per-file DiffHunk objects
    hunks: dict[str, DiffHunk] = {
        fp: DiffHunk(file_path=fp, text=text) for fp, text in diff_map.items()
    }

    return CorrectionRecord(
        ok=True,
        missing=[],
        hunks=hunks,
        note="",
    )


# ---------------------------------------------------------------------------
# Code-lesson builder
# ---------------------------------------------------------------------------


def build_code_lesson(
    hunk: DiffHunk,
    *,
    area: str = "",
    convention: str = "",
    confidence: str = "low",
) -> CodeLesson:
    """Build a code-lesson record from a correction diff hunk.

    The hunk text is quoted **verbatim** as the evidence field.  Interpretation
    fields (``area``, ``convention``) are marked ``origin=model`` because they
    represent model-derived analysis, not observed fact.

    Parameters
    ----------
    hunk:
        The diff hunk to build the lesson from.
    area:
        The code area or concern (model interpretation, optional).
    convention:
        The convention or pattern captured (model interpretation, optional).
    confidence:
        Confidence level; defaults to ``"low"``.

    Returns
    -------
    CodeLesson
        With the hunk text as verbatim evidence and ``origin="model"``.
    """
    return CodeLesson(
        file_path=hunk.file_path,
        evidence=hunk.text,
        area=area,
        convention=convention,
        origin="model",
        confidence=confidence,
    )

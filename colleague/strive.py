"""Strive — bounded-attempt hypothesis-driven iteration (plan t13).

Drives a bounded number of attempts toward a goal, recording schema-enforced
hypothesis ledger entries and detecting novelty stalls. The retry policy lives
in this module, not in ``chain.py`` — ``chain.CONTINUABLE_REASONS`` remains
unchanged at ``{"budget-exhausted"}``.

Each attempt declares a delta (the planned change) and a hypothesis (the
expected outcome) BEFORE dispatch. An attempt with no delta or new hypothesis
is recorded as exactly that — no fabricated progress.

The ledger persists to ``.colleague/strive/<goal-hash>.json`` (hex digest
filenames — entries carry the goal verbatim) as a list of
schema-checked dicts. K consecutive attempts whose normalized hypothesis
exactly matches a refuted prior hypothesis = a recorded novelty stall.

Covers: c6, h6, c8, h8
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from colleague.policy import Policy

#: Canonical ledger keys — every record must have exactly these.
_LEADER_KEYS: frozenset[str] = frozenset(
    {
        "goal",
        "attempt",
        "score",
        "hypothesis",
        "test",
        "result",
        "cause",
        "lesson",
        "next_delta",
    }
)

#: Valid result values.
_VALID_RESULTS: frozenset[str] = frozenset({"supported", "refuted"})

#: Default novelty-stall threshold — K consecutive refuted attempts with the
#: same normalized hypothesis triggers a stall record.
DEFAULT_NOVELTY_STALL_K: int = 3


@dataclass
class StriveAttempt:
    """One attempt in a strive run.

    The *delta* (planned change) and *hypothesis* (expected outcome) are
    declared BEFORE dispatch. An attempt with no delta or hypothesis records
    empty strings — never fabricated progress.
    """

    goal: str
    attempt: int
    delta: str = ""
    hypothesis: str = ""


@dataclass
class HypothesisLedger:
    """Persistent, schema-enforced hypothesis ledger.

    Records are stored as dicts with exactly the keys in :data:`_LEADER_KEYS`.
    The ledger persists to ``<ledger_dir>/<goal-hash>.json`` (a hex digest
    of the goal — S2083: no goal text in the path; entries carry the goal).

    Parameters
    ----------
    ledger_dir:
        Directory path for ledger files (e.g. ``.colleague/strive``).
    """

    ledger_dir: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def _path(self, goal: str) -> Path:
        """The ledger file for *goal* — content-addressed, never goal-derived text.

        The filename is a hex digest of the goal (S2083: no user-controlled
        text ever reaches the filesystem path), so any goal string maps to a
        safe constant-alphabet name. Every ledger ENTRY carries the goal
        verbatim, so the mapping stays readable from the file itself.
        """
        return Path(self.ledger_dir) / _ledger_filename(goal)

    def load(self, goal: str) -> None:
        """Load persisted entries for *goal* from disk."""
        path = self._path(goal)
        if not path.exists():
            self.entries = []
            return
        try:
            # The filename is a hex digest (_ledger_filename) — constant
            # alphabet, no goal text can shape this path (S2083).
            self.entries = json.loads(path.read_text(encoding="utf-8"))  # NOSONAR
        except (json.JSONDecodeError, OSError):
            self.entries = []

    def save(self, goal: str) -> None:
        """Persist entries for *goal* to disk."""
        path = self._path(goal)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Hex-digest filename — no user-controlled text in the path (S2083).
        path.write_text(  # NOSONAR
            json.dumps(self.entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def record(self, entry: dict[str, Any]) -> None:
        """Record a schema-checked ledger entry.

        Raises :class:`ValueError` if the entry is missing keys, has extra keys,
        or has an invalid ``result`` value.
        """
        entry_keys = set(entry.keys())
        missing = _LEADER_KEYS - entry_keys
        if missing:
            raise ValueError(f"missing ledger keys: {missing}")
        extra = entry_keys - _LEADER_KEYS
        if extra:
            raise ValueError(f"unexpected ledger keys: {extra}")
        if entry.get("result") not in _VALID_RESULTS:
            raise ValueError(
                f"invalid result {entry.get('result')!r}; must be one of {_VALID_RESULTS}"
            )
        self.entries.append(entry)
        self.save(entry["goal"])

    def novelty_stalls(self, k: int = DEFAULT_NOVELTY_STALL_K) -> list[dict[str, Any]]:
        """Detect novelty stalls: K consecutive refuted attempts with the same
        normalized hypothesis.

        Returns a list of stall dicts with ``start_attempt``, ``end_attempt``,
        and ``repeated_hypothesis``.
        """
        stalls: list[dict[str, Any]] = []
        if len(self.entries) < k:
            return stalls

        i = 0
        while i <= len(self.entries) - k:
            window = self.entries[i : i + k]
            if self._is_novelty_stall(window, k):
                stalls.append(
                    {
                        "start_attempt": window[0]["attempt"],
                        "end_attempt": window[-1]["attempt"],
                        "repeated_hypothesis": _normalize(window[0]["hypothesis"]),
                    }
                )
                i += k  # skip past this stall
            else:
                i += 1
        return stalls

    @staticmethod
    def _is_novelty_stall(window: list[dict[str, Any]], k: int) -> bool:
        """Check if *window* of entries is a novelty stall."""
        if len(window) != k:
            return False
        norm = _normalize(window[0]["hypothesis"])
        for entry in window:
            if entry["result"] != "refuted":
                return False
            if _normalize(entry["hypothesis"]) != norm:
                return False
        return True


def _ledger_filename(goal: str) -> str:
    """The content-addressed ledger filename for *goal* (hex digest + .json)."""
    return hashlib.sha256(goal.encode("utf-8")).hexdigest()[:16] + ".json"


def _slug(goal: str) -> str:
    """Convert a goal string to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")


def _normalize(hypothesis: str) -> str:
    """Normalize a hypothesis for comparison: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", hypothesis.strip().lower())


def _extract_score(returncode: int, output: str) -> float:
    """Extract a numeric score from measure output.

    Returns the last number found in *output* (int or float). When no number
    is found, falls back to *returncode* as the score.

    This is the scoring contract: score = exit code or last printed number.
    """
    numbers = re.findall(r"-?\d+\.?\d*", output)
    if numbers:
        try:
            return float(numbers[-1])
        except ValueError:
            pass
    return float(returncode)


def _run_measure_cmd(
    cmd: str,
    policy: Policy | None = None,
    cwd: str | Path | None = None,
) -> tuple[int, str, bool]:
    """Run a measure command, routing through the approval-gate policy.

    The measure command routes through the same ``check_run_command`` policy
    gate as ``run_command`` — same policy gate, not a sandbox. When the
    ``run_command`` section is absent from the policy (no ``approvals.json``
    or empty policy), the command runs normally (absent-file default unchanged).

    Parameters
    ----------
    cmd:
        Shell command string to execute.
    policy:
        Approval policy to gate the command. When ``None``, defaults to an
        empty (no-op) policy.
    cwd:
        Working directory for the subprocess — should be the episode worktree
        path, never the operator tree.

    Returns
    -------
    A tuple of ``(returncode, stdout, denied)`` where ``denied`` is ``True``
    when the policy gate blocked execution.

    .. warning::
        This is a **policy gate, not a sandbox**. It only inspects the first
        shell token, so it is trivially bypassable by ``sh -c '...'``, pipes,
        command substitution, shell expansion, or an absolute path to a
        renamed binary. It exists to encode operator *intent*, not to contain
        a hostile process. Real isolation is explicitly out of v0 scope.
    """
    if policy is None:
        policy = Policy()

    # Route through the same approval-gate check as run_command.
    verdict = policy.check_run_command(cmd)
    if not verdict.allowed:
        return -1, verdict.reason, True

    try:
        result = subprocess.run(  # nosec B602 - shell by design; trusted operator env (D2)
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(cwd) if cwd else None,
        )
        return result.returncode, result.stdout.strip(), False
    except subprocess.TimeoutExpired:
        return -1, "", False
    except OSError as exc:
        return -1, str(exc), False


def _classify_measure(returncode: int, output: str, denied: bool) -> tuple[float, str, str]:
    """Turn one measure invocation into (score, supported|refuted, cause)."""
    if denied:
        return 0.0, "refuted", f"measure denied by policy: {output}"
    score = _extract_score(returncode, output)
    supported = returncode == 0 and score > 0
    return (
        score,
        "supported" if supported else "refuted",
        f"measure returned {returncode}: {output[:100]}",
    )


def drive_strive(
    *,
    goal: str,
    attempts: int,
    measure_cmd: str,
    dispatch: Callable[[str, int, str, str], None],
    ledger_dir: str | None = None,
    novelty_stall_k: int = DEFAULT_NOVELTY_STALL_K,
    policy: Policy | None = None,
    worktree_path: str | Path | None = None,
) -> dict[str, Any]:
    """Drive bounded attempts toward a goal via the episode machinery.

    For each attempt:
    1. The dispatch callable proposes a delta and hypothesis.
    2. The delta declaration is recorded BEFORE the measure command runs.
    3. The measure command runs inside the episode worktree and produces a score.
    4. The result (supported/refuted) is determined from the score.
    5. The ledger entry is persisted.

    The measure command routes through the same ``check_run_command`` policy
    gate as ``run_command`` (same policy gate, not a sandbox). When the
    ``run_command`` section is absent from the policy, the command runs
    normally (absent-file default unchanged).

    The measure subprocess runs inside *worktree_path* (the episode worktree),
    never the operator tree.

    An attempt with no delta or new hypothesis is recorded as exactly that —
    empty strings, never fabricated progress.

    K consecutive refuted attempts with the same normalized hypothesis = a
    recorded novelty stall.

    Parameters
    ----------
    goal:
        The goal string (e.g. "make it faster").
    attempts:
        Maximum number of attempts to run.
    measure_cmd:
        Shell command to run for measuring each attempt's outcome.
    dispatch:
        Callable that proposes the next attempt's delta and hypothesis.
        Signature: ``dispatch(goal, attempt, delta, hypothesis)``.
        The *delta* and *hypothesis* args are the values the dispatch
        should use for this attempt (may be empty strings).
    ledger_dir:
        Directory for ledger persistence (default: ``.colleague/strive``).
    novelty_stall_k:
        Consecutive refuted threshold for novelty stall detection.
    policy:
        Approval policy to gate the measure command. When ``None``, defaults
        to an empty (no-op) policy.
    worktree_path:
        Working directory for the measure subprocess — the episode worktree.
        When ``None``, the measure runs in the current working directory.

    Returns
    -------
    A dict with ``goal``, ``attempts_run``, ``ledger_entries``, and
    optionally ``novelty_stall`` if a stall was detected.
    """
    if ledger_dir is None:
        ledger_dir = ".colleague/strive"

    ledger = HypothesisLedger(ledger_dir)
    ledger.load(goal)

    result: dict[str, Any] = {
        "goal": goal,
        "attempts_run": 0,
        "ledger_entries": [],
    }

    for attempt_num in range(1, attempts + 1):
        # Get delta/hypothesis from the previous attempt's next_delta, or empty.
        if ledger.entries and ledger.entries[-1].get("next_delta"):
            delta = ledger.entries[-1]["next_delta"]
            hypothesis = ledger.entries[-1].get("hypothesis", "")
        else:
            delta = ""
            hypothesis = ""

        # Record the delta declaration BEFORE dispatch is called.
        # This is the key invariant: the declaration is recorded first.
        entry = {
            "goal": goal,
            "attempt": attempt_num,
            "score": 0.0,
            "hypothesis": hypothesis,
            "test": measure_cmd,
            "result": "refuted",
            "cause": "pending measure",
            "lesson": "",
            "next_delta": "",
        }

        try:
            ledger.record(entry)
        except ValueError:
            pass

        # Now dispatch the attempt.
        dispatch(goal, attempt_num, delta, hypothesis)

        # Run the measure command — routed through the policy gate, in the
        # episode worktree cwd.
        returncode, output, denied = _run_measure_cmd(measure_cmd, policy=policy, cwd=worktree_path)
        score, test_result, cause = _classify_measure(returncode, output, denied)

        # Update the declaration entry in place with the actual result.
        entry["score"] = score
        entry["result"] = test_result
        entry["cause"] = cause
        ledger.save(goal)

        result["ledger_entries"].append(entry)
        result["attempts_run"] = attempt_num

    # Check for novelty stalls.
    stalls = ledger.novelty_stalls(novelty_stall_k)
    if stalls:
        result["novelty_stall"] = stalls[0]

    return result

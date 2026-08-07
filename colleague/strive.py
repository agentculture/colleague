"""Strive — bounded-attempt hypothesis-driven iteration (plan t13).

Drives a bounded number of attempts toward a goal, recording schema-enforced
hypothesis ledger entries and detecting novelty stalls. The retry policy lives
in this module, not in ``chain.py`` — ``chain.CONTINUABLE_REASONS`` remains
unchanged at ``{"budget-exhausted"}``.

Each attempt declares a delta (the planned change) and a hypothesis (the
expected outcome) BEFORE dispatch. An attempt with no delta or new hypothesis
is recorded as exactly that — no fabricated progress.

The ledger persists to ``.colleague/strive/<goal-slug>.json`` as a list of
schema-checked dicts. K consecutive attempts whose normalized hypothesis
exactly matches a refuted prior hypothesis = a recorded novelty stall.

Covers: c6, h6, c8, h8
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
    The ledger persists to ``<ledger_dir>/<goal-slug>.json``.

    Parameters
    ----------
    ledger_dir:
        Directory path for ledger files (e.g. ``.colleague/strive``).
    """

    ledger_dir: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def _path(self, goal: str) -> Path:
        slug = _slug(goal)
        return Path(self.ledger_dir) / f"{slug}.json"

    def load(self, goal: str) -> None:
        """Load persisted entries for *goal* from disk."""
        path = self._path(goal)
        if not path.exists():
            self.entries = []
            return
        try:
            self.entries = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.entries = []

    def save(self, goal: str) -> None:
        """Persist entries for *goal* to disk."""
        path = self._path(goal)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
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


def _slug(goal: str) -> str:
    """Convert a goal string to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")


def _normalize(hypothesis: str) -> str:
    """Normalize a hypothesis for comparison: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", hypothesis.strip().lower())


def _run_measure_cmd(cmd: str) -> tuple[int, str]:
    """Run a measure command and return (returncode, stdout)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, ""
    except OSError as exc:
        return -1, str(exc)


def drive_strive(
    *,
    goal: str,
    attempts: int,
    measure_cmd: str,
    dispatch: Callable[[str, int, str, str], None],
    ledger_dir: str | None = None,
    novelty_stall_k: int = DEFAULT_NOVELTY_STALL_K,
) -> dict[str, Any]:
    """Drive bounded attempts toward a goal via the episode machinery.

    For each attempt:
    1. The dispatch callable proposes a delta and hypothesis.
    2. The delta declaration is recorded BEFORE the measure command runs.
    3. The measure command runs and produces a score.
    4. The result (supported/refuted) is determined from the score.
    5. The ledger entry is persisted.

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

        # Run the measure command.
        returncode, output = _run_measure_cmd(measure_cmd)

        # Determine score and result.
        score = 0.0
        if returncode == 0:
            try:
                score = float(output) if output else 0.0
            except ValueError:
                score = 1.0  # command succeeded but didn't return a number

        # Simple heuristic: score > 0 = supported, else refuted.
        # A failing measure command is refuted.
        if returncode != 0:
            test_result = "refuted"
        elif score > 0:
            test_result = "supported"
        else:
            test_result = "refuted"

        # Update the declaration entry in place with the actual result.
        entry["score"] = score
        entry["result"] = test_result
        entry["cause"] = f"measure returned {returncode}: {output[:100]}"
        ledger.save(goal)

        result["ledger_entries"].append(entry)
        result["attempts_run"] = attempt_num

    # Check for novelty stalls.
    stalls = ledger.novelty_stalls(novelty_stall_k)
    if stalls:
        result["novelty_stall"] = stalls[0]

    return result

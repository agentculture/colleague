"""Strive measure execution tests — approval-gated, episode-worktree cwd (plan t14).

Covers: c7, h7, c33, h27

Test-first: these tests define the contract for the measure execution surface in
``colleague/strive.py`` — the measure command must route through the same
approval-gate check as ``run_command`` and run inside the episode worktree cwd.
"""

from __future__ import annotations

from pathlib import Path

from colleague.policy import Policy
from colleague.strive import (
    _extract_score,
    _run_measure_cmd,
    drive_strive,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy_with_deny(token: str) -> Policy:
    """A Policy whose run_command section explicitly denies *token*."""
    return Policy(
        run_command={"deny": [token], "allow": []},
        present=frozenset({"run_command"}),
    )


def _policy_with_allow(*tokens: str) -> Policy:
    """A Policy whose run_command section only allows the listed *tokens*."""
    return Policy(
        run_command={"allow": list(tokens), "deny": []},
        present=frozenset({"run_command"}),
    )


def _empty_policy() -> Policy:
    """A Policy with no sections — total no-op."""
    return Policy()


# ---------------------------------------------------------------------------
# _extract_score — score = exit code or last printed number
# ---------------------------------------------------------------------------


def test_extract_score_from_exit_code():
    """Score defaults to the exit code when no number is printed."""
    score = _extract_score(returncode=0, output="")
    assert score == 0.0


def test_extract_score_from_exit_code_nonzero():
    """A non-zero exit code is the score when no number is printed."""
    score = _extract_score(returncode=42, output="")
    assert score == 42.0


def test_extract_score_from_last_printed_number():
    """The last printed number on stdout is the score."""
    score = _extract_score(returncode=0, output="tests passed: 42")
    assert score == 42.0


def test_extract_score_from_last_printed_number_multiline():
    """The last number across all lines wins."""
    score = _extract_score(returncode=0, output="step 1: 10\nstep 2: 20\nfinal: 30")
    assert score == 30.0


def test_extract_score_from_float_output():
    """A float in the output is extracted as the score."""
    score = _extract_score(returncode=0, output="score: 0.75")
    assert score == 0.75


def test_extract_score_no_number_uses_exit_code():
    """When no number is found in output, fall back to exit code."""
    score = _extract_score(returncode=1, output="all tests failed")
    assert score == 1.0


def test_extract_score_negative_exit_code():
    """A negative exit code (e.g. signal) is preserved."""
    score = _extract_score(returncode=-1, output="")
    assert score == -1.0


# ---------------------------------------------------------------------------
# _run_measure_cmd — policy gate
# ---------------------------------------------------------------------------


def test_measure_routes_through_policy_gate_allowed(tmp_path: Path):
    """AC1: a measure command whose token is allowed by policy executes normally."""
    policy = _policy_with_allow("echo")

    returncode, output, denied = _run_measure_cmd(
        cmd="echo hello",
        policy=policy,
        cwd=tmp_path,
    )

    assert denied is False
    assert returncode == 0
    assert "hello" in output


def test_measure_routes_through_policy_gate_denied(tmp_path: Path):
    """AC1: a measure command whose token is denied by policy is NOT executed."""
    policy = _policy_with_deny("rm")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("original", encoding="utf-8")

    returncode, output, denied = _run_measure_cmd(
        cmd=f"rm {sentinel}",
        policy=policy,
        cwd=tmp_path,
    )

    # Command was denied — sentinel untouched
    assert denied is True
    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "original"


def test_measure_empty_policy_allows_everything(tmp_path: Path):
    """AC1: with no run_command section (empty policy), measure runs normally."""
    policy = _empty_policy()

    returncode, output, denied = _run_measure_cmd(
        cmd="echo hello",
        policy=policy,
        cwd=tmp_path,
    )

    assert denied is False
    assert returncode == 0
    assert "hello" in output


def test_measure_policy_gate_uses_same_check_as_run_command():
    """AC1: the measure command uses check_run_command, the same method the
    loop uses for run_command tool calls — same policy gate, not a sandbox."""
    policy = _policy_with_deny("curl")

    # Verify the same policy denies both run_command and measure
    run_command_verdict = policy.check_run_command("curl http://example.com")
    assert run_command_verdict.allowed is False

    returncode, output, denied = _run_measure_cmd(
        cmd="curl http://example.com",
        policy=policy,
        cwd="/tmp",
    )

    assert denied is True


def test_measure_absent_file_default_unchanged(tmp_path: Path):
    """AC1: when no approvals.json exists (empty policy), measure runs normally —
    the absent-file default is unchanged, matching run_command behavior."""
    # Empty policy simulates no approvals.json on disk
    policy = _empty_policy()

    returncode, output, denied = _run_measure_cmd(
        cmd="echo no-policy",
        policy=policy,
        cwd=tmp_path,
    )

    assert denied is False
    assert returncode == 0


# ---------------------------------------------------------------------------
# _run_measure_cmd — episode worktree cwd
# ---------------------------------------------------------------------------


def test_measure_runs_in_worktree_cwd(tmp_path: Path):
    """AC2: the measure subprocess cwd is the episode worktree, not the operator tree."""
    # Create a distinct worktree directory
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    operator_tree = tmp_path / "operator"
    operator_tree.mkdir()

    # Put a marker file ONLY in the worktree
    (worktree / "marker.txt").write_text("in-worktree", encoding="utf-8")

    policy = _empty_policy()

    # Run a command that reads from cwd
    returncode, output, denied = _run_measure_cmd(
        cmd="cat marker.txt",
        policy=policy,
        cwd=worktree,
    )

    assert denied is False
    assert returncode == 0
    assert "in-worktree" in output


def test_measure_cwd_is_not_operator_tree(tmp_path: Path):
    """AC2: the measure subprocess does NOT run in the operator tree — a file
    that exists only in the operator tree is not visible to the measure."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    operator_tree = tmp_path / "operator"
    operator_tree.mkdir()

    # Put a marker file ONLY in the operator tree
    (operator_tree / "secret.txt").write_text("operator-only", encoding="utf-8")

    policy = _empty_policy()

    # Try to read the operator-only file from the worktree cwd
    returncode, output, denied = _run_measure_cmd(
        cmd="cat secret.txt",
        policy=policy,
        cwd=worktree,
    )

    # The command should fail because secret.txt is not in the worktree
    assert denied is False
    assert returncode != 0


def test_measure_cwd_isolation_from_operator_tree(tmp_path: Path):
    """AC2: a write in the measure subprocess lands in the worktree, not the
    operator tree — proving cwd isolation."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    operator_tree = tmp_path / "operator"
    operator_tree.mkdir()

    policy = _empty_policy()

    # Write a file via the measure command
    returncode, output, denied = _run_measure_cmd(
        cmd="echo measure-output > measure.log",
        policy=policy,
        cwd=worktree,
    )

    assert denied is False
    assert returncode == 0

    # The file should be in the worktree, not the operator tree
    assert (worktree / "measure.log").exists()
    assert not (operator_tree / "measure.log").exists()


# ---------------------------------------------------------------------------
# drive_strive — integration with policy and worktree
# ---------------------------------------------------------------------------


def test_drive_strive_measure_policy_gate(tmp_path: Path):
    """Integration: drive_strive routes measure through the policy gate."""
    goal = "make it faster"
    policy = _policy_with_deny("echo")

    class CountingDispatch:
        def __init__(self):
            self.calls = []

        def __call__(self, goal, attempt, delta, hypothesis):
            self.calls.append({"attempt": attempt})

    dispatch = CountingDispatch()
    result = drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd="echo 42",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
        policy=policy,
    )

    # The measure was denied, so the attempt still ran but measure was blocked
    assert len(dispatch.calls) == 1
    assert result["attempts_run"] == 1


def test_drive_strive_measure_in_worktree(tmp_path: Path):
    """Integration: drive_strive runs measure in the episode worktree cwd."""
    goal = "make it faster"
    worktree = tmp_path / "episode_worktree"
    worktree.mkdir()

    # Create a marker file in the worktree
    (worktree / "score.txt").write_text("99", encoding="utf-8")

    policy = _empty_policy()

    class CountingDispatch:
        def __init__(self):
            self.calls = []

        def __call__(self, goal, attempt, delta, hypothesis):
            self.calls.append({"attempt": attempt})

    dispatch = CountingDispatch()
    result = drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd="cat score.txt",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
        policy=policy,
        worktree_path=str(worktree),
    )

    assert result["attempts_run"] == 1
    # The measure should have read the file from the worktree
    entry = result["ledger_entries"][0]
    assert entry["score"] == 99.0


def test_drive_strive_measure_worktree_isolation(tmp_path: Path):
    """Integration: measure in drive_strive cannot see files outside the worktree."""
    goal = "make it faster"
    worktree = tmp_path / "episode_worktree"
    worktree.mkdir()

    # Put a file in the operator tree (tmp_path root), NOT in the worktree
    (tmp_path / "operator_file.txt").write_text("operator-only", encoding="utf-8")

    policy = _empty_policy()

    class CountingDispatch:
        def __init__(self):
            self.calls = []

        def __call__(self, goal, attempt, delta, hypothesis):
            self.calls.append({"attempt": attempt})

    dispatch = CountingDispatch()
    result = drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd="cat operator_file.txt",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
        policy=policy,
        worktree_path=str(worktree),
    )

    # The measure should fail because the file is not in the worktree
    entry = result["ledger_entries"][0]
    assert entry["result"] == "refuted"


def test_drive_strive_score_from_exit_code(tmp_path: Path):
    """Score = exit code when no number is printed."""
    goal = "make it faster"
    policy = _empty_policy()

    class CountingDispatch:
        def __init__(self):
            self.calls = []

        def __call__(self, goal, attempt, delta, hypothesis):
            self.calls.append({"attempt": attempt})

    dispatch = CountingDispatch()
    result = drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd="exit 7",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
        policy=policy,
    )

    entry = result["ledger_entries"][0]
    assert entry["score"] == 7.0


def test_drive_strive_score_from_last_printed_number(tmp_path: Path):
    """Score = last printed number when the command outputs one."""
    goal = "make it faster"
    policy = _empty_policy()

    class CountingDispatch:
        def __init__(self):
            self.calls = []

        def __call__(self, goal, attempt, delta, hypothesis):
            self.calls.append({"attempt": attempt})

    dispatch = CountingDispatch()
    result = drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd="echo 'tests passed: 85'",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
        policy=policy,
    )

    entry = result["ledger_entries"][0]
    assert entry["score"] == 85.0


def test_drive_strive_records_score_per_attempt(tmp_path: Path):
    """Each attempt records its own score independently."""
    goal = "make it faster"
    policy = _empty_policy()

    class CountingDispatch:
        def __init__(self):
            self.calls = []

        def __call__(self, goal, attempt, delta, hypothesis):
            self.calls.append({"attempt": attempt})

    dispatch = CountingDispatch()
    result = drive_strive(
        goal=goal,
        attempts=3,
        measure_cmd="echo 10",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
        policy=policy,
    )

    assert len(result["ledger_entries"]) == 3
    for entry in result["ledger_entries"]:
        assert entry["score"] == 10.0

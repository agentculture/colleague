"""Tests for the result-fidelity contract additions (issue #109, task t1).

Verifies that ``colleague.contract`` exposes a stable, importable sentinel
value that callers can use to detect "no output was produced" without
string-matching a step-count summary.
"""

from colleague.contract import NO_RESULT_PRODUCED


def test_no_result_produced_is_importable():
    """The sentinel must be importable from colleague.contract."""
    # Import at module level above; if it fails the whole module errors out,
    # which is itself a clear signal.  This assertion is belt-and-suspenders.
    assert NO_RESULT_PRODUCED is not None


def test_no_result_produced_is_non_empty_string():
    """The sentinel must be a non-empty string so callers can compare safely."""
    assert isinstance(NO_RESULT_PRODUCED, str)
    assert len(NO_RESULT_PRODUCED) > 0


def test_no_result_produced_is_stable():
    """The sentinel value must be exactly the documented string.

    Callers will write ``result.summary == NO_RESULT_PRODUCED``; if the value
    changes their comparisons silently break.  Pin the exact text here.
    """
    assert NO_RESULT_PRODUCED == "no result produced"


def test_no_result_produced_does_not_contain_step_count():
    """The sentinel must not look like a step-count fallback summary.

    The whole point is to give callers something stable to branch on that is
    NOT the "completed in N step(s)" string — verify the sentinel is distinct.
    """
    assert "step" not in NO_RESULT_PRODUCED
    assert "completed" not in NO_RESULT_PRODUCED

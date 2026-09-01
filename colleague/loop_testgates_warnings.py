"""Gate warnings on non-finished outcomes (#480).

Extracted from ``colleague/loop_testgates.py`` to stay under its file-length
ratchet baseline (repo convention: a near-baseline module gets a small
sibling rather than growing past it). A pure move of two small warning-shape
builders — no behaviour lives here beyond dict construction.

Both the affected-tests and test-integrity gates already run — and record
their report on ``TaskResult`` — on EVERY loop exit outcome; only their
bounded fix-turn is gated on a clean finish (``outcome == _EXIT_FINISHED``).
But a FAILED report never carried a ``TaskResult.warnings`` entry when the
outcome wasn't a clean finish (colleague#480 / run ``cc5d1f1a2c5f``): the
operator saw zero fix turns and an empty ``warnings`` list, and never learned
the branch was broken. These two builders give each gate's failure state the
same named ``{'kind': ..., ...}`` shape the step-stall / loop-guard warnings
already use (:mod:`colleague.loop_transport`, :mod:`colleague.loopguards`).
"""

from __future__ import annotations

import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from colleague import affectedtests as _affectedtests
    from colleague import testintegrity as _testintegrity


def build_affected_tests_warning(report: "_affectedtests.AffectedTestsReport") -> dict[str, Any]:
    """The ``affected-tests-failed`` warning (#480 AC1), naming the selection so
    the operator can see WHICH tests broke without opening the full report."""
    return {
        "kind": "affected-tests-failed",
        "selection": list(report.selected),
        "failed": report.failed,
        "passed": report.passed,
    }


def build_test_integrity_warning(report: "_testintegrity.TestIntegrityReport") -> dict[str, Any]:
    """The ``test-integrity-flagged`` warning (#480 AC2) — the analogous shape for
    the test-integrity gate's identical non-finished-outcome silent-failure
    pattern (``loop_testgates.py``:197), naming the flagged symbols."""
    return {
        "kind": "test-integrity-flagged",
        "symbols": [f.symbol for f in report.findings],
        "count": len(report.findings),
    }


def surface_affected_tests(report: "_affectedtests.AffectedTestsReport") -> None:
    """Write the affected-tests summary to stderr (advisory; never raises)."""
    with suppress(OSError):
        sys.stderr.write(report.summary_line() + "\n")


def surface_test_integrity(report: "_testintegrity.TestIntegrityReport") -> None:
    """Write the mirror-signature findings to stderr (advisory; never raises)."""
    detail = "; ".join(
        f"{f.symbol} ({f.kind}) co-introduced in {f.test_file} & {f.impl_file}"
        for f in report.findings
    )
    with suppress(OSError):
        sys.stderr.write(
            "test-integrity: possible self-confirming test(s) — mirror signature "
            f"flagged: {detail}\n"
        )

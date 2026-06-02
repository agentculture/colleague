"""_report.py — shared check-dict factory and aggregation for doc-test-alignment.

All check modules in checks/ use make_check() to build check dicts. The
aggregate() function computes the top-level alignment verdict.
"""

from __future__ import annotations

__all__ = ["SEVERITIES", "make_check", "aggregate"]

SEVERITIES = ("error", "warning", "info")
_SEVERITIES_SET = frozenset(SEVERITIES)


def make_check(
    id: str,  # noqa: A002 - "id" is the contract key name
    passed: bool,
    severity: str,
    message: str,
    remediation: str = "",
) -> dict:
    """Construct a contract-shaped check dict.

    Returns exactly: {"id", "passed", "severity", "message", "remediation"}.

    Raises ValueError if severity is not one of SEVERITIES.
    """
    if severity not in _SEVERITIES_SET:
        raise ValueError(
            f"invalid severity {severity!r}; expected one of {sorted(_SEVERITIES_SET)}"
        )
    return {
        "id": id,
        "passed": passed,
        "severity": severity,
        "message": message,
        "remediation": remediation,
    }


def aggregate(checks: list) -> dict:
    """Aggregate a flat list of check dicts into a top-level verdict.

    Returns {"aligned": bool, "checks": checks}.

    aligned is False iff at least one check has severity=="error" AND passed is False.
    Failed warning/info checks never flip alignment.
    """
    aligned = not any(c["severity"] == "error" and not c["passed"] for c in checks)
    return {"aligned": aligned, "checks": checks}

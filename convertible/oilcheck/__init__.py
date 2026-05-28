"""oilcheck — the configuration-readiness health spine behind ``convertible doctor``.

This package is the **chassis-level** home for health diagnostics, the same way
:mod:`convertible.telemetry` is the chassis-level home for GPS. The ``doctor``
CLI verb (:mod:`convertible.cli._commands.doctor`) is the thin presentation
layer; *all* the diagnostic logic lives here so it can be reused, tested, and
extended without touching the CLI.

The check-group contract (READ THIS BEFORE WRITING A GROUP)
===========================================================
oilcheck aggregates many small, independent **check-groups** into one report.
Five sibling modules each own one group; this docstring is their spec.

A **check** is a plain ``dict`` with *exactly* five keys:

* ``id`` — ``str``, unique across the whole report, ``snake_case`` (e.g.
  ``provider_base_url``). Two groups must not emit the same id.
* ``passed`` — ``bool``. ``True`` means the invariant holds.
* ``severity`` — one of ``"error"``, ``"warning"``, ``"info"``. Only a
  **failed** ``"error"`` (``passed is False``) makes the whole report
  unhealthy. ``"warning"`` and ``"info"`` are advisory and never flip health,
  even when they fail. ``"info"`` is for facts/observations, not pass/fail
  gates (use ``passed=True`` for an info you are merely reporting).
* ``message`` — ``str``, a one-line human summary of what was observed.
* ``remediation`` — ``str``, what the operator should *do* about it. It MUST be
  the empty string when ``passed`` is ``True`` (there is nothing to remediate);
  give a concrete, actionable hint when ``passed`` is ``False``.

Build checks with :func:`make_check`, which enforces this shape::

    from convertible.oilcheck import make_check

    def checks() -> list[dict]:
        return [make_check("git_on_path", True, "info", "git found")]

A **check-group** is a module exposing a single top-level callable::

    def checks() -> list[dict]:
        ...

with these contract obligations:

* It returns a ``list`` of zero or more check dicts (an empty list is valid —
  the group simply had nothing to report).
* It is **read-only**: it must not write files, mutate state, open sockets, or
  make network calls. Probing config, the filesystem (reads), env vars, and
  entry-point metadata is fine.
* It **must never raise.** A group that hits an unexpected error must catch it
  and turn it into a failed check (typically ``severity="error"``) describing
  the failure, so one broken group cannot take down the whole report. The
  aggregator does not wrap groups in try/except — robustness is the group's job
  (and is what keeps the failure legible: the operator sees *which* group
  failed and why, as a check, rather than a stack trace).

Registration
============
:data:`CHECK_GROUPS` is an **ordered** list of the groups' ``checks`` callables.
Order is the report order. A new group is wired by importing its module and
appending its ``checks`` to this list. The order is deliberate: identity first
(who am I), then the engine/provider plumbing, then observability, then the
broader environment.

The aggregator
==============
:func:`diagnose` runs every registered group in order, concatenates their
checks into one flat list, and computes ``healthy`` from the severity rule
above. Its return value is the exact rubric shape the agent-first contract
expects: ``{"healthy": bool, "checks": [...]}``.
"""

from __future__ import annotations

from typing import Callable, List

__all__ = ["make_check", "diagnose", "CHECK_GROUPS"]

# Severities the contract allows. A failed check of severity "error" is the
# only thing that flips a report unhealthy.
_SEVERITIES = frozenset({"error", "warning", "info"})

# A check-group is a zero-argument callable returning a list of check dicts.
CheckGroup = Callable[[], List[dict]]


def make_check(
    id: str,  # noqa: A002 - "id" is the contract key name; shadowing builtins is intentional here.
    passed: bool,
    severity: str,
    message: str,
    remediation: str = "",
) -> dict:
    """Construct a contract-shaped check dict.

    The single helper every check-group should use so the five-key shape and
    the severity vocabulary stay consistent across groups. ``remediation``
    defaults to ``""`` (the required value when ``passed`` is ``True``).
    """
    if severity not in _SEVERITIES:
        raise ValueError(f"invalid severity {severity!r}; expected one of {sorted(_SEVERITIES)}")
    return {
        "id": id,
        "passed": passed,
        "severity": severity,
        "message": message,
        "remediation": remediation,
    }


# Submodule imports come *after* make_check is defined: each group module does
# ``from convertible.oilcheck import make_check`` at import time, so make_check
# must already be bound on the package when these run. (identity imports it; the
# stubs do not yet, but the spec tells siblings to — keep the order.)
from convertible.oilcheck import (  # noqa: E402 - must follow make_check (see above).
    engines,
    environment,
    identity,
    otel,
    provider,
)

# Ordered registry of check-groups. Identity first (who am I), then the
# engine/provider plumbing, then observability, then the broader environment.
# Sibling agents fill in the stub groups; the order here is the report order.
CHECK_GROUPS: List[CheckGroup] = [
    identity.checks,
    provider.checks,
    engines.checks,
    otel.checks,
    environment.checks,
]


def diagnose() -> dict:
    """Run every registered check-group and aggregate one health report.

    Runs the groups in :data:`CHECK_GROUPS` order, concatenates their checks
    into one flat list, and computes health: the report is **unhealthy** iff at
    least one check has ``severity == "error"`` and ``passed is False``.
    Warnings and info never flip health, even when they fail.

    Returns the rubric shape ``{"healthy": bool, "checks": list[dict]}``.
    Read-only: it neither writes files nor opens sockets (each group is
    contractually read-only, and the aggregator only concatenates).
    """
    checks: List[dict] = []
    for group in CHECK_GROUPS:
        checks.extend(group())
    healthy = not any(c["severity"] == "error" and not c["passed"] for c in checks)
    return {"healthy": healthy, "checks": checks}

"""oilcheck — the configuration-readiness health spine behind ``colleague doctor``.

This package is the **runtime-level** home for health diagnostics, the same way
:mod:`colleague.telemetry` is the runtime-level home for telemetry. The ``doctor``
CLI verb (:mod:`colleague.cli._commands.doctor`) is the thin presentation
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

    from colleague.oilcheck import make_check

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
    if passed and remediation:
        raise ValueError("remediation must be empty when passed is True")
    return {
        "id": id,
        "passed": passed,
        "severity": severity,
        "message": message,
        "remediation": remediation,
    }


# Submodule imports come *after* make_check is defined: each group module does
# ``from colleague.oilcheck import make_check`` at import time, so make_check
# must already be bound on the package when these run. (identity imports it; the
# stubs do not yet, but the spec tells siblings to — keep the order.)
from colleague.oilcheck import (  # noqa: E402 - must follow make_check (see above).
    engines,
    environment,
    identity,
    otel,
    provider,
    stale_refs,
    usage,
)

# Ordered registry of check-groups. Identity first (who am I), then the
# backend/provider plumbing (provider config, usage-readiness, backend plugins),
# then observability, then the broader environment. The order here is the report
# order. Every group registered here is contractually read-only and opens no
# socket / makes no network call (see the check-group contract above) — the
# opt-in reachability probe (``diagnose(probe=True)``) is deliberately NOT a
# registered group for exactly that reason.
CHECK_GROUPS: List[CheckGroup] = [
    identity.checks,
    provider.checks,
    usage.checks,
    engines.checks,
    otel.checks,
    environment.checks,
    stale_refs.checks,
]


def diagnose(probe: bool = False) -> dict:
    """Run every registered check-group and aggregate one health report.

    Runs the groups in :data:`CHECK_GROUPS` order, concatenates their checks
    into one flat list, and computes health: the report is **unhealthy** iff at
    least one check has ``severity == "error"`` and ``passed is False``.
    Warnings and info never flip health, even when they fail.

    When ``probe`` is ``True`` (``colleague doctor --probe``), the opt-in
    :mod:`colleague.oilcheck.reachability` group is appended *after* the
    registered groups. It is the deliberate, documented exception to the
    "groups open no socket / make no network call" rule — a live provider ping —
    so it is invoked here explicitly rather than being registered in
    :data:`CHECK_GROUPS`. Off by default the diagnosis stays fully no-network.

    Returns the rubric shape ``{"healthy": bool, "checks": list[dict]}``.
    Read-only by default: it neither writes files nor opens sockets (each
    registered group is contractually read-only, and the aggregator only
    concatenates); only the opt-in ``probe`` path touches the network.
    """
    checks: List[dict] = []
    for group in CHECK_GROUPS:
        checks.extend(group())
    if probe:
        # Imported lazily so the no-network default path never even loads the
        # module that knows how to open a connection.
        from colleague.oilcheck import reachability

        checks.extend(reachability.checks())
    healthy = not any(c["severity"] == "error" and not c["passed"] for c in checks)
    return {"healthy": healthy, "checks": checks}

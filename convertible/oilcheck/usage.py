"""Usage-readiness check-group — will a bare drive actually do real work?

This group answers the question ``doctor`` previously could not: *which engine
will a bare ``convertible drive`` / ``convertible session`` pick, and is it a
real one?* (issue #53 — "doctor reported healthy while the tool was unusable
because the default engine was the no-op mock").

``usage_effective_engine`` (info | warning, always emitted)
    Resolves the engine a bare invocation would select (no ``--engine`` flag) via
    :func:`convertible.config.resolve_engine`. Reports it as ``info`` when it is a
    real engine; emits a ``warning`` when it is ``mock`` (the no-op contract
    reference, which writes a canned marker file and never calls a model). A
    warning is advisory — it surfaces a visible ``[FAIL]`` line in ``doctor``
    output but never flips the report unhealthy (config gaps are advisory).

Read-only: resolves config from env + defaults only; opens no connection.
Catches any unexpected error and returns it as a single failed ``warning`` check
rather than raising.
"""

from __future__ import annotations

from convertible.config import resolve_engine
from convertible.oilcheck import make_check


def checks() -> list[dict]:
    """Return usage-readiness checks (see module docstring)."""
    try:
        return _checks()
    except Exception as exc:  # pragma: no cover — safety net; normal paths don't raise
        return [
            make_check(
                "usage_effective_engine",
                False,
                "warning",
                f"engine resolution failed: {exc}",
                remediation="check the CONVERTIBLE_ENGINE env var and re-run doctor",
            )
        ]


def _checks() -> list[dict]:
    # What a bare ``drive``/``session`` (no --engine flag) would resolve to.
    engine = resolve_engine(None)

    if engine == "mock":
        return [
            make_check(
                "usage_effective_engine",
                False,
                "warning",
                (
                    "effective engine is 'mock' (a no-op contract reference); "
                    "real drives will not call a model — they only write a marker file"
                ),
                remediation=(
                    "set CONVERTIBLE_ENGINE=vllm-openai (or pass --engine <name>) to "
                    "drive a real model; list engines with: convertible wheels list"
                ),
            )
        ]

    return [
        make_check(
            "usage_effective_engine",
            True,
            "info",
            f"effective engine: {engine!r} (a bare drive/session uses this)",
        )
    ]

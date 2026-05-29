"""Opt-in provider-reachability probe (``convertible doctor --probe``).

This module is the **deliberate exception** to the oilcheck check-group rule
that groups must open no socket and make no network call. It is *not* registered
in :data:`convertible.oilcheck.CHECK_GROUPS`; :func:`convertible.oilcheck.diagnose`
invokes it only when ``probe=True``, so the default diagnosis stays fully
no-network. A live readiness ping is genuinely useful (issue #53: "doctor didn't
help") but must be explicit, hence the flag.

``provider_reachable`` (info | warning)
    GETs ``{base_url}/models`` (the OpenAI-compatible discovery endpoint) with a
    short timeout. *Any* HTTP response — including ``401``/``404`` — means the
    server is up and is reported as ``info``/passed. A connection error or
    timeout is reported as a ``warning`` (advisory: it never flips ``doctor``
    unhealthy, consistent with the rest of the readiness rubric). Bump the
    severity to ``"error"`` if you want ``doctor --probe`` to gate CI.

Like every oilcheck group this never raises: any unexpected error becomes a
failed ``warning`` check. It uses stdlib ``urllib`` only (the same surface the
vLLM driver speaks) — no third-party dep, and no raw ``socket`` module import
(the zero-socket guard stays green).
"""

from __future__ import annotations

import urllib.error
import urllib.request

from convertible.config import EngineConfig
from convertible.oilcheck import make_check

_PROBE_TIMEOUT = 3.0


def checks() -> list[dict]:
    """Return the provider-reachability check (see module docstring)."""
    try:
        return _checks()
    except Exception as exc:  # pragma: no cover — safety net; normal paths don't raise
        return [
            make_check(
                "provider_reachable",
                False,
                "warning",
                f"reachability probe failed: {exc}",
                remediation="check CONVERTIBLE_BASE_URL / OPENAI_BASE_URL and re-run with --probe",
            )
        ]


def _checks() -> list[dict]:
    base_url = EngineConfig.resolve().base_url
    url = base_url.rstrip("/") + "/models"

    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - operator-configured endpoint
            request, timeout=_PROBE_TIMEOUT
        ):
            reachable, reason = True, ""
    except urllib.error.HTTPError:
        # The server responded (e.g. 401/404) — it is up, just not at /models.
        reachable, reason = True, ""
    except OSError as exc:
        # OSError covers URLError (connection refused), TimeoutError, and the
        # socket-level connection errors — all subclasses (S5713: no redundant
        # subclasses in the tuple). HTTPError is handled above, before this.
        reachable, reason = False, str(getattr(exc, "reason", exc))

    if reachable:
        return [
            make_check(
                "provider_reachable",
                True,
                "info",
                f"provider reachable at {base_url!r}",
            )
        ]
    return [
        make_check(
            "provider_reachable",
            False,
            "warning",
            f"provider not reachable at {base_url!r}: {reason}",
            remediation=(
                "start the engine server (for vLLM: --enable-auto-tool-choice plus a "
                "--tool-call-parser) or point CONVERTIBLE_BASE_URL at a running server"
            ),
        )
    ]

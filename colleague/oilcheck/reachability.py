"""Opt-in provider-reachability probe (``colleague doctor --probe``).

This module is the **deliberate exception** to the oilcheck check-group rule
that groups must open no socket and make no network call. It is *not* registered
in :data:`colleague.oilcheck.CHECK_GROUPS`; :func:`colleague.oilcheck.diagnose`
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

``provider_model_available`` (info | warning, emitted only when the model list
    parses)
    When the ``/models`` GET returns a parseable OpenAI ``{"data": [...]}`` list,
    this check compares the *configured* model id against the served ids. A match
    is ``info``/passed; a miss is a ``warning`` naming both the configured model
    and what the server actually serves — the legible form of the otherwise
    cryptic ``404 model does not exist`` a drive would hit. When the list cannot
    be enumerated (HTTP error, connection refused, timeout, malformed body) the
    check is omitted entirely: we cannot tell, so we say nothing.

Like every oilcheck group this never raises: any unexpected error becomes a
failed ``warning`` check. It uses stdlib ``urllib`` only (the same surface the
vLLM driver speaks) — no third-party dep, and no raw ``socket`` module import
(the zero-socket guard stays green).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from colleague.config import EngineConfig
from colleague.oilcheck import make_check

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
                remediation="check COLLEAGUE_BASE_URL / OPENAI_BASE_URL and re-run with --probe",
            )
        ]


def _checks() -> list[dict]:
    config = EngineConfig.resolve()
    base_url = config.base_url
    url = base_url.rstrip("/") + "/models"

    served: list[str] | None = None
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - operator-configured endpoint
            request, timeout=_PROBE_TIMEOUT
        ) as response:
            reachable, reason = True, ""
            served = _served_models(response)
    except urllib.error.HTTPError:
        # The server responded (e.g. 401/404) — it is up, just not at /models.
        reachable, reason = True, ""
    except OSError as exc:
        # OSError covers URLError (connection refused), TimeoutError, and the
        # socket-level connection errors — all subclasses (S5713: no redundant
        # subclasses in the tuple). HTTPError is handled above, before this.
        reachable, reason = False, str(getattr(exc, "reason", exc))

    if reachable:
        results = [
            make_check(
                "provider_reachable",
                True,
                "info",
                f"provider reachable at {base_url!r}",
            )
        ]
    else:
        results = [
            make_check(
                "provider_reachable",
                False,
                "warning",
                f"provider not reachable at {base_url!r}: {reason}",
                remediation=(
                    "start the engine server (for vLLM: --enable-auto-tool-choice plus a "
                    "--tool-call-parser) or point COLLEAGUE_BASE_URL at a running server"
                ),
            )
        ]

    model_check = _model_available_check(config.model, base_url, served)
    if model_check is not None:
        results.append(model_check)
    return results


def _served_models(response: object) -> list[str] | None:
    """Parse an OpenAI ``/models`` body into a list of served model ids.

    Returns ``None`` when the body is missing/unreadable/malformed (so the caller
    omits the model-availability verdict rather than guessing).
    """
    try:
        payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data")
    except (AttributeError, ValueError):
        # ValueError covers JSONDecodeError and UnicodeDecodeError (both
        # subclasses — S5713: no redundant subclasses in the tuple).
        return None
    if not isinstance(data, list):
        return None
    return [entry["id"] for entry in data if isinstance(entry, dict) and "id" in entry]


def _model_available_check(model: str, base_url: str, served: list[str] | None) -> dict | None:
    """Compare the configured model against the served ids (``None`` ⇒ omit)."""
    if served is None:
        return None
    if model in served:
        return make_check(
            "provider_model_available",
            True,
            "info",
            f"configured model {model!r} is served at {base_url!r}",
        )
    served_desc = ", ".join(served) if served else "(none)"
    return make_check(
        "provider_model_available",
        False,
        "warning",
        f"configured model {model!r} is not served at {base_url!r}; served: {served_desc}",
        remediation=(
            "set COLLEAGUE_MODEL (or --model) to one of the served ids, or serve "
            f"{model!r} on the provider"
        ),
    )

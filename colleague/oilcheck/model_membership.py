"""Model-membership check-group for the doctor health-check (plan task t10).

Verifies the configured MAIN model id is present in the provider's /v1/models
list, and names the config source that pinned it. Follows the three_tier
membership-check pattern and respects the doctor --probe network gating.

Two layers:

1. **Static checks** (always run, registered in CHECK_GROUPS):
   - ``model_membership_source`` — reports the configured model id and the
     config source that pinned it (env var, config.json, lobes discovery,
     or builtin default). Always info/passed, no network.

2. **Probe checks** (only with ``--probe``):
   - ``model_membership`` — GETs ``{base_url}/v1/models`` and compares the
     configured model id against the served ids. A match is info/passed;
     a miss is a warning naming both the model id and its pinning source.
     A provider without /v1/models or unreachable yields skip/info, never
     a hard failure (h6). HTTP 401 means the endpoint is alive but
     unauthenticated — skip membership, not a failure.

Never raises: any unexpected error becomes a skip/info check.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from colleague.config import (
    _DEFAULT_MODEL,
    EngineConfig,
    _merged_config_json,
    resolve_lobes_gateway_url,
)
from colleague.oilcheck import make_check

_PROBE_TIMEOUT = 5.0


def _resolve_model_source(repo_path=None) -> tuple[str, str]:
    """Return (model_id, source_description) for the configured MAIN model.

    Resolution precedence mirrors EngineConfig.resolve:
    1. COLLEAGUE_MODEL env var
    2. CONVERTIBLE_MODEL env var (deprecated alias)
    3. .colleague/config.json model key
    4. Lobes discovery (gateway cortex model)
    5. Built-in default
    """
    # 1. COLLEAGUE_MODEL env var
    env_val = os.environ.get("COLLEAGUE_MODEL")
    if env_val and env_val.strip():
        return env_val.strip(), "env COLLEAGUE_MODEL"

    # 2. CONVERTIBLE_MODEL env var (deprecated)
    env_val = os.environ.get("CONVERTIBLE_MODEL")
    if env_val and env_val.strip():
        return env_val.strip(), "env CONVERTIBLE_MODEL (deprecated alias)"

    # 3. .colleague/config.json
    if repo_path is not None:
        try:
            data = _merged_config_json(repo_path)
            file_model = data.get("model")
            if file_model and str(file_model).strip():
                return str(file_model).strip(), "config.json"
        except Exception:  # nosec B110 - degrade gracefully; source detection is advisory
            pass

    # 4. Lobes discovery
    gateway = resolve_lobes_gateway_url(repo_path)
    if gateway is not None:
        try:
            from colleague import lobes as _lobes

            roles = _lobes.resolve_roles(gateway)
            if roles is not None and getattr(roles.cortex, "model", None):
                return roles.cortex.model, "lobes discovery (cortex role)"
        except Exception:  # nosec B110 - degrade gracefully; source detection is advisory
            pass

    # 5. Built-in default
    return _DEFAULT_MODEL, "builtin default"


def checks(repo_path=None) -> list[dict]:
    """Return the static model-membership check (see module docstring).

    Read-only, no network. Reports the configured model id and its source.
    When *repo_path* is provided, config.json from that repo is consulted.
    """
    try:
        return _checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net
        return [
            make_check(
                "model_membership_source",
                False,
                "warning",
                f"model membership source check failed: {exc}",
                remediation="re-run 'colleague doctor'",
            )
        ]


def _checks(repo_path=None) -> list[dict]:
    model_id, source = _resolve_model_source(repo_path)
    return [
        make_check(
            "model_membership_source",
            True,
            "info",
            f"configured model {model_id!r} (source: {source}); "
            "run 'doctor --probe' to verify against provider /v1/models",
        )
    ]


# ---------------------------------------------------------------------------
# Probe checks (only with --probe)
# ---------------------------------------------------------------------------


def probe_checks(repo_path=None) -> list[dict]:
    """Opt-in model-membership probe — invoked ONLY by ``diagnose(probe=True)``.

    GETs the provider's /v1/models and compares the configured model id
    against the served ids. Never raises.
    """
    try:
        return _probe_checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net
        return [
            make_check(
                "model_membership",
                True,
                "info",
                f"model membership probe failed: {exc} — skipping",
            )
        ]


def _probe_checks(repo_path=None) -> list[dict]:
    model_id, source = _resolve_model_source(repo_path)
    config = EngineConfig.resolve(repo_path=repo_path, discover_lobes=False)
    base_url = config.base_url
    url = base_url.rstrip("/") + "/v1/models"

    served: list[str] | None = None
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - operator-configured endpoint
            request, timeout=_PROBE_TIMEOUT
        ) as response:
            served = _served_models(response)
    except urllib.error.HTTPError:
        # HTTP error (401, 404, etc.) — the server responded, but we can't
        # parse the model list. Endpoint is alive, skip membership check.
        return [
            make_check(
                "model_membership",
                True,
                "info",
                f"provider responded at {url!r} but /v1/models was not parseable — "
                f"skipping membership check for {model_id!r}",
            )
        ]
    except OSError:
        # Connection refused, timeout, etc. — skip, not a failure.
        return [
            make_check(
                "model_membership",
                True,
                "info",
                f"provider not reachable at {url!r} — skipping membership check "
                f"for {model_id!r}",
            )
        ]

    if served is None:
        return [
            make_check(
                "model_membership",
                True,
                "info",
                f"could not parse /v1/models response from {url!r} — "
                f"skipping membership check for {model_id!r}",
            )
        ]

    if model_id in served:
        return [
            make_check(
                "model_membership",
                True,
                "info",
                f"model {model_id!r} (source: {source}) is served at {base_url!r}",
            )
        ]

    served_desc = ", ".join(served) if served else "(none)"
    return [
        make_check(
            "model_membership",
            False,
            "warning",
            (
                f"model {model_id!r} (source: {source}) is NOT served at "
                f"{base_url!r}; served: {served_desc}"
            ),
            remediation=(
                f"set COLLEAGUE_MODEL (or --model) to one of the served ids, "
                f"or serve {model_id!r} on the provider"
            ),
        )
    ]


def _served_models(response: object) -> list[str] | None:
    """Parse an OpenAI /models body into a list of served model ids.

    Returns None when the body is missing/unreadable/malformed.
    """
    try:
        payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data")
    except (AttributeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return [entry["id"] for entry in data if isinstance(entry, dict) and "id" in entry]

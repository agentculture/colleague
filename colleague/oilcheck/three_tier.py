"""Three-tier readiness check-group for the doctor health-check (plan task t10).

Extends the colleague doctor rubric with a new ``three_tier`` group that
validates the three-tier worker seat readiness. Two layers:

1. **Static checks** (always run, registered in CHECK_GROUPS):
   - ``three_tier_armed`` — whether three-tier is armed (env COLLEAGUE_THREE_TIER
     or config.json three_tier). When not armed, reports informational OK lines
     and never fails the rubric.
   - ``three_tier_gateway`` — whether the lobes gateway config exists (only
     meaningful when armed; when unarmed, reports info/passed).

2. **Probe checks** (only with ``--probe``, only when armed):
   - ``three_tier_worker_role`` — worker role advertised by the gateway
     ``/capabilities``.
   - ``three_tier_worker_dialable`` — worker endpoint responds to a GET.
   - ``three_tier_worker_tool_calling`` — a minimal tool-calling probe (one
     chat completion with one trivial tool schema; asserts the response carries
     a structured tool_call).
   - ``three_tier_worker_model_match`` — served-model-id-matches-advert:
     compares the ``/capabilities`` worker model id against the gateway
     ``/v1/models`` list. A mismatch is a FAIL (``error``) that NAMES the
     exact failing model id and makes doctor exit 1.

When not armed, the group reports informational OK lines and never fails
the rubric. The probe checks are NOT registered in CHECK_GROUPS (probe-only,
invoked by :func:`colleague.oilcheck.diagnose` when ``probe=True``).

Never raises: any unexpected error becomes a failed check.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.request

from colleague.config import EngineConfig, resolve_lobes_gateway_url
from colleague.oilcheck import make_check

_PROBE_TIMEOUT = 5.0

# Minimal tool-calling probe payload (same shape as tool_calling.py).
_PROBE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "A no-op probe tool.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]
_PROBE_MESSAGES = [{"role": "user", "content": "Call the ping tool now."}]

# SIZED FROM LIVE MEASUREMENT (t3, 2026-08-20) — kept in step with
# ``tool_calling._PROBE_MAX_TOKENS``, which carries the full measurement table.
# This probe targets the WORKER seat, and the operator rig's worker
# (unsloth/Qwen3.6-35B-A3B-NVFP4) needs 163 completion tokens to emit the
# ping call: at 128 it returns a 200 with finish_reason=length and no
# ``tool_calls``, which this module then reports as "accepted a tools request
# but returned no tool_call" — a false negative about a working server. 512 is
# 3.1x the measured worst case.
_PROBE_MAX_TOKENS = 512


def _three_tier_armed(repo_path=None) -> bool:
    """Check if three-tier execution is armed (env or config)."""
    import os

    env = os.environ.get("COLLEAGUE_THREE_TIER")
    if env is not None and env.strip() != "":
        return env.strip().lower() not in ("0", "false", "no", "")
    # Check config.json — an unreadable config resolves to unarmed, the same
    # degrade-to-legacy stance resolution itself takes.
    if repo_path is not None:
        with contextlib.suppress(Exception):
            from colleague.config import _merged_config_json

            data = _merged_config_json(repo_path)
            section = data.get("three_tier")
            if section is not None:
                # String-tolerant like config._parse_bool — bool("false") is
                # True and would report an explicitly disabled config as
                # armed (the same misparse Qodo flagged in config.py).
                from colleague.config import _parse_bool

                if isinstance(section, dict):
                    return _parse_bool(str(section.get("enabled", True)))
                return _parse_bool(str(section))
    return False


def checks(repo_path=None) -> list[dict]:
    """Return the three-tier static checks (see module docstring).

    Read-only, no network. When not armed, reports informational OK lines.
    When armed, checks gateway config presence. Never raises.
    """
    try:
        return _checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net
        return [
            make_check(
                "three_tier_armed",
                False,
                "warning",
                f"three-tier static check failed: {exc}",
                remediation="re-run 'colleague doctor'",
            )
        ]


def _checks(repo_path=None) -> list[dict]:
    armed = _three_tier_armed(repo_path)
    gateway = resolve_lobes_gateway_url(repo_path)

    if not armed:
        return [
            make_check(
                "three_tier_armed",
                True,
                "info",
                (
                    "three-tier execution not armed "
                    "(default — set COLLEAGUE_THREE_TIER or config.json "
                    "three_tier to enable)"
                ),
            ),
            make_check(
                "three_tier_gateway",
                True,
                "info",
                "three-tier unarmed — gateway check skipped",
            ),
        ]

    # Armed: report armed status
    armed_check = make_check(
        "three_tier_armed",
        True,
        "info",
        "three-tier execution armed",
    )

    # Check gateway config
    if gateway is not None:
        gw_check = make_check(
            "three_tier_gateway",
            True,
            "info",
            f"lobes gateway configured at {gateway!r}",
        )
    else:
        gw_check = make_check(
            "three_tier_gateway",
            False,
            "warning",
            "three-tier armed but no lobes gateway configured — worker role cannot be discovered",
            remediation=(
                "set COLLEAGUE_LOBES_URL or add a 'lobes' section to "
                ".colleague/config.json, or unset three_tier"
            ),
        )

    return [armed_check, gw_check]


# ---------------------------------------------------------------------------
# Probe checks (only with --probe, only when armed)
# ---------------------------------------------------------------------------


def probe_checks(repo_path=None) -> list[dict]:
    """Opt-in three-tier probe checks — invoked ONLY by ``diagnose(probe=True)``.

    Returns an empty list when three-tier is not armed (no network calls).
    When armed, probes: worker role advertised, worker dialable, tool-calling,
    and model-id match. Never raises.
    """
    try:
        return _probe_checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net
        return [
            make_check(
                "three_tier_probe_error",
                False,
                "warning",
                f"three-tier probe failed: {exc}",
                remediation="re-run 'colleague doctor --probe'",
            )
        ]


def _probe_checks(repo_path=None) -> list[dict]:
    armed = _three_tier_armed(repo_path)
    if not armed:
        return []

    gateway = resolve_lobes_gateway_url(repo_path)
    if gateway is None:
        # Static checks already report this; probe can't do more.
        return []

    from colleague import lobes as _lobes

    roles = _lobes.resolve_roles(gateway)
    if roles is None:
        return [
            make_check(
                "three_tier_worker_role",
                False,
                "warning",
                f"three-tier armed but lobes gateway {gateway!r} unreachable at /capabilities",
                remediation="start the lobes gateway, or unset COLLEAGUE_THREE_TIER",
            )
        ]

    results: list[dict] = []

    # 1. Worker role advertised
    worker_role = getattr(roles, "worker", None)
    if worker_role is None or not getattr(worker_role, "ready", False):
        results.append(
            make_check(
                "three_tier_worker_role",
                False,
                "warning",
                (
                    "lobes gateway advertises no ready worker role "
                    f"(cortex={roles.cortex.model!r}, senses={roles.senses.model!r})"
                ),
                remediation=("arm a ready worker role on the lobes gateway, or unset three_tier"),
            )
        )
        # Can't probe further without a worker role
        return results

    results.append(
        make_check(
            "three_tier_worker_role",
            True,
            "info",
            f"worker role advertised: model={worker_role.model!r}, "
            f"endpoint={worker_role.endpoint!r}, ready={worker_role.ready}",
        )
    )

    # 2. Worker dialable (GET /models on worker endpoint)
    worker_base_url = _lobes.resolve_role_base_url(worker_role, gateway)
    dial_check = _worker_dialable(worker_base_url)
    results.append(dial_check)

    if not dial_check["passed"]:
        # Can't probe tool-calling or model match if worker is not dialable
        return results

    # 3. Tool-calling probe on worker
    config = EngineConfig.resolve(repo_path=repo_path)
    tc_check = _worker_tool_calling(worker_base_url, worker_role.model, config.api_key)
    results.append(tc_check)

    if not tc_check["passed"]:
        return results

    # 4. Model-id match: compare worker model id against gateway /v1/models
    match_check = _worker_model_match(gateway, worker_role.model)
    results.append(match_check)

    return results


def _worker_dialable(base_url: str) -> dict:
    """Check if the worker endpoint responds to a GET /models request."""
    url = base_url.rstrip("/") + "/models"
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - operator-configured endpoint
            request, timeout=_PROBE_TIMEOUT
        ):
            return make_check(
                "three_tier_worker_dialable",
                True,
                "info",
                f"worker endpoint dialable at {base_url!r}",
            )
    except urllib.error.HTTPError:
        # HTTP error still means the server responded
        return make_check(
            "three_tier_worker_dialable",
            True,
            "info",
            f"worker endpoint responded at {base_url!r} (HTTP error — still dialable)",
        )
    except OSError as exc:
        return make_check(
            "three_tier_worker_dialable",
            False,
            "warning",
            f"worker endpoint not dialable at {base_url!r}: {getattr(exc, 'reason', exc)}",
            remediation="check the worker endpoint is running and reachable",
        )


def _worker_tool_calling(base_url: str, model: str, api_key: str) -> dict:
    """Send a minimal tool-calling probe to the worker endpoint."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": _PROBE_MESSAGES,
        "tools": _PROBE_TOOLS,
        "tool_choice": "auto",
        "max_tokens": _PROBE_MAX_TOKENS,
        "temperature": 0.0,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - operator-configured endpoint
            request, timeout=_PROBE_TIMEOUT
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return make_check(
            "three_tier_worker_tool_calling",
            False,
            "warning",
            f"worker tool-calling probe failed: HTTP {exc.code} at {url!r}",
            remediation="check the worker endpoint supports tool calling",
        )
    except OSError as exc:
        return make_check(
            "three_tier_worker_tool_calling",
            False,
            "warning",
            f"worker tool-calling probe connection failed: {getattr(exc, 'reason', exc)}",
            remediation="check the worker endpoint is reachable",
        )

    if _response_has_tool_call(data):
        return make_check(
            "three_tier_worker_tool_calling",
            True,
            "info",
            f"worker tool-calling OK at {url!r} (server emitted a tool_call)",
        )
    return make_check(
        "three_tier_worker_tool_calling",
        False,
        "warning",
        f"worker accepted a tools request at {url!r} but returned no tool_call",
        remediation="verify the worker model supports tool calling",
    )


def _response_has_tool_call(data: object) -> bool:
    """True iff the chat-completion response carries a tool_call."""
    if not isinstance(data, dict):
        return False
    choices = data.get("choices") or [{}]
    message = choices[0].get("message", {})
    return bool(isinstance(message, dict) and message.get("tool_calls"))


def _worker_model_match(gateway_url: str, worker_model: str) -> dict:
    """Compare the worker model id against the gateway's /v1/models list.

    A mismatch is an ``error`` (FAIL) that NAMES the exact failing model id.
    """
    url = gateway_url.rstrip("/") + "/v1/models"
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - operator gateway
            request, timeout=_PROBE_TIMEOUT
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        # Can't verify — omit rather than guess
        return make_check(
            "three_tier_worker_model_match",
            True,
            "info",
            (
                f"could not verify worker model {worker_model!r} against "
                f"gateway {gateway_url!r} — skipping"
            ),
        )

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return make_check(
            "three_tier_worker_model_match",
            True,
            "info",
            "gateway /v1/models response unparseable — skipping model match check",
        )

    served_ids = [entry["id"] for entry in data if isinstance(entry, dict) and "id" in entry]

    if worker_model in served_ids:
        return make_check(
            "three_tier_worker_model_match",
            True,
            "info",
            f"worker model {worker_model!r} is served by gateway {gateway_url!r}",
        )

    served_desc = ", ".join(served_ids) if served_ids else "(none)"
    return make_check(
        "three_tier_worker_model_match",
        False,
        "error",
        (
            f"worker model {worker_model!r} is NOT served by gateway "
            f"{gateway_url!r}; served: {served_desc}"
        ),
        remediation=(
            f"ensure the gateway serves {worker_model!r}, or update the "
            "lobes gateway worker role to a model that is served"
        ),
    )

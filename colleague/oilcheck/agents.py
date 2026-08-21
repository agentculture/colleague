"""Model-bound agents readiness check-group for the doctor health-check (#411, t7).

Two layers, mirroring ``oilcheck/three_tier.py``:

1. **Static checks** (registered in CHECK_GROUPS, read-only, no network):
   - ``agents_armed`` — the mode is armed (env ``COLLEAGUE_AGENTS`` or the
     config.json ``agents`` key); **unarmed → the group returns NOTHING**, so
     an unarmed doctor report is byte-identical to today.
   - ``agents_gateway`` — whether a lobes gateway is configured (armed only).

2. **Probe checks** (only with ``--probe``, only when armed): one
   ``agents_role_<role>`` line per reference role — ``senses`` (talker),
   ``worker`` (dormant by deviation d3), ``cortex`` (thinker/coder),
   ``associate`` (the reserved fast-coder) — reporting ``ready`` or
   ``absent/not ready → cortex fallback`` from the same lobes resolution the
   three-tier probe uses. The fallback is the #411 contract (never a refusal),
   so these lines are informational, never a rubric failure; only an
   unreachable gateway or a missing cortex role warns.

Never raises: any unexpected error becomes a failed check.
"""

from __future__ import annotations

import contextlib

from colleague.config import resolve_lobes_gateway_url
from colleague.oilcheck import make_check

#: The reference purposes' roles, in report order (role name → purpose label).
_REFERENCE_ROLES = (
    ("senses", "talker"),
    ("worker", "worker (dormant, deviation d3)"),
    ("cortex", "thinker/coder"),
    ("associate", "associate (reserved fast coder)"),
)


def _agents_armed(repo_path=None) -> bool:
    """Is the agents mode armed (env or merged config.json)? Unreadable → unarmed."""
    import os

    env = os.environ.get("COLLEAGUE_AGENTS")
    if env is not None and env.strip() != "":
        return env.strip().lower() not in ("0", "false", "no", "")
    if repo_path is not None:
        with contextlib.suppress(Exception):
            from colleague.config import _merged_config_json, _parse_bool

            section = _merged_config_json(repo_path).get("agents")
            if section is not None:
                if isinstance(section, dict):
                    return _parse_bool(str(section.get("enabled", True)))
                return _parse_bool(str(section))
    return False


def checks(repo_path=None) -> list[dict]:
    """The static ``agents`` group: NOTHING when unarmed; armed + gateway lines otherwise."""
    try:
        return _checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net
        return [
            make_check(
                "agents_armed",
                False,
                "warning",
                f"agents static check failed: {exc}",
                remediation="re-run 'colleague doctor'",
            )
        ]


def _checks(repo_path=None) -> list[dict]:
    if not _agents_armed(repo_path):
        return []
    gateway = resolve_lobes_gateway_url(repo_path)
    results = [
        make_check(
            "agents_armed",
            True,
            "info",
            "model-bound agents armed (COLLEAGUE_AGENTS / config.json agents)",
        )
    ]
    if gateway is None:
        results.append(
            make_check(
                "agents_gateway",
                False,
                "warning",
                "agents armed but no lobes gateway is configured — every purpose "
                "will resolve to the configured main model under the recorded fallback",
                remediation="set COLLEAGUE_LOBES_URL or config.json lobes, or unset agents",
            )
        )
    else:
        results.append(
            make_check("agents_gateway", True, "info", f"lobes gateway configured at {gateway!r}")
        )
    return results


def probe_checks(repo_path=None) -> list[dict]:
    """Opt-in per-role probe — invoked ONLY by ``diagnose(probe=True)``; never raises."""
    try:
        return _probe_checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net
        return [
            make_check(
                "agents_probe_error",
                False,
                "warning",
                f"agents probe failed: {exc}",
                remediation="re-run 'colleague doctor --probe'",
            )
        ]


def _probe_checks(repo_path=None) -> list[dict]:
    if not _agents_armed(repo_path):
        return []
    gateway = resolve_lobes_gateway_url(repo_path)
    if gateway is None:
        return []
    from colleague import lobes as _lobes

    roles = _lobes.resolve_roles(gateway)
    if roles is None:
        return [
            make_check(
                "agents_gateway_reachable",
                False,
                "warning",
                f"agents armed but lobes gateway {gateway!r} unreachable at /capabilities "
                "— every purpose will run on the configured main model under the fallback",
                remediation="start the lobes gateway, or unset COLLEAGUE_AGENTS",
            )
        ]
    cortex = getattr(roles, "cortex", None)
    results: list[dict] = []
    if cortex is None or not getattr(cortex, "ready", False):
        results.append(
            make_check(
                "agents_role_cortex",
                False,
                "warning",
                "lobes gateway advertises no ready cortex role — the fallback floor is missing",
                remediation="arm a ready cortex role on the gateway",
            )
        )
    for role_name, purpose in _REFERENCE_ROLES:
        role = getattr(roles, role_name, None)
        if role is not None and getattr(role, "ready", False):
            results.append(
                make_check(
                    f"agents_role_{role_name}",
                    True,
                    "info",
                    f"{role_name} ({purpose}): ready — {role.model}",
                )
            )
        elif role_name == "cortex":
            continue  # reported above
        else:
            state = "not ready" if role is not None else "absent"
            floor = getattr(cortex, "model", None) or "the configured main model"
            results.append(
                make_check(
                    f"agents_role_{role_name}",
                    True,
                    "info",
                    f"{role_name} ({purpose}): {state} → cortex fallback ({floor}), "
                    "recorded on every invocation",
                )
            )
    return results

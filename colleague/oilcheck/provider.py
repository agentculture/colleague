"""Provider check-group — reports on the resolved engine provider config.

This group calls :meth:`colleague.config.EngineConfig.resolve` (read-only,
no network) and emits:

``provider_config`` (info, always)
    Reports the effective ``base_url`` and ``model``. The ``api_key`` is
    **redacted** — it never appears in any check message.

``provider_credentials`` (warning, non-default base_url only)
    Fires when ``base_url`` points at a non-local / third-party host *and*
    the resolved ``api_key`` is still the placeholder default ``"EMPTY"``.
    Silent on the default localhost rig (a local vLLM server needs no key).

``provider_budget`` (warning, non-default base_url only)
    Fires when ``base_url`` points at a third-party host *and* no
    ``COLLEAGUE_BUDGET`` env var is set (advisory spend-cap reminder).
    Silent on the default localhost rig.

All checks here are ``info`` or ``warning``; no ``error`` is ever emitted.
Read-only: resolves config from env vars, the repo's ``.colleague/config.json``
(only when ``checks`` is given a ``repo_path`` — e.g. ``colleague doctor
--repo <path>``), and built-in defaults; opens no connection. The same
precedence ``EngineConfig.resolve`` uses everywhere applies (explicit > env >
config file > default), so this reports exactly what a work item in that repo
would resolve. Catches any unexpected error and returns it as a single failed
``warning`` check rather than raising.
"""

from __future__ import annotations

import os

from colleague.config import (
    _DEFAULT_API_KEY,
    _DEFAULT_BASE_URL,
    EngineConfig,
    resolve_lobes_gateway_url,
)
from colleague.oilcheck import make_check


def checks(repo_path=None) -> list[dict]:
    """Return provider-config checks (see module docstring).

    When *repo_path* is provided, ``EngineConfig.resolve`` will also read
    ``.colleague/config.json`` from that repo, so the checks reflect the
    persistent config-file override.
    """
    try:
        return _checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net; normal paths don't raise
        return [
            make_check(
                "provider_config",
                False,
                "warning",
                f"provider config resolution failed: {exc}",
                remediation="check COLLEAGUE_* / OPENAI_* env vars and re-run doctor",
            )
        ]


def _checks(repo_path) -> list[dict]:
    cfg = EngineConfig.resolve(repo_path=repo_path)
    out: list[dict] = []

    # 1. provider_config — always emitted; api_key is redacted.
    out.append(
        make_check(
            "provider_config",
            True,
            "info",
            f"provider base_url={cfg.base_url!r} model={cfg.model!r} api_key=<redacted>",
        )
    )

    # 1b. provider_timeout — the effective per-turn request timeout + its source
    # (#268 ask 4: COLLEAGUE_TIMEOUT used to appear only in the failure hint,
    # after the work was already lost). Always emitted, always healthy (info).
    if (os.environ.get("COLLEAGUE_TIMEOUT") or "").strip():
        timeout_source = "env COLLEAGUE_TIMEOUT"
    elif (os.environ.get("CONVERTIBLE_TIMEOUT") or "").strip():
        timeout_source = "env CONVERTIBLE_TIMEOUT (deprecated alias)"
    else:
        timeout_source = "default"
    out.append(
        make_check(
            "provider_timeout",
            True,
            "info",
            (
                f"engine request timeout: {cfg.timeout:.0f}s per model turn "
                f"(source: {timeout_source}); a mid-flight turn timeout or armed "
                "backpressure raises it once in-flight, bounded x2 — raise "
                "COLLEAGUE_TIMEOUT up front for big-context audits"
            ),
        )
    )

    # 1c. provider_lobes — the lobes discovery rung (cortex/senses arc, t4).
    # ARMED-state report only (no network — reads env / config.json via
    # resolve_lobes_gateway_url); the LIVE gateway consultation + which rung is
    # actually in effect belongs to the opt-in reachability probe (--probe).
    # Emitted only when armed, so an unarmed rig's report is byte-identical.
    gateway = resolve_lobes_gateway_url(repo_path)
    if gateway is not None:
        out.append(
            make_check(
                "provider_lobes",
                True,
                "info",
                (
                    f"lobes discovery armed (gateway={gateway!r}); resolved "
                    f"model={cfg.model!r} — cortex/senses resolve by role from the "
                    "gateway (below config.json, above the builtin default); run "
                    "'doctor --probe' to check live reachability"
                ),
            )
        )

    # For checks 2 and 3, only fire on a non-default (third-party) base_url.
    # A local vLLM rig (default base_url) needs no credentials or budget cap.
    is_third_party = cfg.base_url != _DEFAULT_BASE_URL

    if not is_third_party:
        return out

    # 2. provider_credentials — warn when key is still the placeholder default.
    key_is_default = cfg.api_key == _DEFAULT_API_KEY
    # Also check whether the operator set any key-related env var (belt-and-
    # suspenders: EngineConfig.resolve() would have picked it up already, but
    # we only need to fire when the resolved key is still EMPTY).
    if key_is_default:
        out.append(
            make_check(
                "provider_credentials",
                False,
                "warning",
                (
                    f"base_url is set to a non-default provider ({cfg.base_url!r}) "
                    "but api_key is still the placeholder default — credentials likely unset"
                ),
                remediation=("set COLLEAGUE_API_KEY or OPENAI_API_KEY to your provider's API key"),
            )
        )

    # 3. provider_budget — advisory: warn when no spend-cap env var is set.
    budget_set = bool(
        (os.environ.get("COLLEAGUE_BUDGET") or os.environ.get("CONVERTIBLE_BUDGET") or "").strip()
    )
    if not budget_set:
        out.append(
            make_check(
                "provider_budget",
                False,
                "warning",
                (
                    f"base_url is set to a non-default provider ({cfg.base_url!r}) "
                    "but COLLEAGUE_BUDGET is not set — no spend cap configured"
                ),
                remediation=(
                    "set COLLEAGUE_BUDGET to a spend cap (e.g. '10' for $10) "
                    "or confirm your provider quota/billing limits are in place"
                ),
            )
        )

    return out

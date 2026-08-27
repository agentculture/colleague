"""Harness-mechanics check-group for ``colleague doctor`` (plan t20, spec c43/h32).

Four INFORMATIONAL rows — ``severity="info"``, always ``passed=True`` — that
make the adopt-from-qwen-code mechanisms' configuration visible without ever
flipping the rubric:

* ``harness_stream_guards`` — the SSE idle / lifetime bounds
  (:mod:`colleague.streamguards`, plan t7) and whether ``idle < lifetime``
  (a lifetime shorter than the idle bound makes the idle guard dead weight;
  reported as a fact, not a failure);
* ``harness_tool_concurrency`` — the read-only batch width
  (``COLLEAGUE_TOOL_CONCURRENCY``, :mod:`colleague.toolbatch_loop`, plan t15;
  ``1`` = sequential);
* ``harness_ripgrep`` — whether ``rg`` is on ``PATH`` (the fast
  ``grep_search`` backend, :mod:`colleague.search_tools`, plan t5) or the
  stdlib walker will serve;
* ``harness_associate`` — the associate seat's resolution state (plan t18/t19):
  ``consumed`` (armed, served model named), ``opt-in`` (the gateway
  advertises the role but ``COLLEAGUE_ASSOCIATE_MODEL`` is unset) or
  ``fallback`` (no role advertised — the seats run on cortex).

Read-only: env, ``PATH`` lookup, one ``EngineConfig.resolve`` and — only
when a gateway is configured — the same ``/capabilities`` read every lobes
rung performs (a cached HTTP GET, degrading to "unknown" on any failure).
Never raises: an unexpected error becomes one failed ``warning`` check.
"""

from __future__ import annotations

import shutil

from colleague.oilcheck import make_check


def checks(repo_path=None) -> list[dict]:
    """The ``harness`` group: four informational rows (see the module docstring)."""
    try:
        return [_stream_guards(), _tool_concurrency(), _ripgrep(), _associate(repo_path)]
    except Exception as exc:  # pragma: no cover — safety net per the group contract
        return [
            make_check(
                "harness_stream_guards",
                False,
                "warning",
                f"harness check failed: {exc}",
                remediation="re-run 'colleague doctor'",
            )
        ]


def _stream_guards() -> dict:
    from colleague import streamguards

    guards = streamguards.StreamGuards.from_env()
    if guards is None:
        return make_check(
            "harness_stream_guards", True, "info", "stream guards: off (both bounds 0)"
        )
    idle, lifetime = guards.idle, guards.lifetime
    sane = idle is None or lifetime is None or idle < lifetime
    note = "" if sane else " — idle >= lifetime: the idle guard can never fire first"
    return make_check(
        "harness_stream_guards",
        True,
        "info",
        f"stream guards: idle={_fmt(idle)} lifetime={_fmt(lifetime)}{note}",
    )


def _tool_concurrency() -> dict:
    from colleague import toolbatch_loop

    width = toolbatch_loop.concurrency_width()
    mode = "sequential" if width <= 1 else f"parallel read-only batches up to {width}"
    return make_check(
        "harness_tool_concurrency", True, "info", f"tool concurrency: {width} ({mode})"
    )


def _ripgrep() -> dict:
    path = shutil.which("rg")
    message = f"ripgrep: present ({path})" if path else "ripgrep: absent (stdlib grep walker)"
    return make_check("harness_ripgrep", True, "info", message)


def _associate(repo_path=None) -> dict:
    from colleague import lobes as _lobes
    from colleague.config import EngineConfig, resolve_lobes_gateway_url

    cfg = EngineConfig.resolve(repo_path=repo_path)
    seat = getattr(cfg, "associate", None)
    if seat is not None:
        state = f"consumed → {seat.model} (wire model {seat.wire_model!r})"
    else:
        gateway = resolve_lobes_gateway_url(repo_path)
        roles = _lobes.resolve_roles(gateway) if gateway else None
        advertised = getattr(roles, "associate", None)
        if advertised is not None:
            state = f"opt-in (advertised {advertised.model}; set COLLEAGUE_ASSOCIATE_MODEL=lobes)"
        elif gateway and roles is None:
            state = "unknown (lobes gateway unreachable) — seats fall back to cortex"
        else:
            state = "fallback (no associate role advertised) — seats run on cortex"
    return make_check("harness_associate", True, "info", f"associate: {state}")


def _fmt(bound) -> str:
    return "off" if bound is None else f"{bound:.0f}s"

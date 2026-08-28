"""Associate-seat rendering for the two inspection verbs (t18, spec c49).

Split out of ``colleague/cli/_commands/config.py`` and ``lobes.py`` so those
modules stay under the file-length ratchet: each calls ONE function here.
"""

from __future__ import annotations

import os
from typing import Any

ARMED_STATES = ("not_configured", "armed_reachable", "armed_unreachable")


def config_show_lines(lines: list[str], cfg: object) -> dict[str, Any]:
    """Append the armed ``associate → …`` line to *lines*; return the JSON fragment.

    Names the SERVED model and how the wire is addressed — the role name via
    the gateway proxy (a lobes-discovered seat) or an explicit model id — the
    consumed counterpart of the ``not consumed (opt-in)`` line. ``{}`` when
    the seat is not armed, so ``config show`` stays byte-identical unarmed.
    """
    assoc = getattr(cfg, "associate", None)
    if assoc is None:
        return {}
    how = "addressed as role name via proxy" if assoc.addressed_as_role else "explicit model id"
    lines.append(f"associate → {assoc.model} ({how})")
    return {
        "associate": {
            "served_model": assoc.model,
            "wire_model": assoc.wire_model,
            "addressed_as_role": assoc.addressed_as_role,
        }
    }


def optional_roles(roles: object) -> tuple[tuple[str, object], ...]:
    """The OPTIONAL gateway roles ``lobes show`` renders when advertised.

    stt/tts (voice arc), muse (two-machines-two-minds t4) and — since t18 —
    associate, the fast non-coding seat proxied like muse (``config-proxy``
    ready kind). Order is the render order.
    """
    return (
        ("stt", getattr(roles, "stt", None)),
        ("tts", getattr(roles, "tts", None)),
        ("muse", getattr(roles, "muse", None)),
        ("associate", getattr(roles, "associate", None)),
    )


def declared(repo: object) -> bool:
    """Whether an associate seat is DECLARED (env or config.json) — no network."""
    if (os.environ.get("COLLEAGUE_ASSOCIATE_MODEL") or "").strip():
        return True
    from colleague import associate_config

    try:
        return bool((associate_config.load_associate_overrides(repo).get("model") or "").strip())
    except Exception:  # noqa: BLE001 — an unreadable config.json is "not declared"
        return False


def armed_state(role: object, repo: object) -> str:
    """The canonical armed state of the associate row (Qodo #441-3).

    ``not_configured`` when no seat is declared; otherwise ``armed_reachable`` /
    ``armed_unreachable`` from the gateway's already-fetched ``ready`` flag —
    one of :data:`ARMED_STATES`, never a fourth value, no extra network call.
    """
    if not declared(repo):
        return ARMED_STATES[0]
    return ARMED_STATES[1] if getattr(role, "ready", False) else ARMED_STATES[2]

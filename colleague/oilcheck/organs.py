"""Organs check-group — presence/version/armed-state for the AI-coworker organism.

colleague-integration-front (issue #291, requirement R10 / "S10") frames colleague
as the operator front for a small organism of sibling CLIs — each an independent
repo, each behind its own published contract. This group answers one question,
with zero network calls: *what is wired in, and is it here?*

This is a **curated table, not a plugin registry** — colleague does not discover
organs dynamically (contrast :mod:`colleague.registry`'s entry-point discovery
for engine backends). The table in :data:`ORGANS` is hand-maintained; adding an
organ means adding a row here, the same way a new oilcheck check-group is wired
by hand into :data:`colleague.oilcheck.CHECK_GROUPS`.

For each organ this reports:

* **presence** — ``shutil.which(binary)``, a filesystem PATH lookup only.
* **version** — ``importlib.metadata.version(distribution)`` on a curated
  binary→distribution mapping. Many of these organs are installed as isolated
  CLI tools (e.g. ``uv tool install``), not as importable packages inside
  colleague's own environment, so a present binary very often still reads back
  ``"unknown"`` — that is the honest, expected common case, not a bug.
* **armed** — read from colleague's OWN config resolution (env vars,
  ``.colleague/config.json``, and — for the memory organ — a plain
  ``pathlib`` directory check for ``.eidetic/``). Never a network call.

Deliberately **no subprocess**: unlike :mod:`colleague.memory` /
:mod:`colleague.culture` / :mod:`colleague.devague` (which shell out to these
same CLIs from the *runtime*), this introspection module never launches one —
:mod:`colleague.oilcheck` is not in ``tests/test_boundary.py``'s
``_SUBPROCESS_ALLOWED`` allow-list, and it must stay that way (a health check
that can hang on a broken child process is a broken health check).

Severity contract: a missing/not-yet-wired organ is always a ``warning`` with a
remediation hint (``uv tool install <distribution>``) — **never** unhealthy.
Some organs (coherence, sloth, data-refinery) are listed here even though
colleague does not consume them yet (their colleague-side integration is a
planned, separately-tracked spec — see ``docs/organs.md``); they always report
``armed=False`` honestly rather than being omitted, so the organism map is
complete from day one.

See also: :func:`colleague.oilcheck.organs.probe_checks` — the opt-in,
network-touching sibling invoked only by ``colleague doctor --probe``
(mirrors :mod:`colleague.oilcheck.reachability`), and
``colleague/cli/_commands/organs.py`` — the ``organs list`` rendered tool that
renders this SAME resolver (:func:`resolve_organs`) as a second view.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Callable, Optional

from colleague.config import EngineConfig, resolve_lobes_gateway_url
from colleague.oilcheck import make_check

#: Bound the live probe's GET (mirrors ``reachability._PROBE_TIMEOUT``).
_PROBE_TIMEOUT = 3.0


def _repo_root(repo_path) -> Path:
    """Resolve *repo_path* to a concrete directory, defaulting to cwd.

    Mirrors the ``Path.cwd()`` fallback :mod:`colleague.oilcheck.stale_refs`
    uses — a bare ``diagnose()`` call (no ``--repo``) still resolves to
    somewhere real, never ``None``-propagating into a ``Path()`` call.
    """
    return Path(repo_path).expanduser() if repo_path is not None else Path.cwd()


def _lobes_armed(repo_path: Optional[str]) -> bool:
    """Lobes discovery rung armed — env/config only, see ``colleague.config``."""
    return resolve_lobes_gateway_url(repo_path) is not None


def _eidetic_armed(repo_path: Optional[str]) -> bool:
    """Memory armed — ``config.memory`` AND a ``.eidetic/`` store present.

    Mirrors ``colleague/loop.py``'s ``_memory_armed`` triple-gate (config +
    store presence; CLI presence is reported separately as this organ's own
    ``present`` column) without importing the loop module.
    """
    cfg = EngineConfig.resolve(repo_path=repo_path, discover_lobes=False)
    if not cfg.memory:
        return False
    return (_repo_root(repo_path) / ".eidetic").is_dir()


def _culture_tool_armed(_repo_path: Optional[str]) -> bool:
    """agtag / devex / devague are unconditional curated tools.

    They are part of the base tool surface whenever the loop offers tools
    (``colleague/culture.py``'s ``ALLOWED_CLIS``, ``colleague/devague.py``'s
    ``ALLOWED_MOVES``) — there is no operator opt-out toggle to read, so
    "armed" here means exactly "wired into the tool surface", which is always
    true. Presence of the actual binary is the separate ``present`` column.
    """
    return True


def _not_yet_wired(_repo_path: Optional[str]) -> bool:
    """coherence / sloth / data-refinery: no colleague-side integration yet.

    Tracked as planned specs (see ``docs/organs.md``); reported honestly as
    never armed today rather than omitted from the table.
    """
    return False


@dataclass(frozen=True)
class Organ:
    """One curated organ row — presence/version/armed-state descriptor."""

    #: Short organ id, e.g. ``"lobes"``. Unique across :data:`ORGANS`.
    name: str
    #: The executable :func:`shutil.which` probes for presence.
    binary: str
    #: The ``importlib.metadata`` distribution name whose version is read
    #: when *binary* is present (may differ from *binary* — e.g. ``devex`` /
    #: ``devex-cli``).
    distribution: str
    #: One-line description of how colleague talks to this organ today (or
    #: would, once its planned integration lands).
    seam: str
    #: Pointer to the organ's own published contract artifact (see
    #: ``docs/organs.md`` for the full per-organ writeup).
    contract: str
    #: Pure, no-network, no-subprocess armed-state check.
    armed_check: Callable[[Optional[str]], bool]


#: The curated organ table (NOT a plugin registry — see the module docstring).
#: Order mirrors ``docs/organs.md``.
ORGANS: tuple[Organ, ...] = (
    Organ(
        name="lobes",
        binary="lobes",
        distribution="lobes-cli",
        seam="discovery rung (colleague/lobes.py + config.py resolve_lobes_gateway_url precedence)",
        contract="GET /capabilities RoleInfo shape — docs/organs.md#lobes",
        armed_check=_lobes_armed,
    ),
    Organ(
        name="eidetic",
        binary="eidetic",
        distribution="eidetic-cli",
        seam="memory shell-out (colleague/memory.py; recall/remember allow-list)",
        contract="eidetic conventions (README.md#storage) — docs/organs.md#eidetic",
        armed_check=_eidetic_armed,
    ),
    Organ(
        name="coherence",
        binary="coherence",
        distribution="coherence-cli",
        seam="gate — planned colleague#294 (S3); not yet built",
        contract="coherence meaning score --json shape — docs/organs.md#coherence",
        armed_check=_not_yet_wired,
    ),
    Organ(
        name="sloth",
        binary="sloth",
        distribution="unsloth-cli",
        seam="experiment — planned colleague#295 (S5); not yet built",
        contract="run TOML config + training_metadata.json — docs/organs.md#sloth",
        armed_check=_not_yet_wired,
    ),
    Organ(
        name="data-refinery",
        binary="data-refinery",
        distribution="data-refinery-cli",
        seam="dataset pipeline — planned data-refinery-cli#14 (S6); not yet built colleague-side",
        contract="data-refinery docs/contract.md v3 — docs/organs.md#data-refinery",
        armed_check=_not_yet_wired,
    ),
    Organ(
        name="agtag",
        binary="agtag",
        distribution="agtag",
        seam="culture tool (colleague/culture.py allow-list)",
        contract="agtag issue --json shape — docs/organs.md#agtag",
        armed_check=_culture_tool_armed,
    ),
    Organ(
        name="devex",
        binary="devex",
        distribution="devex-cli",
        seam="culture tool (colleague/culture.py allow-list)",
        contract="devex explain/overview/learn catalog — docs/organs.md#devex",
        armed_check=_culture_tool_armed,
    ),
    Organ(
        name="devague",
        binary="devague",
        distribution="devague",
        seam="destination tool (colleague/devague.py allow-list)",
        contract="devague spec-contract.md move I/O — docs/organs.md#devague",
        armed_check=_culture_tool_armed,
    ),
)


def _organ_version(organ: Organ, present: bool) -> str:
    """``importlib.metadata.version(organ.distribution)``, or ``"unknown"``.

    ``"unknown"`` covers both "not installed" and the very common case of an
    isolated-tool install (e.g. ``uv tool install``) that is on ``PATH`` but
    not importable as a distribution from colleague's own environment — never
    a crash either way.
    """
    if not present:
        return "unknown"
    try:
        return _pkg_version(organ.distribution)
    except PackageNotFoundError:
        return "unknown"


def resolve_organ(organ: Organ, *, repo_path=None) -> dict:
    """Resolve one organ's presence/version/armed-state dict (no network, no subprocess)."""
    present = shutil.which(organ.binary) is not None
    try:
        armed = bool(organ.armed_check(repo_path))
    except Exception:  # noqa: BLE001 - an armed-check must never take the group down
        armed = False
    return {
        "organ": organ.name,
        "seam": organ.seam,
        "contract": organ.contract,
        "present": present,
        "version": _organ_version(organ, present),
        "armed": armed,
        "distribution": organ.distribution,
    }


def resolve_organs(repo_path=None) -> list[dict]:
    """Resolve every curated organ — the ONE resolver ``doctor`` and ``organs list`` share."""
    return [resolve_organ(organ, repo_path=repo_path) for organ in ORGANS]


def checks(repo_path=None) -> list[dict]:
    """Return the organs checks (see module docstring). Read-only; never raises."""
    try:
        return _checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net; normal paths don't raise
        return [
            make_check(
                "organs_probe_error",
                False,
                "warning",
                f"organs probe failed: {exc}",
                remediation="re-run 'colleague doctor'; see 'colleague organs list' for detail",
            )
        ]


def _checks(repo_path) -> list[dict]:
    out: list[dict] = []
    for entry in resolve_organs(repo_path):
        check_id = "organ_" + entry["organ"].replace("-", "_")
        if entry["present"]:
            out.append(
                make_check(
                    check_id,
                    True,
                    "info",
                    (
                        f"{entry['organ']} present (version {entry['version']}); "
                        f"armed={entry['armed']}; seam: {entry['seam']}"
                    ),
                )
            )
        else:
            out.append(
                make_check(
                    check_id,
                    False,
                    "warning",
                    f"{entry['organ']} not installed — seam: {entry['seam']}",
                    remediation=f"uv tool install {entry['distribution']}",
                )
            )
    return out


# --- opt-in reachability probe (``colleague doctor --probe`` only) ----------


def probe_checks(repo_path=None) -> list[dict]:
    """Opt-in organ reachability — invoked ONLY by ``diagnose(probe=True)``.

    Mirrors :mod:`colleague.oilcheck.reachability`: NOT registered in
    :data:`colleague.oilcheck.CHECK_GROUPS`, so the default no-network
    diagnosis never calls this. Today lobes is the only organ with a live
    network surface to probe here (agtag/devex/devague/eidetic are local
    subprocess shell-outs already covered by their presence check; coherence/
    sloth/data-refinery have no colleague-side network surface yet). Reuses
    :func:`colleague.lobes.resolve_roles` — no new network client — and, when
    the gateway also serves an ``embedder`` role (the future one-embedder-
    contract organ, colleague#293/S2 — not yet consumed for real resolution
    by colleague), reports its endpoint as an informational extra. Degrades
    to an empty list when lobes is unarmed; never raises.
    """
    try:
        return _probe_checks(repo_path)
    except Exception as exc:  # pragma: no cover — safety net; normal paths don't raise
        return [
            make_check(
                "organ_lobes_reachable",
                False,
                "warning",
                f"organs reachability probe failed: {exc}",
                remediation="check COLLEAGUE_LOBES_URL and re-run 'doctor --probe'",
            )
        ]


def _probe_checks(repo_path) -> list[dict]:
    gateway = resolve_lobes_gateway_url(repo_path)
    if gateway is None:
        return []

    from colleague import lobes as _lobes

    roles = _lobes.resolve_roles(gateway)
    if roles is None:
        return [
            make_check(
                "organ_lobes_reachable",
                False,
                "warning",
                f"lobes organ armed ({gateway!r}) but unreachable at /capabilities",
                remediation="start the lobes gateway, or unset COLLEAGUE_LOBES_URL",
            )
        ]

    out = [
        make_check(
            "organ_lobes_reachable",
            True,
            "info",
            f"lobes organ reachable at {gateway!r}: cortex={roles.cortex.model!r} "
            f"senses={roles.senses.model!r}",
        )
    ]
    embedder_endpoint = _embedder_endpoint(gateway)
    if embedder_endpoint is not None:
        out.append(
            make_check(
                "organ_lobes_embedder_endpoint",
                True,
                "info",
                (
                    f"lobes also serves an embedder role at {embedder_endpoint!r} "
                    "(not yet consumed by colleague — planned colleague#293/S2)"
                ),
            )
        )
    return out


def _embedder_endpoint(gateway: str) -> Optional[str]:
    """Best-effort read of the raw ``/capabilities`` embedder endpoint, or ``None``.

    A pure informational extra: never raises, never gates health. Speaks
    stdlib ``urllib`` directly (the same surface :mod:`colleague.lobes` and
    :mod:`colleague.oilcheck.reachability` already use) rather than extending
    :mod:`colleague.lobes`'s ``RoleInfo`` parsing to a role it does not yet
    resolve — that parsing change is a separate, same-wave sibling task's
    scope, not this one's.
    """
    import json
    import urllib.request
    from urllib.parse import urlsplit

    if urlsplit(gateway).scheme not in ("http", "https"):
        return None
    try:
        url = gateway.rstrip("/") + "/capabilities"
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - operator gateway, scheme-checked
            request, timeout=_PROBE_TIMEOUT
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - a best-effort informational extra, never raises
        return None
    embedder = payload.get("embedder") if isinstance(payload, dict) else None
    if not isinstance(embedder, dict):
        return None
    endpoint = embedder.get("endpoint")
    return endpoint if isinstance(endpoint, str) and endpoint else None

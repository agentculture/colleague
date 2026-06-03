"""Process-level identity resolution module.

Resolves the agent's identity (nick/name) from ordered sources:

1. **culture.yaml** at the repo root — first a top-level ``nick:`` field, then
   (when absent) the first agent block's ``suffix:`` field. The canonical
   AgentCulture template nests the nick as a ``suffix:`` under an ``agents:``
   list rather than a top-level ``nick:`` — the same field ``colleague whoami``
   reads — so resolve_identity must honor it too, or the propagated
   ``COLLEAGUE_IDENTITY`` (and the feedback ``by`` default) silently come up
   empty for the standard clone. Parsed with a minimal stdlib line-scan (no
   PyYAML) because YAML is an optional runtime dep and this module must stay
   zero-deps. The scan handles only simple scalar ``nick: <value>`` /
   ``suffix: <value>`` lines; multi-line / block / anchor forms are
   intentionally out of scope and treated as absent.

2. **.colleague/identity.json** — an optional JSON file with an ``"as"``
   key. Follows the same repo-first, user-home-fallback precedence as the
   rest of colleague's config layer (see ``colleague/configdir.py``).

# TODO(zehut sub-identity): zehut sub-identity resolution would slot in here,
# between source 1 (culture.yaml) and source 2 (identity.json), once the
# zehut spec converges. See the v0 scope note in CLAUDE.md.

The resolved identity is propagated downward to subcommands via the
``COLLEAGUE_IDENTITY`` environment variable (and the legacy ``CONVERTIBLE_IDENTITY``
name, still emitted so sibling AgentCulture CLIs that only read the old variable
keep working) so any subprocess inherits it without a per-call flag. Use
``identity_env()`` to build the env mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague.configdir import config_roots

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_identity(
    repo_path: str | Path,
    *,
    user_home: str | Path | None = None,
) -> str | None:
    """Resolve the agent identity for *repo_path*.

    Resolution order (first non-empty value wins):

    1. ``culture.yaml`` at the repo root — top-level ``nick:`` field, else the
       first agent block's ``suffix:`` field (the canonical template shape).
    2. ``.colleague/identity.json`` (repo-level first, then user-level) — ``"as"`` key.

    Returns ``None`` when no identity can be resolved.

    Args:
        repo_path: Path to the repo directory.
        user_home: (test fixture) Path to user's home; defaults to ``Path.home()``.

    Returns:
        The resolved identity string, or ``None``.
    """
    repo_path = Path(repo_path)
    if user_home is None:
        user_home = Path.home()
    else:
        user_home = Path(user_home)

    # --- Source 1: culture.yaml — top-level nick:, else first agent suffix: ---
    # Read the file at most ONCE, then scan the buffer for both keys: on the
    # canonical (no top-level nick:) path the suffix fallback would otherwise
    # re-read the same file, and resolve_identity runs per culture/devague
    # subprocess and per feedback record.
    culture_yaml = _read_culture_yaml(repo_path)
    if culture_yaml is not None:
        nick = _scan_top_level_nick(culture_yaml)
        if nick:
            return nick
        suffix = _scan_first_agent_suffix(culture_yaml)
        if suffix:
            return suffix

    # --- Source 2: .colleague/identity.json (repo then user) ---
    as_name = _read_identity_json(repo_path, user_home)
    if as_name:
        return as_name

    return None


def identity_env(identity: str | None) -> dict[str, str]:
    """Return the environment mapping for downward propagation.

    Subcommands should merge this dict into their ``env`` or
    ``subprocess.run(..., env={**os.environ, **identity_env(...)})`` call so
    the identity flows down without a per-call flag.

    Args:
        identity: The resolved identity string, or ``None``.

    Returns:
        ``{"COLLEAGUE_IDENTITY": identity, "CONVERTIBLE_IDENTITY": identity}``
        when *identity* is a non-empty string, otherwise an empty dict. Both keys
        carry the same value: ``COLLEAGUE_IDENTITY`` is the new name and
        ``CONVERTIBLE_IDENTITY`` is the deprecated alias kept so sibling CLIs
        (``agtag``/``devex``/``devague``) that only read the old variable still
        inherit the identity.
    """
    if identity:
        return {"COLLEAGUE_IDENTITY": identity, "CONVERTIBLE_IDENTITY": identity}
    return {}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_NICK_PREFIX = "nick:"


def _read_culture_yaml(repo_path: Path) -> str | None:
    """Read the repo-root ``culture.yaml`` once, returning its text.

    Returns the file content, or ``None`` if the file is absent or unreadable.
    Callers scan the returned buffer (no YAML parser — zero-deps) so the file is
    read at most once per :func:`resolve_identity` call even when both the
    ``nick:`` and ``suffix:`` scans run.

    Args:
        repo_path: Path to the repo directory.

    Returns:
        The culture.yaml text, or ``None``.
    """
    culture_yaml = repo_path / "culture.yaml"
    if not culture_yaml.is_file():
        return None
    try:
        return culture_yaml.read_text(encoding="utf-8")
    except OSError:
        return None


def _scan_top_level_nick(content: str) -> str | None:
    """Scan ``culture.yaml`` text for a top-level ``nick:`` value.

    Only simple scalar ``nick: <value>`` lines are recognised; YAML block
    scalars, anchors, and flow mappings are outside scope and treated as absent.

    Args:
        content: The culture.yaml text.

    Returns:
        The nick string if found and non-empty, otherwise ``None``.
    """
    for line in content.splitlines():
        # Only a TOP-LEVEL ``nick:`` counts — a line with leading whitespace is
        # nested under some other key (e.g. ``agents:\n  - nick: other``) and must
        # not be misread as the document's nick. Match the raw (un-stripped) line.
        if line != line.lstrip():
            continue
        if line.startswith(_NICK_PREFIX):
            value = line[len(_NICK_PREFIX) :].strip()
            return value if value else None

    return None


def _scan_first_agent_suffix(content: str) -> str | None:
    """Scan ``culture.yaml`` text for the first agent block's ``suffix:``.

    The canonical AgentCulture template nests the agent nick as a ``suffix:``
    under an ``agents:`` list rather than a top-level ``nick:``::

        agents:
        - suffix: colleague
          backend: claude

    ``colleague whoami`` already reads this shape; resolve_identity must agree,
    or ``COLLEAGUE_IDENTITY`` and the feedback ``by`` default come up empty for a
    standard clone. Matches a ``suffix:`` key whether bare or the first key of a
    list item (``- suffix: …``); takes the FIRST match (the first agent block),
    mirroring ``whoami``. Zero-dep line scan. Returns None if absent or empty.

    Args:
        content: The culture.yaml text.

    Returns:
        The first agent's suffix if found and non-empty, otherwise ``None``.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- suffix:", "suffix:")):
            _, _, value = stripped.partition("suffix:")
            value = value.strip().strip("'\"")
            return value or None

    return None


def _read_identity_json(repo_path: Path, user_home: Path) -> str | None:
    """Read the ``"as"`` field from ``identity.json`` across the config roots.

    Resolves through :func:`colleague.configdir.config_roots`, so it inherits the
    same precedence as every other config file: repo overrides user, and within
    each level the new ``.colleague/`` shadows the deprecated legacy
    ``.convertible/`` (back-compat for the rename). Returns the first non-empty
    ``"as"`` value found.

    Args:
        repo_path: Path to the repo directory.
        user_home: Path to the user's home directory.

    Returns:
        The ``"as"`` value if found and non-empty, otherwise ``None``.
    """
    for root in config_roots(repo_path, user_home=user_home):
        value = _parse_identity_json_as(root / "identity.json")
        if value:
            return value
    return None


def _parse_identity_json_as(path: Path) -> str | None:
    """Parse the ``"as"`` key from *path* if it exists and is readable.

    Args:
        path: Path to an identity.json file.

    Returns:
        The ``"as"`` value if found and non-empty, otherwise ``None``.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    value = data.get("as", "")
    return str(value).strip() if value else None

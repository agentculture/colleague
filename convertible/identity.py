"""Process-level identity resolution module.

Resolves the agent's identity (nick/name) from two ordered sources:

1. **culture.yaml** at the repo root — reads the top-level ``nick:`` field.
   Parsed with a minimal stdlib line-scan (no PyYAML) because YAML is an
   optional runtime dep and this module must stay zero-deps. The scan handles
   only simple scalar ``nick: <value>`` lines; multi-line / block / anchor
   forms are intentionally out of scope and treated as absent.

2. **.convertible/identity.json** — an optional JSON file with an ``"as"``
   key. Follows the same repo-first, user-home-fallback precedence as the
   rest of convertible's config layer (see ``convertible/configdir.py``).

# TODO(zehut sub-identity): zehut sub-identity resolution would slot in here,
# between source 1 (culture.yaml) and source 2 (identity.json), once the
# zehut spec converges. See the v0 scope note in CLAUDE.md.

The resolved identity is propagated downward to subcommands via the
``CONVERTIBLE_IDENTITY`` environment variable so any subprocess inherits it
without a per-call flag. Use ``identity_env()`` to build the env mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

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

    1. ``culture.yaml`` at the repo root — top-level ``nick:`` field.
    2. ``.convertible/identity.json`` (repo-level first, then user-level) — ``"as"`` key.

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

    # --- Source 1: culture.yaml nick ---
    nick = _read_culture_yaml_nick(repo_path)
    if nick:
        return nick

    # --- Source 2: .convertible/identity.json (repo then user) ---
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
        ``{"CONVERTIBLE_IDENTITY": identity}`` when *identity* is a non-empty
        string, otherwise an empty dict.
    """
    if identity:
        return {"CONVERTIBLE_IDENTITY": identity}
    return {}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_NICK_PREFIX = "nick:"


def _read_culture_yaml_nick(repo_path: Path) -> str | None:
    """Scan the repo-root ``culture.yaml`` for a top-level ``nick:`` value.

    Uses a minimal line-by-line scan — no YAML parser — to stay zero-deps.
    Only simple scalar ``nick: <value>`` lines are recognised; YAML block
    scalars, anchors, and flow mappings are outside scope and treated as absent.

    Args:
        repo_path: Path to the repo directory.

    Returns:
        The nick string if found and non-empty, otherwise ``None``.
    """
    culture_yaml = repo_path / "culture.yaml"
    if not culture_yaml.is_file():
        return None

    try:
        content = culture_yaml.read_text(encoding="utf-8")
    except OSError:
        return None

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


def _read_identity_json(repo_path: Path, user_home: Path) -> str | None:
    """Read the ``"as"`` field from ``.convertible/identity.json``.

    Checks repo-level first, then user-level — matching the repo-overrides-user
    convention of ``convertible/configdir.py``.

    Args:
        repo_path: Path to the repo directory.
        user_home: Path to the user's home directory.

    Returns:
        The ``"as"`` value if found and non-empty, otherwise ``None``.
    """
    candidates = [
        repo_path / ".convertible" / "identity.json",
        user_home / ".convertible" / "identity.json",
    ]
    for candidate in candidates:
        value = _parse_identity_json_as(candidate)
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

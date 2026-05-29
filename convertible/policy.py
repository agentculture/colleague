"""Approval-gate policy: operator-declared allow-lists + checksum approvals (t1).

This module is the core of an operator-declared **approval gate**. It reads
``.convertible/approvals.json`` (repo-over-user via :mod:`convertible.configdir`,
plus a per-model overlay ``.convertible/<sanitize_model(model)>/approvals.json``
built by **exact path construction** — sibling model dirs are never globbed, so
model X can never load model Y's policy) and answers two questions for the loop:

* may this ``run_command`` token run? (``check_run_command``)
* is this hook / command file approved and unchanged? (``check_file``)

Config shape (``approvals.json``)::

    {
      "run_command": { "allow": ["git", "pytest", "uv"], "deny": [] },
      "hooks":    { "lint.sh":  "sha256:<hex>" },
      "commands": { "fix-lint": "sha256:<hex>" }
    }

**Enforcement = allow-list per category, only when the section is PRESENT.**
This is the key semantic:

* If a category's section is **absent** from the merged policy → that category is
  a strict **no-op** (everything allowed). This preserves back-compat: a repo
  with no ``approvals.json`` behaves exactly as it did before the gate existed.
* If a category's section is **present** → allow-list semantics: only
  matching / approved entries pass; anything unlisted, unapproved, or tampered
  is **denied**.

**Checksum-only for v0.** Approval values are algorithm-prefixed strings —
``"sha256:<hex>"`` (default) or ``"md5:<hex>"``. There is intentionally **no**
``version`` field in v0 (version matching is a documented follow-up, not built).

Resilience mirrors :mod:`convertible.hooks`: an absent or malformed config file
is treated as empty and **never** raises — a bad policy file degrades to a no-op
rather than aborting a drive.

Only the standard library is used (``json``, ``shlex``, ``hashlib``,
``hmac`` for constant-time compare, ``pathlib``, ``dataclasses``), consistent
with convertible's zero-runtime-deps convention.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from convertible.configdir import resolve_file
from convertible.layers import sanitize_model

#: The approval-gate config filename, resolved through ``.convertible/``.
POLICY_FILENAME = "approvals.json"

#: Default checksum algorithm when none is specified.
DEFAULT_ALGO = "sha256"

#: Checksum algorithms convertible knows how to compute / verify.
_SUPPORTED_ALGOS = frozenset({"sha256", "md5"})

#: The file categories ``check_file`` gates.
_FILE_CATEGORIES = frozenset({"hooks", "commands"})


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The outcome of one policy check.

    Fields
    ------
    allowed:
        ``True`` when the check passes, ``False`` when the gate denies it.
    reason:
        A human-readable explanation, populated **only** when ``allowed`` is
        ``False`` (an allowed verdict carries an empty reason).
    """

    allowed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------


def file_checksum(path: str | Path, algo: str = DEFAULT_ALGO) -> str:
    """Return ``"{algo}:{hexdigest}"`` for *path*'s bytes under *algo*.

    The digest is computed with :func:`hashlib.new` over the file's raw bytes,
    so it is content-exact (line-ending / encoding sensitive). The returned
    value is the algorithm-prefixed form an operator records in
    ``approvals.json``.

    Raises :class:`OSError` if the file cannot be read and :class:`ValueError`
    for an unsupported *algo* — this is the *authoring* side (an operator
    generating an approval), so surfacing the error is appropriate; the
    *verifying* side (:func:`verify_checksum`) is the one that must never raise.
    """
    if algo not in _SUPPORTED_ALGOS:
        raise ValueError(f"unsupported checksum algorithm: {algo!r}")
    data = Path(path).read_bytes()
    digest = hashlib.new(algo, data).hexdigest()
    return f"{algo}:{digest}"


def verify_checksum(path: str | Path, approval: str) -> bool:
    """Return ``True`` iff *path*'s bytes match the *approval* checksum.

    *approval* is an algorithm-prefixed string like ``"sha256:<hex>"``. The
    algorithm is parsed from the prefix, the file's current digest is recomputed
    under it, and the two are compared with :func:`hmac.compare_digest`
    (constant-time, defensive — a checksum is not a secret but the habit is
    cheap).

    This is the **verifying** side of the gate and must **never raise**: an
    unknown algorithm, a malformed ``approval`` (no ``algo:hex`` split), or a
    missing / unreadable file all return ``False`` (cannot verify → deny). The
    only safe failure mode for an approval gate is to *withhold* approval.
    """
    if not isinstance(approval, str) or ":" not in approval:
        return False
    algo, _, expected = approval.partition(":")
    if algo not in _SUPPORTED_ALGOS or not expected:
        return False
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    actual = hashlib.new(algo, data).hexdigest()
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------------------
# Policy object
# ---------------------------------------------------------------------------


class Policy:
    """A resolved approval policy: present sections gate, absent ones no-op.

    Construct via :func:`load_policy`; this constructor takes the already-merged
    section mappings plus the set of section names that were *present* in at
    least one contributing config file. Presence — not emptiness — is what
    drives gating: a ``run_command`` section that exists but lists nothing still
    counts as present (it simply gates nothing, because its allow/deny lists are
    empty), whereas a *missing* ``run_command`` section is a strict no-op.
    """

    def __init__(
        self,
        *,
        run_command: dict | None = None,
        files: dict[str, dict] | None = None,
        present: frozenset[str] | None = None,
    ) -> None:
        self._run_command = run_command or {}
        # Per-category name -> approval-string maps, e.g. {"hooks": {...}}.
        self._files = files or {}
        # Section names present in at least one contributing file.
        self._present = present or frozenset()

    def is_empty(self) -> bool:
        """Return ``True`` when **no** sections are present at all.

        An empty policy is a total no-op: every :meth:`check_run_command` and
        :meth:`check_file` call passes through allowed.
        """
        return not self._present

    def section_present(self, category: str) -> bool:
        """Whether *category* was present in any contributing config (gating active)."""
        return category in self._present

    def file_approval(self, category: str, name: str) -> str | None:
        """The recorded approval string for ``(category, name)`` in the *merged* policy.

        Returns ``None`` when the category is absent or has no entry for *name*.
        Read-only view for introspection (the ``list`` verbs) so the displayed
        status reflects the same repo-over-user + per-model merge that enforcement
        uses — not a raw single-file read.
        """
        return self._files.get(category, {}).get(name)

    def run_command_config(self) -> dict | None:
        """The merged ``run_command`` allow/deny config, or ``None`` when absent."""
        if "run_command" not in self._present:
            return None
        return self._run_command

    def check_run_command(self, command: str) -> Verdict:
        """Gate a ``run_command`` invocation by its program token.

        Semantics:

        * If the ``run_command`` section is **absent** → ``Verdict(True)`` (the
          category is not gated at all).
        * Otherwise the program token is ``shlex.split(command)[0]`` (an empty
          or unparseable command yields no token). Then:

          - if the token is in ``deny`` → denied (deny wins over allow);
          - if an ``allow`` list is **present and non-empty** and the token is
            not in it → denied;
          - otherwise → allowed.

        The reason names the offending token and which rule fired.

        .. warning::
           This is a **policy gate, not a sandbox**. It only inspects the first
           shell token, so it is trivially bypassable by ``sh -c '...'``, pipes,
           command substitution, shell expansion, or an absolute path to a
           renamed binary. It exists to encode operator *intent*, not to contain
           a hostile process. Real isolation is explicitly out of v0 scope.
        """
        if "run_command" not in self._present:
            return Verdict(True)

        token = _first_token(command)
        if token is None:
            return Verdict(
                False,
                "run_command denied: empty command has no program token to approve",
            )

        deny = _str_list(self._run_command.get("deny"))
        if token in deny:
            return Verdict(False, f"run_command denied: {token!r} is on the deny list")

        allow = _str_list(self._run_command.get("allow"))
        if allow and token not in allow:
            return Verdict(False, f"run_command denied: {token!r} is not on the allow list")

        return Verdict(True)

    def check_file(self, category: str, name: str, path: str | Path) -> Verdict:
        """Gate a hook / command file by name + content checksum.

        *category* is one of ``"hooks"`` / ``"commands"``. *name* is the lookup
        key (a hook filename like ``"lint.sh"`` or a command stem like
        ``"fix-lint"``); *path* is the on-disk file to verify.

        Semantics:

        * If that category's section is **absent** → ``Verdict(True)`` (not
          gated).
        * Otherwise look up *name*:

          - no entry → denied (allow-list: an unlisted file is not approved);
          - an entry → :func:`verify_checksum` against *path*; a match is
            allowed, a mismatch is denied (content changed → approval void);
          - a missing / unreadable file → denied (cannot verify).

        An unrecognised *category* is treated as ungated (``Verdict(True)``) —
        only the known file categories participate in the gate.
        """
        if category not in _FILE_CATEGORIES:
            return Verdict(True)
        if category not in self._present:
            return Verdict(True)

        approvals = self._files.get(category, {})
        approval = approvals.get(name)
        if approval is None:
            return Verdict(
                False,
                f"{category} denied: {name!r} is not approved (no entry in approvals.json)",
            )

        if verify_checksum(path, approval):
            return Verdict(True)
        return Verdict(
            False,
            f"{category} denied: {name!r} content changed / approval void "
            "(checksum mismatch or file unreadable)",
        )


# ---------------------------------------------------------------------------
# Loading / merging
# ---------------------------------------------------------------------------


def _str_list(value: object) -> list[str]:
    """Coerce a config value to a list of strings, tolerating bad shapes.

    A non-list (or a list with non-string members) degrades gracefully: only
    string members survive, anything else yields an empty list. This keeps a
    malformed allow/deny list from gating unexpectedly or raising.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _first_token(command: str) -> str | None:
    """Return the first shlex token of *command*, or ``None`` if there is none.

    An empty / whitespace-only command yields ``None``. A command that does not
    lex cleanly (e.g. an unbalanced quote) is treated as having no parseable
    token (``None``) rather than raising — under an allow-list that denies,
    which is the safe direction for a gate.
    """
    if not command or not command.strip():
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    return parts[0] if parts else None


def _parse_policy_file(path: Path | None) -> dict[str, dict]:
    """Parse one ``approvals.json`` into a section -> object mapping.

    Returns an empty mapping when *path* is ``None``, unreadable, not valid
    JSON, or not a JSON object — **never raises**, mirroring
    :func:`convertible.hooks._parse_hooks_file`. Within a valid object, only
    sections whose value is itself an object survive; a section with the wrong
    shape (a string, a list, ``null``) is dropped, so it is treated as absent
    rather than gating unexpectedly.
    """
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(value, dict)}


def _str_map(value: object) -> dict[str, str]:
    """Coerce a section value to a ``{name: approval}`` map of strings."""
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def load_policy(
    repo_path: str | Path,
    *,
    model: str | None = None,
    user_home: str | Path | None = None,
) -> Policy:
    """Load the approval :class:`Policy` for *repo_path*, with optional overlay.

    Resolution mirrors :func:`convertible.hooks.load_hooks`:

    1. The base ``approvals.json`` is resolved via
       :func:`convertible.configdir.resolve_file` (repo-over-user precedence).
    2. When *model* is given, the per-model overlay
       ``.convertible/<sanitize_model(model)>/approvals.json`` is resolved
       through the **same** configdir machinery. The overlay path is built by
       **exact construction** via :func:`convertible.layers.sanitize_model` —
       sibling ``.convertible/*/`` directories are never globbed, so model X can
       never load model Y's policy.

    **Merge / precedence.** The overlay wins for the keys it defines: an overlay
    that redefines ``run_command`` replaces the base ``run_command`` wholesale,
    while sections only the base defines survive untouched. A section is
    considered **present** (and therefore gating, per the allow-list-when-present
    rule) if *any* contributing file defines it.

    **Strict no-op.** With ``model=None`` and no base file — or any combination
    where no section is defined anywhere — the returned policy is empty
    (:meth:`Policy.is_empty` is ``True``) and every check passes through. An
    absent or malformed file at any layer is skipped, never raised.
    """
    base = _parse_policy_file(resolve_file(repo_path, POLICY_FILENAME, user_home=user_home))

    overlay: dict[str, dict] = {}
    if model is not None:
        safe = sanitize_model(model)
        overlay = _parse_policy_file(
            resolve_file(repo_path, f"{safe}/{POLICY_FILENAME}", user_home=user_home)
        )

    # Overlay wins per key; a section is present if any layer defines it.
    merged = {**base, **overlay}
    present = frozenset(merged)

    run_command = merged.get("run_command", {})
    files = {category: _str_map(merged.get(category)) for category in _FILE_CATEGORIES}

    return Policy(run_command=run_command, files=files, present=present)

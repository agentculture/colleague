"""Identity minting for the colleague resident.

Writes a ``culture.yaml`` at the repo root in the canonical AgentCulture template
shape, and a matching prompt file, such that :func:`colleague.identity.resolve_identity`
reads back the minted nick from the first agent block's ``suffix:`` field.

No PyYAML — the file is written as plain text matching the minimal shape that
:func:`colleague.identity._scan_first_agent_suffix` accepts (a zero-dep line-scanner).
No asyncio, no subprocess, no socket.  Stdlib + colleague only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Default resident system prompt
# ---------------------------------------------------------------------------

_DEFAULT_PROMPT = """\
# Colleague Resident

You are a colleague resident — a long-lived mesh peer that works alongside
other agents in the AgentCulture IRC mesh.  Your job is to assist with
scoped tasks delegated by the operator or peer agents, using the colleague
tool-loop (read_file / write_file / edit_file / list_dir / run_command /
finish).

Follow the operator's AGENTS.md instructions and the skills loaded from
.colleague/skills/ when present.  Prefer small, reversible steps; handoff
via finish when done.
"""

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ConflictError(ValueError):
    """A ``culture.yaml`` already exists with different content.

    Raised by :func:`mint_identity` when a pre-existing ``culture.yaml``
    does not match the content that would be written, and ``overwrite=False``
    (the default).  Pass ``overwrite=True`` to replace it.
    """


@dataclass(frozen=True)
class MintResult:
    """Record of what :func:`mint_identity` wrote.

    Attributes:
        nick: The resolved nick — the ``suffix`` value written into ``culture.yaml``.
        culture_yaml_path: Absolute path to the written ``culture.yaml``.
        prompt_path: Absolute path to the written prompt file.
    """

    nick: str
    culture_yaml_path: Path
    prompt_path: Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mint_identity(
    repo_path: str | Path,
    *,
    suffix: str,
    model: str,
    prompt_text: str | None = None,
    prompt_filename: str = "AGENTS.colleague.md",
    overwrite: bool = False,
) -> MintResult:
    """Mint a stable mesh identity for the colleague resident.

    Writes two files at *repo_path*:

    1. ``culture.yaml`` — the canonical AgentCulture template shape so that
       :func:`colleague.identity.resolve_identity` reads the nick back from
       the first agent block's ``suffix:``:

       .. code-block:: yaml

           agents:
           - suffix: <suffix>
             backend: colleague
             model: <model>

    2. *prompt_filename* (default ``AGENTS.colleague.md``) — the resident
       system prompt, using *prompt_text* or a built-in default when omitted.

    The function is **idempotent**: calling it twice with the same arguments
    produces byte-identical files (no clobber, no error).  If a
    ``culture.yaml`` already exists with *different* content and
    ``overwrite=False``, :exc:`ConflictError` is raised and nothing is
    written.  Pass ``overwrite=True`` to replace the existing file.

    Args:
        repo_path: Root of the repository where the files will be written.
        suffix: The agent nick — written as ``suffix:`` in ``culture.yaml``
            and returned as :attr:`MintResult.nick`.
        model: The model identifier — written as ``model:`` in ``culture.yaml``.
        prompt_text: Text for the prompt file.  When ``None``, a short
            built-in resident system prompt is used.
        prompt_filename: Filename (not path) for the prompt file.
            Defaults to ``"AGENTS.colleague.md"``.
        overwrite: When ``True``, an existing ``culture.yaml`` with different
            content is replaced.  When ``False`` (default) such a conflict
            raises :exc:`ConflictError`.

    Returns:
        A :class:`MintResult` record with the resolved nick and the absolute
        paths of both written files.

    Raises:
        ConflictError: When ``culture.yaml`` already exists with different
            content and ``overwrite=False``.
    """
    repo_path = Path(repo_path).resolve()

    if prompt_text is None:
        prompt_text = _DEFAULT_PROMPT

    culture_yaml_content = _render_culture_yaml(suffix=suffix, model=model)
    culture_yaml_path = repo_path / "culture.yaml"

    # ------------------------------------------------------------------
    # Idempotence + conflict guard
    # ------------------------------------------------------------------
    if culture_yaml_path.exists():
        existing = culture_yaml_path.read_text(encoding="utf-8")
        if existing == culture_yaml_content:
            # Byte-identical — idempotent re-mint, no write needed.
            pass
        elif overwrite:
            culture_yaml_path.write_text(culture_yaml_content, encoding="utf-8")
        else:
            raise ConflictError(
                f"culture.yaml already exists at {culture_yaml_path} with different "
                f"content.  Pass overwrite=True to replace it, or remove it manually."
            )
    else:
        culture_yaml_path.write_text(culture_yaml_content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Prompt file (always written; idempotent by content)
    # ------------------------------------------------------------------
    prompt_path = repo_path / prompt_filename
    prompt_path.write_text(prompt_text, encoding="utf-8")

    return MintResult(
        nick=suffix,
        culture_yaml_path=culture_yaml_path,
        prompt_path=prompt_path,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _render_culture_yaml(*, suffix: str, model: str) -> str:
    """Render the canonical culture.yaml text for the given *suffix* and *model*.

    The shape is the minimal AgentCulture template that
    :func:`colleague.identity._scan_first_agent_suffix` (zero-dep line scanner)
    reads back: an ``agents:`` list with a single entry carrying ``suffix:``,
    ``backend: colleague``, and ``model:``.

    No PyYAML — plain text construction keeps the module zero-dep.

    Args:
        suffix: The agent nick.
        model: The model identifier.

    Returns:
        The culture.yaml content as a UTF-8 string.
    """
    return f"agents:\n- suffix: {suffix}\n  backend: colleague\n  model: {model}\n"

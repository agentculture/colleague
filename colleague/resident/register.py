"""colleague.resident.register — self-registration: steward template path + arrival signal.

Places the resident's minted identity (``culture.yaml`` + prompt file) where the Culture
steward discovers it, then optionally signals arrival by calling the steward CLI.

The **arrival subcommand** used to signal arrival is ``["doctor"]``.  The rationale:
``steward doctor`` is a read-only health check that every operator environment is
expected to support and that triggers a presence announcement when the resident's
identity is injected into the environment.  It is the safest idempotent signal — it
cannot modify state and will not fail if the resident is already known to the mesh.
The constant :data:`ARRIVAL_SUBCOMMAND` documents this choice; operators who want a
stronger signal (e.g. ``["register"]``) can pass ``arrival_args`` explicitly.

No subprocess here — subprocess is confined to :mod:`colleague.resident.steward` by the
boundary guard (``tests/test_boundary.py``).  This module calls
:func:`colleague.resident.steward.run_steward` for all CLI interaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from colleague.resident.identity_mint import mint_identity
from colleague.resident.steward import StewardError, parse_steward_output, run_steward

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The steward subcommand used to signal arrival.
#:
#: ``steward doctor`` is chosen because it is a read-only, idempotent health-check
#: that announces the resident's presence via the injected ``COLLEAGUE_IDENTITY``
#: environment variable without mutating steward state.  It is universally supported
#: and safe to call repeatedly.
ARRIVAL_SUBCOMMAND: list[str] = ["doctor"]

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterResult:
    """Record of what :func:`register_resident` wrote and signalled.

    Attributes:
        nick: The resolved resident nick (the ``suffix`` written into ``culture.yaml``).
        culture_yaml_path: Absolute path to the written ``culture.yaml``.
        prompt_path: Absolute path to the written prompt file.
        signalled: ``True`` if arrival was successfully signalled to the steward CLI.
        signal_output: The steward CLI output string when ``signalled`` is ``True``;
            the degradation note when ``signalled`` is ``False`` and signalling was
            attempted; ``""`` when ``signal=False`` was passed.
    """

    nick: str
    culture_yaml_path: Path
    prompt_path: Path
    signalled: bool
    signal_output: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_resident(
    repo_path: str | Path,
    *,
    suffix: str,
    model: str,
    steward_cli: str = "steward",
    steward_root: str | Path | None = None,
    prompt_text: str | None = None,
    arrival_args: list[str] | None = None,
    signal: bool = True,
    overwrite: bool = False,
) -> RegisterResult:
    """Mint the resident's identity at the steward-discovered location and signal arrival.

    **Registration** (always runs): calls :func:`~colleague.resident.identity_mint.mint_identity`
    to write ``culture.yaml`` and a prompt file under *steward_root* (defaults to *repo_path*).
    The function is **idempotent** — calling it repeatedly with the same arguments writes
    byte-identical files without raising an error.

    **Arrival signal** (when ``signal=True``, the default): calls
    :func:`~colleague.resident.steward.run_steward` with the chosen CLI and
    :data:`ARRIVAL_SUBCOMMAND` (or a caller-supplied *arrival_args* override).
    If the CLI raises :exc:`~colleague.resident.steward.StewardError` (absent,
    timed-out, or otherwise unreachable), the registration files are **not** rolled
    back — the result records ``signalled=False`` and a clear note; **no exception
    escapes**.

    Args:
        repo_path: Root of the repository.  Used as the default for *steward_root*.
        suffix: The resident nick — written as ``suffix:`` in ``culture.yaml`` and
            returned as :attr:`RegisterResult.nick`.
        model: The model identifier — written as ``model:`` in ``culture.yaml``.
        steward_cli: The roster CLI to call (must be in
            :data:`~colleague.resident.steward.ALLOWED_STEWARD_CLIS`).
            Defaults to ``"steward"``.
        steward_root: Where to write the identity files and where the steward CLI
            is called from.  Defaults to *repo_path*.
        prompt_text: Text for the resident prompt file.  ``None`` uses the
            built-in default from :mod:`colleague.resident.identity_mint`.
        arrival_args: Argv to forward to the steward CLI (everything after the
            program name).  Defaults to :data:`ARRIVAL_SUBCOMMAND` (``["doctor"]``).
        signal: When ``True`` (default), call the steward CLI to signal arrival.
            Pass ``False`` to skip the signal entirely (useful for dry-run / offline
            scenarios).
        overwrite: When ``True``, an existing ``culture.yaml`` with different content
            is replaced.  When ``False`` (default), a conflict raises
            :exc:`~colleague.resident.identity_mint.ConflictError`.

    Returns:
        A :class:`RegisterResult` record with the nick, the written paths, and
        arrival-signal status.

    Raises:
        colleague.resident.identity_mint.ConflictError: When ``culture.yaml`` already
            exists with different content and ``overwrite=False``.  The signal step is
            never attempted after a ConflictError.
    """
    root = Path(steward_root if steward_root is not None else repo_path).resolve()

    # ------------------------------------------------------------------
    # Step 1: Write the identity files (may raise ConflictError — let it propagate).
    # ------------------------------------------------------------------
    mint_result = mint_identity(
        root,
        suffix=suffix,
        model=model,
        prompt_text=prompt_text,
        overwrite=overwrite,
    )

    # ------------------------------------------------------------------
    # Step 2: Signal arrival (graceful degrade on StewardError).
    # ------------------------------------------------------------------
    signalled = False
    signal_output = ""

    if signal:
        args = arrival_args if arrival_args is not None else ARRIVAL_SUBCOMMAND
        try:
            signal_output = run_steward(steward_cli, args, root=root)
            # The CLI ran; only a zero exit counts as a successful arrival signal —
            # a non-zero exit is a CLI-reported failure, not a success (qodo flag).
            exit_code, _ = parse_steward_output(signal_output)
            signalled = exit_code == 0
        except StewardError as exc:
            signalled = False
            signal_output = (
                f"arrival signal skipped — steward CLI '{steward_cli}' unavailable: {exc}"
            )

    return RegisterResult(
        nick=mint_result.nick,
        culture_yaml_path=mint_result.culture_yaml_path,
        prompt_path=mint_result.prompt_path,
        signalled=signalled,
        signal_output=signal_output,
    )

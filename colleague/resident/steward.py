"""colleague.resident.steward — the resident's one sanctioned subprocess consumer.

The resident learns *which channels are relevant* and *announces its arrival* by
shelling out to the operator-installed Culture roster CLI (``steward`` or
``culture``), exactly as :mod:`colleague.culture` shells out to ``agtag`` /
``devex``: a subprocess, never an import — no socket, no daemon, no live MCP. The
resolved process identity is injected into the child (so the CLI auto-signs from
``culture.yaml``) and ``cwd`` is pinned at the repo root.

This is the **only** module under ``colleague/resident/`` permitted to import
``subprocess`` (the boundary allow-list in ``tests/test_boundary.py``). The
sibling modules — ``channels`` (selection) and ``register`` (self-registration) —
hold the *logic* and call into here for the *transport*, so subprocess stays
confined to one file. An absent CLI, a timeout, or any launch failure maps to a
clean :class:`StewardError` string, never a traceback.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - launching operator roster CLIs is the point (trusted env, D2)
from pathlib import Path
from typing import Sequence

from colleague.identity import identity_env, resolve_identity

#: The curated allow-list of roster/registrar CLIs the resident may launch. Any
#: name outside this set is rejected before any subprocess is spawned.
ALLOWED_STEWARD_CLIS: frozenset[str] = frozenset({"steward", "culture"})

#: Cap child output (mirrors culture._MAX_OUTPUT_CHARS).
_MAX_OUTPUT_CHARS = 20_000

#: Bound a runaway CLI so it cannot stall the resident indefinitely.
_TIMEOUT_SECONDS = 120


class StewardError(Exception):
    """A roster/registrar CLI call that cannot be honored (bad name, absent CLI, timeout).

    Callers (``channels`` / ``register``) translate this into their own clean
    result so the resident never crashes on a missing or hung operator CLI.
    """


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n... [truncated at {_MAX_OUTPUT_CHARS} chars]"


def run_steward(
    cli: str,
    args: Sequence[str],
    *,
    root: str | Path,
) -> str:
    """Launch an allow-listed roster/registrar CLI as a subprocess; return its output.

    Args:
        cli: The CLI name — must be in :data:`ALLOWED_STEWARD_CLIS`
            (``steward`` / ``culture``).
        args: The argv to forward (everything after the program name).
        root: The repo root; the child runs with ``cwd`` pinned here and the
            resolved identity injected into its environment.

    Returns:
        ``exit=<code>\\n<combined stdout+stderr>``, truncated.

    Raises:
        StewardError: if *cli* is outside the allow-list, the CLI is not
            installed (``FileNotFoundError``), it times out
            (``subprocess.TimeoutExpired``), or it otherwise fails to launch
            (``OSError``) — always a clean error, never a traceback.
    """
    if cli not in ALLOWED_STEWARD_CLIS:
        allowed = ", ".join(sorted(ALLOWED_STEWARD_CLIS))
        raise StewardError(f"roster CLI '{cli}' is not in the allow-list ({allowed})")

    root_path = Path(root).resolve()
    identity = resolve_identity(root_path)
    env = {**os.environ, **identity_env(identity)}

    argv = [cli, *[str(a) for a in args]]
    try:
        proc = subprocess.run(  # nosec B603 - allow-listed CLI, no shell, trusted env (D2)
            argv,
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            env=env,
        )
    except FileNotFoundError as exc:
        raise StewardError(f"roster CLI '{cli}' not found — is it installed and on PATH?") from exc
    except subprocess.TimeoutExpired as exc:
        raise StewardError(f"roster CLI '{cli}' timed out after {_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise StewardError(f"roster CLI '{cli}' failed to launch: {exc}") from exc

    body = (proc.stdout or "") + (proc.stderr or "")
    return _truncate(f"exit={proc.returncode}\n{body}")


def parse_steward_output(output: str) -> tuple[int, str]:
    """Split :func:`run_steward`'s ``"exit=<code>\\n<body>"`` into ``(exit_code, body)``.

    :func:`run_steward` reports the CLI's exit code *in-band* — it raises only on an
    absent/hung CLI, never on a non-zero exit (mirroring
    :func:`colleague.culture.run_culture`). A colleague-side caller that must
    distinguish a clean run from a CLI-reported failure uses this to read the code
    rather than acting on error output. A missing/garbled header is treated as a
    non-zero (unknown) failure, so a malformed result never reads as success.

    Args:
        output: The string returned by :func:`run_steward`.

    Returns:
        ``(exit_code, body)`` — the parsed exit code and the body after the header.
    """
    head, _, body = output.partition("\n")
    if head.startswith("exit="):
        try:
            return int(head[len("exit=") :]), body
        except ValueError:
            pass
    return 1, output

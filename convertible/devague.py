"""Curated devague loop tool — shell out to the operator-installed devague CLI.

The chassis offers the model a *single* shared ``devague`` tool (registered into
the closed tool surface in :mod:`convertible.tools`) that lets an engine set and
converge a goal-frame when a task warrants one, drive toward it, and declare the
announcement on arrival — so convertible knows where it's going, not just where
it is.

An allow-list (:data:`ALLOWED_MOVES`) restricts which devague *moves* the engine
may invoke.  The curated set intentionally excludes:

- ``confirm`` and ``reject`` — these are **user-only** decisions; the engine
  must never be able to confirm its own claims (structural epistemic discipline).
- ``export`` — this is an **operator-only** move; arrival is recorded as a
  lightweight announcement, the engine does not write spec files.

Identity propagation.  Each invocation injects the resolved process identity
into the child via :func:`convertible.identity.identity_env` so the CLI
inherits ``CONVERTIBLE_IDENTITY``, and runs with ``cwd`` pinned at the repo
root so devague that auto-signs from ``culture.yaml`` sees it.  The CLI is
*launched as a subprocess*, never imported as Python — no socket, no daemon.
A missing CLI (``FileNotFoundError``), a timeout (``subprocess.TimeoutExpired``),
or any other launch failure (``OSError``) is mapped to a clean
:class:`DevagueToolError`, never a traceback — so a hung or broken CLI returns a
tool-error string to the model instead of crashing the drive.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - launching operator CLI is the point (trusted env, D2)
from pathlib import Path
from typing import Any, Sequence

from convertible.identity import identity_env, resolve_identity

#: The curated allow-list of moves the engine may invoke.  Excludes
#: ``confirm`` / ``reject`` (user-only decisions) and ``export``
#: (operator-only; arrival is recorded as a lightweight announcement).
ALLOWED_MOVES: frozenset[str] = frozenset(
    {"new", "capture", "interrogate", "park", "converge", "status", "show"}
)

#: Cap child output fed back to the model (mirrors tools._MAX_OUTPUT_CHARS intent).
_MAX_OUTPUT_CHARS = 20_000

#: Bound a runaway CLI so it cannot stall the loop indefinitely.
_TIMEOUT_SECONDS = 300


class DevagueToolError(Exception):
    """A devague tool call that cannot be honored (bad move, absent CLI).

    :mod:`convertible.tools` translates this into its own ``ToolError`` so the
    loop feeds a clean string back to the model.
    """


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n... [truncated at {_MAX_OUTPUT_CHARS} chars]"


def run_devague(
    move: str,
    args: Sequence[str],
    *,
    root: str | Path,
) -> str:
    """Launch a curated devague move as a subprocess and return its output.

    Args:
        move: The devague move — must be in :data:`ALLOWED_MOVES`.
            ``confirm``, ``reject``, and ``export`` are deliberately excluded.
        args: The argv to forward to the CLI (everything after the move name).
        root: The repo root; the child runs with ``cwd`` pinned here and the
            resolved identity is injected into its environment.

    Returns:
        A string of the form ``exit=<code>\\n<combined stdout+stderr>``, truncated.

    Raises:
        DevagueToolError: if *move* is outside the allow-list, the ``devague``
            binary is not installed (``FileNotFoundError``), the move times out
            (``subprocess.TimeoutExpired``), or it otherwise fails to launch
            (``OSError``) — always a clean error, never a traceback.
    """
    if move not in ALLOWED_MOVES:
        allowed = ", ".join(sorted(ALLOWED_MOVES))
        raise DevagueToolError(f"devague move '{move}' is not in the allow-list ({allowed})")

    root_path = Path(root).resolve()
    identity = resolve_identity(root_path)
    env = {**os.environ, **identity_env(identity)}

    argv = ["devague", move, *[str(a) for a in args]]
    try:
        proc = subprocess.run(  # nosec B603 - allow-listed move, no shell, trusted env (D2)
            argv,
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            env=env,
        )
    except FileNotFoundError as exc:
        raise DevagueToolError("devague CLI not found — is it installed and on PATH?") from exc
    except subprocess.TimeoutExpired as exc:
        # A hung CLI must surface as a clean tool error, not an uncaught
        # exception that escapes ToolExecutor and crashes the drive (the loop
        # only catches ToolError around tool execution).
        raise DevagueToolError(
            f"devague move '{move}' timed out after {_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        # Any other launch/IO failure (e.g. permission denied) → clean error.
        raise DevagueToolError(f"devague move '{move}' failed to launch: {exc}") from exc

    body = (proc.stdout or "") + (proc.stderr or "")
    return _truncate(f"exit={proc.returncode}\n{body}")


def normalize_args(raw: Any) -> list[str]:
    """Coerce the model-supplied ``args`` into a clean list of strings.

    Accepts a list (the declared shape) or a single string (a lenient fallback
    for models that pass argv as one blob); anything else becomes an empty argv.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return raw.split()
    if isinstance(raw, (list, tuple)):
        return [str(a) for a in raw]
    return []

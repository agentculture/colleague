"""Curated culture loop tools — shell out to operator-installed AgentCulture CLIs.

The chassis offers the model a *single* shared ``culture`` tool (registered into
the closed tool surface in :mod:`convertible.tools`) rather than one tool per CLI.
A single tool keeps the surface minimal — "less tools is good" — while an
allow-list (:data:`ALLOWED_CLIS`) restricts which CLI it may launch: exactly
``agtag`` (mesh issues — ``agtag issue post/fetch/reply``) and ``agex``
(inspect a repo's agent-first surface — ``agex explain/overview/learn``).

These tools are UNGATED: they execute like ``run_command`` does (trusted-operator
environment, decision D2) — no special gating, no trust prompt.

Identity propagation. Each invocation injects the resolved process identity into
the child via :func:`convertible.identity.identity_env` so the CLI inherits
``CONVERTIBLE_IDENTITY``, and runs with ``cwd`` pinned at the repo root so a CLI
like ``agtag`` that auto-signs from ``culture.yaml`` sees it. The CLI is *launched
as a subprocess*, never imported as Python — no socket, no daemon. An absent CLI
(``FileNotFoundError``), a timeout (``subprocess.TimeoutExpired``), or any other
launch failure (``OSError``) is mapped to a clean
:class:`~convertible.tools.ToolError` string fed back to the model, never a
traceback — so a hung or broken CLI cannot crash the drive.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - launching operator CLIs is the point (trusted env, D2)
from pathlib import Path
from typing import Any, Sequence

from convertible.identity import identity_env, resolve_identity

#: The curated allow-list. Any CLI name outside this set is rejected with a
#: clean error before any subprocess is spawned.
ALLOWED_CLIS: frozenset[str] = frozenset({"agtag", "agex"})

#: Cap child output fed back to the model (mirrors tools._MAX_OUTPUT_CHARS intent).
_MAX_OUTPUT_CHARS = 20_000

#: Bound a runaway CLI so it cannot stall the loop indefinitely.
_TIMEOUT_SECONDS = 300


class CultureToolError(Exception):
    """A culture tool call that cannot be honored (bad CLI name, absent CLI).

    :mod:`convertible.tools` translates this into its own ``ToolError`` so the
    loop feeds a clean string back to the model.
    """


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n... [truncated at {_MAX_OUTPUT_CHARS} chars]"


def run_culture(
    cli: str,
    args: Sequence[str],
    *,
    root: str | Path,
) -> str:
    """Launch an allow-listed AgentCulture CLI as a subprocess and return its output.

    Args:
        cli: The CLI name — must be in :data:`ALLOWED_CLIS` (``agtag`` / ``agex``).
        args: The argv to forward to the CLI (everything after the program name).
        root: The repo root; the child runs with ``cwd`` pinned here and the
            resolved identity is injected into its environment.

    Returns:
        A string of the form ``exit=<code>\\n<combined stdout+stderr>``, truncated.

    Raises:
        CultureToolError: if *cli* is outside the allow-list, the CLI is not
            installed (``FileNotFoundError``), it times out
            (``subprocess.TimeoutExpired``), or it otherwise fails to launch
            (``OSError``) — always a clean error, never a traceback.
    """
    if cli not in ALLOWED_CLIS:
        allowed = ", ".join(sorted(ALLOWED_CLIS))
        raise CultureToolError(f"culture CLI '{cli}' is not in the allow-list ({allowed})")

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
        raise CultureToolError(
            f"culture CLI '{cli}' not found — is it installed and on PATH?"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        # A hung CLI must surface as a clean tool error, not an uncaught
        # exception that escapes ToolExecutor and crashes the drive (the loop
        # only catches ToolError around tool execution).
        raise CultureToolError(f"culture CLI '{cli}' timed out after {_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        # Any other launch/IO failure (e.g. permission denied) → clean error.
        raise CultureToolError(f"culture CLI '{cli}' failed to launch: {exc}") from exc

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

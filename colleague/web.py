"""Curated webglass loop tool — shell out to the operator-installed webglass CLI.

Mirrors :mod:`colleague.devague`'s shape (identity injection, cwd pinned at
the repo root, output truncation, clean error mapping) but for the
``webglass`` web-scout CLI instead of ``devague``. The child does not run to
quick completion the way a devague move does — a browser-driving CLI can
legitimately hang on a slow page — so containment here is stronger: the child
is launched as its own **process group leader**
(``subprocess.Popen(..., start_new_session=True)``) and, on timeout, the
*whole group* is killed with :func:`os.killpg`, mirroring
:mod:`colleague.background`'s detach style without adopting its detach (this
child is still waited on synchronously, just group-contained).

An allow-list (:data:`ALLOWED_VERBS`) restricts which webglass verbs the
engine may invoke. Deliberately excluded: ``action`` and ``session`` (no
verb of that shape is in the allow-list at all) and ``page screenshot``
(binary output has no place in a text tool loop). A small set of argv
tokens (:data:`FORBIDDEN_TOKENS`) that name session/profile identifiers are
refused unconditionally, and any URL argument must match ``^https?://`` —
both checks run **before** the child is ever spawned.

The CLI is *launched as a subprocess*, never imported as Python — no socket,
no daemon, no polling loop. A missing CLI (``FileNotFoundError``), a
timeout (``subprocess.TimeoutExpired``), or any other launch failure
(``OSError``) is mapped to a clean :class:`WebToolError`, never a traceback.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess  # nosec B404 - launching operator CLI is the point (trusted env, D2)
from pathlib import Path
from typing import Sequence

from colleague.identity import identity_env, resolve_identity

#: The ``page open`` verb — the url is a positional argument.
PAGE_OPEN = "page open"

#: The ``page extract`` verb — may add a free-text query after ``--``.
PAGE_EXTRACT = "page extract"

#: The curated allow-list of webglass verbs the engine may invoke. Excludes
#: ``action`` / ``session`` (no such verb is a member) and ``page
#: screenshot`` (binary output has no place in a text tool loop).
ALLOWED_VERBS: frozenset[str] = frozenset(
    {
        "search",
        PAGE_OPEN,
        "page read",
        "page inspect",
        PAGE_EXTRACT,
        "page links",
    }
)

#: The subset of :data:`ALLOWED_VERBS` that take a URL as their first
#: free argument.
_URL_VERBS: frozenset[str] = frozenset(
    {PAGE_OPEN, "page read", "page inspect", PAGE_EXTRACT, "page links"}
)

#: argv tokens that name a session/profile identifier — always refused,
#: regardless of verb, before the child is spawned.
FORBIDDEN_TOKENS: frozenset[str] = frozenset({"--session-id", "--page-ref", "--policy-profile"})

#: A bare ``http(s)://`` URL — the only shape accepted for a url argument.
_URL_RE = re.compile(r"^https?://")

#: Safety ceiling on the raw CLI output returned to the caller. The model-facing
#: bound is the executor's own ``_truncate`` (which honours
#: ``EngineConfig.max_output_chars``); this only stops a runaway CLI from
#: returning an unbounded blob. It is deliberately far above any legitimate
#: JSON envelope so a large-but-valid envelope is never cut mid-way before it
#: can be parsed (Qodo #2 + #5).
_MAX_RAW_CHARS = 2_000_000

#: Bound a runaway CLI so it cannot stall the loop indefinitely. A module
#: constant (not a default arg) so tests can monkeypatch it directly.
_TIMEOUT_SECONDS = 120


class WebToolError(Exception):
    """A webglass tool call that cannot be honored (bad verb, absent CLI).

    :mod:`colleague.tools` translates this into its own ``ToolError`` so the
    loop feeds a clean string back to the model.
    """


def _truncate(text: str) -> str:
    if len(text) <= _MAX_RAW_CHARS:
        return text
    return text[:_MAX_RAW_CHARS] + f"\n... [truncated at {_MAX_RAW_CHARS} chars]"


def _check_forbidden_tokens(verb: str, args: Sequence[str]) -> None:
    for token in args:
        if token in FORBIDDEN_TOKENS:
            raise WebToolError(f"webglass verb '{verb}' refused: forbidden argument {token!r}")


def _build_search_argv(args: list[str]) -> list[str]:
    """``search`` argv: options FIRST, then a literal ``--``, then the
    free-text query — so a query that starts with ``-`` can never be
    mistaken for a flag.

    ``args[0]`` is the free-text query (see web_schemas._build_args); the
    remaining args are options (e.g. --limit N).
    """
    if not args:
        raise WebToolError("webglass verb 'search' requires a query argument")
    argv = ["webglass", "search", "--json", *args[1:]]
    argv.extend(["--", args[0]])
    return argv


def _check_url(verb: str, args: list[str]) -> tuple[str, list[str]]:
    """Validate the url argument of a URL verb; return ``(url, rest)``."""
    if not args or not _URL_RE.match(str(args[0])):
        raise WebToolError(f"webglass verb '{verb}' requires a url argument matching ^https?://")
    return args[0], args[1:]


def _split_options_and_query(rest: list[str]) -> tuple[list[str], list[str]]:
    """Split *rest* into (options, query) for ``page extract``.

    Options (--limit N, ...) are emitted as pairs BEFORE ``--``; only the
    free-text query goes after it (Qodo #7).
    """
    options: list[str] = []
    query: list[str] = []
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("--"):
            options.append(token)
            # A flag with a value (--limit N) keeps its value adjacent and
            # BEFORE "--".
            if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
                options.append(rest[i + 1])
                i += 1
        else:
            query.append(token)
        i += 1
    return options, query


def _build_argv(verb: str, args: list[str]) -> list[str]:
    """Build the webglass argv for *verb* (grammar verified 2026-08-28 against
    ``webglass <verb> --help``).

    * ``search``: options FIRST, then a literal ``--``, then the free-text
      query — so a query that starts with ``-`` can never be mistaken for a
      flag.
    * ``page open``: the url is a positional argument.
    * ``page read|inspect|extract|links``: the url goes as ``--url <url>``,
      never positional; ``page extract`` may add the free-text query after
      ``--``.
    """
    if verb == "search":
        return _build_search_argv(args)

    if verb in _URL_VERBS:
        url, rest = _check_url(verb, args)
        if verb == PAGE_OPEN:
            # page open takes the url positionally.
            return ["webglass", "page", "open", "--json", url, *rest]
        # page read|inspect|extract|links take the url as --url, never
        # positional.
        argv = ["webglass", "page", verb.split()[1], "--json", "--url", url]
        if verb == PAGE_EXTRACT:
            # extract may carry a free-text query after a literal "--".
            options, query = _split_options_and_query(rest)
            argv.extend(options)
            if query:
                argv.extend(["--", *query])
        else:
            argv.extend(rest)
        return argv

    return ["webglass", *verb.split(), *args, "--json"]


def run_web(verb: str, args: Sequence[str], *, root: str | Path) -> str:
    """Launch a curated webglass verb as a subprocess and return its output.

    Args:
        verb: The webglass verb — must be in :data:`ALLOWED_VERBS`.
        args: The argv to forward to the CLI (everything after the verb).
        root: The repo root; the child runs with ``cwd`` pinned here and the
            resolved identity is injected into its environment.

    Returns:
        A string of the form ``exit=<code>\\n<combined stdout+stderr>`` — the
        FULL output, bounded only by the :data:`_MAX_RAW_CHARS` safety ceiling.
        The model-facing bound is applied by the executor's own ``_truncate``
        (``EngineConfig.max_output_chars``) AFTER the envelope is parsed and
        rendered, so a large-but-valid JSON envelope is never cut mid-way
        before it can be parsed (Qodo #2 + #5).

    Raises:
        WebToolError: if *verb* is outside the allow-list, *args* contains a
            forbidden token, a required url argument is missing or malformed,
            the ``webglass`` binary is not installed (``FileNotFoundError``),
            the call times out (``subprocess.TimeoutExpired``), or it
            otherwise fails to launch (``OSError``) — always a clean error,
            never a traceback.
    """
    if verb not in ALLOWED_VERBS:
        allowed = ", ".join(sorted(ALLOWED_VERBS))
        raise WebToolError(f"webglass verb '{verb}' is not in the allow-list ({allowed})")

    # Hidden-state guard (TOCTOU): the knob may have been set after the schema
    # was curated, so refuse here — before the child is ever spawned.
    if os.environ.get("COLLEAGUE_WEB") == "0":
        raise WebToolError("web tool hidden by COLLEAGUE_WEB=0")

    str_args = [str(a) for a in args]
    _check_forbidden_tokens(verb, str_args)
    argv = _build_argv(verb, str_args)

    root_path = Path(root).resolve()
    identity = resolve_identity(root_path)
    env = {**os.environ, **identity_env(identity)}

    try:
        proc = subprocess.Popen(  # nosec B603 - allow-listed verb, no shell, trusted env (D2)
            argv,
            cwd=str(root_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise WebToolError("webglass CLI not found — is it installed and on PATH?") from exc
    except OSError as exc:
        raise WebToolError(f"webglass verb '{verb}' failed to launch: {exc}") from exc

    try:
        stdout, stderr = proc.communicate(timeout=_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        # Kill the WHOLE process group the child leads (start_new_session
        # made it a group leader), not just the direct child — a hung
        # webglass CLI may have spawned a browser/grandchild of its own.
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise WebToolError(f"webglass verb '{verb}' timed out after {_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise WebToolError(f"webglass verb '{verb}' failed: {exc}") from exc

    body = (stdout or "") + (stderr or "")
    return _truncate(f"exit={proc.returncode}\n{body}")

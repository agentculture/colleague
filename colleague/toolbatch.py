"""Concurrency-safety partitioning + read-only shell checking (pure, stdlib).

adapted-from: qwen-code packages/core/src/core/coreToolScheduler.ts:1284-1348,
tools/tools.ts:1111, utils/shellReadOnlyChecker.ts

Colleague's tool loop (``colleague/loop.py``) is a strictly sequential
request/act/observe cycle today. This module is the standalone, dependency-free
building block a future loop change could use to run a *contiguous run of
read-only tool calls* concurrently instead of one at a time — nothing in the
loop calls into it yet (plan task t2 of the adopt-from-qwen-code arc; wiring
it into ``loop.py`` is a later, separately-reviewed task). It has three parts:

* :data:`CONCURRENCY_SAFE_TOOLS` + :func:`is_tool_call_concurrency_safe` — the
  allow-list of colleague tool names that never mutate the tree or shared
  state, ported from qwen-code's ``CONCURRENCY_SAFE_KINDS`` /
  ``isToolCallConcurrencySafe``. A ``run_command`` call is safe only when its
  ``command`` argument passes :func:`is_shell_command_read_only`; a ``memory``
  call is safe only when it selects ``recall`` (never ``remember``).
* :func:`is_shell_command_read_only` — a conservative, allow-list-based
  read-only shell-command checker ported from qwen-code's (upstream-deprecated,
  regex + ``shell-quote``) ``isShellCommandReadOnly``. Upstream has since moved
  to a tree-sitter-bash AST parser for its *permission* decisions; colleague
  takes no new third-party dependency (stdlib only, per this repo's zero-deps
  convention) and does not need AST fidelity for what is only a *scheduling*
  decision, so this keeps the allow-list form and, deliberately, makes it
  *more* conservative than upstream's regex version: any occurrence anywhere
  in the raw command string of a shell metacharacter or compounding form
  (``;``, ``|``, ``&``, ``$(``, a backtick, ``>``, ``>>``, ``<``) fails closed,
  even inside quotes — upstream's quote-aware scanning is not reproduced. A
  root command outside the read-only allow-list, or a wrapper/wrapping
  command such as ``sh -c`` / ``bash -c`` / ``xargs`` (never members of that
  allow-list), also fails closed. ``find -exec``/``find -delete``, ``sed -i``,
  and ``awk`` with a ``system(`` call each fail closed via a dedicated
  per-command check; a non-read-only ``git`` subcommand (e.g. ``push``,
  ``commit``, ``reset``) fails closed via a small read-only-subcommand
  allow-list, with ``branch``/``remote`` further restricted to their
  non-mutating argument forms (bare/``--list``, and ``show``/``get-url``
  respectively) since those two subcommands can otherwise mutate local/remote
  refs.
* :func:`partition_by_concurrency_safety` — the generic batching algorithm
  ported from qwen-code's ``partitionByConcurrencySafety``: consecutive safe
  items merge into one batch, each unsafe item forms its own single-item
  batch, order is preserved.
* :func:`run_batch` — a small ``ThreadPoolExecutor``-backed helper that runs a
  list of calls through a supplied ``execute`` function with at most ``width``
  concurrent, returning results in input order. This module is the ONE
  sanctioned NEW thread consumer this arc adds (see
  ``tests/test_boundary.py``'s ``_THREADS_ALLOWED``): ``width <= 1`` runs a
  plain sequential loop and never instantiates a ``ThreadPoolExecutor`` at
  all, so a caller that never asks for concurrency stays byte-identical to
  today's sequential loop.

**None of the above is a permission decision.** Every function here answers
exactly one question — "can this run at the same time as other safe calls
without stepping on shared state?" — for the sole purpose of deciding how a
*already-approved* batch of tool calls may be scheduled. It has no bearing on,
and must never be treated as a substitute for, colleague's approval gate
(``colleague/policy.py``) or any other authorization check: a command judged
"not read-only" here is simply run sequentially like any other tool call, not
blocked, denied, or logged as a violation.

This module imports nothing from ``colleague.loop`` or ``colleague.tools`` (or
any other colleague module) — it is standalone stdlib, callable from either
side without creating an import cycle.
"""

from __future__ import annotations

import re
import shlex
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Mapping, Optional, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

# ---------------------------------------------------------------------------
# Tool-name concurrency safety
# ---------------------------------------------------------------------------

#: Colleague tool names that are always concurrency-safe: pure reads with no
#: side effects and no shared mutable state. Mirrors qwen-code's
#: ``CONCURRENCY_SAFE_KINDS`` (``Kind.Read``/``Kind.Search``/``Kind.Fetch``)
#: collapsed onto colleague's own tool-name surface. Deliberately excludes
#: ``run_command`` and ``memory`` — both are conditionally safe and are
#: handled by dedicated predicates in :func:`is_tool_call_concurrency_safe`.
CONCURRENCY_SAFE_TOOLS: frozenset = frozenset(
    {
        "read_file",
        "list_dir",
        "grep_search",
        "glob",
        "view_media",
    }
)


def is_memory_recall_call(tool_name: str, arguments: Optional[Mapping[str, Any]]) -> bool:
    """True only for a ``memory`` call whose arguments select ``recall``.

    A ``memory`` call selecting ``remember`` (or any other/absent verb) is
    never concurrency-safe — it writes a record into the shared eidetic
    store.
    """
    if tool_name != "memory":
        return False
    if not isinstance(arguments, Mapping):
        return False
    return arguments.get("verb") == "recall"


def is_shell_command_read_only(command: str) -> bool:
    """Conservative, allow-list read-only check for a shell command string.

    adapted-from: qwen-code utils/shellReadOnlyChecker.ts ``isShellCommandReadOnly``
    (the allow-list regex+``shell-quote`` form upstream now marks deprecated
    in favour of a tree-sitter AST parser; this port keeps the allow-list
    form and takes no new dependency — see the module docstring for the
    deliberate fail-closed simplifications).

    Returns ``False`` (never raises) for anything that is not a plain,
    single, allow-listed read-only command invocation. The steps below are
    each factored into a small helper purely to keep this function's own
    cognitive complexity low (SonarCloud python:S3776); the control flow and
    verdicts are unchanged from the single-function form.
    """
    if not isinstance(command, str) or not command.strip():
        return False

    # Fail closed on ANY shell metacharacter or compounding form, anywhere in
    # the raw string (including inside quotes — see module docstring). This
    # alone rejects every ``;``/``|``/``&&``/``||`` command chain, every
    # ``$(...)``/backtick command substitution, and every ``>``/``>>``/``<``
    # redirection in one pass.
    if _contains_shell_metacharacter(command):
        return False

    tokens = _tokenize_shell_command(command)
    if tokens is None:
        return False

    split = _split_env_prefix(tokens)
    if split is None:
        # A command that is nothing but env-var assignments (e.g. "FOO=bar")
        # runs no program at all — fail closed rather than guess.
        return False
    root, args = split

    if not _root_command_is_candidate(root):
        return False

    checker = _PER_ROOT_COMMAND_CHECKS.get(root)
    if checker is not None:
        return checker(args)
    return True


_SHELL_METACHARACTERS: tuple = (";", "|", "&", "$(", "`", ">", "<")

# python:S6353 (NOSONAR): `[A-Za-z0-9_]` looks like it can collapse to `\w`,
# but `\w` (without re.ASCII) also matches Unicode word characters, which
# would widen what this regex accepts as an env-var-assignment token (shells
# only ever produce ASCII identifiers here) and could change which token is
# treated as the command root. Kept explicit deliberately — see the module
# docstring's fail-closed philosophy.
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")  # NOSONAR


def _contains_shell_metacharacter(command: str) -> bool:
    """True if *command* contains any shell metacharacter/compounding form
    anywhere in the raw string (see :data:`_SHELL_METACHARACTERS`)."""
    return any(meta in command for meta in _SHELL_METACHARACTERS)


def _tokenize_shell_command(command: str) -> Optional[List[str]]:
    """Shell-split *command*, or ``None`` on unbalanced quotes / no tokens."""
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        # Unbalanced quotes etc. — fail closed.
        return None
    return tokens or None


def _split_env_prefix(tokens: Sequence[str]) -> Optional[tuple]:
    """Skip leading ``NAME=value`` assignment tokens; return the remaining
    ``(root, args)`` pair, or ``None`` if nothing but assignments remain."""
    index = 0
    while index < len(tokens) and _ENV_ASSIGNMENT_RE.match(tokens[index]):
        index += 1
    if index >= len(tokens):
        return None
    return tokens[index], tokens[index + 1 :]


def _root_command_is_candidate(root: str) -> bool:
    """True when *root* is lowercase, not a wrapper command, and sits in the
    read-only allow-list — the three gate checks every root must pass before
    a per-command exception (find/sed/awk/git) even gets consulted."""
    if root != root.lower():
        # A command name is never expected to carry uppercase letters; fail
        # closed rather than case-fold it into a false allow-list match.
        return False
    if root in _SHELL_WRAPPER_COMMANDS:
        # sh -c / bash -c / xargs (and siblings) hand a sub-command to
        # another shell/process — never safe to treat as read-only regardless
        # of what follows. (Already excluded by the allow-list below; named
        # explicitly so the rejection reads as intentional, not incidental.)
        return False
    return root in READ_ONLY_ROOT_COMMANDS


#: Root commands that hand their argument off to another interpreter/process
#: and so can never be judged read-only from the outer command line alone.
_SHELL_WRAPPER_COMMANDS: frozenset = frozenset({"sh", "bash", "zsh", "ksh", "dash", "xargs"})

#: Bare root commands that never write to the filesystem or mutate state,
#: absent one of the per-command exceptions handled below (find/sed/awk/git).
READ_ONLY_ROOT_COMMANDS: frozenset = frozenset(
    {
        "awk",
        "basename",
        "cat",
        "cd",
        "column",
        "cut",
        "df",
        "dirname",
        "du",
        "echo",
        "find",
        "git",
        "grep",
        "head",
        "ls",
        "printenv",
        "ps",
        "pwd",
        "sed",
        "tail",
        "wc",
        "which",
        "where",
        "whoami",
    }
)

_BLOCKED_FIND_FLAGS: frozenset = frozenset({"-exec", "-execdir", "-delete", "-ok", "-okdir"})

_READ_ONLY_GIT_SUBCOMMANDS: frozenset = frozenset(
    {
        "blame",
        "branch",
        "cat-file",
        "diff",
        "grep",
        "log",
        "ls-files",
        "remote",
        "rev-parse",
        "show",
        "status",
        "describe",
    }
)


def _find_args_are_read_only(args: Sequence[str]) -> bool:
    return not any(tok.lower() in _BLOCKED_FIND_FLAGS for tok in args)


def _sed_args_are_read_only(args: Sequence[str]) -> bool:
    for tok in args:
        if (
            tok == "-i"
            or tok.startswith("-i")
            or tok == "--in-place"
            or tok.startswith("--in-place=")
        ):
            return False
    return True


def _awk_args_are_read_only(args: Sequence[str]) -> bool:
    return not any("system(" in tok for tok in args)


def _git_args_are_read_only(args: Sequence[str]) -> bool:
    if args and args[0].startswith("-"):
        flag = args[0].lower()
        if flag == "--version":
            return True
        if flag == "--help":
            return len(args) == 1
        return False
    if not args:
        return True
    subcommand = args[0].lower()
    if subcommand not in _READ_ONLY_GIT_SUBCOMMANDS:
        return False
    rest = args[1:]
    if subcommand == "branch":
        # bare "git branch" / "git branch --list" only list; anything else
        # (a branch name, -d/-m/...) can create/delete/rename a branch.
        return len(rest) == 0 or rest == ["--list"]
    if subcommand == "remote":
        # "git remote" / "git remote show ..." / "git remote get-url ..." only;
        # add/remove/rename/set-url/prune/update all mutate remote config.
        action = next((a for a in rest if not a.startswith("-")), None)
        return action is None or action.lower() in ("show", "get-url")
    return True


#: Root commands with a dedicated per-command exception, dispatched from
#: :func:`is_shell_command_read_only` by simple dict lookup (rather than a
#: chain of ``if root == "...":`` branches) to keep that function's own
#: cognitive complexity low.
_PER_ROOT_COMMAND_CHECKS: Mapping[str, Callable[[Sequence[str]], bool]] = {
    "find": _find_args_are_read_only,
    "sed": _sed_args_are_read_only,
    "awk": _awk_args_are_read_only,
    "git": _git_args_are_read_only,
}


def is_tool_call_concurrency_safe(tool_name: str, arguments: Optional[Mapping[str, Any]]) -> bool:
    """True when ``tool_name``/``arguments`` may run concurrently with other
    safe calls (no side effects, no shared mutable state).

    adapted-from: qwen-code coreToolScheduler.ts ``isToolCallConcurrencySafe``
    (lines 1283-1305), collapsed onto colleague's tool-name surface (no
    ``Kind``/registry lookup exists here — this module never imports
    ``colleague.tools``).

    Never raises: an unrecognised or malformed ``run_command`` call fails
    closed (returns ``False``) exactly like ``isShellCommandReadOnly``'s
    caller upstream.
    """
    if tool_name == "memory":
        return is_memory_recall_call(tool_name, arguments)
    if tool_name == "run_command":
        command = (arguments or {}).get("command") if isinstance(arguments, Mapping) else None
        if not isinstance(command, str):
            return False
        try:
            return is_shell_command_read_only(command)
        except Exception:
            return False
    return tool_name in CONCURRENCY_SAFE_TOOLS


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------


def partition_by_concurrency_safety(
    items: Sequence[T], is_safe: Callable[[T], bool]
) -> List[List[T]]:
    """Partition ``items`` into consecutive batches by concurrency safety.

    adapted-from: qwen-code coreToolScheduler.ts ``partitionByConcurrencySafety``
    (lines 1331-1345).

    Consecutive safe items merge into one batch; each unsafe item forms its
    own single-item batch. Order is preserved. A batch's own safety verdict
    can be recovered afterward from ``is_safe(batch[0])`` — every item
    sharing a batch shares the same verdict, since an unsafe item never
    merges with anything and a merged batch is built entirely of safe items.

    >>> partition_by_concurrency_safety(
    ...     ["Read", "Read", "Edit", "Read"], lambda x: x == "Read"
    ... )
    [['Read', 'Read'], ['Edit'], ['Read']]
    """
    batches: List[List[T]] = []
    batch_is_safe: List[bool] = []
    for item in items:
        safe = is_safe(item)
        if safe and batches and batch_is_safe[-1]:
            batches[-1].append(item)
        else:
            batches.append([item])
            batch_is_safe.append(safe)
    return batches


# ---------------------------------------------------------------------------
# Bounded-concurrency execution helper
# ---------------------------------------------------------------------------


def run_batch(execute: Callable[[T], R], calls: Sequence[T], width: int) -> List[R]:
    """Run ``calls`` through ``execute(call)`` with at most ``width`` concurrent.

    Results are returned in INPUT order regardless of completion order.
    ``width <= 1`` (or fewer than two calls) runs a plain sequential loop —
    no ``ThreadPoolExecutor`` is ever instantiated, so a caller that never
    asks for concurrency is byte-identical to a hand-written ``for`` loop.
    This function (plus the module import itself) is the ONE sanctioned NEW
    thread consumer this module adds to colleague — see
    ``tests/test_boundary.py``'s ``_THREADS_ALLOWED``.
    """
    if width <= 1 or len(calls) <= 1:
        return [execute(call) for call in calls]
    with ThreadPoolExecutor(max_workers=width) as pool:
        return list(pool.map(execute, calls))

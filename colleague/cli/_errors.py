"""CliError and exit-code policy (stable-contract).

Every failure inside colleague raises :class:`CliError`. The top-level
``main()`` catches it, formats via :mod:`colleague.cli._output`, and exits with
:attr:`CliError.code`. This guarantees:

* no Python traceback leaks to stderr (the agent-first error contract);
* every error has a structured shape ``{code, message, remediation}``;
* the exit-code policy is centralised in one place.

Since colleague's CLI is rendered from an imported agentfront App registry,
:class:`CliError` is a **subclass of** :class:`agentfront.errors.AgentfrontError`.
agentfront's ``run_cli`` dispatch catches ``AgentfrontError`` and renders its
``{code, message, remediation}`` to stderr (the ``error:``/``hint:`` form) — so
a ``CliError`` raised anywhere in colleague is caught and rendered *natively* by
the agentfront-rendered CLI, with no per-handler bridging. ``AgentfrontError``
and the old hand-rolled ``CliError`` are byte-identical (same fields, same
``to_dict``), so this subclassing changes no observable error contract. The
colleague-only ``result`` field (the work-item partial-trace path) is preserved
as a subclass addition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentfront.errors import AgentfrontError

if TYPE_CHECKING:
    from colleague.contract import TaskResult

# Exit-code policy. Documented in ``colleague learn`` output. Identical to
# agentfront's (re-exported here so existing colleague imports stay stable).
# 0      = success
# 1      = user-input error (bad flag, missing required arg, unknown path)
# 2      = environment / setup error (tool not installed, file unreadable)
# 3+     = reserved for future categorisation
EXIT_SUCCESS = 0
EXIT_USER_ERROR = 1
EXIT_ENV_ERROR = 2


@dataclass
class CliError(AgentfrontError):
    """Structured error raised within the CLI; carries a remediation hint for agents.

    A subclass of :class:`agentfront.errors.AgentfrontError` so the
    agentfront-rendered CLI dispatch (``run_cli``) catches it and renders its
    ``{code, message, remediation}`` identically — inheriting ``code`` /
    ``message`` / ``remediation`` and ``to_dict`` from the base.

    The optional *result* field carries a partial :class:`~colleague.contract.TaskResult`
    on the work item-failure path so that ``cmd_work --json`` can surface it to stdout while
    still exiting non-zero (honesty condition h5 — the partial trace is never silently
    swallowed by a ``--json`` caller).  All existing call-sites that omit *result* are
    unaffected — it defaults to ``None``.
    """

    result: "TaskResult | None" = field(default=None, compare=False)

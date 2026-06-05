"""CliError and exit-code policy (stable-contract).

Every failure inside colleague raises :class:`CliError`. The
top-level ``main()`` catches it, formats via :mod:`colleague.cli._output`,
and exits with :attr:`CliError.code`. This guarantees:

* no Python traceback leaks to stderr (the agent-first error contract);
* every error has a structured shape ``{code, message, remediation}``;
* the exit-code policy is centralised in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from colleague.contract import TaskResult

# Exit-code policy. Documented in ``colleague learn`` output.
# 0      = success
# 1      = user-input error (bad flag, missing required arg, unknown path)
# 2      = environment / setup error (tool not installed, file unreadable)
# 3+     = reserved for future categorisation
EXIT_SUCCESS = 0
EXIT_USER_ERROR = 1
EXIT_ENV_ERROR = 2


@dataclass
class CliError(Exception):
    """Structured error raised within the CLI; carries a remediation hint for agents.

    The optional *result* field carries a partial :class:`~colleague.contract.TaskResult`
    on the work item-failure path so that ``cmd_work --json`` can surface it to stdout while
    still exiting non-zero (honesty condition h5 — the partial trace is never silently
    swallowed by a ``--json`` caller).  All existing call-sites that omit *result* are
    unaffected — it defaults to ``None``.
    """

    code: int
    message: str
    remediation: str = ""
    result: "TaskResult | None" = field(default=None, compare=False)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }

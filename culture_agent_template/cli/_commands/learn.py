"""``culture-agent-template learn`` — the learnability affordance.

Prints a structured self-teaching prompt. Must satisfy the agent-first rubric:
>=200 chars and mention purpose, command map, exit codes, --json, and explain.
"""

from __future__ import annotations

import argparse

from culture_agent_template import __version__
from culture_agent_template.cli._output import emit_result

_TEXT = """\
culture-agent-template — a clonable template for AgentCulture mesh agents.

Purpose
-------
Scaffold for a new Culture mesh agent: an agent-first CLI (cited from the teken
`python-cli` reference), an identity (culture.yaml + CLAUDE.md), the canonical
guildmaster skill kit under .claude/skills/, and a deploy/CI baseline. Clone it,
rename the package, and edit culture.yaml to mint a new agent.

Commands
--------
  culture-agent-template whoami             Identity from culture.yaml.
  culture-agent-template learn              This self-teaching prompt.
  culture-agent-template explain <path>...  Markdown docs for any noun/verb path.
  culture-agent-template overview           Descriptive snapshot of the agent.
  culture-agent-template doctor             Check the agent-identity invariants.
  culture-agent-template cli overview       Describe the CLI surface itself.

Machine-readable output
-----------------------
Every command supports --json. Errors in JSON mode emit
{"code", "message", "remediation"} to stderr. Stdout and stderr never mix.

Exit-code policy
----------------
  0 success
  1 user-input error (bad flag, bad path, missing arg)
  2 environment / setup error
  3+ reserved

More detail
-----------
  culture-agent-template explain culture-agent-template
"""


def _as_json_payload() -> dict[str, object]:
    return {
        "tool": "culture-agent-template",
        "version": __version__,
        "purpose": "Clonable scaffold for a new AgentCulture mesh agent.",
        "commands": [
            {"path": ["whoami"], "summary": "Identity probe from culture.yaml."},
            {"path": ["learn"], "summary": "Self-teaching prompt."},
            {"path": ["explain"], "summary": "Markdown docs by path."},
            {"path": ["overview"], "summary": "Descriptive snapshot of the agent."},
            {"path": ["doctor"], "summary": "Check the agent-identity invariants."},
            {"path": ["cli", "overview"], "summary": "Describe the CLI surface."},
        ],
        "exit_codes": {
            "0": "success",
            "1": "user-input error",
            "2": "environment/setup error",
        },
        "json_support": True,
        "explain_pointer": "culture-agent-template explain <path>",
    }


def cmd_learn(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        emit_result(_as_json_payload(), json_mode=True)
    else:
        emit_result(_TEXT, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "learn",
        help="Print a structured self-teaching prompt for agent consumers.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_learn)

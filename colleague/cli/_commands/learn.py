"""``colleague learn`` — the learnability affordance.

Prints a structured self-teaching prompt aimed at *another agent that wants to
work with colleague* — delegate a scoped task to it and fold the answer back.
Must satisfy the agent-first rubric: >=200 chars and mention purpose, command
map, exit codes, --json, and explain.
"""

from __future__ import annotations

import argparse

from colleague import __version__
from colleague.cli._output import emit_result

_TEXT = """\
colleague — a swappable coder-agent harness. Hand it a scoped repo task and it
works a model backend through through a bounded tool-loop, then returns a JSON run
report. One runtime, many minds.

Work with colleague from another agent
--------------------------------------
Its purpose for you: a *different* mind you can delegate scoped repo work to —
not a stronger one. Diversity is the point: a second, independent perspective
catches what your own glides past. Reach for it before you present work or open
a PR.

The first-party `ask-colleague` Claude Code skill (.claude/skills/ask-colleague/)
is the front door:
  ask-colleague explore "<area>"   Read-only investigation; reports findings.
  ask-colleague review  "<focus>"  A diverse second opinion on your committed
                                   <base>...HEAD diff. The headline verb.
  ask-colleague write   "<task>"   Delegate a small change. Previews by default
                                   (throwaway worktree, no side effects); --apply
                                   lands a work branch, --pr opens a PR.
  ask-colleague feedback ...       Grade a finished work item (closes the ROI loop).
  ask-colleague monitor|guide|stop <id>   Pilot a running flight: watch its live feed,
                                           send mid-flight guidance, or stop it cooperatively.
explore/review are read-only (worktree-isolated) — always safe to run.

Or run it directly:
  colleague work "<task>" --repo . --engine <backend> --no-pr
Backend resolution: --engine > COLLEAGUE_ENGINE > vllm-openai (never a silent
mock). Each work item writes a run report (TaskResult JSON + step trace) with an
always-on stats block (what it cost); pair it with a feedback record (how good
it was) to compute the ROI of outsourcing the task.

Teach colleague with skills
---------------------------
colleague folds two layered, instructional-text surfaces into the backend system
prompt on every work item — author them so colleague works your repo well:
  .colleague/skills/<name>.md    One skill per convention every work item should
                                 honor: the test command, the lint gate, code
                                 style, a domain glossary, "never touch <X>".
                                 Per-model overlay: .colleague/<model>/skills/.
  AGENTS.md, AGENTS.colleague.md, AGENTS.colleague.<model>.md
                                 Broader standing instructions, general->specific.
In both overlays <model> is the filename-safe model id, not the raw one:
slashes collapse to dashes (Qwen/Qwen3-32B -> Qwen-Qwen3-32B), so a literal
.colleague/<org>/<model>/ never loads.
Skills are instructional text only (no execution model in v0). Inspect what
resolves with:  colleague skills list  and  colleague agents list

Commands
--------
  colleague work <task>       Run a repo task through a coder backend.
  colleague plan "<request>"  Colleague plans a complex task (spec -> plan -> workforce).
  colleague plan continue     Resume an interrupted plan run without re-asking
                               gates it already resolved (needs a prior checkpoint).
  colleague backends list      List discovered backend plugins.
  colleague whoami             Mesh identity + the live work engine/model.
  colleague feedback ...       Grade a work item / read its ROI record.
  colleague skills list        Show the skill docs resolved for a model.
  colleague agents list        Show the AGENTS instructions resolved for a model.
  colleague learn              This self-teaching prompt.
  colleague explain <path>...  Markdown docs for any noun/verb path.
  colleague overview           Descriptive snapshot of the agent.
  colleague doctor             Check configuration readiness (health check).
  colleague flight ...        Pilot a running work item (watch/guide/stop a flight).

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
  colleague explain colleague    The architecture, part by part.
  colleague explain ask-colleague  The collaboration verbs in depth.
  colleague explain skills       What skills to author, and how they layer.
  colleague explain work        The task contract a work item runs.
"""


def _as_json_payload() -> dict[str, object]:
    return {
        "tool": "colleague",
        "version": __version__,
        "purpose": (
            "A swappable coder-agent harness you delegate scoped repo tasks to: "
            "it works a model backend through through a bounded tool-loop and returns a "
            "JSON run report. A different mind, not a stronger one — diversity is "
            "the point."
        ),
        "work_with": {
            "skill": ".claude/skills/ask-colleague/",
            "verbs": [
                {
                    "verb": "ask-colleague explore",
                    "summary": "Read-only investigation of an area (worktree-isolated).",
                },
                {
                    "verb": "ask-colleague review",
                    "summary": "A diverse second opinion on a <base>...HEAD diff (headline).",
                },
                {
                    "verb": "ask-colleague write",
                    "summary": "Delegate a small change; previews unless --apply/--pr.",
                },
                {
                    "verb": "ask-colleague feedback",
                    "summary": "Grade a finished work item (closes the ROI loop).",
                },
                {
                    "verb": "ask-colleague monitor|guide|stop",
                    "summary": "Pilot a running flight (watch feed / guide / cooperative stop).",
                },
            ],
            "work": 'colleague work "<task>" --repo . --engine <backend> --no-pr',
            "backend_resolution": "--engine > COLLEAGUE_ENGINE > vllm-openai (never a silent mock)",
        },
        "teach_with_skills": {
            "skills": ".colleague/skills/<name>.md (per-model overlay: .colleague/<model>/skills/)",
            "agents": "AGENTS.md -> AGENTS.colleague.md -> AGENTS.colleague.<model>.md",
            "model_placeholder": (
                "<model> in overlay paths is the filename-safe id, not the raw one: "
                "slashes collapse to dashes (Qwen/Qwen3-32B -> Qwen-Qwen3-32B)."
            ),
            "what_to_create": (
                "One skill per repo convention every work item should honor: the test "
                "command, the lint gate, code style, a domain glossary, files not "
                "to touch. Instructional text only (no execution model in v0)."
            ),
            "inspect": ["colleague skills list", "colleague agents list"],
        },
        "commands": [
            {"path": ["work"], "summary": "Run a repo task through a coder backend."},
            {
                "path": ["plan"],
                "summary": (
                    "Colleague plans a complex task (spec -> plan -> workforce); "
                    "'plan continue' resumes an interrupted run without re-asking "
                    "gates it already resolved."
                ),
            },
            {"path": ["backends", "list"], "summary": "List discovered backend plugins."},
            {"path": ["whoami"], "summary": "Mesh identity + the live work engine/model."},
            {"path": ["feedback"], "summary": "Grade a work item / read its ROI record."},
            {"path": ["skills", "list"], "summary": "Show the skill docs resolved for a model."},
            {
                "path": ["agents", "list"],
                "summary": "Show the AGENTS instructions resolved for a model.",
            },
            {"path": ["learn"], "summary": "Self-teaching prompt."},
            {"path": ["explain"], "summary": "Markdown docs by path."},
            {"path": ["overview"], "summary": "Descriptive snapshot of the agent."},
            {
                "path": ["doctor"],
                "summary": "Check configuration readiness across all check-groups.",
            },
            {
                "path": ["flight"],
                "summary": "Pilot a running work item (watch/guide/stop a flight).",
            },
        ],
        "exit_codes": {
            "0": "success",
            "1": "user-input error",
            "2": "environment/setup error",
        },
        "json_support": True,
        "explain_pointer": "colleague explain <path>",
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

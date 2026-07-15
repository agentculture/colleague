"""Pure heal-choice module — the heal choice model with consequence + undo copy.

Three choices for recovering from a dirty working tree (#149).

Copy + parsing only — no git calls, no session wiring. The actions run in a
later task. Follows the cockpit label-state-consequence policy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealChoice:
    """One heal option: key, display label, consequence, and undo command."""

    key: str
    label: str
    consequence: str
    undo: str


# ── Constants ─────────────────────────────────────────────────────

COMMIT = HealChoice(
    key="commit-onto-work-branch",
    label="Commit onto work branch",
    consequence="commits your uncommitted tracked edits onto the work branch",
    undo="git reset --soft HEAD~1",
)

STASH = HealChoice(
    key="stash",
    label="Stash changes",
    consequence="stashes your uncommitted tracked edits",
    undo="git stash pop",
)

ABORT = HealChoice(
    key="abort",
    label="Abort",
    consequence="aborts the operation — your edits remain untouched",
    undo="(none needed)",
)

#: Ordered list of heal choices presented to the operator.
heal_choices: list[HealChoice] = [COMMIT, STASH, ABORT]


# ── Prompt rendering ──────────────────────────────────────────────


def render_heal_prompt() -> str:
    """Return the heal prompt text carrying consequence AND undo verbatim.

    Renders numbered choices with label, consequence, and undo per choice.
    Follows the cockpit label-state-consequence policy.
    """
    lines: list[str] = [
        "Your working tree has uncommitted tracked changes. Choose how to proceed:",
        "",
    ]
    for idx, choice in enumerate(heal_choices, start=1):
        lines.extend(
            [
                f"{idx}. {choice.label} ({choice.key})",
                f"   Consequence: {choice.consequence}",
                f"   Undo: {choice.undo}",
                "",
            ]
        )
    lines.append("Enter choice number or key (default: abort):")
    return "\n".join(lines)


# ── Input parsing ────────────────────────────────────────────────


def parse_heal_choice(input_str: str) -> HealChoice:
    """Parse operator input into a HealChoice.

    Accepts '1', '2', '3' or the key strings. Returns ABORT for empty or
    unknown input.
    """
    stripped = input_str.strip()
    if not stripped:
        return ABORT

    # Numeric input.
    if stripped in ("1", "2", "3"):
        return heal_choices[int(stripped) - 1]

    # Key string input.
    for choice in heal_choices:
        if stripped == choice.key:
            return choice

    return ABORT

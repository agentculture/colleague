"""Adversarial reviewer for colleague's plan mode.

Before the operator gate on a proposed plan-mode item, a critic reviews it
using the SAME model but a DIFFERENT (adversarial critic) system prompt, and
surfaces weaknesses as ADVISORY input.  The reviewer NEVER confirms or approves
— confirmation is the operator's job.

Pure stdlib only.  No devague import.  No engine/network import.  Designed for
testability via dependency injection: the ``complete`` callable is injected by
the caller, so the reviewer is engine-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# ── Critique ─────────────────────────────────────────────────────────────────


@dataclass
class Critique:
    """Advisory critique of a proposed plan-mode item.

    Fields
    ------
    text:
        The full critique text returned by the model.
    concerns:
        Parsed list of specific concerns (may be empty).
    """

    text: str
    concerns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "concerns": self.concerns}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Critique":
        return cls(
            text=str(data["text"]),
            concerns=list(data.get("concerns", [])),
        )


# ── CRITIC_SYSTEM_PROMPT ────────────────────────────────────────────────────

CRITIC_SYSTEM_PROMPT: str = (
    "You are an adversarial reviewer for a proposed plan-mode item. "
    "Your job is to find weaknesses, risks, missing honesty conditions, "
    "and over-broad scope in the proposal. "
    "Do NOT endorse or validate the item. "
    "Surface every concern you can identify. "
    "Your output is purely advisory — the operator makes the final decision."
)


# ── review_item ──────────────────────────────────────────────────────────────


def review_item(
    item_text: str,
    complete: Callable[[str, str], str],
    *,
    enabled: bool = True,
) -> Critique | None:
    """Review a proposed plan-mode item using an adversarial critic.

    Parameters
    ----------
    item_text:
        The text of the proposed plan-mode item.
    complete:
        Injected callable with signature
        ``complete(system_prompt: str, user_prompt: str) -> str``.
    enabled:
        When ``True``, call ``complete`` exactly once with the critic system
        prompt and return a :class:`Critique`.  When ``False``, do NOT call
        ``complete`` at all and return ``None`` (byte-identical no-op).

    Returns
    -------
    Critique or None
        A non-authoritative critique when enabled; ``None`` when disabled.
    """
    if not enabled:
        return None

    response = complete(CRITIC_SYSTEM_PROMPT, item_text)
    return Critique(text=response)

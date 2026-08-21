"""Purpose→role delegation guidance (#411, plan task t12).

The enumerated guidance table for the model-bound agents arc. It is PROMPT
TEXT, never a runtime branch: :data:`GUIDANCE` is a frozen tuple of
``(purpose, when-to-prefer bullets)`` and :func:`build_guidance_text` renders
it deterministically into the delegating agent's system prompt fragment.

**The runtime never routes.** No function in this module takes task text and
returns a model or a role — the only model switch in the arc is an explicit
delegation (plan task t11). This module just tells the delegating agent, in
words, which *purpose* fits which shape of work. A grep guard (plan task t18)
pins that no function under ``colleague/agents/`` reads task text to choose a
model.

**Purposes, not vendors.** The table names the closed purpose set — never a
model family. A grep guard (plan task t18) pins that no file under
``colleague/agents/`` names a vendor model.

**Deviation d3 (operator, 2026-08-21).** The non-coding ``worker`` purpose
stays DORMANT — its profile exists but the role is never bound — so the table
deliberately omits it. Routine coding routes to the reserved fast-coder
``associate`` purpose when present, else to ``thinker_coder`` — never to
``worker``.

Modelled on the "Routing policy" section of issue #411 (Prefer Talker /
Worker / Thinker when…), reworded as guidance to the agent. Stdlib only; no
imports from ``colleague/loop.py``.
"""

from __future__ import annotations

__all__ = ["GUIDANCE", "build_guidance_text"]

#: The enumerated purpose→when-to-prefer table. A frozen tuple of
#: ``(purpose, bullets)`` pairs, where *purpose* is one of the closed purpose
#: names and *bullets* is a tuple of "prefer this purpose when…" phrases.
#:
#: The order is the escalation order: the human-facing conversation seat first,
#: then the fast coder (routine coding), then the deep reasoner (hard work).
#: The dormant ``worker`` purpose is deliberately absent (deviation d3).
GUIDANCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "talker",
        (
            "direct human conversation",
            "presentation and status reporting",
            "multimodal interpretation",
            "conversational clarification",
            "no substantial work is required",
        ),
    ),
    (
        "associate",
        (
            "routine, well-scoped coding where the approach is already clear",
            "small bounded implementations and mechanical edits",
            "applying a known pattern to a familiar area",
            "fast iteration on a task whose shape is settled",
        ),
    ),
    (
        "thinker_coder",
        (
            "code must be authored or materially changed",
            "difficult debugging",
            "architecture and design",
            "complex planning",
            "conflicting evidence",
            "high ambiguity or novelty",
            "explicit deep reasoning",
            "technical critique and final review",
        ),
    ),
)


def build_guidance_text() -> str:
    """Render :data:`GUIDANCE` into the delegating agent's system prompt fragment.

    Pure and deterministic: the same table always renders to the same string
    (no timestamps, no randomness, no I/O). Takes no task text — this module
    never routes; it only describes, in words, which purpose fits which shape
    of work. The caller (the loop wiring, plan task t15) decides whether to
    include the fragment at all: it is absent from the prompt when agents is
    unarmed.
    """
    lines = [
        "## Choosing a purpose for delegated work",
        "",
        "The runtime never routes work for you. When you delegate, pick the",
        "purpose that fits the shape of the work; model switching happens only",
        "through those explicit delegations. Prefer a purpose when:",
        "",
    ]
    for purpose, bullets in GUIDANCE:
        lines.append(f"- **{purpose}**")
        for bullet in bullets:
            lines.append(f"  - {bullet}")
        lines.append("")
    lines.extend(
        [
            "Route routine coding to **associate** when it is present, else to",
            "**thinker_coder** — never to the dormant **worker** purpose.",
        ]
    )
    return "\n".join(lines)

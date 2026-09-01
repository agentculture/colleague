"""Pure fill-line helpers — the proactive capacity-decision primitives (#156).

When the running context crosses a fill-line threshold (a fraction of the context
budget), the loop asks the backend to declare ONE opinionated move and acts on it:

- ``compact`` — summarize the working history to itself, replacing the elided turns
  with a model-authored summary (the new v1 capability; lossy windowing remains the
  fallback floor when the summary turn itself cannot fit).
- ``split`` — fan the work out to child instances via the existing ``subagents`` tool.
- ``finish-with-handoff`` — stop and hand the caller a continuation summary.

The decision is offered per CROSSING of the line (indefinite-run t1, superseding
v1's at-most-once-per-work-item): a resolved offer re-arms once the run drops back
under the line, and the total compaction turns a run may spend are bounded by
``DEFAULT_COMPACTION_CAP`` (anti-thrash; the cap reached suppresses further offers,
recorded on the trace).

A compact summary is VALIDATED before it replaces history (indefinite-run t2, c4):
:func:`validate_compaction` cross-checks the MAIN model's note against the run's own
evidence (the goal/original request + the changed-file paths from the trace) and
repairs anything missing deterministically — no second-model call (non-goal c12).
Only an empty/whitespace note is unrepairable and REJECTED; the loop then keeps its
lossy-windowing floor, or — with continuation chaining armed — takes
FINISH-WITH-HANDOFF via :func:`build_handoff_instruction` (decision c23).

This module owns only the *pure* pieces (threshold maths, the decision-prompt text,
the declaration classifier, the compaction-cap maths, the compaction
request/apply transforms, and the summary validator). The loop (`colleague/loop.py`)
owns the firing, the model calls, and recording the decision — so every backend
inherits the behaviour identically (the all-engines rule). All stdlib only — zero
runtime dependencies; no subprocess, threading, sockets, or network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from colleague.context import window_messages

if TYPE_CHECKING:  # pragma: no cover - type-checking only, avoids the config->fillline cycle
    from colleague.config import EngineConfig

__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_COMPACTION_CAP",
    "MOVE_COMPACT",
    "MOVE_SPLIT",
    "MOVE_HANDOFF",
    "armed",
    "crossed",
    "cap_reached",
    "build_decision_prompt",
    "classify_declaration",
    "build_compaction_request",
    "apply_compaction",
    "validate_compaction",
    "build_handoff_instruction",
    "design_seat_config",
]


def design_seat_config(config: EngineConfig) -> EngineConfig:
    """The 'fillline.split' design call-site seat (#416 t6, c14/h9): xhigh by default.

    The standing honest limit is unchanged and still true: the fill-line
    decision prompt this module builds (:func:`build_decision_prompt`) is
    injected as an ordinary message the loop's SINGLE per-turn completion
    consumes on its next turn
    (:func:`colleague.loop_context._offer_fillline`/``_resolve_fillline``) —
    the ``split`` move is classified from that SAME declaring turn's tool
    calls, so there is no dedicated fill-line completion to build a seat for.

    **This builder is nonetheless LIVE as of #484 t9.** Its ``xhigh`` (and the
    c32 operator-override / kill-switch precedence it resolves) is read by
    :meth:`colleague.loop_gateescalation.SeatEscalator.fillline_rung`, which
    pushes that rung onto the acting config for exactly the declaring turn —
    the only way to escalate a turn that must keep the run's own tool surface
    (``subagents`` declares SPLIT, ``finish`` declares FINISH-WITH-HANDOFF).
    Armed only under ``COLLEAGUE_EFFORT_SPIKES=1``; unarmed, nothing calls
    this and the payloads stay byte-identical.
    """
    from colleague.design import design_seat_config as _design_seat_config

    return _design_seat_config(config, "fillline.split")


# Fraction of the context budget at which the fill-line decision is offered.
# 0.8 leaves headroom for the decision prompt + the model's declaring turn before a
# hard overflow. Tunable per environment via COLLEAGUE_FILLLINE_THRESHOLD.
DEFAULT_THRESHOLD = 0.8

# Per-run cap on compaction turns (indefinite-run t1). The fill-line re-arms per
# CROSSING (superseding v1's "fires at most once per work item", #156), so a
# degenerate run could otherwise thrash compact→fill→compact for its whole step
# budget; the cap bounds the total compaction turns spent. The loop consumes it at
# offer time — the cap reached suppresses further offers (recorded on the trace,
# never silent) and lossy windowing remains the floor. A module constant for now:
# the config knob that makes it operator-tunable is t3's (colleague/config.py is
# deliberately untouched here).
DEFAULT_COMPACTION_CAP = 4

MOVE_COMPACT = "compact"
MOVE_SPLIT = "split"
MOVE_HANDOFF = "finish-with-handoff"

# The summarization instruction sent over the windowed history on the compact branch.
_COMPACTION_INSTRUCTION = (
    "You are running low on context. Summarize everything done so far in this work "
    "item — decisions made, files read/edited, what is known, and what remains — as a "
    "compact, self-contained note you can continue from. Write ONLY the summary; do "
    "not call any tool."
)

_COMPACTION_PREFIX = "[Compacted summary of earlier work in this work item]\n"

# Header of the deterministic evidence block :func:`validate_compaction` appends to a
# summary missing facts from the run's own trace (indefinite-run t2, c4).
_EVIDENCE_HEADER = "[Run evidence the summary omitted — appended by the runtime]"

# The deterministic FINISH-WITH-HANDOFF instruction the loop injects when a
# compaction note is unrepairable (empty) AND continuation chaining is armed
# (decision c23). Mirrors the decision prompt's FINISH-WITH-HANDOFF move wording.
_HANDOFF_INSTRUCTION = (
    "The compaction turn produced an empty summary, so the working history cannot "
    "be safely compacted, and continuation chaining is armed: take "
    "FINISH-WITH-HANDOFF now — call `finish` with a continuation summary (what is "
    "done / what remains) so the next episode can resume from it."
)


def armed(context_budget: Optional[int], threshold: Optional[float]) -> bool:
    """True when the fill-line decision is armed for this work item.

    Armed iff degradation is active (a positive ``context_budget``) AND a usable
    threshold fraction in ``(0, 1]`` is configured. Dormant (``False``) otherwise —
    a strict no-op identical to the pre-feature loop.
    """
    return (
        isinstance(context_budget, int)
        and context_budget > 0
        and isinstance(threshold, (int, float))
        and 0 < threshold <= 1
    )


def crossed(prompt_tokens: int, context_budget: int, threshold: float) -> bool:
    """True when the last turn's prompt token count crosses the fill-line threshold."""
    return prompt_tokens >= threshold * context_budget


def cap_reached(compaction_turns: int, cap: int) -> bool:
    """True when *compaction_turns* has exhausted the per-run *cap* (indefinite-run t1).

    ``cap <= 0`` means no cap — never reached (the 0-is-unlimited convention the
    chain knobs use, e.g. ``--max-episodes 0``).
    """
    return cap > 0 and compaction_turns >= cap


def build_decision_prompt(
    *,
    used_tokens: int,
    budget_tokens: int,
    per_child_budget_tokens: int,
    max_children: int,
) -> str:
    """Render the ONE structured fill-line decision prompt (deterministic).

    Names the three moves and the concrete capacity numbers, and tells the model how
    to declare each move by its NEXT action so the runtime can record + act on it. No
    randomness, no timestamps.
    """
    return (
        f"Context check: this work item is now using about {used_tokens} of "
        f"{budget_tokens} budgeted context tokens — past the fill line. To keep "
        f"making durable progress instead of silently losing older context, declare "
        f"ONE move by your next action:\n"
        f"  - COMPACT: reply WITHOUT calling any tool. The runtime will summarize the "
        f"work so far into a compact note and you continue from it.\n"
        f"  - SPLIT: call the `subagents` tool to fan the remaining work out into at "
        f"most {max_children} coherent child assignments (per-child budget: "
        f"{per_child_budget_tokens} tokens).\n"
        f"  - FINISH-WITH-HANDOFF: call `finish` with a continuation summary (what is "
        f"done / what remains) so the caller can resume.\n"
        f"This is advisory — pick the move that best fits the remaining work."
    )


def classify_declaration(tool_names: list[str]) -> str:
    """Classify the model's declaring turn into one of the three moves.

    A ``subagents``/``subagent`` call declares SPLIT; a ``finish`` call declares
    FINISH-WITH-HANDOFF; anything else (a no-tool reply, or a plain working tool call)
    declares COMPACT — the default "summarize and keep going".
    """
    names = set(tool_names)
    if names & {"subagents", "subagent"}:
        return MOVE_SPLIT
    if "finish" in names:
        return MOVE_HANDOFF
    return MOVE_COMPACT


def build_compaction_request(
    messages: list[dict],
    budget_tokens: int,
    count_tokens: Optional[Callable[[list[dict]], int]] = None,
) -> list[dict]:
    """Build the windowed message list to send for the self-summary (compact branch).

    The history is windowed to the budget first (so the summarization call itself has
    room), then a final user turn carries the summarization instruction. The original
    assignment in ``messages[:2]`` is always preserved by :func:`window_messages`.
    """
    windowed = window_messages(messages, budget_tokens, count_tokens)
    return windowed + [{"role": "user", "content": _COMPACTION_INSTRUCTION}]


def apply_compaction(messages: list[dict], summary: str) -> list[dict]:
    """Replace the working history with the model-authored *summary*.

    Keeps the preserved head (``messages[:2]`` — system prompt + original assignment)
    verbatim and replaces everything after it with a single user message holding the
    summary. The result is always OpenAI-valid (no orphan tool messages): a finish /
    split / further work turn then proceeds from head + summary.

    The loop validates the summary FIRST (:func:`validate_compaction`, indefinite-run
    t2) and never routes an empty note here — an empty summary is rejected upstream,
    so the ``(no summary produced)`` placeholder below is a last-resort guard for
    direct callers only, no longer a loop path (the silent-amnesia fix, c4/h4).
    """
    head = messages[:2]
    text = (summary or "").strip() or "(no summary produced)"
    return head + [{"role": "user", "content": _COMPACTION_PREFIX + text}]


def validate_compaction(
    summary: Optional[str], goal: Optional[str], changed_files: Optional[list[str]]
) -> tuple[str, bool]:
    """Cross-check a compaction *summary* against the run's own evidence (t2, c4).

    Pure, deterministic, and MAIN-model-only — the inputs are the summary text, the
    run's goal/original request, and the changed-file paths from the run's own trace;
    no second-model call is introduced (non-goal c12).

    - Empty/whitespace summary → ``("", False)`` — REJECTED. An empty note carries no
      evidence and is the one *unrepairable* case: it must never replace history
      (the caller applies its floor/handoff policy, h4).
    - Non-empty summary → ALWAYS repaired, never rejected: the goal's first line
      (a case-insensitive containment heuristic) and every changed-file path must
      appear in the text; anything missing is appended as ONE deterministic evidence
      block → ``(repaired_text, True)``. A summary already carrying every fact passes
      through byte-identical, and the repair is idempotent — validating a repaired
      text appends nothing further.
    """
    text = (summary or "").strip()
    if not text:
        return ("", False)
    missing: list[str] = []
    goal_text = (goal or "").strip()
    goal_line = goal_text.splitlines()[0].strip() if goal_text else ""
    if goal_line and goal_line.lower() not in text.lower():
        missing.append(f"goal: {goal_line}")
    for path in changed_files or []:
        if path and path not in text:
            missing.append(f"changed file: {path}")
    if not missing:
        return (text, True)
    block = "\n".join([_EVIDENCE_HEADER] + [f"- {item}" for item in missing])
    return (f"{text}\n\n{block}", True)


def build_handoff_instruction() -> str:
    """Render the deterministic FINISH-WITH-HANDOFF instruction (decision c23).

    Injected by the loop as ONE user message when a compaction note is unrepairable
    (empty/whitespace — :func:`validate_compaction` rejected it) AND continuation
    chaining is armed: instead of grinding on with a history that can no longer be
    compacted, the model is told to ``finish`` with a continuation summary the next
    episode resumes from — mirroring the decision prompt's FINISH-WITH-HANDOFF move
    wording. No randomness, no timestamps.
    """
    return _HANDOFF_INSTRUCTION

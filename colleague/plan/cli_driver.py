"""Engine-backed seams for the ``colleague plan`` verb.

The orchestrator (:mod:`colleague.plan.orchestrator`) is engine-agnostic: it takes
``propose_claims`` / ``propose_plan_items`` / ``decide`` / ``batch_spawn`` as
injected callables.  This module wires those proposal seams to a *live* backend —
the model emits its proposals as JSON, which we parse into the native frame
types — while keeping the model call an injected ``complete`` callable so the
whole module is unit-testable with no network.

Pure stdlib (``json``); the only colleague imports are the native plan types.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from colleague.plan.frame import Claim, HonestyCondition, PlanFrame
from colleague.plan.plan_stage import PlanItem

#: A one-shot text completion: ``(system_prompt, user_prompt) -> text``.
SimpleComplete = Callable[[str, str], str]

CLAIMS_SYSTEM_PROMPT = (
    "You are the planning mind for colleague's plan mode. Read the request and "
    "propose the spec claims that a buildable spec needs. Reply with ONLY a JSON "
    'object of the form: {"claims": [{"id": "c1", "kind": "announcement", '
    '"text": "..."}], "honesty": [{"id": "h1", "claim_id": "c1", '
    '"text": "..."}]}. Use these claim kinds: announcement, audience, '
    "after_state, before_state, why_it_matters, boundary, success_signal, "
    "requirement, assumption, decision, non_goal. Cover the mandatory kinds "
    "(announcement, audience, after_state, boundary, success_signal, and "
    "before_state or why_it_matters) and attach an honesty condition to each "
    "spec-affecting claim. No prose outside the JSON."
)

PLAN_SYSTEM_PROMPT = (
    "You are the planning mind for colleague's plan mode. Given the confirmed "
    "spec claims, propose a small set of plan items, each sized for ONE bounded "
    "child work item, each with acceptance criteria and an explicit acyclic "
    'dependency order. Reply with ONLY a JSON object of the form: {"items": '
    '[{"id": "t1", "summary": "...", "acceptance": ["..."], '
    '"deps": ["t0"]}]}. No prose outside the JSON.'
)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Tolerantly extract the first top-level JSON object from *text*.

    A served model often wraps JSON in prose or a ```json fence; this finds the
    first balanced ``{...}`` and parses it. Raises ``ValueError`` when no valid
    JSON object is present.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model output")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                return json.loads(candidate)
    raise ValueError("unbalanced JSON object in model output")


def parse_claims(text: str) -> tuple[list[Claim], list[HonestyCondition]]:
    """Parse a model claims-proposal JSON blob into proposed frame items."""
    data = _extract_json_object(text)
    claims = [
        Claim(
            id=str(c["id"]),
            kind=str(c["kind"]),
            text=str(c["text"]),
            state="proposed",
        )
        for c in data.get("claims", [])
    ]
    honesty = [
        HonestyCondition(
            id=str(h["id"]),
            claim_id=str(h["claim_id"]),
            text=str(h["text"]),
            state="proposed",
        )
        for h in data.get("honesty", [])
    ]
    return claims, honesty


def parse_plan_items(text: str) -> list[PlanItem]:
    """Parse a model plan-items-proposal JSON blob into PlanItem objects."""
    data = _extract_json_object(text)
    return [
        PlanItem(
            id=str(i["id"]),
            summary=str(i["summary"]),
            acceptance=[str(a) for a in i.get("acceptance", [])],
            deps=[str(d) for d in i.get("deps", [])],
        )
        for i in data.get("items", [])
    ]


def to_simple_complete(complete: Callable[[list[dict]], Any]) -> SimpleComplete:
    """Adapt a loop ``CompleteFn`` (``messages -> ModelResponse``) to a one-shot
    ``(system, user) -> text`` callable, returning the response's ``content``.
    """

    def simple(system_prompt: str, user_prompt: str) -> str:
        resp = complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return getattr(resp, "content", "") or ""

    return simple


def make_propose_claims(
    simple: SimpleComplete,
) -> Callable[[str], tuple[list[Claim], list[HonestyCondition]]]:
    """Build a ``propose_claims(request)`` seam backed by *simple*."""

    def propose_claims(request: str) -> tuple[list[Claim], list[HonestyCondition]]:
        return parse_claims(simple(CLAIMS_SYSTEM_PROMPT, request))

    return propose_claims


def make_propose_plan_items(
    simple: SimpleComplete,
) -> Callable[[PlanFrame], list[PlanItem]]:
    """Build a ``propose_plan_items(frame)`` seam backed by *simple*."""

    def propose_plan_items(frame: PlanFrame) -> list[PlanItem]:
        confirmed = [c.text for c in frame.claims if c.state == "confirmed"]
        user = "Confirmed spec claims:\n" + "\n".join(f"- {t}" for t in confirmed)
        return parse_plan_items(simple(PLAN_SYSTEM_PROMPT, user))

    return propose_plan_items

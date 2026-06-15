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


def _scan_string(text: str, i: int) -> int:
    """Scan past a JSON string. *i* points just after the opening quote; returns
    the index just after the closing quote (or ``len(text)`` if unterminated).
    """
    escape = False
    while i < len(text):
        ch = text[i]
        if escape:
            escape = False
        elif ch == "\\":
            escape = True
        elif ch == '"':
            return i + 1
        i += 1
    return i


def _extract_json_object(text: str) -> dict[str, Any]:
    """Tolerantly extract the first top-level JSON object from *text*.

    A served model often wraps JSON in prose or a ```json fence; this finds the
    first balanced ``{...}`` and parses it. String contents (which may contain
    braces or escaped quotes) are skipped via :func:`_scan_string`. Raises
    ``ValueError`` when no valid JSON object is present.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model output")
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i = _scan_string(text, i + 1)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
        i += 1
    raise ValueError("unbalanced JSON object in model output")


def parse_claims(text: str) -> tuple[list[Claim], list[HonestyCondition]]:
    """Parse a model claims-proposal JSON blob into proposed frame items.

    Tolerant of model hallucination: a non-dict entry, or one missing the
    essential ``id`` key, is skipped (not a crash); other fields default to ``""``.
    """
    data = _extract_json_object(text)
    claims = [
        Claim(
            id=str(c["id"]),
            kind=str(c.get("kind", "")),
            text=str(c.get("text", "")),
            state="proposed",
        )
        for c in data.get("claims", [])
        if isinstance(c, dict) and "id" in c
    ]
    honesty = [
        HonestyCondition(
            id=str(h["id"]),
            claim_id=str(h.get("claim_id", "")),
            text=str(h.get("text", "")),
            state="proposed",
        )
        for h in data.get("honesty", [])
        if isinstance(h, dict) and "id" in h
    ]
    return claims, honesty


def _coerce_str_list(value: object) -> list[str]:
    """Coerce *value* to a list of strings.

    If *value* is a ``str``, return ``[value]``.  If it is a list/tuple,
    return ``[str(x) for x in value]``.  Otherwise return ``[]``.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return []


def parse_plan_items(text: str) -> list[PlanItem]:
    """Parse a model plan-items-proposal JSON blob into PlanItem objects.

    Tolerant: a non-dict entry, or one missing ``id``, is skipped; other fields
    default safely.
    """
    data = _extract_json_object(text)
    return [
        PlanItem(
            id=str(i["id"]),
            summary=str(i.get("summary", "")),
            acceptance=_coerce_str_list(i.get("acceptance")),
            deps=_coerce_str_list(i.get("deps")),
        )
        for i in data.get("items", [])
        if isinstance(i, dict) and "id" in i
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

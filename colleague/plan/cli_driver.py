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

from colleague.context import classify_degradable
from colleague.plan.frame import Claim, HonestyCondition, PlanFrame
from colleague.plan.plan_stage import PlanItem

#: A one-shot text completion: ``(system_prompt, user_prompt) -> text``.
SimpleComplete = Callable[[str, str], str]

CLAIMS_MANDATORY_SYSTEM_PROMPT = (
    "You are the planning mind for colleague's plan mode. Read the request and "
    "propose the MANDATORY spec claims. Reply with ONLY a JSON object of the form: "
    '{"claims": [{"id": "c1", "kind": "announcement", "text": "..."}]}. '
    "Use ONLY these claim kinds: announcement, audience, after_state, "
    "before_state, why_it_matters, boundary, success_signal. Cover all of them. "
    "No prose outside the JSON."
)

CLAIMS_REQUIREMENTS_SYSTEM_PROMPT = (
    "You are the planning mind for colleague's plan mode. Given the already-proposed "
    "claims below, propose additional requirement claims and honesty conditions. "
    "Reply with ONLY a JSON object of the form: "
    '{"claims": [{"id": "c1", "kind": "requirement", "text": "..."}], '
    '"honesty": [{"id": "h1", "claim_id": "c1", "text": "..."}]}. '
    "Use these claim kinds: requirement, assumption, decision, non_goal. "
    "Attach an honesty condition to each spec-affecting claim. "
    "No prose outside the JSON."
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


# Retry caps mirroring the loop's degradation constants.
_MAX_TIMEOUT_RETRIES = 1
_MAX_OVERFLOW_RETRIES = 3

_FOLLOWUP_PROMPT = "Respond with ONLY the JSON object now. Do not think step by step."


def robust_simple_complete(complete: Callable[[list[dict]], Any]) -> SimpleComplete:
    """Adapt a ``CompleteFn`` to a one-shot ``(system, user) -> text`` callable
    that handles reasoning models returning empty ``content``.

    Strategy
    --------
    1. Call ``complete`` with [system, user].
    2. If ``resp.content`` is empty/whitespace, append the (empty) assistant
       message + a follow-up user message, call ``complete`` again, and use
       the new content.
    3. If content is *still* empty after the follow-up, fall back to
       ``resp.reasoning`` so the caller's ``_extract_json_object`` can
       recover the JSON the reasoning model placed in its reasoning channel.
    4. On a degradable error (``classify_degradable``), retry: timeout
       once, overflow up to three times.  Non-degradable errors re-raise.

    When ``resp.content`` is non-empty on the first turn the result is
    byte-identical to :func:`to_simple_complete`.
    """

    def simple(system_prompt: str, user_prompt: str) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        def _call(messages: list[dict[str, str]]) -> Any:
            return complete(messages)

        # --- First attempt with retry on degradable errors ---
        resp = _call_with_retry(messages, _call)

        # --- Empty content: follow-up turn ---
        content = getattr(resp, "content", "") or ""
        if not content.strip():
            # Append the (empty) assistant message and a follow-up prompt.
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": _FOLLOWUP_PROMPT})
            resp2 = _call_with_retry(messages, _call)
            content = getattr(resp2, "content", "") or ""
            if not content.strip():
                # Still empty — fall back to reasoning.
                content = getattr(resp2, "reasoning", "") or ""
        return content

    return simple


def _call_with_retry(
    messages: list[dict[str, str]],
    call: Callable[[list[dict[str, str]]], Any],
) -> Any:
    """Call *call(messages)* with bounded retry on degradable errors.

    Timeout: retry once (``_MAX_TIMEOUT_RETRIES``).
    Overflow: retry up to three times (``_MAX_OVERFLOW_RETRIES``).
    Non-degradable errors re-raise immediately.
    """
    attempt = 0
    saw_overflow = False
    cap = _MAX_OVERFLOW_RETRIES

    while attempt <= cap:
        try:
            return call(messages)
        except Exception as exc:
            signal = classify_degradable(str(exc))
            if signal is None:
                raise  # non-degradable: propagate immediately
            saw_overflow = saw_overflow or signal == "overflow"
            cap = _MAX_OVERFLOW_RETRIES if saw_overflow else _MAX_TIMEOUT_RETRIES
            attempt += 1
            if attempt > cap:
                raise


def make_propose_claims(
    simple: SimpleComplete,
) -> Callable[[str], tuple[list[Claim], list[HonestyCondition]]]:
    """Build a ``propose_claims(request)`` seam backed by *simple*.

    Issues TWO calls:
    1. Mandatory claim kinds (announcement, audience, after_state, boundary,
       success_signal, before_state/why_it_matters).
    2. Requirement claims + honesty conditions, conditioned on call-1 results.

    A failing or empty chunk is tolerated (skipped), never aborting the stage.
    """

    def propose_claims(request: str) -> tuple[list[Claim], list[HonestyCondition]]:
        all_claims: list[Claim] = []
        all_honesty: list[HonestyCondition] = []

        # --- Call 1: mandatory kinds ---
        try:
            text = simple(CLAIMS_MANDATORY_SYSTEM_PROMPT, request)
            claims, honesty = parse_claims(text)
            all_claims.extend(claims)
            all_honesty.extend(honesty)
        except ValueError:
            pass  # tolerate unparseable JSON

        # --- Call 2: requirements + honesty, conditioned on call-1 ---
        if all_claims:
            context = "Already-proposed claims:\n" + "\n".join(
                f"- [{c.kind}] {c.text}" for c in all_claims
            )
            try:
                text = simple(CLAIMS_REQUIREMENTS_SYSTEM_PROMPT, context)
                claims, honesty = parse_claims(text)
                all_claims.extend(claims)
                all_honesty.extend(honesty)
            except ValueError:
                pass  # tolerate unparseable JSON

        return all_claims, all_honesty

    return propose_claims


#: Maximum plan items per batch (keeps each call small for slower models).
_PLAN_ITEM_BATCH = 5
#: Maximum number of batches (bounds total call count).
_PLAN_ITEM_MAX_BATCHES = 4


def make_propose_plan_items(
    simple: SimpleComplete,
) -> Callable[[PlanFrame], list[PlanItem]]:
    """Build a ``propose_plan_items(frame)`` seam backed by *simple*.

    Proposes plan items in bounded batches of at most ``_PLAN_ITEM_BATCH``.
    Each batch is conditioned on items already proposed (so deps can reference
    prior items).  Stops when a batch returns no new items or the max-batch
    cap is reached.  A failing or empty batch is tolerated (skipped).
    """

    def propose_plan_items(frame: PlanFrame) -> list[PlanItem]:
        confirmed = [c.text for c in frame.claims if c.state == "confirmed"]
        base_user = "Confirmed spec claims:\n" + "\n".join(f"- {t}" for t in confirmed)

        all_items: list[PlanItem] = []

        for _batch in range(_PLAN_ITEM_MAX_BATCHES):
            # Build user prompt: base context + already-proposed items
            user = base_user
            if all_items:
                user += "\n\nAlready-proposed plan items:\n"
                user += "\n".join(f"- [{item.id}] {item.summary}" for item in all_items)

            prompt = PLAN_SYSTEM_PROMPT + f"\n\nPropose up to {_PLAN_ITEM_BATCH} plan items."
            try:
                text = simple(prompt, user)
                items = parse_plan_items(text)
                if not items:
                    break  # empty batch -> stop
                all_items.extend(items)
            except ValueError:
                pass  # tolerate unparseable JSON; continue to next batch

        return all_items

    return propose_plan_items

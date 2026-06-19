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
from colleague.plan.convergence import SPEC_AFFECTING_KINDS
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

# A DEDICATED honesty-only call. Splitting honesty out of the combined
# requirements+honesty call above is the #215 fix: the served reference 27B
# reliably returns claims from the combined call but ZERO honesty conditions, so
# every confirmed spec-affecting claim fails convergence. A focused single-array
# ask — and a per-claim fallback (ONE_HONESTY_SYSTEM_PROMPT) — gets the weak model
# to produce them. Smaller jumps, one output shape.
CLAIMS_HONESTY_SYSTEM_PROMPT = (
    "You are the planning mind for colleague's plan mode. For EACH claim listed "
    "below, propose ONE honesty condition: a concrete, checkable statement of what "
    "must be true for that claim to hold. Reply with ONLY a JSON object of the form: "
    '{"honesty": [{"id": "h1", "claim_id": "c1", "text": "..."}]}. '
    "Produce exactly one honesty entry per claim, reusing the claim's id as "
    "claim_id. No prose outside the JSON."
)

ONE_HONESTY_SYSTEM_PROMPT = (
    "You are the planning mind for colleague's plan mode. Propose ONE honesty "
    "condition for the single claim below: a concrete, checkable statement of what "
    "must be true for that claim to hold. Reply with ONLY a JSON object of the form: "
    '{"honesty": [{"id": "h1", "claim_id": "CLAIM_ID", "text": "..."}]}. '
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


def _find_object_end(text: str, start: int) -> int:
    """Index of the ``}`` closing the object that opens at ``text[start] == '{'``.

    Skips string contents (:func:`_scan_string`) so braces inside string values
    don't miscount. Returns ``-1`` when the object never closes (truncated).
    """
    depth = 0
    i, n = start, len(text)
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
                return i
        i += 1
    return -1


def _close_and_load(frag: str) -> dict[str, Any] | None:
    """Append the closers implied by *frag*'s unclosed ``{``/``[`` stack, then parse.

    Skips string contents. Returns the parsed dict, or ``None`` when the balanced
    text still isn't a valid JSON object.
    """
    stack: list[str] = []
    i, n = 0, len(frag)
    while i < n:
        ch = frag[i]
        if ch == '"':
            i = _scan_string(frag, i + 1)
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
        i += 1
    closed = frag + "".join("}" if c == "{" else "]" for c in reversed(stack))
    try:
        obj = json.loads(closed)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _last_top_level_close(frag: str) -> int:
    """Index of the last ``}``/``]`` lying OUTSIDE a string literal, or ``-1``.

    A string-blind ``rfind`` could cut inside a value that contains a brace.
    """
    last = -1
    i, n = 0, len(frag)
    while i < n:
        ch = frag[i]
        if ch == '"':
            i = _scan_string(frag, i + 1)
            continue
        if ch in "}]":
            last = i
        i += 1
    return last


def _balance_and_parse(fragment: str) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object **truncated mid-structure**.

    A served reasoning model sometimes stops before the final ``}`` (it runs out
    of budget or just halts), leaving e.g. ``{"items": [ {...}, {...} ]`` with
    the closing brace missing. Append the implied closers and parse; if that
    fails (truncation landed mid-token), retreat to the last complete ``}``/``]``
    and retry once. Returns ``None`` when unrecoverable.
    """
    obj = _close_and_load(fragment)
    if obj is not None:
        return obj
    last_close = _last_top_level_close(fragment)
    if last_close <= 0:
        return None
    return _close_and_load(fragment[: last_close + 1])


def _try_load(s: str) -> Any:
    """``json.loads(s)`` or ``None`` on a decode error."""
    try:
        return json.loads(s)
    except ValueError:
        return None


def _select_object(
    obj: Any, required_key: str | None, first_obj: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Decide whether *obj* satisfies the extraction.

    Returns ``(result, first_obj)``: *result* is the object to return now (it
    carries *required_key*, or no key is required), else ``None``. The first dict
    seen is remembered in *first_obj* as the no-key fallback.
    """
    if not isinstance(obj, dict):
        return None, first_obj
    if required_key is None or required_key in obj:
        return obj, first_obj
    return None, first_obj if first_obj is not None else obj


def _extract_json_object(text: str, required_key: str | None = None) -> dict[str, Any]:
    """Tolerantly extract a top-level JSON object from *text*.

    A served model often wraps JSON in prose or a ```json fence. When
    *required_key* is given, successive top-level objects are scanned and the
    first one **containing that key** is returned — so a stray ``{...}`` in a
    reasoning model's prose (an inline schema example) cannot shadow the real
    payload; otherwise the first balanced object is returned. A trailing object
    truncated mid-structure is repaired via :func:`_balance_and_parse`. Raises
    ``ValueError`` when no valid JSON object is present.
    """
    pos = 0
    first_obj: dict[str, Any] | None = None
    saw_brace = False
    while True:
        start = text.find("{", pos)
        if start == -1:
            break
        saw_brace = True
        end = _find_object_end(text, start)
        if end == -1:
            # Truncated mid-structure: bounded repair, then stop (no later object
            # can close once we hit an unclosed one).
            result, first_obj = _select_object(
                _balance_and_parse(text[start:]), required_key, first_obj
            )
            return result if result is not None else _resolve_or_raise(first_obj, saw_brace)
        result, first_obj = _select_object(
            _try_load(text[start : end + 1]), required_key, first_obj
        )
        if result is not None:
            return result
        pos = end + 1
    return _resolve_or_raise(first_obj, saw_brace)


def _resolve_or_raise(first_obj: dict[str, Any] | None, saw_brace: bool) -> dict[str, Any]:
    """Return the fallback object, or raise the appropriate ``ValueError``."""
    if first_obj is not None:
        return first_obj
    if not saw_brace:
        raise ValueError("no JSON object found in model output")
    raise ValueError("unbalanced JSON object in model output")


def parse_claims(text: str) -> tuple[list[Claim], list[HonestyCondition]]:
    """Parse a model claims-proposal JSON blob into proposed frame items.

    Tolerant of model hallucination: a non-dict entry, or one missing the
    essential ``id`` key, is skipped (not a crash); other fields default to ``""``.
    """
    data = _extract_json_object(text, required_key="claims")
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
    data = _extract_json_object(text, required_key="items")
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
            # Capture first response's reasoning before the follow-up, so we
            # never lose JSON that lived in the reasoning channel.
            first_reasoning = getattr(resp, "reasoning", "") or ""
            # Append the (empty) assistant message and a follow-up prompt.
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": _FOLLOWUP_PROMPT})
            resp2 = _call_with_retry(messages, _call)
            content = getattr(resp2, "content", "") or ""
            if not content.strip():
                # Still empty — fall back to reasoning.  Prefer the follow-up's
                # reasoning, but never lose the first response's reasoning.
                content = getattr(resp2, "reasoning", "") or ""
                if not content:
                    content = first_reasoning
        return content

    return simple


def _shrink_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Shrink *messages* by truncating the longest user-role message to half its
    length.  Returns a new list with the mutated message in place.

    Used as a degradation step before retrying on overflow: a too-large
    proposal prompt gets smaller on each overflow retry.
    """
    # Find the longest user-role message.
    longest_idx = -1
    longest_len = 0
    for idx, msg in enumerate(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if len(content) > longest_len:
                longest_len = len(content)
                longest_idx = idx
    if longest_idx < 0:
        return messages  # no user message to shrink
    # Truncate to roughly half.
    half = max(1, longest_len // 2)
    messages[longest_idx]["content"] = messages[longest_idx]["content"][:half]
    return messages


def _call_with_retry(
    messages: list[dict[str, str]],
    call: Callable[[list[dict[str, str]]], Any],
) -> Any:
    """Call *call(messages)* with bounded retry on degradable errors.

    Timeout: retry once (``_MAX_TIMEOUT_RETRIES``).
    Overflow: retry up to three times (``_MAX_OVERFLOW_RETRIES``), shrinking
    the request on each overflow retry so a too-large prompt gets smaller.
    Non-degradable errors re-raise immediately.
    """
    attempt = 0
    saw_overflow = False

    while True:
        try:
            return call(messages)
        except Exception as exc:
            signal = classify_degradable(str(exc))
            if signal is None:
                raise  # non-degradable: propagate immediately
            if signal == "overflow":
                # An overflow re-sent unchanged just repeats; shrink before retry.
                saw_overflow = True
                _shrink_messages(messages)
            cap = _MAX_OVERFLOW_RETRIES if saw_overflow else _MAX_TIMEOUT_RETRIES
            attempt += 1
            if attempt > cap:
                raise


class _ClaimAcc:
    """Accumulate claims + honesty across chunked proposal calls, deduped by id.

    A model (or a re-prompted chunk) may re-emit prior items; duplicate ids would
    otherwise break downstream validation.
    """

    def __init__(self) -> None:
        self.claims: list[Claim] = []
        self.honesty: list[HonestyCondition] = []
        self._claim_ids: set[str] = set()
        self._honesty_ids: set[str] = set()

    def absorb(self, text: str) -> None:
        claims, honesty = parse_claims(text)
        for c in claims:
            if c.id not in self._claim_ids:
                self._claim_ids.add(c.id)
                self.claims.append(c)
        for h in honesty:
            if h.id not in self._honesty_ids:
                self._honesty_ids.add(h.id)
                self.honesty.append(h)

    def _mint_honesty_id(self) -> str:
        """A fresh ``h<n>`` id not yet used (the model may reuse ``h1``)."""
        n = len(self.honesty) + 1
        new_id = f"h{n}"
        while new_id in self._honesty_ids:
            n += 1
            new_id = f"h{n}"
        return new_id

    def claims_missing_honesty(self) -> list[Claim]:
        """Spec-affecting claims that have no honesty condition yet.

        Keyed on ``claim_id`` (the convergence rule binds honesty to a *claim*,
        not to a honesty-condition id), so a claim is "covered" once any honesty
        condition references it.
        """
        covered = {h.claim_id for h in self.honesty}
        return [c for c in self.claims if c.kind in SPEC_AFFECTING_KINDS and c.id not in covered]

    def absorb_honesty(self, text: str) -> None:
        """Absorb a honesty-only proposal, one condition per not-yet-covered claim.

        Unlike :meth:`absorb` this keys on ``claim_id`` and mints a fresh unique
        id for each accepted condition — the dedicated/per-claim honesty calls
        often reuse ``"h1"``, which :meth:`absorb`'s id-dedup would silently drop.
        """
        _, honesty = parse_claims(text)
        covered = {h.claim_id for h in self.honesty}
        for h in honesty:
            if not h.claim_id or h.claim_id in covered:
                continue
            covered.add(h.claim_id)
            new_id = self._mint_honesty_id()
            self._honesty_ids.add(new_id)
            self.honesty.append(
                HonestyCondition(
                    id=new_id,
                    claim_id=h.claim_id,
                    text=h.text,
                    state="proposed",
                )
            )


def _try_absorb(acc: _ClaimAcc, simple: SimpleComplete, system: str, user: str) -> None:
    """Run one proposal call and absorb its claims; tolerate unparseable JSON."""
    try:
        acc.absorb(simple(system, user))
    except ValueError:
        pass  # partial chunk failure is non-fatal


#: Max per-claim honesty fallback calls (bounds the total honesty call count).
_MAX_HONESTY_FALLBACK = 8


def _try_fill_honesty(acc: _ClaimAcc, simple: SimpleComplete, system: str, user: str) -> None:
    """Run one honesty-only call and absorb its conditions; tolerate bad JSON."""
    try:
        acc.absorb_honesty(simple(system, user))
    except ValueError:
        pass  # an empty/unparseable honesty chunk is non-fatal, never a crash


def _fill_honesty(acc: _ClaimAcc, simple: SimpleComplete) -> None:
    """Ensure spec-affecting claims carry an honesty condition (#215).

    The combined requirements+honesty call (call 2) reliably yields claims but no
    honesty on a weak served model. This recovers honesty in two bounded steps:

    1. ONE dedicated honesty-only call listing every spec-affecting claim still
       missing a condition (a single ``{"honesty": [...]}`` ask — the shape a
       weak model handles best).
    2. A bounded per-claim fallback (at most :data:`_MAX_HONESTY_FALLBACK` calls)
       for any claim the batch call still left uncovered.

    All calls route through ``simple`` (``robust_simple_complete`` in production),
    so reasoning-channel recovery and degradation retries apply. Honesty
    conditions land ``state="proposed"`` — the operator/gate still confirms them.
    """
    missing = acc.claims_missing_honesty()
    if not missing:
        return

    # 1. Dedicated batch honesty call.
    listing = "Claims needing an honesty condition:\n" + "\n".join(
        f"- [{c.id}] ({c.kind}) {c.text}" for c in missing
    )
    _try_fill_honesty(acc, simple, CLAIMS_HONESTY_SYSTEM_PROMPT, listing)

    # 2. Bounded per-claim fallback for any claim still uncovered.
    for claim in acc.claims_missing_honesty()[:_MAX_HONESTY_FALLBACK]:
        system = ONE_HONESTY_SYSTEM_PROMPT.replace("CLAIM_ID", claim.id)
        user = f"Claim {claim.id} ({claim.kind}): {claim.text}"
        _try_fill_honesty(acc, simple, system, user)


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
        acc = _ClaimAcc()

        # --- Call 1: mandatory kinds ---
        _try_absorb(acc, simple, CLAIMS_MANDATORY_SYSTEM_PROMPT, request)

        # --- Call 2: requirements + honesty, conditioned on call-1 ---
        if acc.claims:
            context = "Already-proposed claims:\n" + "\n".join(
                f"- [{c.kind}] {c.text}" for c in acc.claims
            )
            _try_absorb(acc, simple, CLAIMS_REQUIREMENTS_SYSTEM_PROMPT, context)

        # A partial failure (one bad chunk) is tolerated above, but a TOTAL
        # failure (no claims parsed at all) must still surface the clean
        # "unusable plan proposal" error, never a silent empty frame.
        if not acc.claims:
            raise ValueError("no claims could be parsed from the model output")

        # --- Call 3+: dedicated honesty pass (the #215 fix) ---
        # The combined call above reliably drops honesty on a weak model; recover
        # it with a focused single-shape call + bounded per-claim fallback so the
        # spec stage can actually converge.
        _fill_honesty(acc, simple)

        return acc.claims, acc.honesty

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
        seen_ids: set[str] = set()

        for _batch in range(_PLAN_ITEM_MAX_BATCHES):
            # Build user prompt: base context + already-proposed items
            user = base_user
            if all_items:
                user += "\n\nAlready-proposed plan items:\n"
                user += "\n".join(f"- [{item.id}] {item.summary}" for item in all_items)

            prompt = PLAN_SYSTEM_PROMPT + f"\n\nPropose up to {_PLAN_ITEM_BATCH} plan items."
            try:
                items = parse_plan_items(simple(prompt, user))
            except ValueError:
                continue  # tolerate unparseable JSON; try the next batch
            # Dedup by id: a model may re-propose prior items. A batch that adds
            # nothing new ends the loop (and bounds the call count regardless).
            fresh = [it for it in items if it.id not in seen_ids]
            if not fresh:
                break
            seen_ids.update(it.id for it in fresh)
            all_items.extend(fresh)

        # A total failure (no items parsed across all batches) surfaces the clean
        # "unusable plan proposal" error rather than a silent converged-with-no-work
        # run (validate_items([]) reports no problems) — symmetric with
        # make_propose_claims raising on zero claims.
        if not all_items:
            raise ValueError("no plan items could be parsed from the model output")

        return all_items

    return propose_plan_items

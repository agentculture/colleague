"""The ``hire_colleague`` handler — a bounded two-round negotiation (plan
t12, spec c18/h9/c40/h24; ``assign_to_colleague`` lands in
:mod:`colleague.hire_assign`, t13).

The negotiation is between the HIRER (the calling model, whose tool call
carries the proposal) and a CANDIDATE voice on the SAME cortex seat: each
round is exactly ONE tools-off completion through the existing
:meth:`colleague.engine.Engine.make_complete` seam
(``make_complete(seat_config, tools=[])`` — the deepthink h2 invariant:
nothing tool-shaped on the wire), NEVER a new transport. Round 1 sends the
proposal (purpose, when, base_role, prompt) asking for a one-line
``accept | amend: purpose=...; when=... | decline: <reason>``; an amend
revision gets round 2 (accept/decline only). Parsing is tolerant, the bound
is strict: at most 2 completions ever; a malformed second reply is
``not hired``. The candidate turn's thinking effort is the seat's
:data:`colleague.effort.ROLE_TABLE` row for the proposed base role
(``reasoning_effort_seat``, the same plain attribute the deepthink seat
uses), honoring the global ``default`` kill-switch.

Roster seam (documented for t13): minted hires live ON THE EXECUTOR as
``executor.hire_roster`` — a :class:`colleague.hire.Roster`, lazily created
on first use, the same per-run attribute family as ``executor.sub_results``
— so t13's assign handler reaches a live hire via
``executor.hire_roster.get(agent_id)`` with no new constructor kwarg.

Config + engine reach the handler like :mod:`colleague.purpose_schemas`
does: the resolved parent ``EngineConfig`` as ``executor._spawn.parent_config``
and the backend name as ``executor._spawn.parent_engine``
(:func:`colleague.subagents.make_spawn`'s no-wiring seam). An optional
``executor.hire_engine_loader`` overrides :func:`colleague.registry.load`
(tests inject a fake — no network). The ``mock`` engine has no
``make_complete``; its deterministic candidate rule is
``MockEngine.hire_candidate_complete`` (see :mod:`colleague.engines.mock`).

Refusal contract (h30): an unarmed call is one readable ``ToolError`` step;
a refused hire — roster cap, over-cap when/prompt, unknown base, a dead
candidate seam — is the readable tool RESULT ``not hired: <reason>``, never
an exception, and the roster is left unchanged. Honest limits: ``task_id``
and ``created_step`` on the minted :class:`~colleague.hire.Hire` are best
effort (read from optional executor attributes, ``""``/``0`` when absent).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable, Optional

from colleague import effort, hire, hire_schemas

__all__ = ["dispatch"]

#: The strict bound: at most this many candidate completions per hire call.
MAX_ROUNDS = 2

_ROUND1_REPLY_FORMS = (
    "Reply with EXACTLY ONE line in one of these forms:\n"
    "accept\n"
    "amend: purpose=<revised purpose>; when=<revised when>\n"
    "decline: <reason>"
)

_ROUND2_REPLY_FORMS = (
    "This is round 2 — the final offer. Reply with EXACTLY ONE line:\n"
    "accept\n"
    "decline: <reason>"
)

_CANDIDATE_SYSTEM = (
    "You are a candidate colleague being offered a run-scoped position. "
    "Read the offer and answer in the requested one-line form only."
)

_AMEND_PURPOSE_RE = re.compile(r"purpose\s*=\s*(.*?)\s*(?:;\s*when\s*=|$)", re.IGNORECASE)
_AMEND_WHEN_RE = re.compile(r"when\s*=\s*(.*)\s*$", re.IGNORECASE)


def _offer_text(purpose: str, when: str, base_role: str, prompt: str, *, round2: bool) -> str:
    lines = [
        "You are offered a run-scoped position." if not round2 else "Round 2 of the negotiation.",
        f"purpose: {purpose}",
        f"when: {when}",
        f"base_role: {base_role}",
        f"prompt: {prompt}",
        _ROUND2_REPLY_FORMS if round2 else _ROUND1_REPLY_FORMS,
    ]
    return "\n".join(lines)


def _reply_text(response: Any) -> str:
    """The reply's text: ``response.content`` (ModelResponse shape) or ``str``."""
    if isinstance(response, str):
        return response
    return str(getattr(response, "content", "") or "")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _parse_reply(text: str, *, allow_amend: bool) -> tuple[str, str, str]:
    """Tolerant one-line parse → ``(verdict, arg1, arg2)``.

    ``("accept", "", "")`` / ``("decline", reason, "")`` /
    ``("amend", purpose, when)`` (round 1 only; an unparseable amend, or any
    other shape, is ``("malformed", <line>, "")``).
    """
    line = _first_line(text)
    lowered = line.lower()
    if lowered.startswith("accept"):
        return ("accept", "", "")
    if lowered.startswith("decline"):
        reason = line.split(":", 1)[1].strip() if ":" in line else "declined"
        return ("decline", reason or "declined", "")
    if allow_amend and lowered.startswith("amend"):
        purpose_match = _AMEND_PURPOSE_RE.search(line)
        if purpose_match and purpose_match.group(1).strip():
            when_match = _AMEND_WHEN_RE.search(line)
            when = when_match.group(1).strip() if when_match else ""
            return ("amend", purpose_match.group(1).strip(), when)
    return ("malformed", line, "")


def _candidate_seat_config(config: Any, base_role: str) -> Any:
    """A shallow copy of the MAIN (cortex) config carrying the candidate
    turn's effort: the :data:`colleague.effort.ROLE_TABLE` row for
    *base_role* on ``reasoning_effort_seat`` (the plain attribute
    ``vllm_openai._effort_for`` honors), ``None`` under the global
    ``default`` kill-switch. Same model/base_url — the candidate is a voice
    on the SAME seat, never a second model."""
    seat = copy.copy(config)
    seat.reasoning_effort_seat = effort.resolve_effort(
        kill_switch=getattr(config, "reasoning_effort", None) == effort.DEFAULT_SENTINEL,
        role=base_role,
    )
    return seat


def _candidate_complete(executor: Any, config: Any, base_role: str) -> Callable[..., Any]:
    """Bind ONE tools-off completion for the candidate voice.

    ``engine.make_complete(seat_config, tools=[])`` — the existing seam. An
    engine without it (``mock``) falls back to its own documented
    ``hire_candidate_complete(seat_config)`` scripted rule; neither present
    raises (the caller renders the readable ``not hired`` result).
    """
    loader = getattr(executor, "hire_engine_loader", None)
    if loader is None:
        from colleague import registry  # local: keep import surface minimal

        loader = registry.load
    engine_name = getattr(getattr(executor, "_spawn", None), "parent_engine", None) or ""
    engine = loader(engine_name)
    seat_config = _candidate_seat_config(config, base_role)
    try:
        return engine.make_complete(seat_config, tools=[])
    except NotImplementedError:
        fallback = getattr(engine, "hire_candidate_complete", None)
        if fallback is None:
            raise
        return fallback(seat_config)


def _roster(executor: Any) -> hire.Roster:
    """``executor.hire_roster``, lazily created — the t13 assign seam."""
    roster = getattr(executor, "hire_roster", None)
    if roster is None:
        roster = hire.Roster()
        executor.hire_roster = roster
    return roster


def _refusal(arguments: dict[str, Any], roster: hire.Roster) -> Optional[str]:
    """The pre-negotiation readable refusal reason, or ``None`` to proceed.

    The h30 enumerated set: unknown base role, over-cap when/prompt, a full
    roster — each refused BEFORE any completion is spent."""
    base_role = str(arguments["base_role"])
    if base_role not in hire_schemas.BUILTIN_ROLE_NAMES:
        return f"unknown base role {base_role!r} — a hire overlays a builtin role: " + ", ".join(
            hire_schemas.BUILTIN_ROLE_NAMES
        )
    when = str(arguments["when"])
    if len(when) > hire.MAX_WHEN_CHARS:
        return f"when clause is {len(when)} chars — the cap is {hire.MAX_WHEN_CHARS}"
    prompt = str(arguments["prompt"])
    if len(prompt) > hire.MAX_PROMPT_CHARS:
        return f"authored prompt is {len(prompt)} chars — the cap is {hire.MAX_PROMPT_CHARS}"
    from colleague.config import MAX_SUBAGENT_FANOUT  # local: config imports stay lazy

    if len(roster) >= MAX_SUBAGENT_FANOUT:
        return f"the roster is full — at most {MAX_SUBAGENT_FANOUT} hires per run"
    return None


def _negotiate(
    complete: Callable[..., Any], purpose: str, when: str, base_role: str, prompt: str
) -> tuple[bool, str, str, str, int]:
    """Run the bounded rounds → ``(hired, purpose, when, reason, completions)``.

    Round 1 offers the proposal (amend allowed); a decline or a malformed
    first reply gets ONE final-offer round 2 on the original terms; an amend
    gets round 2 on the amended terms. Round 2 parses accept/decline only —
    anything else is a malformed second reply. Exactly <= MAX_ROUNDS
    completions by construction.
    """
    messages = [
        {"role": "system", "content": _CANDIDATE_SYSTEM},
        {"role": "user", "content": _offer_text(purpose, when, base_role, prompt, round2=False)},
    ]
    verdict, arg1, arg2 = _parse_reply(_reply_text(complete(messages)), allow_amend=True)
    completions = 1
    if verdict == "accept":
        return (True, purpose, when, "", completions)
    if verdict == "amend":
        purpose, when = arg1, arg2
    reason = arg1 if verdict == "decline" else "no agreement in round 1"
    messages = [
        {"role": "system", "content": _CANDIDATE_SYSTEM},
        {"role": "user", "content": _offer_text(purpose, when, base_role, prompt, round2=True)},
    ]
    verdict2, arg1, _ = _parse_reply(_reply_text(complete(messages)), allow_amend=False)
    completions += 1
    if verdict2 == "accept":
        return (True, purpose, when, "", completions)
    if verdict2 == "decline":
        return (False, purpose, when, arg1, completions)
    return (
        False,
        purpose,
        when,
        f"malformed second reply ({arg1!r}); first: {reason}",
        completions,
    )


def dispatch(executor: Any) -> dict[str, Callable[[dict[str, Any]], Any]]:
    """The ``hire_colleague`` :meth:`ToolExecutor.execute` handler, bound to
    *executor* (the :func:`colleague.purpose_schemas.dispatch` shape)."""
    from colleague.tools import ToolError, ToolOutcome  # local: avoids the import cycle

    def handler(arguments: dict[str, Any]) -> Any:
        config = getattr(getattr(executor, "_spawn", None), "parent_config", None)
        if not getattr(config, "hire", False):
            raise ToolError(
                "hire_colleague is not armed for this run "
                "(COLLEAGUE_HIRE=1 or config.json 'hire': true)"
            )
        for key in ("purpose", "when", "base_role", "prompt"):
            value = arguments.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ToolError(f"hire_colleague requires a non-empty '{key}' string")

        def _result(text: str) -> Any:
            return ToolOutcome(result=executor._truncate(text, "hire_colleague"))

        roster = _roster(executor)
        reason = _refusal(arguments, roster)
        if reason is not None:
            return _result(f"not hired: {reason}")
        base_role = str(arguments["base_role"])
        try:
            complete = _candidate_complete(executor, config, base_role)
        except Exception as exc:  # no candidate seam -> readable, never a crash (h30)
            return _result(f"not hired: no candidate completion available ({exc})")
        try:
            hired, purpose, when, reason, completions = _negotiate(
                complete,
                str(arguments["purpose"]),
                str(arguments["when"]),
                base_role,
                str(arguments["prompt"]),
            )
        except Exception as exc:  # a wire failure mid-round -> readable (h30)
            return _result(f"not hired: candidate completion failed ({exc})")
        if not hired:
            return _result(f"not hired: {reason}")
        agent_id = f"hire-{len(roster) + 1}"
        try:
            minted = hire.mint_hire(
                agent_id=agent_id,
                hirer_id="cortex",
                base_role=base_role,
                purpose=purpose,
                when=when,
                prompt_fragment=str(arguments["prompt"]),
                task_id=str(getattr(executor, "task_id", "") or ""),
                created_step=int(getattr(executor, "step_count", 0) or 0),
            )
            roster.add(minted)
        except hire.HireError as exc:  # e.g. an over-cap AMENDED when clause
            return _result(f"not hired: {exc}")
        return _result(
            f"hired: {agent_id} (base_role={base_role}, "
            f"{completions} negotiation completion(s))\n"
            f"purpose: {purpose}\nwhen: {when}\n"
            f"Assign it work with assign_to_colleague(agent_id={agent_id!r}, task=...)."
        )

    return {"hire_colleague": handler}

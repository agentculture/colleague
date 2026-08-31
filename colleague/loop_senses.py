"""The injection lane: senses records, the context packet, self-knowledge, the
media bridge, and the up-front advisories.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A pure move.
"""

from __future__ import annotations

import sys

from colleague import autosplit as _autosplit
from colleague import media
from colleague.capacity import assess_capacity
from colleague.context import count_tokens_chars
from colleague.contract import ContextPacket, SensesBlock, SensesRecord, TaskResult
from colleague.loop_constants import (
    _CONTEXT_PACKET_ADVISORY,
    _MEDIA_BRIDGE_QUESTION,
    _MEDIA_DELIVERED,
    _MEDIA_DELIVERY_FLOOR,
    _MEDIA_DROPPED,
    _MEDIA_UNKNOWN,
    _POINT_MEDIA_BRIDGE,
    _SELF_KNOWLEDGE_ADVISORY,
    _SELF_KNOWLEDGE_GUIDE_CAP,
)
from colleague.loop_context import _autosplit_armed
from colleague.loop_types import _Work
from colleague.loop_wire import ModelResponse
from colleague.selfknowledge import build_guide_index, build_self_facts, classify_selfknowledge


def _classify_media_delivery(prompt_tokens: int, text_only_tokens: int, n_parts: int) -> str:
    """Classify media delivery from the token-contribution signal (t9, c25).

    ``delivered`` iff the prompt's reported tokens exceed the text-only
    estimate by at least the per-part floor — the exact signal the live
    silent-drop probe exposed (an image contributes hundreds of prompt
    tokens; a drop contributes ~0). A server that reported NO usage
    (``prompt_tokens <= 0`` — e.g. a scripted mock) classifies ``unknown``:
    a drop is never claimed without evidence. The word is DELIVERED, never
    "understood" — comprehension is claimed only by the livecheck proof.
    """
    if prompt_tokens <= 0:
        return _MEDIA_UNKNOWN
    if prompt_tokens - text_only_tokens >= _MEDIA_DELIVERY_FLOOR * max(1, n_parts):
        return _MEDIA_DELIVERED
    return _MEDIA_DROPPED


def _maybe_record_media_delivery(ctx: _Work, resp: ModelResponse) -> None:
    """Record the delivered/dropped verdict for the task's attachments (t9).

    Fires once, on the first completion after the media-bearing initial
    message; strict no-op with no attachments or once recorded. Zero extra
    model turns: the text-only baseline is counted locally (the exact counter
    when bound — flattened messages are all-string, so it can count them —
    else the char estimate) and compared against the server-reported
    ``prompt_tokens``. A drop warns on stderr and is recorded on
    ``TaskResult.media``; it never blocks or aborts the run.
    """
    if not ctx.task.attachments or ctx.result.media is not None:
        return
    flattened = [
        (
            dict(m, content=media.flatten_parts(m["content"]))
            if isinstance(m.get("content"), list)
            else m
        )
        for m in ctx.messages
    ]
    counter = ctx.count_tokens if ctx.count_tokens is not None else count_tokens_chars
    try:
        text_only = counter(flattened)
    except Exception:  # noqa: BLE001 - a counter failure must never abort the run
        text_only = count_tokens_chars(flattened)
    initial = ctx.messages[1].get("content") if len(ctx.messages) > 1 else None
    n_parts = (
        sum(
            1
            for p in initial
            if isinstance(p, dict) and p.get("type") in ("image_url", "input_audio")
        )
        if isinstance(initial, list)
        else len(ctx.task.attachments)
    )
    status = _classify_media_delivery(resp.prompt_tokens, text_only, n_parts)
    ctx.result.media = {
        "attachments": [
            {"path": str(a.get("path", "?")), "status": status}
            for a in ctx.task.attachments
            if isinstance(a, dict)
        ]
    }
    if status == _MEDIA_DROPPED:
        print(
            f"warning: {n_parts} media attachment(s) were NOT delivered to the "
            "model (prompt token contribution below the per-part floor) — "
            "recorded on the artifact's media key",
            file=sys.stderr,
        )


def _ensure_senses_block(
    result: TaskResult, *, mode: str = "split", packet: "ContextPacket | None" = None
) -> SensesBlock:
    """Init-on-first the ``TaskResult.senses`` block (the senses twin of the
    deepthink init in :func:`_record_deepthink`).

    A run with no senses involvement never calls this, so ``result.senses``
    stays ``None`` and the artifact key is omitted (byte-identical). The first
    caller sets ``mode``/``packet``; a later caller (e.g. the media bridge after
    the packet injection) keeps the existing block and only fills a still-absent
    packet, so mode/packet are never clobbered.
    """
    if result.senses is None:
        result.senses = SensesBlock(mode=mode, packet=packet, records=[])
    elif packet is not None and result.senses.packet is None:
        result.senses.packet = packet
    return result.senses


def _record_senses_call(
    result: TaskResult,
    record: SensesRecord,
    *,
    mode: str = "split",
    packet: "ContextPacket | None" = None,
) -> None:
    """Append one :class:`SensesRecord` to ``result.senses`` (init-on-first)."""
    _ensure_senses_block(result, mode=mode, packet=packet).records.append(record)


def _record_senses_injection(result: TaskResult, entry: dict, *, mode: str = "cortex-only") -> None:
    """Append one applied-injection entry to ``result.senses.injections`` (t5).

    Mode defaults to ``cortex-only`` for the fresh-block case (an operator relayed
    guidance into a cortex-only run); ``_ensure_senses_block`` keeps an existing
    block's mode (e.g. ``split`` when senses also ran intake), so mode is never
    clobbered. Init-on-first — a run with no injection never touches ``senses``.
    """
    _ensure_senses_block(result, mode=mode).injections.append(entry)


def _maybe_inject_context_packet(ctx: _Work) -> None:
    """Inject the senses :class:`ContextPacket` as ONE advisory companion (t6).

    When the task carries a ``context_packet`` (the session/resident ran senses
    intake), cortex's first user message is ALREADY the operator's verbatim
    original (``_build_user_message`` uses ``task.instruction``) — the packet
    never replaces it. This appends the senses model's interpretation as ONE
    advisory user message (the recall-before precedent) and records the packet on
    ``TaskResult.senses`` (mode ``split``). Strict no-op with no packet
    (byte-identical): ``result.senses`` stays ``None``.
    """
    packet = getattr(ctx.task, "context_packet", None)
    if packet is None:
        return
    lines = [_CONTEXT_PACKET_ADVISORY]
    if packet.interpretation:
        lines.append(f"Interpretation: {packet.interpretation}")
    if packet.task_type:
        lines.append(f"Task type: {packet.task_type}")
    if packet.confidence:
        lines.append(f"Confidence: {packet.confidence}")
    if packet.omissions:
        lines.append("Possible omissions: " + "; ".join(packet.omissions))
    ctx.messages.append({"role": "user", "content": "\n".join(lines)})
    _ensure_senses_block(ctx.result, mode="split", packet=packet)


class _SensesFact:
    """The minimal ``senses``-shaped holder ``build_self_facts`` duck-reads (t9):
    it checks ``senses is not None and senses.model`` — this carries exactly that
    one attribute (the ``_StubSenses`` shape the selfknowledge unit tests pin)."""

    def __init__(self, model: str) -> None:
        self.model = model


class _SelfFactsSource:
    """Adapt ``_Work`` to the duck-typed surface :func:`build_self_facts` reads (t9).

    The loop does NOT hold a resolved :class:`~colleague.config.EngineConfig` — it
    takes a curated :class:`ContextControls` (the deliberate import-cycle boundary
    ``from_config``/``resolve_role`` also observe), so a full config is not cheaply
    reachable here. This exposes exactly what the loop DOES know under the attribute
    names ``build_self_facts`` expects: the cortex ``model`` id (threaded onto
    ``_Work.model``), the five gate booleans, and — when armed — the resolved senses
    model id (``ContextControls.senses_model`` → ``_Work.senses_model``), so an
    armed session renders the REAL id and only a genuinely absent one renders
    ``build_self_facts``'s honest ``not configured`` default (never a fabricated
    id, and never a false absent line when the value is present). The armed lobes
    gateway travels the same way (``_Work.lobes_gateway``) but is passed as
    ``build_self_facts``'s ``gateway_url=`` parameter by the caller, not exposed
    here.
    """

    def __init__(self, ctx: "_Work") -> None:
        self.model = ctx.model
        self.senses = _SensesFact(ctx.senses_model) if ctx.senses_model else None
        self.lint = ctx.lint_enabled
        self.testintegrity = ctx.testintegrity_enabled
        self.affected_tests = ctx.affectedtests_enabled
        self.memory = ctx.memory_enabled
        self.coherence = ctx.coherence_enabled


def _maybe_inject_self_knowledge(ctx: _Work) -> None:
    """Inject the guide index + resolved self-facts on a self-knowledge turn (t9 / #306).

    Mirrors :func:`_maybe_inject_context_packet` in shape, gating, and placement:
    cortex's first user message is ALREADY the operator's verbatim instruction
    (``_build_initial_content``) — this appends ONE advisory user message so cortex
    answers questions ABOUT colleague from the LIVE guide docs + resolved runtime
    state instead of guessing. Gated on the deterministic
    :func:`colleague.selfknowledge.classify_selfknowledge`; an ordinary
    (non-self-knowledge) instruction is a STRICT no-op — no guide index, no
    self-facts, no extra message — so the guide docs are loaded ONLY when a
    self-knowledge turn triggers them and an ordinary run is byte-identical (#306).

    Facts-block plumbing (honest both ways): the loop reaches the cortex model id
    (``_Work.model``), the five gate booleans, and — threaded through
    ``ContextControls.from_config`` by every backend (all-engines rule) — the
    resolved senses model id (``config.senses.model``) plus the ARMED lobes gateway
    origin (``config.lobes_gateway_url``, set by ``EngineConfig.resolve``); it does
    NOT hold the full :class:`~colleague.config.EngineConfig` (see
    :class:`_SelfFactsSource`). An armed session therefore renders the REAL senses
    id + gateway URL; only a genuinely absent value renders ``build_self_facts``'s
    honest ``not configured`` / ``not armed`` defaults — a present value must never
    render as absent (that would be a FALSE fact), and an absent one is never
    fabricated. When even the cortex model id is absent (a direct ``run`` caller
    that passed no ``model``) the facts block is dropped entirely and the guide
    index alone is injected — the task's honest-degradation clause: never a
    fabricated facts block.

    The #206 invariant holds: this appends a companion user message but never fires
    the progress sink or advances ``step_count`` (it runs before the loop body, like
    the packet/recall injections).
    """
    if not classify_selfknowledge(ctx.task.instruction or ""):
        return
    lines = [_SELF_KNOWLEDGE_ADVISORY]

    guides = build_guide_index(ctx.task.repo_path)
    if guides:
        shown = guides[:_SELF_KNOWLEDGE_GUIDE_CAP]
        lines.append("colleague guide docs (open one with read_file for detail):")
        lines.extend(f"- {path}" for path in shown)
        if len(guides) > len(shown):
            lines.append(f"- … and {len(guides) - len(shown)} more")

    # Facts block only when the cortex model id is genuinely known — never a
    # fabricated facts block (guide index alone otherwise). gateway_url carries
    # the ARMED lobes origin ("" → None → the honest "not armed" line).
    if ctx.model:
        lines.append("")
        lines.append("resolved runtime state:")
        lines.append(build_self_facts(_SelfFactsSource(ctx), gateway_url=ctx.lobes_gateway or None))

    ctx.messages.append({"role": "user", "content": "\n".join(lines)})


def _maybe_run_senses_media_bridge(ctx: _Work) -> bool:
    """Run the cortex/senses media bridge if armed + PREFERRED (t6).

    The senses-lobe twin of the deepthink bridge in :func:`_maybe_run_media_bridge`,
    and PREFERRED over it: when the operator declared the senses model multimodal
    (``senses_media_bridge``) the real media parts ride ONE tools-off completion to
    the senses endpoint (the text-only cortex wire is flattened first), the record
    lands on ``TaskResult.senses`` (never ``deepthink``), and the description folds
    back as ONE advisory user message. Returns ``True`` when it HANDLED the bridge
    (so the deepthink path is skipped — senses is preferred, a degraded senses run
    does NOT fall back to deepthink), ``False`` to fall through (not armed, or no
    media parts present) leaving the deepthink path byte-identical.
    """
    if not ctx.senses_media_bridge or ctx.senses_run is None or not ctx.task.attachments:
        return False
    initial = ctx.messages[1].get("content") if len(ctx.messages) > 1 else None
    if not isinstance(initial, list):
        return False
    parts = [
        p for p in initial if isinstance(p, dict) and p.get("type") in ("image_url", "input_audio")
    ]
    if not parts:
        return False
    # The cortex (main) wire is DECLARED text-only — flatten it so the parts ride
    # ONLY the senses escalation (the deepthink-bridge invariant, t6/c24).
    ctx.messages[1] = dict(ctx.messages[1], content=media.flatten_parts(initial))
    question = _MEDIA_BRIDGE_QUESTION + (ctx.task.instruction or "")
    text, record = ctx.senses_run(question, parts)
    _record_senses_call(ctx.result, record)
    if getattr(record, "degraded", False) or not (text or "").strip():
        # Degraded senses bridge: nothing folds; the (now text-only) cortex turn
        # proceeds. Senses is preferred — no deepthink fallback (handled=True).
        return True
    ctx.messages.append(
        {
            "role": "user",
            "content": "[media bridge] A multimodal senses model examined the attached "
            "media and reports:\n" + text,
        }
    )
    # Delivery record (c25 vocabulary): cortex saw placeholders, the description
    # was delivered via the senses model — recorded as "bridged", mirroring the
    # deepthink bridge (the t9 verifier skips a set record).
    ctx.result.media = {
        "attachments": [
            {"path": str(a.get("path", "?")), "status": "bridged"}
            for a in ctx.task.attachments
            if isinstance(a, dict)
        ]
    }
    return True


def _maybe_run_media_bridge(ctx: _Work) -> None:
    """Escalate attached media to the declared multimodal second model (t8, c24).

    Fires ONCE, before the first turn, and only when ALL of: the task carries
    attachments, a dual-model config is bound (``deepthink_run``), and the
    operator declared the second model multimodal (``media_bridge`` — never
    probed or inferred). The escalation is one bounded tools-off completion
    (``run_media_bridge`` via the binding's ``media_parts`` path); its
    description folds back as exactly ONE advisory user message. A degraded
    bridge records honestly on ``TaskResult.deepthink`` and folds nothing —
    the run continues from the text alone (h18: degrade, never raise; the
    delivered/dropped record is task t9's).

    Cortex/senses (t6): a declared multimodal SENSES config is PREFERRED — the
    senses bridge runs first and, when it handles the bridge, records under
    ``TaskResult.senses`` and returns before the deepthink path below. When only
    deepthink is declared the senses branch is a strict no-op and the deepthink
    path is byte-identical to v1.34.0.
    """
    if _maybe_run_senses_media_bridge(ctx):
        return
    if not ctx.media_bridge or ctx.deepthink_run is None or not ctx.task.attachments:
        return
    initial = ctx.messages[1].get("content") if len(ctx.messages) > 1 else None
    if not isinstance(initial, list):
        return
    parts = [
        p for p in initial if isinstance(p, dict) and p.get("type") in ("image_url", "input_audio")
    ]
    if not parts:
        return
    # The main model is DECLARED text-only (that is what armed the bridge), so
    # the parts must not ride its wire at all — a text-only vLLM endpoint
    # typically rejects image parts outright rather than dropping them. The
    # main wire gets the flattened text (placeholders); the REAL parts travel
    # only on the bridge escalation below (h12/h18 extended to the main wire).
    ctx.messages[1] = dict(ctx.messages[1], content=media.flatten_parts(initial))
    question = (
        "You are the multimodal half of a dual-model rig. The MAIN model "
        "driving this task is text-only and cannot see the attached media. "
        "Describe the attached media precisely and completely as it relates "
        "to the task below, so a text-only model can act on your description "
        "alone.\n\nTask:\n" + (ctx.task.instruction or "")
    )
    res = ctx.deepthink_run(question, "", point=_POINT_MEDIA_BRIDGE, media_parts=parts)
    call = getattr(res, "call", None)
    if call is not None:
        _record_deepthink(ctx.result, call)
    text = (getattr(res, "text", "") or "").strip()
    if call is not None and getattr(call, "degraded", False) or not text:
        # Degraded bridge: nothing folds; the media record stays unset so the
        # t9 verifier classifies the (now text-only) first completion honestly
        # — dropped with real usage, unknown without.
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": "[media bridge] A multimodal model examined the attached "
            "media and reports:\n" + text,
        }
    )
    # Delivery record (c25 vocabulary + the bridge case): the MAIN model saw
    # placeholders, the description was delivered via the second model —
    # recorded as "bridged" (preset here; the t9 verifier skips a set record).
    ctx.result.media = {
        "attachments": [
            {"path": str(a.get("path", "?")), "status": "bridged"}
            for a in ctx.task.attachments
            if isinstance(a, dict)
        ]
    }


def _maybe_inject_upfront_hint(ctx: _Work) -> None:
    """Append the up-front advisory split hint when armed and the task looks big (#151).

    A COARSE estimate of the instruction alone (it cannot see the repo surface the
    work will touch — the parked limit r2): when armed and that estimate already
    exceeds one context window, append ONE optional early suggestion to split via
    the ``subagents`` tool. Advisory only — it never blocks and adds NO model turn
    (just context the first turn sees). It almost never fires for a normal-sized
    task, so the default path stays byte-identical. Extracted from :func:`run` to
    keep that function's cognitive complexity within budget.
    """
    if not _autosplit_armed(ctx):
        return
    budget = int(ctx.context_budget)
    estimate = _autosplit.estimate_instruction_tokens(ctx.task.instruction, ctx.count_tokens)
    if estimate <= budget:
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": _autosplit.build_upfront_hint(
                estimate_tokens=estimate,
                per_child_budget_tokens=budget,
                max_children=_autosplit.child_count(int(ctx.autosplit_target), budget),
            ),
        }
    )


def _maybe_warn_too_big(ctx: _Work) -> None:
    """Set the warn-only "too big for one repo" caller warning (#156, t7).

    A coarse up-front capacity assessment (deps/folders/files + an instruction token
    estimate via :mod:`colleague.capacity`) that judges the assignment to exceed even
    the in-repo split capacity records a caller-visible warning on
    ``result.capacity_warning`` — surfaced (CLI prints it to stderr; it is recorded in
    the artifact), never silent. Colleague performs NO cross-repo write: the operator
    splits the work across repos/instances (neighbours stay read-only). A strict no-op
    for a normal-sized job (verdict != over_split_capacity → warning stays ``None`` →
    omitted from the artifact). Gated on a positive budget like the other context
    features. The estimate is coarse (it cannot see the repo surface the work will
    touch — the parked limit r2)."""
    budget = ctx.context_budget
    if not isinstance(budget, int) or budget <= 0:
        return
    # Pass the REAL split capacity (the autosplit target = max children × per-child
    # budget) so the verdict isn't a magic 4× proxy; the assessment folds the repo's
    # complexity (deps/folders/files) into the effective size it judges.
    split_capacity = ctx.autosplit_target if isinstance(ctx.autosplit_target, int) else None
    verdict = assess_capacity(
        ctx.task.repo_path,
        ctx.task.instruction,
        budget,
        ctx.count_tokens,
        split_capacity_tokens=split_capacity,
    )
    if verdict.verdict == "over_split_capacity":
        ceiling = split_capacity if split_capacity else budget * 4
        ctx.result.capacity_warning = (
            f"This assignment looks too big to hold in one repo: an estimated "
            f"{verdict.effective_tokens} effective tokens (instruction + repo complexity) "
            f"exceeds even the in-repo split capacity (~{ceiling} tokens across child "
            f"instances). Consider splitting it across multiple repositories or colleague "
            f"instances — colleague will not write across repos (warn-only)."
        )


def _record_deepthink(result: TaskResult, call: object) -> None:
    """Append one DeepthinkCall record to ``result.deepthink`` (init-on-first)."""
    if result.deepthink is None:
        result.deepthink = []
    result.deepthink.append(call)

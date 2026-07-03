"""colleague.resident.appserver — the resident's Harness for MESH WORK REQUESTS.

Plan task t13 ("Resident harness (appserver mode)"): colleague consumes
``agent_lifecycle.runtime`` as a **library embed** (the upstream spec's
decision, ``agent-lifecycle`` docs/specs/2026-07-02-…-focused-lifecycle-
core-that.md: "colleague consumes agent-lifecycle by library embed") so it can
live on the Culture mesh as a resident that accepts work requests and runs
them as background **work items** — the same ``Task``/``TaskResult``/artifact
shape ``colleague work`` produces, not a bare conversational reply.

:class:`AppserverHarness` is a **second** Harness implementation alongside
:class:`colleague.resident.harness.ColleagueHarness` (the conversational
resident wired by ``colleague promote --serve``). The two are deliberately
distinct, not a generalisation of one another:

* :class:`~colleague.resident.harness.ColleagueHarness` — one bounded
  ``engine.work()`` turn per message, no artifact, no git handoff; a chat
  reply.
* :class:`AppserverHarness` (here) — one full :func:`colleague.cli._commands.
  work.execute_work` invocation per accepted message: writes a real result
  artifact, runs the lint/test-integrity/affected-tests gates (all inherited
  for free — they live in ``colleague/loop.py``, which every ``engine.work()``
  call already goes through), acquires the rig-level concurrency slot
  (``colleague/rig.py``), and — for an operator's write-capable request only —
  commits/PRs via the normal git handoff. A non-operator's downgraded
  read-only dispatch skips the handoff entirely (the read-only role
  *structurally* writes nothing — see ``colleague/roles.py``).

Dispatch choice (design constraint, spec R4/h10 precedent): the plan task
description offered two options — reuse :mod:`colleague.background`'s
one-shot subprocess detach, or call ``execute_work`` directly in-process.
This module calls ``execute_work`` **directly**, run via
``loop.run_in_executor`` (mirroring :class:`ColleagueHarness`) rather than
spawning a child process, because:

1. The upstream contract requires the *reply* to carry the result summary
   **and** the artifact pointer (see ``docs/colleague-embed.md``'s minimal
   example) — ``execute_work`` returns exactly that pair
   ``(TaskResult, artifact_path)`` synchronously, so the reply can carry the
   real completed summary rather than a bare "accepted, check back later"
   acknowledgement that a detached child would force.
2. Rig-budget governance (spec R5/#258, ``colleague/rig.py``) is already
   built into ``execute_work`` (it acquires one rig slot around
   ``engine.work()``), so calling it directly gives "background work items
   (rig-budget governed)" for free — no extra wiring needed here.
3. It keeps the appserver's own module surface subprocess-free: no new
   sanctioned ``subprocess`` consumer, and the existing background one-shot
   primitive (``colleague/background.py``, plan t12) stays reserved for its
   documented purpose — detaching ``colleague work --background`` from an
   operator's own terminal, a different shape of problem entirely.

**Batch semantics — the upstream hard question, answered here.** The upstream
spec asks: "batch agents run to completion rather than staying alive — does
the runtime need a run-to-completion lifecycle mode, or is restart-policy
'never' already sufficient?" Answer from this consumer: **restart-policy
'never' is sufficient.** ``agent_lifecycle.runtime.Supervisor``'s inbound pump
processes messages **sequentially** — it ``await``s ``feed_message()`` in
full before pulling the next message off ``transport.receive()`` — and each
``feed_message()`` call here already runs ONE ``execute_work`` to completion
(success, handoff-skipped read-only completion, or a caught
:class:`~colleague.cli._errors.CliError` converted to an error reply) before
returning. There is nothing to *restart*: a colleague work item is a
run-to-completion one-shot by construction (it either finishes or its failure
is recorded on the artifact/reply), so no supervised-process restart
machinery is ever exercised by this consumption path. This composes cleanly
with the known single-GPU-serializes-requests reality documented elsewhere in
this repo (``docs/live-testing.md`` / eidetic memory
``colleague-workforce-concurrency-limit``): the resident naturally processes
one work item at a time, which is exactly what the served model can sustain
today.

**Trust model (c19)** is enforced by :mod:`colleague.resident.trust`
*before* any dispatch: a non-operator's plain request is downgraded to the
read-only ``explorer`` role (never touches the write handoff); a
non-operator's *explicit* request for write access is refused outright, with
no ``execute_work`` call at all.

**Failure surfacing.** A genuine work-item failure (``execute_work`` raising
:class:`~colleague.cli._errors.CliError` — the *expected* "this task failed"
signal, e.g. an unreachable engine) is caught here and turned into an error
reply, so ONE bad request does not end the resident's long-lived session
(mirroring honesty h10: "the bounded step cap bounds a turn, never the
session"). Any **other**, unexpected exception is deliberately left
uncaught — it propagates out of ``feed_message()``, and
``agent_lifecycle.runtime.supervisor.Supervisor`` catches it at the pump
boundary, records it via :meth:`~agent_lifecycle.runtime.supervisor.
Supervisor.failure`, and transitions to ``FAILED`` — genuine infrastructure
failures are surfaced, never silently swallowed.

**Real-transport status (h15): PENDING.** This module is proven end-to-end
against ``agent_lifecycle.reference.InMemoryTransport`` (see
``tests/test_resident_appserver.py``) — the upstream reference double, no
network. A real mesh transport for work *requests* (as opposed to the
existing IRC wire the conversational resident uses) has not shipped upstream
yet; wiring one in is a follow-up once agent-lifecycle ships it, not part of
this task.

Kept out of ``colleague/cli/_commands/work.py`` deliberately: that module's
own boundary test (``tests/test_resident_no_work_path.py``
``test_work_cli_source_has_no_resident_reference``) pins that the bounded
work CLI never references the resident package — this module reaching
*into* ``execute_work`` is the permitted, one-way direction of that boundary
(the resident depends on the work path; the work path never depends on the
resident).

**Media references (task t12).** A mesh request's ``body`` MAY reference
local media via a line-anchored ``attach: <path>`` token — one per line, at
most :data:`_MAX_ATTACHMENTS`; :func:`_extract_attach_lines` parses these OUT
of the request text (a matched line never reaches the model as prose) and
returns the candidate paths. Each candidate is checked against the c19 trust
boundary FIRST, via :func:`colleague.resident.trust.check_attachment_path`
(operator: any local path; non-operator: must resolve inside the repo
working tree — the anti-exfiltration rule) — this runs *before*
``colleague.media.validate_attachment`` ever touches the filesystem for
content. Only a path that clears BOTH the trust check and
``validate_attachment`` becomes a ``Task.attachments`` entry (the same
``{"path", "media_type"}`` shape a CLI-authored attachment carries); a
refusal at either stage drops just that one attachment — recorded as a note,
never a crash, and the request still runs under whatever role
:func:`~colleague.resident.trust.classify_request` already assigned.

**Audio reply link (task t8).** When ``config.voice`` is armed with a
``tts_model`` (senses live-presence + voice arc), a SUCCESSFUL dispatch's
reply text is additionally synthesized to a ``.wav`` written beside that work
item's artifact (:func:`colleague.voice.synthesize`, degrade-never-raise), and
the reply gains one extra line — ``audio: <path>`` — naming that wav's path
**relative to the repo root** (the same root the artifact's own ``.colleague/``
directory lives under, so a mesh peer with a checkout of the same repo can
resolve it directly; see :meth:`_synthesize_reply_audio`). A mic-less peer thus
consumes the reply as a text-plus-file-link pair instead of needing real-time
audio. On ``synthesize`` returning ``None`` (the documented honest limit: the
reference rig's speech proxy currently 502s) the reply is **byte-identical**
to a no-tts reply — no line, no crash; this feature is purely additive.
Unarmed voice (``config.voice is None``) never calls ``synthesize`` at all.

**Trust-gated relay (task t8).** A mesh message MAY address an
ALREADY-RUNNING flight via a line-anchored convention: a message whose body
contains a line ``relay <task-id>: <text>`` (case-insensitive ``relay``
keyword; *task-id* is a single non-whitespace, non-colon token). Detecting
this line is checked BEFORE the normal work-item dispatch path in
:meth:`feed_message` — a relay message never spawns its own ``execute_work``
call; it is a side-channel action against a *different*, already-running work
item. :meth:`_handle_relay` owns the full contract:

1. *task-id* is validated with :func:`colleague.flight.is_safe_task_id`
   FIRST, for every requester (including the operator) — an unsafe id (path
   traversal, an absolute path, ``..``) is refused before anything else runs,
   so no requester can smuggle a filesystem escape through this convention.
2. The relay text is ALWAYS routed through the senses live-presence talk lane
   (:func:`colleague.senses.run_senses_talk`, via :meth:`_senses_talk` — the
   SAME tools-off, degrade-never-raise seam :meth:`_senses_intake` /
   :meth:`_speakback_and_finalize` already use) to produce a conversational
   answer, when a senses model is resolved; with no senses model configured
   at all this step is skipped (``talk is None``).
3. **The trust gate.** Whether *this* request may actually append guidance
   onto the addressed flight is decided by reusing the EXACT SAME verdict
   :func:`~colleague.resident.trust.classify_request` already produced for
   this message (``decision.outcome == colleague.resident.trust.ALLOW_WRITE``
   — the identical check :func:`~colleague.resident.trust.RequestDecision`
   encodes for "this sender is the confirmed operator"; this task invents NO
   second trust-decision path). Only inside that ``is_operator`` branch does
   :func:`colleague.flight.append_guidance` ever get called — structurally,
   there is exactly ONE call site for it in this module, and it sits inside
   that one conditional. A non-operator's relay attempt takes the sibling
   branch, which can NEVER reach that call: it replies with the senses
   answer when one was produced, or (senses unconfigured) a plain refusal
   line naming the addressed task id and pointing the requester at the
   operator — mirroring the wording :func:`classify_request` already uses for
   its own REFUSE verdict, but never itself calling ``append_guidance``.
4. An operator's relay is always visibly labeled in the reply with a
   ``-> cortex(<task-id>): <text>`` line (in addition to any senses answer),
   so the operator can see exactly what was injected and where; a
   non-operator's reply never carries that label (nothing was injected).

This is deliberately a DIFFERENT lane from the normal work-item dispatch:
no ``Task``/``execute_work``/artifact is ever created for a relay message —
only the two file-based flight-plane primitives (:func:`is_safe_task_id`,
:func:`append_guidance`) and the senses talk lane are touched, exactly the
primitives :mod:`colleague.flight` and :mod:`colleague.senses` already
expose (no duplication).
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from agent_lifecycle.runtime.message import Message
from agent_lifecycle.runtime.supervisor import Supervisor

from colleague import registry
from colleague.artifact import artifact_dir
from colleague.artifact import write as _write_artifact
from colleague.contract import SensesBlock, Task
from colleague.flight import append_guidance, feed_path, is_safe_task_id
from colleague.media import validate_attachment
from colleague.resident.trust import ALLOW_WRITE, check_attachment_path, classify_request
from colleague.senses import (
    run_senses_intake,
    run_senses_speakback,
    run_senses_talk,
    senses_engine_config,
)
from colleague.voice import synthesize

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import
    from agent_lifecycle.runtime.transport import Transport

    from colleague.config import EngineConfig

# Sentinel placed on the reply queue by stop() to end the replies() stream.
_STOP: object = object()

# t12: the mesh media-reference convention -- a line-anchored `attach: <path>`
# token, one per line. Capped so a request can't smuggle an unbounded number
# of filesystem probes through one message; extras beyond the cap are counted
# and reported, never silently dropped.
_MAX_ATTACHMENTS = 4
_ATTACH_LINE_RE = re.compile(r"^attach:\s*(\S.*)$")


def _extract_attach_lines(text: str) -> tuple[str, list[str], int]:
    """Split *text* into ``(cleaned_text, candidate_paths, dropped_count)``.

    Recognises the ``attach: <path>`` convention (see the module docstring).
    A matched line is REMOVED from the returned text entirely. At most
    :data:`_MAX_ATTACHMENTS` candidates are kept, in order; any further
    matches are counted in *dropped_count* (never silently truncated without
    a trace -- the caller turns that count into a recorded note).

    A *text* with no ``attach:`` lines is returned completely unchanged
    (same object, even) -- a request with no media reference behaves
    byte-identically to before this feature existed.
    """
    lines = text.splitlines()
    if not any(_ATTACH_LINE_RE.match(line) for line in lines):
        return text, [], 0

    kept_lines: list[str] = []
    candidates: list[str] = []
    dropped = 0
    for line in lines:
        match = _ATTACH_LINE_RE.match(line)
        if not match:
            kept_lines.append(line)
            continue
        path = match.group(1).rstrip()
        if len(candidates) < _MAX_ATTACHMENTS:
            candidates.append(path)
        else:
            dropped += 1
    return "\n".join(kept_lines), candidates, dropped


# t8: the mesh relay-addressing convention -- a line-anchored `relay <task-id>:
# <text>` token (case-insensitive keyword; the task id is a single non-whitespace,
# non-colon token). See the module docstring's "Trust-gated relay" section.
_RELAY_LINE_RE = re.compile(r"^relay\s+([^\s:]+):\s*(\S.*)$", re.IGNORECASE)


def _extract_relay_line(text: str) -> Optional[tuple[str, str]]:
    """Return ``(task_id, relay_text)`` for the FIRST ``relay <task-id>: <text>``
    line found in *text*, or ``None`` when no line matches the convention.

    Unlike :func:`_extract_attach_lines` (which strips matched lines and lets
    the REST of the message proceed as a normal work request), a matched relay
    line takes the message down an entirely different path (see
    :meth:`AppserverHarness._handle_relay`) — no work item is ever dispatched
    for it, so there is nothing to "clean" and return alongside it.
    """
    for line in text.splitlines():
        match = _RELAY_LINE_RE.match(line.strip())
        if match:
            return match.group(1), match.group(2).rstrip()
    return None


class AppserverHarness:
    """agent-lifecycle ``Harness`` adapter dispatching mesh requests as work items.

    Satisfies :class:`agent_lifecycle.runtime.harness.Harness` structurally
    (no base-class import required). All four methods are asyncio-native;
    none accepts a transport, presence, channel, or connection — the
    Supervisor bridges the transport layer externally.

    Args:
        repo_path: The repo this resident works in (each accepted request runs
            here, isolated in its own throwaway worktree — see
            ``execute_work``'s ``isolate=True``).
        config: The resolved :class:`~colleague.config.EngineConfig`. A
            per-request COPY (:func:`dataclasses.replace`) is dispatched so a
            role restriction from one request never leaks into a concurrent
            or later one.
        engine_name: Backend name; defaults to ``config.engine`` (present
            only on a test double — the real ``EngineConfig`` has no
            ``engine`` field, so this normally falls back to ``"mock"``
            unless the caller passes it explicitly).
        agent_nick: This resident's identity, used as ``sender`` on replies.
        operator_identity: The mesh identity treated as authoritative under
            the c19 trust model (see :mod:`colleague.resident.trust`).
            ``None`` means no operator is configured — every requester is
            then downgraded/refused (fail-safe).
        default_target: Fallback ``target`` for a reply when the inbound
            message carries none.
        open_pr: Forwarded to ``execute_work`` for an operator's write-capable
            dispatch. Defaults to ``False`` (commit locally only) — an
            appserver accepting mesh requests should not push/open a PR
            without the operator opting in explicitly.
        base: Base branch for the PR handoff (only reached on a write-capable,
            successful dispatch).
        allow_dirty: Forwarded to ``execute_work``. Defaults to ``True``
            because a dispatch is **always** isolated (``isolate=True``): the
            isolated worktree checks out the operator's HEAD fresh, so the
            operator's own uncommitted tracked edits are excluded from the
            work item by construction (the documented q1 clean-HEAD-isolation
            decision) — the dirty-tree guard's purpose does not apply to an
            unattended resident the way it does to an interactive
            ``colleague work`` invocation, so refusing every request whenever
            the operator's own tree happens to be dirty would make the
            appserver largely non-functional day to day.
    """

    def __init__(
        self,
        repo_path: str,
        config: "EngineConfig",
        *,
        engine_name: str | None = None,
        agent_nick: str = "colleague",
        operator_identity: str | None = None,
        default_target: str = "",
        open_pr: bool = False,
        base: str = "main",
        allow_dirty: bool = True,
    ) -> None:
        self._repo_path = str(repo_path)
        self._config = config
        self._engine_name = engine_name or getattr(config, "engine", "mock")
        self._agent_nick = agent_nick
        self._operator_identity = operator_identity
        self._default_target = default_target
        self._open_pr = open_pr
        self._base = base
        self._allow_dirty = allow_dirty
        # Queue bridges synchronous dispatch completion -> the replies() async
        # generator, mirroring ColleagueHarness's pattern exactly.
        self._reply_queue: "asyncio.Queue[Any]" = asyncio.Queue()
        self._replies_iter: Optional[AsyncIterator[Message]] = None

    # `async` with no `await` is required here: the upstream agent_lifecycle
    # Harness Protocol declares `async def start()`, and the supervisor awaits
    # it — a sync def would not conform, hence the suppression below.
    async def start(self) -> None:  # NOSONAR(S7503)
        """Fresh reply stream per session (supports restart of the harness itself)."""
        self._replies_iter = None

    async def feed_message(self, message: Message) -> None:
        """Classify, dispatch (or refuse), and enqueue exactly one reply.

        Trust classification (:func:`colleague.resident.trust.classify_request`)
        happens FIRST, before any work is dispatched — a refused request never
        reaches ``execute_work`` at all.

        A ``relay <task-id>: <text>`` line (t8, see the module docstring's
        "Trust-gated relay" section) is checked next — BEFORE the normal
        attach/dispatch pipeline — and takes over the ENTIRE handling of this
        message via :meth:`_handle_relay`: no ``execute_work`` call, no new
        artifact, just a trust-gated side-channel action against an
        already-running flight.

        Otherwise, the allowed request's ``attach:`` candidates are resolved
        by :meth:`_resolve_attachments` (t12: parses, trust-checks, and
        validates each one — see that method's docstring), then the work item
        is run and replied via :meth:`_dispatch_and_reply` (which also owns
        the expected-vs-unexpected failure split described below).

        An expected work-item failure (:class:`~colleague.cli._errors.CliError`
        — e.g. an unreachable engine) is caught and turned into an error reply.
        Any OTHER exception propagates: the Supervisor's pump catches it and
        records it via ``failure()`` — a genuine infrastructure failure is
        never silently swallowed.
        """
        sender = getattr(message, "sender", "") or ""
        target = getattr(message, "target", "") or self._default_target
        metadata = dict(getattr(message, "metadata", {}) or {})

        decision = classify_request(
            sender=sender,
            metadata=metadata,
            operator_identity=self._operator_identity,
        )

        if decision.outcome == "refuse":
            await self._reply_queue.put(
                Message(
                    sender=self._agent_nick,
                    target=target,
                    body=decision.reason,
                    kind="message",
                    metadata={"phase": "refused"},
                )
            )
            return

        raw_body = getattr(message, "body", "") or ""

        relay = _extract_relay_line(raw_body)
        if relay is not None:
            relay_task_id, relay_text = relay
            await self._handle_relay(
                sender=sender,
                target=target,
                decision=decision,
                task_id=relay_task_id,
                relay_text=relay_text,
            )
            return

        body, attachments, attachment_notes = self._resolve_attachments(sender, raw_body)

        # Cortex/senses (t9): with a senses model resolved, perceive the inbound
        # message through senses INTAKE first (→ a ContextPacket on the task, so the
        # loop records mode=split), then shape the reply via SPEAK-BACK below. The
        # c19 trust model is UNCHANGED — intake runs regardless of the request's
        # trust tier (senses is tools-off; write authorization is decision.role's
        # job, untouched here). A degraded intake attaches nothing and the raw
        # message proceeds — the run never fails (senses unresolved = byte-identical).
        senses_active = self._config.senses is not None
        packet, intake_record = None, None
        if senses_active:
            loop = asyncio.get_running_loop()
            packet, intake_record = await loop.run_in_executor(None, self._senses_intake, body)

        task = Task.new(
            self._repo_path,
            body,
            engine=self._engine_name,
            attachments=attachments or None,
        )
        if packet is not None:
            task.context_packet = packet
        req_config = _dc_replace(self._config, role=decision.role)

        await self._dispatch_and_reply(
            task,
            req_config,
            target=target,
            role=decision.role,
            attachment_notes=attachment_notes,
            senses_active=senses_active,
            intake_record=intake_record,
        )

    def _resolve_attachments(
        self, sender: str, raw_body: str
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        """Parse + trust-check + validate a message body's ``attach:`` lines (t12).

        Returns ``(cleaned_body, attachments, attachment_notes)``: the body
        with every ``attach:`` line removed, the accepted attachments in
        ``colleague.media.validate_attachment``'s ``{"path", "media_type"}``
        shape, and a list of human-readable notes for anything dropped (the
        attachment cap, a c19 trust refusal, or a validation failure) — never
        a crash, and the caller proceeds under the SAME role regardless of
        how many attachments were refused. See the module docstring's "Media
        references" section for the full contract.
        """
        body, attach_candidates, dropped = _extract_attach_lines(raw_body)

        attachments: list[dict[str, Any]] = []
        attachment_notes: list[str] = []
        if dropped:
            attachment_notes.append(
                f"ignored {dropped} extra attach: line(s) beyond the "
                f"{_MAX_ATTACHMENTS}-attachment cap"
            )
        for candidate in attach_candidates:
            path_decision = check_attachment_path(
                candidate,
                repo_path=self._repo_path,
                sender=sender,
                operator_identity=self._operator_identity,
            )
            if not path_decision.allowed:
                attachment_notes.append(path_decision.reason)
                continue
            try:
                attachments.append(validate_attachment(candidate))
            except ValueError as exc:
                attachment_notes.append(f"attach: {candidate!r} failed validation — {exc}")

        return body, attachments, attachment_notes

    # ── trust-gated relay (t8) ───────────────────────────────────────────────

    async def _handle_relay(
        self,
        *,
        sender: str,
        target: str,
        decision,
        task_id: str,
        relay_text: str,
    ) -> None:
        """Trust-gated relay dispatch — see the module docstring's "Trust-gated
        relay" section for the full contract; this docstring covers only the
        implementation shape.

        *task_id* is validated with :func:`~colleague.flight.is_safe_task_id`
        FIRST, for every requester (operator included) — an unsafe id is
        refused before anything else runs. The relay text is then routed
        through the senses talk lane (:meth:`_senses_talk`) for a
        conversational answer when a senses model is resolved (``None``
        otherwise). ``is_operator`` reuses the EXACT SAME verdict
        :meth:`feed_message` already computed via
        :func:`~colleague.resident.trust.classify_request` — no second trust
        check. :func:`~colleague.flight.append_guidance` has exactly ONE call
        site in this module, and it sits inside the ``if is_operator:``
        branch below; the ``else`` branch structurally cannot reach it.
        """
        if not is_safe_task_id(task_id):
            await self._reply_queue.put(
                Message(
                    sender=self._agent_nick,
                    target=target,
                    body=f"relay refused: {task_id!r} is not a valid flight id",
                    kind="message",
                    metadata={"relay": False, "reason": "unsafe_task_id"},
                )
            )
            return

        loop = asyncio.get_running_loop()
        talk = await loop.run_in_executor(None, self._senses_talk, relay_text, task_id)

        # The SAME verdict feed_message already computed -- ALLOW_WRITE is
        # returned by classify_request ONLY for the confirmed operator identity
        # (see colleague/resident/trust.py); no second trust-decision path.
        is_operator = decision.outcome == ALLOW_WRITE
        if is_operator:
            # The ONE call site for append_guidance in this entire module.
            try:
                append_guidance(self._repo_path, task_id, relay_text)
                label = f"-> cortex({task_id}): {relay_text}"
                body = f"{label}\n{talk['answer']}" if talk is not None else label
                meta: dict[str, Any] = {"relay": True, "relayed_to": task_id, "role": decision.role}
            except (OSError, ValueError) as exc:
                # Degrade-never-crash: a failed control-file write must not escape the
                # resident message handler. Reply honestly with relay=False so a consumer
                # never assumes the guidance was injected.
                note = f"relay failed ({type(exc).__name__}) — could not write flight control file"
                body = f"{note}\n{talk['answer']}" if talk is not None else note
                meta = {
                    "relay": False,
                    "relayed_to": task_id,
                    "role": decision.role,
                    "relay_failed": True,
                }
        else:
            if talk is not None:
                body = talk["answer"]
            else:
                body = (
                    f"{sender!r} is not the operator — I can't relay guidance into "
                    f"{task_id}; ask the operator, or request a read-only "
                    "explore/review instead."
                )
            meta = {"relay": False, "relay_attempted_task_id": task_id, "role": decision.role}

        await self._reply_queue.put(
            Message(
                sender=self._agent_nick, target=target, body=body, kind="message", metadata=meta
            )
        )

    def _senses_talk(self, message: str, task_id: str):
        """Run ONE senses talk-lane turn grounded in *task_id*'s live flight feed.

        Returns :func:`colleague.senses.run_senses_talk`'s advisory dict, or
        ``None`` when no senses model is resolved at all (the SAME
        None-signals-unarmed contract :meth:`_senses_engine` already uses).
        Sync (executor-bound, mirrors :meth:`_senses_intake`).
        """
        pair = self._senses_engine()
        if pair is None:
            return None
        senses_config, engine = pair
        feed_tail = self._read_feed_tail(task_id)
        return run_senses_talk(
            message,
            feed_tail=feed_tail,
            packet=None,
            task_state=None,
            senses_config=senses_config,
            make_complete=engine.make_complete,
            make_count_tokens=engine.make_count_tokens(senses_config),
        )

    def _read_feed_tail(self, task_id: str, max_chars: int = 4000) -> str:
        """Best-effort tail of *task_id*'s live flight feed (raw JSONL text).

        Reuses :func:`colleague.flight.feed_path` — no new flight.py helper.
        Returns ``""`` when the flight has no feed file yet (an unaddressed or
        not-yet-armed task id) or on any read failure; never raises.
        """
        try:
            path = feed_path(self._repo_path, task_id)
            if not path.is_file():
                return ""
            return path.read_text(encoding="utf-8")[-max_chars:]
        except (OSError, ValueError):
            return ""

    # ── cortex/senses split (t9) ─────────────────────────────────────────────

    def _senses_engine(self):
        """Return ``(senses_config, engine)`` for a senses call, or ``None`` — the
        SAME seam intake and speak-back share. ``None`` when no senses model is
        resolved (byte-identical) or the engine cannot be loaded (proceed raw).
        Sync (runs in the executor); role-independent (senses is tools-off)."""
        senses_config = senses_engine_config(self._config)
        if senses_config is None:
            return None
        try:
            engine = registry.load(self._engine_name)
        except Exception:  # noqa: BLE001 - an unloadable engine → proceed cortex-only
            return None
        return senses_config, engine

    def _senses_intake(self, text: str):
        """Perceive *text* into a ContextPacket (+ record). ``(None, None)`` when
        no senses engine; ``(None, degraded_record)`` when intake degrades — the
        caller then proceeds with the raw text. Sync (executor)."""
        pair = self._senses_engine()
        if pair is None:
            return None, None
        senses_config, engine = pair
        return run_senses_intake(text, senses_config, engine)

    def _speakback_and_finalize(self, result, intake_record):
        """Shape the reply via speak-back AND fold the session-side intake +
        speak-back records onto ``result.senses``, re-saving the artifact.

        Returns the shaped display string (or ``None`` to fall back to the raw
        summary). ``result.summary`` is never mutated — the artifact keeps the raw
        cortex summary; only the mesh reply body is shaped. Sync (executor)."""
        shaped, speakback_record = None, None
        pair = self._senses_engine()
        if pair is not None:
            senses_config, engine = pair
            shaped, speakback_record = run_senses_speakback(result.summary, senses_config, engine)
        if result.senses is None:
            result.senses = SensesBlock(mode="split", packet=None, records=[])
        pre = [intake_record] if intake_record is not None else []
        post = [speakback_record] if speakback_record is not None else []
        result.senses.records = pre + list(result.senses.records) + post
        try:
            _write_artifact(result, artifact_dir(self._repo_path))
        except Exception:  # nosec B110 - a re-save failure must never fail the reply
            pass
        return shaped

    # ── audio reply link (t8) ────────────────────────────────────────────────

    def _synthesize_reply_audio(self, text: str, artifact_path: Path) -> Optional[str]:
        """Synthesize *text* to a wav beside *artifact_path*; return its path
        RELATIVE TO THE REPO ROOT, or ``None`` when there is nothing to attach.

        Returns ``None`` (never calling :func:`colleague.voice.synthesize` at
        all) when ``config.voice`` is unarmed or carries no ``tts_model`` — the
        additive-only contract. When armed, ``synthesize`` itself is
        degrade-never-raise (see :mod:`colleague.voice`); its own ``None``
        (e.g. the reference rig's speech proxy 502ing) propagates straight
        through here, so a degraded synth leaves the reply byte-identical to a
        no-tts reply — no line, no exception. Sync (executor-bound).
        """
        voice_config = self._config.voice
        if voice_config is None or not voice_config.tts_model:
            return None
        wav_path = artifact_path.parent / f"{artifact_path.stem}.wav"
        written = synthesize(
            text,
            tts_model=voice_config.tts_model,
            base_url=voice_config.base_url,
            out_path=wav_path,
            api_key=voice_config.api_key,
        )
        if written is None:
            return None
        return os.path.relpath(str(written), start=self._repo_path)

    async def _dispatch_and_reply(
        self,
        task: Task,
        req_config: "EngineConfig",
        *,
        target: str,
        role: Optional[str],
        attachment_notes: list[str],
        senses_active: bool = False,
        intake_record=None,
    ) -> None:
        """Run one work item via :meth:`_dispatch` and enqueue exactly one reply.

        A caught :class:`~colleague.cli._errors.CliError` becomes an error
        reply (``status: error``); any OTHER exception propagates unchanged so
        the Supervisor's pump records it via ``failure()`` (see the
        :meth:`feed_message` / module docstring). A successful dispatch's
        reply carries the ``TaskResult`` summary + artifact pointer. Either
        reply carries ``attachment_notes`` when non-empty.
        """
        loop = asyncio.get_running_loop()
        try:
            result, artifact_path = await loop.run_in_executor(
                None, self._dispatch, task, req_config
            )
        except Exception as exc:  # noqa: BLE001 - narrowed to CliError below
            from colleague.cli._errors import CliError

            if not isinstance(exc, CliError):
                raise  # a genuine infra failure -> surfaced via Supervisor.failure()
            reply_meta: dict[str, Any] = {"status": "error", "role": role}
            partial = exc.result
            if partial is not None:
                reply_meta["task_id"] = partial.task_id
            if attachment_notes:
                reply_meta["attachment_notes"] = attachment_notes
            await self._reply_queue.put(
                Message(
                    sender=self._agent_nick,
                    target=target,
                    body=f"work item failed: {exc.message}",
                    kind="message",
                    metadata=reply_meta,
                )
            )
            return

        # Cortex/senses (t9): shape the mesh reply via speak-back + fold the
        # intake/speak-back records onto TaskResult.senses (re-saving the
        # artifact). The reply body is the shaped text; the artifact keeps the raw
        # cortex summary. A strict no-op when senses is unresolved (byte-identical).
        reply_body = result.summary or ""
        if senses_active:
            shaped = await loop.run_in_executor(
                None, self._speakback_and_finalize, result, intake_record
            )
            if shaped:
                reply_body = shaped

        # Audio reply link (t8): additive-only. With no tts_model armed this is a
        # strict no-op (never even calls synthesize) -- see the module docstring's
        # "Audio reply link" section.
        audio_rel = await loop.run_in_executor(
            None, self._synthesize_reply_audio, reply_body, artifact_path
        )
        if audio_rel is not None:
            reply_body = f"{reply_body}\naudio: {audio_rel}"

        reply_meta: dict[str, Any] = {
            "task_id": result.task_id,
            "status": result.status,
            "artifact": str(artifact_path),
            "role": role,
        }
        if attachment_notes:
            reply_meta["attachment_notes"] = attachment_notes
        await self._reply_queue.put(
            Message(
                sender=self._agent_nick,
                target=target,
                body=reply_body,
                kind="message",
                metadata=reply_meta,
            )
        )

    def _dispatch(self, task: Task, config: "EngineConfig") -> tuple[Any, Path]:
        """Run one full colleague work item to completion (blocking; executor-bound)."""
        from colleague.cli._commands.work import execute_work

        return execute_work(
            repo=Path(self._repo_path),
            engine_name=self._engine_name,
            task=task,
            open_pr=self._open_pr,
            base=self._base,
            config=config,
            allow_dirty=self._allow_dirty,
            isolate=True,
        )

    def replies(self) -> AsyncIterator[Message]:
        """Return the single async iterator yielding reply Messages until :meth:`stop`.

        The SAME iterator is returned on every call within a session
        (memoised) — the reply stream has exactly one consumer (the
        supervisor's outbound pump), mirroring
        :class:`~colleague.resident.harness.ColleagueHarness`.
        """
        if self._replies_iter is None:
            self._replies_iter = self._replies_gen()
        return self._replies_iter

    async def _replies_gen(self) -> AsyncIterator[Message]:
        while True:
            item = await self._reply_queue.get()
            if item is _STOP:
                return
            yield item

    async def stop(self) -> None:
        """End the reply stream (insert the stop sentinel)."""
        await self._reply_queue.put(_STOP)


def build_appserver_supervisor(
    *,
    transport: "Transport",
    repo_path: str,
    config: "EngineConfig",
    engine_name: str | None = None,
    agent_nick: str = "colleague",
    operator_identity: str | None = None,
    default_target: str = "",
    open_pr: bool = False,
    base: str = "main",
    allow_dirty: bool = True,
    drain_timeout: float = Supervisor.DEFAULT_DRAIN_TIMEOUT,
) -> Supervisor:
    """Wire *transport* to an :class:`AppserverHarness` through agent-lifecycle's Supervisor.

    Unlike :func:`colleague.resident.supervisor.build_resident_supervisor`
    (which is hardcoded to the IRC wire via an injected connection), this
    factory is fully transport-agnostic — the caller supplies ANY object
    satisfying :class:`agent_lifecycle.runtime.transport.Transport`, matching
    the upstream "library embed" consumption doc's framing exactly: "colleague
    supplies its own Harness ... and its own Transport ... and wires them
    together with the in-process Supervisor shipped here."

    Returns an **unstarted** Supervisor; the caller owns its ``start()`` /
    ``stop()`` lifecycle (mirroring ``build_resident_supervisor``).
    """
    harness = AppserverHarness(
        repo_path,
        config,
        engine_name=engine_name,
        agent_nick=agent_nick,
        operator_identity=operator_identity,
        default_target=default_target,
        open_pr=open_pr,
        base=base,
        allow_dirty=allow_dirty,
    )
    return Supervisor(transport, harness, drain_timeout=drain_timeout)


__all__ = ["AppserverHarness", "build_appserver_supervisor"]

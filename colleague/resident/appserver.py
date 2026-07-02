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
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from agent_lifecycle.runtime.message import Message
from agent_lifecycle.runtime.supervisor import Supervisor

from colleague.contract import Task
from colleague.media import validate_attachment
from colleague.resident.trust import check_attachment_path, classify_request

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
        reaches ``execute_work`` at all. An allowed request's ``attach:``
        candidates are resolved by :meth:`_resolve_attachments` (t12: parses,
        trust-checks, and validates each one — see that method's docstring),
        then the work item is run and replied via :meth:`_dispatch_and_reply`
        (which also owns the expected-vs-unexpected failure split described
        below).

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
        body, attachments, attachment_notes = self._resolve_attachments(sender, raw_body)

        task = Task.new(
            self._repo_path,
            body,
            engine=self._engine_name,
            attachments=attachments or None,
        )
        req_config = _dc_replace(self._config, role=decision.role)

        await self._dispatch_and_reply(
            task,
            req_config,
            target=target,
            role=decision.role,
            attachment_notes=attachment_notes,
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

    async def _dispatch_and_reply(
        self,
        task: Task,
        req_config: "EngineConfig",
        *,
        target: str,
        role: Optional[str],
        attachment_notes: list[str],
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
                body=result.summary or "",
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

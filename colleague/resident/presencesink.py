"""colleague.resident.presencesink — the appserver's proactive-update sink.

Extracted verbatim from :mod:`colleague.resident.appserver` (file-length
discipline only — no behaviour change). It stays under ``colleague/resident/``
because ``tests/test_boundary.py`` exempts exactly that prefix from the
repo-wide ``import asyncio`` ban, and this module is part of the same async
resident seam.

Presence-default-everywhere (t11 / c10 / h17): a ``CockpitProgressSink``-shaped
duck that ``execute_work`` drives at each progress boundary while an OPERATOR's
work item runs.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any, Callable, Optional

from colleague.contract import ContextPacket, SensesRecord
from colleague.presence import should_update
from colleague.senses import UPDATE_POINT, run_senses_update


class _ResidentPresenceSink:
    """Cadence-gated proactive-update progress sink for an OPERATOR's resident run.

    Presence-default-everywhere (t11 / c10 / h17). A ``CockpitProgressSink``-shaped
    duck (``__call__(step_index, tool, target, ok)`` + ``close()``) that
    ``execute_work`` drives at each progress boundary WHILE the operator's work
    item runs. When the cadence fires (and the per-run cap is not yet hit), it
    narrates ONE senses update grounded strictly in the accumulated progress
    lines (:func:`colleague.senses.run_senses_update`) and emits it via the
    injected *emit* callback — the caller wires *emit* to a threadsafe
    reply-to-origin mesh enqueue, so the operator is kept posted where they asked.

    Cap-bounded by the update cadence (``COLLEAGUE_SENSES_UPDATE_CAP``) so senses
    can never flood a mesh channel (h17); hitting the cap is recorded ONCE, never
    silent (h4). Built ONLY for the operator (never a non-operator — the c19
    boundary): the appserver constructs it inside the ``ALLOW_WRITE`` branch, so a
    non-operator request never gets one. Every fired update lands on
    ``records``/``chat`` for the artifact fold. Never raises — a narration failure
    can never disturb the cortex work item (the #206 invariant: a beat never
    advances the real step count)."""

    def __init__(
        self,
        *,
        senses_config: Any,
        engine: Any,
        cadence: Any,
        emit: "Callable[[str], None]",
        packet: "Optional[ContextPacket]" = None,
        history: "Optional[list[dict[str, str]]]" = None,
    ) -> None:
        self._senses_config = senses_config
        self._engine = engine
        self._cadence = cadence
        self._emit = emit
        self._packet = packet
        self._history = history
        self._feed_lines: list[str] = []
        self._updates_sent = 0
        self._last_update_step = 0
        self._last_phase = ""
        self._cap_recorded = False
        self.records: list[SensesRecord] = []
        self.chat: list[dict[str, Any]] = []

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        try:
            self._observe(step_index, tool, target, ok)
        except Exception:  # noqa: BLE001 — narration must never disturb the run
            return

    def _observe(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        phase_changed = False
        if tool:
            line = f"step {step_index}: {tool} {target}".strip()
            if not ok:
                # Ground a FAILED step in the narration too — senses can only
                # narrate a failure honestly if the feed actually says one
                # happened (h4: never silent).
                line = f"{line} [failed]"
            self._feed_lines.append(line)
        else:
            # A phase notice (#206): its target is the phase label; only a CHANGE
            # counts toward a cadence fire.
            phase_changed = target != self._last_phase
            self._last_phase = target

        fire, reason = should_update(
            self._cadence,
            step_count=step_index,
            last_update_step=self._last_update_step,
            phase_changed=phase_changed,
            updates_sent=self._updates_sent,
        )
        if reason == "cap":
            if not self._cap_recorded:
                self._cap_recorded = True
                self.chat.append({"kind": "update", "capped": True, "at": time.time()})
            return
        if not fire:
            return

        # A fired attempt consumes senses budget whether or not it produces text
        # — count it toward the cap either way (honest accounting, h4).
        self._updates_sent += 1
        self._last_update_step = step_index
        record = run_senses_update(
            list(self._feed_lines[-40:]),
            self._packet,
            self._senses_config,
            self._engine,
            history=self._history,
        )
        if record is None:
            return
        self.records.append(
            SensesRecord(
                point=UPDATE_POINT,
                latency=record["latency"],
                tokens=record.get("tokens"),
                degraded=record["degraded"],
            )
        )
        text = record.get("update")
        if text:
            self.chat.append(
                {
                    "kind": "update",
                    "text": text,
                    "latency": record["latency"],
                    "degraded": record["degraded"],
                    "at": time.time(),
                }
            )
            with contextlib.suppress(Exception):
                self._emit(text)

    def close(self) -> None:
        """Satisfy the CockpitProgressSink duck — nothing to tear down."""
        return None


__all__ = ["_ResidentPresenceSink"]

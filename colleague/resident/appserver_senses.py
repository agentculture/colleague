"""colleague.resident.appserver_senses — the appserver's senses/voice lane.

Extracted verbatim from :mod:`colleague.resident.appserver` (file-length
discipline only — no behaviour change): the six sync, executor-bound helpers
that make up the appserver's cortex/senses split (t9), its talk-lane grounding
(t8) and its audio reply link (t8). They are mixed into
:class:`~colleague.resident.appserver.AppserverHarness` rather than living as
free functions so the ``self._config`` / ``self._engine_name`` /
``self._repo_path`` seam they already shared stays exactly as it was.

Sits under ``colleague/resident/`` because ``tests/test_boundary.py`` exempts
exactly that prefix from the repo-wide ``import asyncio`` ban and this module is
part of the same resident seam.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from colleague import registry
from colleague.artifact import artifact_dir
from colleague.artifact import write as _write_artifact
from colleague.contract import SensesBlock
from colleague.flight import feed_path
from colleague.senses import (
    run_senses_intake,
    run_senses_speakback,
    run_senses_talk,
    senses_engine_config,
)
from colleague.voice import synthesize


class _SensesLaneMixin:
    """The appserver's senses + audio-reply helpers (see the module docstring)."""

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

    def _speakback_and_finalize(self, result, intake_record, ack_chat=None, presence_sink=None):
        """Shape the reply via speak-back AND fold the session-side intake +
        speak-back records (+ the t11 operator-lane presence beats) onto
        ``result.senses``, re-saving the artifact.

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
        # Presence-default-everywhere (t11): fold the operator-lane beats — the
        # ack (+ clarify) chat entries and the cadence-gated proactive-update
        # records/chat — onto the artifact so the whole reply-to-origin exchange
        # is reconstructable (h6). The proactive-update records slot chronologically
        # (during the run, so BEFORE the terminal speak-back); a no-op ([]/None)
        # for a non-operator or an unarmed run → byte-identical.
        update_records = list(presence_sink.records) if presence_sink is not None else []
        result.senses.records = pre + list(result.senses.records) + update_records + post
        chat_add = list(ack_chat or [])
        if presence_sink is not None:
            chat_add += list(presence_sink.chat)
        if chat_add:
            result.senses.chat = list(result.senses.chat) + chat_add
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
            base_url=voice_config.tts_base_url,
            out_path=wav_path,
            api_key=voice_config.api_key,
        )
        if written is None:
            return None
        return os.path.relpath(str(written), start=self._repo_path)


__all__ = ["_SensesLaneMixin"]

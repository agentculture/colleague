"""livecheck_checks — pure classifiers + small evidence fixtures for livecheck.

Split out of :mod:`colleague.livecheck` (hard-1000-line-file-limit, t8): the
media/latency/presence/streaming/middle-manager classifiers and their tiny
stdlib-only fixture builders (a hand-encoded PNG, a synthetic WAV) live here.
:mod:`colleague.livecheck` re-exports every name so existing importers and
monkeypatch targets resolve unchanged.
"""

from __future__ import annotations

import io
import statistics
import struct
import tempfile
import wave
import zlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from colleague.config import EngineConfig


@dataclass
class ProofResult:
    """Result of running a single live-proof test file."""

    file: str
    status: str  # "passed" | "failed" | "skipped"
    detail: str = ""


def _make_red_png(size: int = 16) -> bytes:
    """Hand-encode a minimal, valid solid-red PNG (stdlib ``zlib``/``struct`` only).

    No third-party imaging library — the whole media arc holds the one
    sanctioned base dep (agentfront) line, so the livecheck fixture is built
    the same way the runtime is: raw PNG chunks (signature, IHDR, IDAT,
    IEND), DEFLATE via the stdlib ``zlib`` module. ``size`` defaults to a
    small but real image (16x16, truecolor, no alpha) — small enough to
    generate instantly, large enough that a live vision model sees a real
    tile rather than a degenerate 1x1 input.
    """
    width = height = size

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolor RGB
    row = b"\x00" + b"\xff\x00\x00" * width  # filter byte (none) + solid-red RGB pixels
    idat = zlib.compress(row * height)
    return signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _make_test_wav(duration_seconds: float = 0.5, framerate: int = 8000) -> bytes:
    """Generate a tiny valid mono WAV clip (stdlib ``wave`` module only)."""
    frame_count = int(duration_seconds * framerate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(framerate)
        handle.writeframes(b"\x00\x00" * frame_count)
    return buf.getvalue()


def _attachment_status(media_record: dict[str, Any] | None) -> str:
    """Extract the first attachment's delivery status.

    Mirrors ``TaskResult.media``'s vocabulary (decision c25): ``delivered``,
    ``dropped``, or ``unknown`` (no usage reported) — plus ``missing`` here
    for a run that recorded no media block at all, so a livecheck classifier
    always has a status to reason about instead of a bare ``None``.
    """
    if not media_record:
        return "missing"
    attachments = media_record.get("attachments") or []
    if not attachments:
        return "missing"
    return str(attachments[0].get("status", "missing"))


def classify_media_image_check(media_record: dict[str, Any] | None, answer: str) -> tuple[str, str]:
    """Classify the image livecheck (t13): PASS only on delivered AND red-named.

    A 200 response is never trusted alone — an attachment that is
    dropped/unknown/missing FAILS the check regardless of what the answer
    text says, and a delivered attachment whose answer doesn't name "red"
    also fails: the check proves *comprehension*, not merely wire delivery
    (spec honesty: "the image livecheck asserts the ANSWER content (red),
    not merely a 200 response").
    """
    status = _attachment_status(media_record)
    names_red = "red" in (answer or "").lower()
    if status == "delivered" and names_red:
        return "passed", "image delivered and the answer names red"
    if status != "delivered":
        return (
            "failed",
            f"attachment not delivered (status={status!r}) — a 200 response is never trusted alone",
        )
    return (
        "failed",
        f"image delivered but the answer did not name red: {(answer or '').strip()[:120]!r}",
    )


# Live rig fact (probed 2026-07-02, docs/live-testing.md): the reference
# endpoint accepts ``input_audio`` with a 200 OK but ~0 prompt tokens — a
# SILENT DROP, not a rejection. Named here so the classifier + CLI/docs agree.
_AUDIO_DROP_REASON = (
    "rig silently drops input_audio (200 OK, ~0 prompt tokens contributed "
    "— see docs/live-testing.md)"
)


def classify_media_audio_check(media_record: dict[str, Any] | None, answer: str) -> tuple[str, str]:
    """Classify the audio livecheck (t13): honest SKIP while the rig drops input_audio.

    Never reports pass while the drop persists — a ``dropped`` (or
    otherwise non-delivered) attachment always SKIPs, naming the silent-drop
    reason. Written so the classification flips automatically the day the
    rig actually consumes ``input_audio``: a ``delivered`` attachment is then
    graded like any other live proof (pass on a real answer, fail on none)
    instead of an unconditional skip.
    """
    status = _attachment_status(media_record)
    if status == "delivered":
        if (answer or "").strip():
            return (
                "passed",
                "audio delivered and the model answered — the rig now consumes input_audio",
            )
        return "failed", "audio delivered but the model produced no answer"
    if status == "dropped":
        return "skipped", _AUDIO_DROP_REASON
    return "skipped", f"attachment status {status!r} — cannot confirm the rig consumed the audio"


# lobes-cli#89 (0.38.0 — colleague#292/291 S1): stt/tts readiness is now
# LIVE-PROBED via the gateway's realtime bridge (lobes.py ready_kind +
# voice.py's bounded 503+Retry-After retry); the round-trip proof checks
# readiness FIRST, SKIPping honestly, never the old bare-"502" workaround.
_VOICE_LANE_NOT_READY_REASON = (
    "gateway reports the role not ready (live-probed via the realtime bridge, "
    "lobes-cli#89) — graded from evidence, never a fabricated pass"
)


def classify_senses_latency_check(
    p50: float | None,
    p95: float | None,
    *,
    p50_target: float = 3.0,
    p95_target: float = 8.0,
) -> tuple[str, str]:
    """Grade the concurrent-senses-latency proof (t10 / spec h9): a senses answer
    issued WHILE cortex is mid-completion must meet the responsiveness target
    (p50 < 3s, p95 < 8s; probe baseline 1.1s alone / 2.3s p50 under cortex load on
    the shared GPU, 2026-07-03).

    A missing measurement SKIPs (never a fabricated pass); a real measurement
    PASSes only when BOTH percentiles clear their target, else FAILs naming the
    breach — the 'answers in seconds' claim is graded from wall-clock evidence.
    """
    if p50 is None or p95 is None:
        return "skipped", "no concurrent-latency measurement recorded"
    if p50 < p50_target and p95 < p95_target:
        return (
            "passed",
            f"senses answered during cortex load at p50={p50:.2f}s / p95={p95:.2f}s "
            f"(target p50<{p50_target:.0f}s / p95<{p95_target:.0f}s)",
        )
    return (
        "failed",
        f"latency breached target: p50={p50:.2f}s / p95={p95:.2f}s "
        f"(target p50<{p50_target:.0f}s / p95<{p95_target:.0f}s)",
    )


def classify_injection_reached_check(in_feed: bool, in_artifact: bool) -> tuple[str, str]:
    """Grade the injection-awareness proof (t10 / spec h8): an APPLIED operator
    injection must be reconstructable from BOTH the flight feed AND the artifact
    record.

    PASS only when the injection is present on both surfaces (the awareness
    invariant); FAIL when either is missing (a silent injection). Never a
    fabricated pass.
    """
    if in_feed and in_artifact:
        return "passed", "injection present in BOTH the flight feed and the artifact record"
    missing = [
        name for name, present in (("feed", in_feed), ("artifact", in_artifact)) if not present
    ]
    return "failed", f"injection not reconstructable — missing from: {', '.join(missing)}"


def classify_flight_reachable_check(
    feed_reachable: bool, survived_cleanup: bool
) -> tuple[str, str]:
    """Grade the #310 flight-reachability proof: a backgrounded/watched
    ``colleague work`` run's flight plane must live in the OPERATOR repo — reachable
    by ``colleague talk`` / ``colleague flight`` — and SURVIVE worktree cleanup.

    PASS only when BOTH hold (the plane the loop writes is the plane the operator
    reads, and it outlives the throwaway worktree); FAIL otherwise (the pre-#310
    bug, where the plane was armed inside the iso worktree and destroyed with it).
    Never a fabricated pass.
    """
    if feed_reachable and survived_cleanup:
        return "passed", "flight plane reachable in the operator repo and survived worktree cleanup"
    missing = [
        name
        for name, ok in (
            ("reachable-in-operator-repo", feed_reachable),
            ("survived-cleanup", survived_cleanup),
        )
        if not ok
    ]
    return "failed", f"flight plane not pilotable — failed: {', '.join(missing)}"


def classify_flight_liveness_check(has_liveness: bool, status_answer: str) -> tuple[str, str]:
    """Grade the #308 liveness proof: during a long first completion the flight feed
    must carry a run-start/heartbeat marker so ``colleague talk`` / senses can surface
    a REAL status instead of "I don't know".

    SKIPs (never FAILs) when the run produced no liveness marker to grade yet (a
    fast turn, or the plane was never armed) — the honest no-measurement stance.
    A recorded status that still says "I don't know" (no ground) FAILs; a grounded
    status PASSes.
    """
    if not has_liveness:
        return "skipped", "no run-start/heartbeat marker recorded yet — nothing to grade"
    if "i don't know" in (status_answer or "").strip().lower():
        return "failed", "feed had a liveness marker but the status answer was still 'I don't know'"
    return "passed", "the flight feed carried a liveness signal and the status answer was grounded"


def classify_honest_incompletion_check(
    status: str, incompletion: dict | None, *, expected_incomplete: bool
) -> tuple[str, str]:
    """Grade the honest-incompletion proof (#313): a run that produced no
    deliverable must come back non-ok carrying an ``incompletion`` record with a
    ``reason`` AND a ``recommendation``; a delivering run must carry NONE.

    PASS when the artifact matches the expectation (no-deliverable <-> non-ok with
    a full incompletion record; delivered <-> ok with no incompletion). SKIP when
    there is no status to grade. FAIL on a mismatch — a silent incomplete (non-ok
    with no record), a wrongly-flagged delivering run, or a run that was expected
    to stall but reported ok. Never a fabricated pass.
    """
    if not status:
        return "skipped", "no run status recorded — nothing to grade"
    is_incomplete = status != "ok"
    record = incompletion if isinstance(incompletion, dict) else {}
    has_record = bool(record.get("reason")) and bool(record.get("recommendation"))
    if expected_incomplete:
        if is_incomplete and has_record:
            return (
                "passed",
                f"no-deliverable run reported {status!r} with "
                f"incompletion.reason={record.get('reason')!r}",
            )
        if is_incomplete:
            return "failed", "run was non-ok but carried no incompletion {reason, recommendation}"
        return (
            "failed",
            f"run expected to be incomplete but reported {status!r} with no incompletion",
        )
    if not is_incomplete and not incompletion:
        return "passed", "delivering run reported ok and carried no incompletion (byte-identical)"
    return (
        "failed",
        f"delivering run wrongly flagged: status={status!r}, incompletion={incompletion!r}",
    )


def classify_voice_lane_check(kind: str, outcome: str) -> tuple[str, str]:
    """Grade an stt/tts voice-lane live proof (t10) from its recorded outcome.

    Since lobes-cli#89 (0.38.0), stt/tts ``ready`` is LIVE-PROBED via the
    gateway's realtime bridge (a warming backend answers 503+Retry-After,
    never a bare 502 — ``colleague/voice.py`` bounds one retry on that). The
    round-trip proof checks readiness FIRST: ``outcome`` is ``"ok"`` (a
    transcript/wav, possibly after one warming retry), ``"not_ready"`` (the
    readiness probe reports the role down — the ONLY SKIP case, honestly
    naming the rig state), or anything else (a genuine FAIL — no longer
    silently SKIPped the way the old bare-502 workaround did).
    """
    if outcome == "ok":
        return "passed", f"{kind} lane round-tripped audio through the gateway"
    if outcome == "not_ready":
        return "skipped", f"{kind}: {_VOICE_LANE_NOT_READY_REASON}"
    return "failed", f"{kind} lane failed unexpectedly: {outcome!r}"


# ---------------------------------------------------------------------------
# Presence-beat narration proof (presence-default-everywhere arc, t12, c17):
# does a rendered ack/update/reply beat produce a companion .wav? Same
# evidence discipline as the media/voice checks — never a fabricated pass.
# Reuses ``colleague.voice.synthesize``'s degrade-never-raise contract (a
# 502/no-audio body writes no file), so "no wav" and "tts proxy down" are
# indistinguishable here (same honest limit as the audio-drop case above).
# ---------------------------------------------------------------------------


def classify_presence_narration_check(narrated: bool) -> tuple[str, str]:
    """Grade the presence-narration live proof (t12) from whether a real wav landed.

    PASSes only when a rendered presence beat produced an actual, non-empty
    ``.wav`` file; SKIPs (never FAILs) when it did not — the reference rig's
    tts proxy currently 502s (colleague#292/291, lobes-cli#89/#92), and a
    failed synth is indistinguishable here from any other "no audio" outcome
    (:func:`colleague.voice.synthesize` degrades both to the same ``None``).
    Never a fabricated pass.
    """
    if narrated:
        return "passed", "a rendered presence beat was narrated to a real .wav file"
    return (
        "skipped",
        f"presence narration produced no audio — {_VOICE_LANE_NOT_READY_REASON}",
    )


def run_presence_narration_check(repo: str | Path, *, model: str | None = None) -> ProofResult:
    """Live proof (t12): wire a rendered presence beat through to a real wav.

    Resolves ``config.voice`` (optionally overridden with an explicit
    ``model`` as the tts model) and, when a ``tts_model`` is present, drives
    one :func:`colleague.voice.build_presence_narrator` call with a short
    presence-beat line into a throwaway directory. SKIPs honestly when voice
    isn't configured, or synthesis degrades (see
    :func:`classify_presence_narration_check`).
    """
    from colleague.attribution import acting_seat_label
    from colleague.voice import build_presence_narrator

    repo_path = str(repo)
    config = EngineConfig.resolve(repo_path=repo_path)
    voice_config = config.voice
    if voice_config is None or not getattr(voice_config, "tts_model", None):
        return ProofResult(
            file="presence_narration",
            status="skipped",
            detail="tts not configured (config.voice/tts_model absent) — nothing to narrate",
        )
    if model:
        voice_config = replace(voice_config, tts_model=model)
    with tempfile.TemporaryDirectory() as tmp_dir:
        narrate = build_presence_narrator(voice_config, tmp_dir)
        assert narrate is not None  # a tts_model was just confirmed present
        seat = acting_seat_label(three_tier=getattr(config, "three_tier", False))
        narrate(f"colleague: {seat}")
        wav_path = Path(tmp_dir) / "presence-0001.wav"
        narrated = wav_path.is_file() and wav_path.stat().st_size > 0
    status, detail = classify_presence_narration_check(narrated)
    return ProofResult(file="presence_narration", status=status, detail=detail)


# ---------------------------------------------------------------------------
# Talking-to-one middle-manager proof (t9): every announcement beat — ack →
# dispatch → grounded update → conversational answer — graded from recorded
# evidence alone, plus front-latency. Pure classifiers; the live drive lives
# in tests/test_vllm_live_talking_to_one.py (gated).
# ---------------------------------------------------------------------------


def front_latencies(senses: dict[str, Any] | None) -> list[float]:
    """Collect every senses-turn wall-clock latency from a ``senses`` payload.

    One entry per :class:`~colleague.contract.SensesRecord` carrying a numeric
    ``latency`` — intake (the ack rides it, zero extra calls), clarify
    re-intakes, proactive updates, speak-back. These are recorded wall-clock
    floats, never estimates; an absent/empty block yields ``[]``.
    """
    if not senses:
        return []
    out: list[float] = []
    for record in senses.get("records", []):
        latency = record.get("latency")
        if isinstance(latency, (int, float)):
            out.append(float(latency))
    return out


def classify_streaming_check(
    first_delta_s: float | None,
    total_s: float | None,
    delta_count: int,
    *,
    error: str | None = None,
    first_target: float = 2.0,
) -> tuple[str, str]:
    """Grade the token-streaming proof (feels-alive arc, spec c10/h13).

    With a delta sink armed, the FIRST visible model output must arrive
    within ``first_target`` seconds (or at worst half the turn) instead of
    only at full-turn latency (pre-arc baseline: a 13.62s turn, longest
    silent gap 4.43s, measured 2026-07-10). Graded from wall-clock evidence:
    an ``error`` SKIPs honestly; zero deltas from an ARMED stream FAILs
    (never engaged); a single delta FAILs (one terminal burst, not a
    stream); else PASS iff the first delta beat the target, else FAIL
    naming the numbers.
    """
    if error:
        return "skipped", f"no streaming measurement: {error}"
    if not delta_count or first_delta_s is None or total_s is None:
        return "failed", "armed stream produced no deltas — streaming never engaged"
    if delta_count < 2:
        return "failed", "a single terminal burst is not a stream (1 delta)"
    if total_s > 0 and first_delta_s >= 0.9 * total_s:
        # Many deltas, ALL landing at the end of the turn: the server did
        # stream (frames exist) but an intermediary delivered them as one
        # terminal burst. Client-agnostic (raw `curl -N` through the lobes
        # gateway shows the same signature, probed 2026-07-10), so this is
        # rig-side — SKIP honestly like the stt/tts-502 voice-lane precedent,
        # never a colleague regression verdict. Colleague-side incrementality
        # stays pinned by the fake-SSE-server unit tests.
        return (
            "skipped",
            f"stream delivered as one terminal burst ({delta_count} deltas, "
            f"first at {first_delta_s:.2f}s of a {total_s:.2f}s turn) — an "
            "intermediary (gateway proxy) buffers SSE; rig-side, not a "
            "colleague regression",
        )
    if first_delta_s <= first_target or first_delta_s <= 0.5 * total_s:
        return (
            "passed",
            f"first delta at {first_delta_s:.2f}s of a {total_s:.2f}s turn "
            f"({delta_count} deltas; target first<{first_target:.0f}s)",
        )
    return (
        "failed",
        f"first delta arrived late: {first_delta_s:.2f}s into a {total_s:.2f}s "
        f"turn ({delta_count} deltas; target first<{first_target:.0f}s or <50% "
        "of the turn)",
    )


def classify_front_latency_check(latencies: list[float], *, target: float = 3.0) -> tuple[str, str]:
    """Grade 'quick is measured' (t9 / spec h7): the senses front must answer in
    low-single-digit seconds — the MEDIAN senses-turn latency clears *target*.

    No recorded latencies SKIPs (never a fabricated pass); a real measurement
    PASSes on median < target, else FAILs naming the numbers.
    """
    if not latencies:
        return "skipped", "no senses-turn latencies recorded"
    med = statistics.median(latencies)
    detail = (
        f"median senses turn {med:.2f}s over {len(latencies)} turn(s) "
        f"(max {max(latencies):.2f}s, target median<{target:.0f}s)"
    )
    if med < target:
        return "passed", detail
    return "failed", f"front latency breached target: {detail}"


def classify_middle_manager_check(
    senses: dict[str, Any] | None, conversation: list[str]
) -> tuple[str, str]:
    """Grade the middle-manager proof (t9 / spec h11+h14) from evidence alone.

    Machine-checkable from the artifact + transcript, no human judgment: the
    ``senses`` payload must contain the ACK chat entry (rendered as its
    ``senses:`` transcript line), at least one PROACTIVE-UPDATE record with a
    rendered non-degraded update line, the folded chat, and a non-degraded
    SPEAK-BACK record (the conversational answer). A fixed-notice ack still
    passes — that is the honest degrade path (h2) — but is named in the
    detail. Anything missing FAILs naming the absent beat; never a fabricated
    pass.
    """
    if not senses:
        return "failed", "no senses block recorded — the middle-manager lane never armed"
    chat = senses.get("chat", [])
    records = senses.get("records", [])
    senses_lines = [line for line in conversation if line.startswith("senses: ")]

    acks = [e for e in chat if e.get("kind") == "ack"]
    if not acks:
        return "failed", "beat missing: no ack chat entry recorded (c9)"
    ack_text = acks[0].get("text", "")
    if f"senses: {ack_text}" not in conversation:
        return "failed", "beat missing: ack recorded but never rendered in the transcript"

    update_records = [r for r in records if r.get("point") == "senses-update"]
    if not update_records:
        return "failed", "beat missing: no proactive-update record (c10)"
    rendered_updates = [
        e
        for e in chat
        if e.get("kind") == "update" and e.get("text") and f"senses: {e['text']}" in conversation
    ]
    if not rendered_updates:
        return (
            "failed",
            "beat missing: updates fired but none rendered a transcript line "
            "(all degraded or capped)",
        )

    speakbacks = [r for r in records if r.get("point") == "senses-speakback"]
    if not speakbacks or all(r.get("degraded") for r in speakbacks):
        return "failed", "beat missing: no non-degraded speak-back (conversational answer)"

    ack_note = " (fixed dispatch notice)" if acks[0].get("fixed") else " (senses' own words)"
    return (
        "passed",
        f"all beats observed: ack{ack_note}, {len(rendered_updates)} rendered "
        f"update(s) of {len(update_records)} fired, conversational answer; "
        f"{len(senses_lines)} senses: transcript line(s), chat folded "
        f"({len(chat)} entr(ies))",
    )


def _has_ack_beat(chat: list[dict[str, Any]], records: list[dict[str, Any]]) -> bool:
    """An ack beat is a kind='ack' chat entry OR a senses-loop dispatch record."""
    if any(e.get("kind") == "ack" for e in chat):
        return True
    return any(str(r.get("point", "")).endswith("dispatch_to_cortex") for r in records)


def _has_narration_beat(chat: list[dict[str, Any]], records: list[dict[str, Any]]) -> bool:
    """A narration beat is a proactive update OR a conversational reply.

    Covers BOTH lanes: the fixed-beat lane (a ``senses-update`` /
    ``senses-speakback`` record, or a kind='update' chat entry with text) and the
    senses-loop lane (a ``senses-loop:reply_to_operator`` record, or a talk-shaped
    chat entry — kind absent — carrying an ``answer``).
    """
    for r in records:
        point = str(r.get("point", ""))
        if point in ("senses-update", "senses-speakback") and not r.get("degraded"):
            return True
        if point.endswith("reply_to_operator"):
            return True
    for e in chat:
        if e.get("kind") == "update" and e.get("text"):
            return True
        if "kind" not in e and str(e.get("answer") or "").strip():
            return True
    return False


def _has_relay_beat(injections: list[dict[str, Any]], records: list[dict[str, Any]]) -> bool:
    """A relay beat is a recorded guidance injection OR a guide_cortex loop record.

    Optional: a run where the operator never spoke has no relay — its absence is
    reported, never a failure.
    """
    if injections:
        return True
    return any(str(r.get("point", "")).endswith("guide_cortex") for r in records)


def classify_front_presence_check(
    senses: dict[str, Any] | None,
    rendered_lines: list[str],
    *,
    front: str = "front",
) -> tuple[str, str]:
    """Grade one front's middle-manager beats from evidence alone (t14).

    REQUIRED beats: an ACK and at least one grounded NARRATION (a proactive
    update or a conversational reply). The guidance RELAY is reported when
    present but never required (not every run relays). Returns ``("skipped",
    reason)`` when the front was not exercised at all (no senses block AND no
    rendered lines); ``("failed", reason)`` when a block exists but a required
    beat is missing (a real regression); ``("passed", detail)`` otherwise —
    never a fabricated pass.
    """
    if not senses and not rendered_lines:
        return "skipped", f"{front}: not exercised (no senses block, no rendered lines)"
    if not senses:
        return "failed", f"{front}: rendered senses lines but no SensesBlock — not reconstructable"

    chat = senses.get("chat", []) or []
    records = senses.get("records", []) or []
    injections = senses.get("injections", []) or []

    if not _has_ack_beat(chat, records):
        return "failed", f"{front}: beat missing — no ack (kind='ack' chat or dispatch record)"
    if not _has_narration_beat(chat, records):
        return "failed", f"{front}: beat missing — no grounded update/reply narration"

    relay = "with a guidance relay" if _has_relay_beat(injections, records) else "no relay this run"
    return (
        "passed",
        f"{front}: ack + narration observed, {relay}; "
        f"{len(records)} record(s), {len(chat)} chat entr(ies), {len(injections)} injection(s)",
    )


def classify_session_presence_check(senses, transcript):  # noqa: ANN001
    """Session-loop front: graded from the cockpit transcript (`senses:` lines)."""
    return classify_front_presence_check(senses, transcript, front="session")


def classify_talk_presence_check(senses, flight_chat_lines):  # noqa: ANN001
    """Talk-attach front: graded from the flight chat log lines."""
    return classify_front_presence_check(senses, flight_chat_lines, front="talk")


def classify_background_presence_check(senses, flight_chat_lines):  # noqa: ANN001
    """Background front: graded from the flight chat log lines."""
    return classify_front_presence_check(senses, flight_chat_lines, front="background")


def classify_resident_presence_check(senses, reply_bodies):  # noqa: ANN001
    """Resident front: graded from the origin reply bodies (ack/update messages)."""
    return classify_front_presence_check(senses, reply_bodies, front="resident")


def classify_work_presence_check(senses, stderr_lines):  # noqa: ANN001
    """One-shot work front: graded from the stderr `senses:` lines."""
    return classify_front_presence_check(senses, stderr_lines, front="work")


# ---------------------------------------------------------------------------
# "One teammate" proof (talking-to-one-teammate arc, t8): a non-repo turn
# ("hi" / "what are you?") must be answered by senses DIRECTLY, no cortex work
# item spawned — the pain the front door removes. Pure classifier; the live
# drive lives wherever the front door is wired and passes evidence in here.
# ---------------------------------------------------------------------------


def classify_one_teammate_check(
    *,
    senses_reachable: bool,
    answered_by: str | None,
    branch_created: bool,
    record_created: bool,
) -> tuple[str, str]:
    """Grade the 'one teammate' front-door proof from evidence alone.

    SKIPs (never a fabricated PASS) when senses itself was unarmed or
    unreachable, so the front door could not run at all — the reference-rig
    reality today. FAILs when a non-repo turn nonetheless spawned a git
    branch and/or an eidetic record (naming which) — that is exactly the
    pain this feature removes. FAILs when cortex, not senses, answered the
    turn (naming what answered). PASSes only when senses answered directly
    with no branch and no record: no cortex work item at all.
    """
    if not senses_reachable:
        return (
            "skipped",
            "senses unarmed/unreachable — the front door could not run",
        )

    spawned = []
    if branch_created:
        spawned.append("a git branch")
    if record_created:
        spawned.append("an eidetic record")
    if spawned:
        return (
            "failed",
            f"non-repo turn spawned {' and '.join(spawned)} — exactly the "
            "pain this feature removes",
        )

    if answered_by != "senses":
        return (
            "failed",
            "cortex answered a turn senses should have handled directly "
            f"(answered_by={answered_by!r})",
        )

    return "passed", "senses answered directly; no cortex work item"


def _grade_at_home_global_arming(evidence: dict[str, object]) -> tuple[str, str]:
    """The machine-global config proof.

    Evidence: ``env_armed`` (was COLLEAGUE_LOBES_URL set? — must be False for
    this proof to mean anything), ``config_show_armed`` / ``lobes_show_armed``
    (what the two introspection verbs reported), ``user_config_present``.
    PASSes only when, with the env unset and only a user-level config carrying
    ``lobes``, BOTH verbs agree armed — the t1 shadow fix plus the t2 drift fix
    in one observable. FAILs on any disagreement (the pre-arc contradiction) or
    on an unarmed verdict. SKIPs when no user-level config exists to prove with.
    """
    if evidence.get("env_armed"):
        return (
            "skipped",
            "COLLEAGUE_LOBES_URL was set — the proof needs the env rung dark",
        )
    if not evidence.get("user_config_present"):
        return "skipped", "no user-level ~/.colleague/config.json to prove with"
    config_armed = bool(evidence.get("config_show_armed"))
    lobes_armed = bool(evidence.get("lobes_show_armed"))
    if config_armed and lobes_armed:
        return (
            "passed",
            "user-level lobes default armed both verbs with zero env vars",
        )
    if config_armed != lobes_armed:
        return (
            "failed",
            f"introspection drift: config show armed={config_armed}, "
            f"lobes show armed={lobes_armed} — the pre-arc contradiction",
        )
    return "failed", "user-level lobes default did not arm (shadowed or unread)"


def _grade_at_home_input_line(evidence: dict[str, object]) -> tuple[str, str]:
    """The mid-run typing proof.

    Evidence: ``armed`` (did the owned line arm on the live TTY?),
    ``repaint_seen`` (did an update line print ABOVE a repainted pending buffer
    — the print_above escape shape?), ``pending_text`` + ``output`` (the typed
    chars and the captured stream — the pending text must survive in the final
    repaint). SKIPs when the owned line never armed (off-TTY capture — the
    structural pytest remains the floor). FAILs when armed but the repaint shape
    never appeared or the pending text was lost — exactly the clobber this arc
    removes.
    """
    if not evidence.get("armed"):
        return (
            "skipped",
            "owned input line never armed (no live colour TTY) — "
            "the structural pytest remains the floor",
        )
    output = str(evidence.get("output", ""))
    pending = str(evidence.get("pending_text", ""))
    if not evidence.get("repaint_seen"):
        return (
            "failed",
            "armed but no print_above repaint appeared around mid-run output",
        )
    if pending and pending not in output:
        return (
            "failed",
            f"pending input {pending!r} lost from the captured stream — "
            "the clobber this arc removes",
        )
    return "passed", "mid-run output printed above a surviving pending input line"


def _grade_at_home_self_knowledge(evidence: dict[str, object]) -> tuple[str, str]:
    """The "knows itself" proof, senses or cortex side.

    Evidence: ``reachable`` (was the answering mind armed/reachable?),
    ``answer`` (the transcript answer), ``expected_ids`` (the RESOLVED model id
    strings that must appear verbatim — exact-match, the c18 measurable).
    PASSes only when every expected id appears verbatim in the answer. FAILs on
    a deferral (the live-proven "i don't know which" shape) or a missing id.
    SKIPs when the mind was unreachable. Never a fabricated pass.
    """
    if not evidence.get("reachable"):
        return "skipped", "answering mind unarmed/unreachable — nothing to grade"
    answer = str(evidence.get("answer", ""))
    lowered = answer.lower()
    if "i don't know which" in lowered or "i do not know which" in lowered:
        return "failed", "answer is the pre-arc deferral, not a resolved fact"
    expected = [str(e) for e in (evidence.get("expected_ids") or []) if str(e)]
    if not expected:
        return "skipped", "no expected ids supplied — nothing exact to grade"
    missing = [e for e in expected if e not in answer]
    if missing:
        return (
            "failed",
            f"answer omitted resolved id(s) {missing!r} — exact-match is the bar",
        )
    return "passed", "answer names every resolved id verbatim"


#: The at-home arc's three live-proof legs, keyed by the ``leg`` selector. An
#: unlisted leg SKIPs honestly rather than falling through to a verdict.
_AT_HOME_LEGS: dict[str, Callable[[dict[str, object]], tuple[str, str]]] = {
    "global-arming": _grade_at_home_global_arming,
    "input-line": _grade_at_home_input_line,
    "self-knowledge": _grade_at_home_self_knowledge,
}


def classify_at_home_check(leg: str, **evidence: object) -> tuple[str, str]:
    """Grade one leg of the at-home arc's live proof from evidence alone.

    Dispatches to the per-leg grader named by *leg* (see :data:`_AT_HOME_LEGS`);
    an unknown leg SKIPs honestly — a typo'd invocation must never fabricate a
    verdict.
    """
    grade = _AT_HOME_LEGS.get(leg)
    if grade is None:
        return "skipped", f"unknown at-home proof leg {leg!r} — nothing to grade"
    return grade(evidence)

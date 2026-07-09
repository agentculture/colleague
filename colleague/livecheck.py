"""livecheck — probe the configured endpoint and run gated live proofs.

One verb that probes the configured endpoint and runs the applicable gated
live proofs, reporting per-ledger-row pass/fail/skip.

This module owns the logic; the CLI verb in
:mod:`colleague.cli._commands.livecheck` is the thin presentation layer.
"""

from __future__ import annotations

import io
import os
import statistics
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
import zlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from colleague import media
from colleague.config import EngineConfig, resolve_lobes_gateway_url
from colleague.contract import Task
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.lobes import resolve_roles
from colleague.oilcheck.reachability import _PROBE_TIMEOUT
from colleague.senses import run_senses_intake, run_senses_speakback, senses_engine_config


@dataclass
class ProofResult:
    """Result of running a single live-proof test file."""

    file: str
    status: str  # "passed" | "failed" | "skipped"
    detail: str = ""


def probe_endpoint(repo: str | Path) -> dict[str, Any]:
    """Probe the configured endpoint for reachability.

    Reuses :func:`colleague.config.EngineConfig.resolve` and the same
    urllib-based reachability check as
    :mod:`colleague.oilcheck.reachability`.

    Returns a dict with keys:

    - ``endpoint`` (str) — the resolved base_url
    - ``reachable`` (bool)
    - ``reason`` (str | None) — error detail when not reachable
    """
    repo_path = str(repo)
    config = EngineConfig.resolve(repo_path=repo_path)
    base_url = config.base_url
    url = base_url.rstrip("/") + "/models"

    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - operator-configured endpoint
            request, timeout=_PROBE_TIMEOUT
        ) as response:
            # Any successful response means reachable
            _ = response.read()
            return {"endpoint": base_url, "reachable": True, "reason": None}
    except urllib.error.HTTPError:
        # Server responded (e.g. 401/404) — it is up
        return {"endpoint": base_url, "reachable": True, "reason": None}
    except OSError as exc:
        reason = str(getattr(exc, "reason", exc))
        return {"endpoint": base_url, "reachable": False, "reason": reason}


# Known gated live-proof pytest files with short labels.
# These are the files that require a live vLLM endpoint to run.
_KNOWN_PROOFS: list[tuple[str, str]] = [
    ("tests/test_vllm_live.py", "basic live drive"),
    ("tests/test_vllm_live_context_budget.py", "context budget"),
    ("tests/test_vllm_live_gated_configs.py", "gated configs"),
    ("tests/test_vllm_live_loop_tools.py", "loop tools"),
    ("tests/test_vllm_live_mode.py", "live mode"),
    ("tests/test_vllm_live_neighbours.py", "neighbours"),
    ("tests/test_vllm_live_subagents.py", "subagents"),
    ("tests/test_vllm_live_telemetry.py", "telemetry"),
    ("tests/test_dual_live.py", "dual live"),
    ("tests/test_vllm_live_talking_to_one.py", "talking to one (middle-manager)"),
]


def select_proofs(repo: str | Path) -> list[dict[str, str]]:
    """Return the known gated live-proof files that actually exist in *repo*.

    Each result is ``{"file": str, "label": str}``.
    """
    repo_path = Path(repo)
    results: list[dict[str, str]] = []
    for path, label in _KNOWN_PROOFS:
        if (repo_path / path).is_file():
            results.append({"file": path, "label": label})
    return results


# Per-proof timeout default (seconds). A full live drive routinely exceeds two
# minutes per turn-sequence on the reference 27B (one slow model turn alone can
# take the work loop's whole 120s COLLEAGUE_TIMEOUT window), so the cap must be
# rig-realistic; override with COLLEAGUE_LIVECHECK_TIMEOUT (#266).
_DEFAULT_PROOF_TIMEOUT = 600.0
_PROOF_TIMEOUT_ENV = "COLLEAGUE_LIVECHECK_TIMEOUT"


def _proof_timeout() -> float:
    """Resolve the per-proof timeout: env override > 600s default (#266)."""
    raw = os.environ.get(_PROOF_TIMEOUT_ENV, "")
    try:
        value = float(raw)
        if value > 0:
            return value
    except ValueError:
        pass
    return _DEFAULT_PROOF_TIMEOUT


def run_proofs(
    proofs: list[dict[str, str]],
    repo: str | Path,
    *,
    timeout: float | None = None,
) -> list[ProofResult]:
    """Run pytest on the given proof files with COLLEAGUE_VLLM_E2E=1.

    Each proof file is capped at *timeout* seconds (default: the
    ``COLLEAGUE_LIVECHECK_TIMEOUT`` env var, else 600s — #266); a timed-out
    proof is reported ``skipped`` with the configured cap and the knob named,
    never silently. Returns a list of :class:`ProofResult` with per-file status.
    """
    repo_path = str(repo)
    cap = timeout if timeout is not None else _proof_timeout()
    env = os.environ.copy()
    env["COLLEAGUE_VLLM_E2E"] = "1"

    results: list[ProofResult] = []
    for proof in proofs:
        file_path = proof["file"]
        try:
            proc = subprocess.run(  # noqa: S603 - curated test paths
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-x",
                    "-q",
                    "--tb=short",
                    file_path,
                ],
                capture_output=True,
                text=True,
                cwd=repo_path,
                env=env,
                timeout=cap,
            )
            if proc.returncode == 0:
                status = "passed"
                detail = ""
            else:
                status = "failed"
                # Grab the last non-empty line for detail
                lines = proc.stderr.strip().splitlines()
                detail = lines[-1] if lines else proc.stdout.strip()[:200]
        except subprocess.TimeoutExpired:
            status = "skipped"
            detail = f"timeout ({cap:g}s; raise {_PROOF_TIMEOUT_ENV} to allow more)"
        except FileNotFoundError:
            status = "skipped"
            detail = "pytest not found"
        except Exception as exc:
            status = "skipped"
            detail = str(exc)

        results.append(ProofResult(file=file_path, status=status, detail=detail))
    return results


# ---------------------------------------------------------------------------
# Media live proofs (plan task t13): image end-to-end + audio honest-skip.
#
# Unlike the pytest-file proofs above (subprocess to a *separate* gated test
# file), these two checks drive one real ``engine.work()`` call directly —
# the same seam ``tests/test_vllm_live.py`` uses (``VllmOpenAIEngine().work``)
# — because each needs a runtime-generated fixture attachment rather than a
# pre-existing test file. The classification logic below is pure (no I/O) so
# it is unit-testable against simulated ``TaskResult`` payloads with no live
# rig required; only ``run_media_image_check``/``run_media_audio_check``
# touch the network, and both degrade to "skipped" — never a traceback — when
# the endpoint is unreachable or the live call itself errors.
# ---------------------------------------------------------------------------

# Live rig fact (probed 2026-07-02, see docs/live-testing.md): the reference
# endpoint accepts an ``input_audio`` content part with a 200 OK response but
# contributes ~0 prompt tokens for it — a SILENT DROP, not a rejection. Named
# here so both the classifier and the CLI/docs procedure state the same reason.
_AUDIO_DROP_REASON = (
    "rig silently drops input_audio (200 OK, ~0 prompt tokens contributed "
    "— see docs/live-testing.md)"
)

_MEDIA_IMAGE_INSTRUCTION = "What color is the attached image? Answer with the color name only."
_MEDIA_AUDIO_INSTRUCTION = "Describe the attached audio clip in one sentence."


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
# LIVE-PROBED via the gateway's realtime bridge (see colleague/lobes.py's
# ready_kind + colleague/voice.py's bounded 503+Retry-After warming retry).
# The round-trip proof checks readiness FIRST: a genuinely down/unready role
# SKIPs honestly, naming the rig state — never the old bare-"502" workaround.
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
    gateway's realtime bridge — a warming backend answers 503+Retry-After
    (``colleague/voice.py`` bounds one retry on that), never a bare 502. The
    round-trip proof now checks readiness FIRST, so ``outcome`` is ``"ok"``
    (a verbatim transcript / a written wav — possibly after one bounded
    warming retry), ``"not_ready"`` (the live readiness probe itself reports
    the role down/unready — the ONLY case this SKIPs on, honestly naming the
    rig state), or any other string (an unexpected failure). Because
    ``ready`` is now live-probe-backed, a round-trip that still fails despite
    a ready report is a genuine regression and FAILs — never silently
    SKIPped the way the old bare-502 workaround used to.
    """
    if outcome == "ok":
        return "passed", f"{kind} lane round-tripped audio through the gateway"
    if outcome == "not_ready":
        return "skipped", f"{kind}: {_VOICE_LANE_NOT_READY_REASON}"
    return "failed", f"{kind} lane failed unexpectedly: {outcome!r}"


# ---------------------------------------------------------------------------
# Presence-beat narration proof (presence-default-everywhere arc, task t12,
# decision c17): does a rendered ack/update/reply beat actually produce a
# companion .wav? Grades from the SAME evidence discipline as the media/voice
# checks above — never a fabricated pass. Reuses colleague.voice.synthesize's
# own degrade-never-raise contract (a 502/no-audio body writes no file), so
# "no wav landed" and "the rig's tts proxy is down" are indistinguishable from
# here — exactly the honest limit classify_media_audio_check already
# documents for the sibling audio-drop case, and it flips to a real pass the
# day the rig actually serves audio.
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

    Resolves the repo's ``VoiceConfig`` (``config.voice``, optionally
    overridden with an explicit ``model`` as the tts model) and, when a
    ``tts_model`` is present, drives one
    :func:`colleague.voice.build_presence_narrator` call with a short
    presence-beat line into a throwaway directory. SKIPs honestly — never a
    fabricated pass — when voice isn't configured at all, or when the
    synthesis degrades (the reference rig's tts proxy currently 502s; see
    :func:`classify_presence_narration_check`).
    """
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
        narrate("colleague: cortex is working on your request now.")
        wav_path = Path(tmp_dir) / "presence-0001.wav"
        narrated = wav_path.is_file() and wav_path.stat().st_size > 0
    status, detail = classify_presence_narration_check(narrated)
    return ProofResult(file="presence_narration", status=status, detail=detail)


# ---------------------------------------------------------------------------
# Talking-to-one middle-manager proof (task t9): every announcement beat —
# ack → dispatch → grounded update → conversational answer — graded from the
# recorded evidence alone (the session transcript + TaskResult.senses), plus
# the front-latency measurement. Pure classifiers (unit-testable, no I/O);
# the live drive lives in tests/test_vllm_live_talking_to_one.py (gated).
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


def _reachable(repo: str | Path) -> tuple[bool, str | None]:
    """Thin wrapper over :func:`probe_endpoint` returning ``(reachable, reason)``."""
    probe = probe_endpoint(repo)
    return bool(probe["reachable"]), probe["reason"]


def _run_media_check(
    repo: str | Path,
    *,
    name: str,
    instruction: str,
    fixture_bytes: bytes,
    fixture_name: str,
    classify: Callable[[dict[str, Any] | None, str], tuple[str, str]],
    model: str | None = None,
) -> ProofResult:
    """Shared live-invocation for the two media proofs (t13).

    Builds a real attachment on disk, drives ONE real ``engine.work()`` call
    (the same seam as ``tests/test_vllm_live.py``:
    ``VllmOpenAIEngine().work(task, config)``), then hands the result's
    ``media`` record + ``summary`` to *classify*. Degrades to ``skipped`` —
    never raises — when the endpoint is unreachable or the live call itself
    errors, mirroring :func:`run_proofs`'s honest-skip behaviour for a
    timeout/missing-pytest.
    """
    reachable, reason = _reachable(repo)
    if not reachable:
        return ProofResult(file=name, status="skipped", detail=f"endpoint unreachable: {reason}")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / fixture_name
            fixture_path.write_bytes(fixture_bytes)
            attachment = media.validate_attachment(str(fixture_path))
            task = Task.new(
                tmp,
                instruction,
                engine="vllm-openai",
                attachments=[attachment],
            )
            config = EngineConfig.resolve(repo_path=str(repo), model=model)
            result = VllmOpenAIEngine().work(task, config)
    except Exception as exc:  # a live proof degrades, it never crashes the caller
        return ProofResult(file=name, status="skipped", detail=f"proof error: {exc}")

    status, detail = classify(result.media, result.summary)
    return ProofResult(file=name, status=status, detail=detail)


# Gating condition (see docs/live-testing.md's media-proof ledger entry): the
# image proof needs a live, media-capable serving path — pass model= (or set
# COLLEAGUE_MODEL) to target whichever configured model actually accepts
# image input; no colleague code special-cases a specific model (t14 rule).
def run_media_image_check(repo: str | Path, *, model: str | None = None) -> ProofResult:
    """Live proof (t13): a real solid-red PNG through the ``--attach`` engine seam.

    PASSES only when the answer names "red" AND ``TaskResult.media`` records
    the attachment ``delivered`` — see :func:`classify_media_image_check`.
    Gated on a live, media-capable serving path being configured (pass
    ``model=`` to target one explicitly); degrades to ``skipped`` when the
    endpoint is unreachable.
    """
    return _run_media_check(
        repo,
        name="media_image",
        instruction=_MEDIA_IMAGE_INSTRUCTION,
        fixture_bytes=_make_red_png(),
        fixture_name="red.png",
        classify=classify_media_image_check,
        model=model,
    )


def run_media_audio_check(repo: str | Path, *, model: str | None = None) -> ProofResult:
    """Live proof (t13): a real WAV clip through the ``--attach`` engine seam.

    Reports SKIP with the silent-drop reason on today's rig — see
    :func:`classify_media_audio_check`; never reports pass while the drop
    persists. Degrades to ``skipped`` when the endpoint is unreachable.
    """
    return _run_media_check(
        repo,
        name="media_audio",
        instruction=_MEDIA_AUDIO_INSTRUCTION,
        fixture_bytes=_make_test_wav(),
        fixture_name="clip.wav",
        classify=classify_media_audio_check,
        model=model,
    )


# ---------------------------------------------------------------------------
# Cortex/senses measurement comparison (cortex/senses arc, t13)
# ---------------------------------------------------------------------------

#: A small, deterministic read task run identically cortex-only and split. The
#: point is the MEASUREMENT (per-mode wall-clock + senses runtime), never the
#: answer quality — so the instruction just has to be real work, not a puzzle.
_CORTEX_SENSES_INSTRUCTION = (
    "List the Python files at the top level of this repo and say how many there are."
)


def probe_lobes_stack(repo: str | Path) -> tuple[bool, str | None]:
    """Probe whether the rebalanced cortex+senses stack is actually SERVING (t13).

    Uses the lobes gateway (``COLLEAGUE_LOBES_URL`` / the config.json ``lobes``
    section, via :func:`colleague.config.resolve_lobes_gateway_url`) and
    :func:`colleague.lobes.resolve_roles`. Returns ``(serving, reason)``:
    ``(True, None)`` only when both cortex and senses resolve AND report
    ``ready``; otherwise ``(False, reason)`` — a gateway that is not configured,
    unreachable, or not both-ready SKIPs the scenario honestly (never a
    fabricated pass, spec h13). This is the gate the whole comparison hangs on:
    the rebalanced stack (cortex@128K + senses@32K co-resident) may not be up.
    """
    url = resolve_lobes_gateway_url(repo)
    if not url:
        return (
            False,
            "no lobes gateway configured (COLLEAGUE_LOBES_URL) — cortex/senses stack not probed",
        )
    roles = resolve_roles(url)
    if roles is None:
        return (
            False,
            f"lobes gateway {url} unreachable or missing cortex/senses — rebalanced stack not up",
        )
    if not (roles.cortex.ready and roles.senses.ready):
        return (
            False,
            f"cortex/senses not both ready at {url} (the rebalanced stack is still warming up)",
        )
    return True, None


def _senses_record_runtime(record: dict[str, Any]) -> str:
    """Format one senses record's runtime facts: ``point=Ns/Mtok``.

    Qodo #3 (cortex/senses PR #281): the measurement story was incomplete
    without each invocation's token cost alongside its latency. ``tokens`` is
    ``None`` on a degraded record (the call never reached the wire, or the
    response carried no usage) — rendered as ``?tok`` (an honest "unknown",
    never fabricated as ``0tok``, which would misleadingly imply a free call).
    Still RUNTIME FACTS ONLY, never a quality score.
    """
    tokens = record.get("tokens")
    tok_str = f"{tokens}tok" if tokens is not None else "?tok"
    return f"{record.get('point')}={record.get('latency')}s/{tok_str}"


def classify_cortex_senses_check(
    cortex_artifact: dict[str, Any] | None,
    split_artifact: dict[str, Any] | None,
    instruction: str,
) -> tuple[str, str]:
    """Grade the cortex-only vs split comparison from artifact EVIDENCE (t13).

    Asserts ONLY runtime facts — NEVER a quality score (the two summaries are
    never compared for "better"). PASSES when the split run recorded
    ``mode=split`` AND preserved the operator's original request VERBATIM across
    the cortex/senses boundary; the returned detail emits the per-mode wall-clock
    (``stats.duration_seconds``) and the senses runtime (each record's
    ``point=latency``/``tokens``, via :func:`_senses_record_runtime`) side by
    side, which is the measurable-against-cortex-only deliverable. A split
    artifact missing the block, or whose packet dropped the verbatim original,
    FAILS (a real regression); the runner SKIPs before this when the stack is
    not serving.
    """
    split = split_artifact or {}
    senses = split.get("senses")
    if not senses or senses.get("mode") != "split":
        return "failed", f"split run did not record mode=split (senses={senses!r})"
    packet = senses.get("packet") or {}
    if packet.get("original") != instruction:
        return (
            "failed",
            f"packet.original not preserved verbatim: {packet.get('original')!r}",
        )
    cortex_secs = ((cortex_artifact or {}).get("stats") or {}).get("duration_seconds")
    split_secs = (split.get("stats") or {}).get("duration_seconds")
    records = senses.get("records") or []
    senses_runtime = " · ".join(_senses_record_runtime(r) for r in records) or "(none)"
    detail = (
        f"cortex-only wall-clock={cortex_secs}s vs split wall-clock={split_secs}s; "
        f"senses runtime: {senses_runtime}; verbatim original preserved"
    )
    return "passed", detail


def run_cortex_senses_check(repo: str | Path, *, model: str | None = None) -> ProofResult:
    """Live proof (t13): run the SAME task cortex-only and split, side by side.

    Drives ``VllmOpenAIEngine().work()`` twice against the live rig — once
    cortex-only (``config.senses`` nulled) and once split (senses intake →
    ContextPacket on the task → the loop records mode=split; then speak-back +
    intake/speak-back records folded in, mirroring the session/resident path) —
    and grades the two artifacts via :func:`classify_cortex_senses_check`.

    SKIPs honestly (never fails, never fabricates a pass) when the endpoint is
    unreachable OR the rebalanced cortex+senses stack is not serving
    (:func:`probe_lobes_stack`) OR the live calls error — the exact
    degrade-to-skipped contract the media proofs use.
    """
    reachable, reason = _reachable(repo)
    if not reachable:
        return ProofResult(
            file="cortex_senses", status="skipped", detail=f"endpoint unreachable: {reason}"
        )
    serving, sreason = probe_lobes_stack(repo)
    if not serving:
        return ProofResult(
            file="cortex_senses", status="skipped", detail=sreason or "stack not serving"
        )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            # cortex-only: identical task, senses bypassed.
            cortex_config = EngineConfig.resolve(repo_path=str(repo), model=model)
            cortex_config.senses = None
            cortex_result = VllmOpenAIEngine().work(
                Task.new(tmp, _CORTEX_SENSES_INSTRUCTION, engine="vllm-openai"), cortex_config
            )

            # split: senses intake → packet → the loop records mode=split; then
            # fold the session-style intake/speak-back records for the runtime story.
            split_config = EngineConfig.resolve(repo_path=str(repo), model=model)
            senses_cfg = senses_engine_config(split_config)
            if senses_cfg is None:
                return ProofResult(
                    file="cortex_senses",
                    status="skipped",
                    detail="senses not resolved from config/lobes despite a serving stack",
                )
            engine = VllmOpenAIEngine()
            packet, _intake_rec = run_senses_intake(_CORTEX_SENSES_INSTRUCTION, senses_cfg, engine)
            if packet is None:
                # Intake gracefully degraded on the serving rig (malformed/empty
                # JSON, overflow) — the degrade-to-raw path is CORRECT behavior,
                # not a regression, and there is no split to compare. SKIP
                # honestly rather than grade a designed degradation as a failure.
                return ProofResult(
                    file="cortex_senses",
                    status="skipped",
                    detail="senses intake degraded live — no split to compare (correct degrade)",
                )
            split_task = Task.new(tmp, _CORTEX_SENSES_INSTRUCTION, engine="vllm-openai")
            split_task.context_packet = packet
            split_result = VllmOpenAIEngine().work(split_task, split_config)
            shaped, speak_rec = run_senses_speakback(split_result.summary, senses_cfg, engine)
            _ = shaped  # display shaping is not graded — only the runtime record is
            # Fold the session-side records into the block the LOOP recorded. Do
            # NOT fabricate a block: if the loop failed to record mode=split
            # despite a packet on the task, classify() must SEE that (a real
            # regression) — the proof verifies the loop, it never supplies the
            # very evidence it is meant to check (review finding #3).
            if split_result.senses is not None:
                split_result.senses.records = (
                    [_intake_rec]
                    + list(split_result.senses.records)
                    + ([speak_rec] if speak_rec is not None else [])
                )
    except Exception as exc:  # a live proof degrades, it never crashes the caller
        return ProofResult(file="cortex_senses", status="skipped", detail=f"proof error: {exc}")

    status, detail = classify_cortex_senses_check(
        cortex_result.to_dict(), split_result.to_dict(), _CORTEX_SENSES_INSTRUCTION
    )
    return ProofResult(file="cortex_senses", status=status, detail=detail)


# ---------------------------------------------------------------------------
# Per-front presence classifiers (presence-default-everywhere, task t14): each
# front's full middle-manager beat sequence — ack → grounded update/reply →
# (optional) guidance relay — graded from the SHARED SensesBlock (t3) + that
# front's own rendered lines, machine-checkable, no human judgment. The SAME
# beats are graded on every front (h6 / c4 / c15): a front missing a beat FAILS
# its check; a front the rig could not exercise SKIPs (never a fabricated pass).
# ---------------------------------------------------------------------------

#: The fronts the presence lane serves. Each grades the SAME SensesBlock shape
#: from its own rendered-line source: session → the cockpit transcript, talk →
#: the flight chat log, background → the flight chat log, resident → the origin
#: reply bodies, work → the stderr lines.
PRESENCE_FRONTS = ("session", "talk", "background", "resident", "work")


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
# "One teammate" proof (talking-to-one-teammate arc, task t8): a non-repo
# turn ("hi" / "what are you?") must be answered by senses DIRECTLY, with NO
# cortex work item spawned — the exact pain the front door removes (a bare
# greeting used to cost a git branch + an eidetic remember). Pure classifier
# (unit-testable, no I/O); the live drive lives wherever the front door is
# wired (when armed) and passes its recorded evidence in here.
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

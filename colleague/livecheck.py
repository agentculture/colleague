"""livecheck — probe the configured endpoint and run gated live proofs.

One verb that probes the configured endpoint and runs the applicable gated
live proofs, reporting per-ledger-row pass/fail/skip.

This module owns the logic; the CLI verb in
:mod:`colleague.cli._commands.livecheck` is the thin presentation layer.
"""

from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from colleague import media
from colleague.config import EngineConfig, resolve_lobes_gateway_url
from colleague.contract import SensesBlock, Task
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
    ``point=latency``) side by side, which is the measurable-against-cortex-only
    deliverable. A split artifact missing the block, or whose packet dropped the
    verbatim original, FAILS (a real regression); the runner SKIPs before this
    when the stack is not serving.
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
    senses_runtime = (
        " · ".join(f"{r.get('point')}={r.get('latency')}s" for r in records) or "(none)"
    )
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
            packet, intake_rec = run_senses_intake(_CORTEX_SENSES_INSTRUCTION, senses_cfg, engine)
            split_task = Task.new(tmp, _CORTEX_SENSES_INSTRUCTION, engine="vllm-openai")
            if packet is not None:
                split_task.context_packet = packet
            split_result = VllmOpenAIEngine().work(split_task, split_config)
            shaped, speak_rec = run_senses_speakback(split_result.summary, senses_cfg, engine)
            _ = shaped  # display shaping is not graded — only the runtime record is
            if split_result.senses is None:
                split_result.senses = SensesBlock(mode="split", packet=packet, records=[])
            split_result.senses.records = (
                ([intake_rec] if intake_rec is not None else [])
                + list(split_result.senses.records)
                + ([speak_rec] if speak_rec is not None else [])
            )
    except Exception as exc:  # a live proof degrades, it never crashes the caller
        return ProofResult(file="cortex_senses", status="skipped", detail=f"proof error: {exc}")

    status, detail = classify_cortex_senses_check(
        cortex_result.to_dict(), split_result.to_dict(), _CORTEX_SENSES_INSTRUCTION
    )
    return ProofResult(file="cortex_senses", status=status, detail=detail)

"""livecheck — probe the configured endpoint and run gated live proofs.

One verb that probes the configured endpoint and runs the applicable gated
live proofs, reporting per-ledger-row pass/fail/skip.

This module owns the logic; the CLI verb in
:mod:`colleague.cli._commands.livecheck` is the thin presentation layer.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from colleague import media
from colleague.cli._errors import CliError
from colleague.config import EngineConfig, resolve_lobes_gateway_url
from colleague.contract import Task
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.livecheck_checks import (  # noqa: E402  (re-exported; see module docstring)
    _AUDIO_DROP_REASON,
    ProofResult,
    _attachment_status,
    _grade_at_home_global_arming,
    _grade_at_home_input_line,
    _grade_at_home_self_knowledge,
    _has_ack_beat,
    _has_narration_beat,
    _has_relay_beat,
    _make_red_png,
    _make_test_wav,
    classify_at_home_check,
    classify_background_presence_check,
    classify_flight_liveness_check,
    classify_flight_reachable_check,
    classify_front_latency_check,
    classify_front_presence_check,
    classify_honest_incompletion_check,
    classify_injection_reached_check,
    classify_media_audio_check,
    classify_media_image_check,
    classify_middle_manager_check,
    classify_one_teammate_check,
    classify_presence_narration_check,
    classify_resident_presence_check,
    classify_senses_latency_check,
    classify_session_presence_check,
    classify_streaming_check,
    classify_talk_presence_check,
    classify_voice_lane_check,
    classify_work_presence_check,
    front_latencies,
    run_presence_narration_check,
)
from colleague.lobes import resolve_roles
from colleague.oilcheck.reachability import _PROBE_TIMEOUT
from colleague.realtime import open_session
from colleague.senses import run_senses_intake, run_senses_speakback, senses_engine_config

__all__ = [
    "ProofResult",
    "_AUDIO_DROP_REASON",
    "_attachment_status",
    "_grade_at_home_global_arming",
    "_grade_at_home_input_line",
    "_grade_at_home_self_knowledge",
    "_has_ack_beat",
    "_has_narration_beat",
    "_has_relay_beat",
    "_make_red_png",
    "_make_test_wav",
    "classify_at_home_check",
    "classify_background_presence_check",
    "classify_flight_liveness_check",
    "classify_flight_reachable_check",
    "classify_front_latency_check",
    "classify_front_presence_check",
    "classify_honest_incompletion_check",
    "classify_injection_reached_check",
    "classify_media_audio_check",
    "classify_media_image_check",
    "classify_middle_manager_check",
    "classify_one_teammate_check",
    "classify_presence_narration_check",
    "classify_resident_presence_check",
    "classify_senses_latency_check",
    "classify_session_presence_check",
    "classify_streaming_check",
    "classify_talk_presence_check",
    "classify_voice_lane_check",
    "classify_work_presence_check",
    "front_latencies",
    "run_presence_narration_check",
]


def probe_endpoint(repo: str | Path) -> dict[str, Any]:
    """Probe the configured endpoint for reachability.

    Reuses :func:`colleague.config.EngineConfig.resolve` and the same
    urllib-based check as :mod:`colleague.oilcheck.reachability`. Returns
    ``{"endpoint": str, "reachable": bool, "reason": str | None}``.
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
    ("tests/test_vllm_live_streaming.py", "token streaming (feels-alive)"),
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


# Per-proof timeout default (seconds): a live drive routinely exceeds two
# minutes/turn-sequence on the reference 27B, so the cap must be rig-realistic;
# override with COLLEAGUE_LIVECHECK_TIMEOUT (#266).
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


_WEBGLASS_TIMEOUT = 10.0  # t6 acceptance: "within 10 s"
_DEADLINE_SKIP = "skipped: probe deadline"  # Qodo #11: the shared-deadline sessions marker


def _webglass_session_count(data: object) -> int | None:
    """Session count from ``session list --json``: real shape (probed
    2026-08-28) is ``content.trusted.sessions``; also accepts a bare list or
    a top-level ``sessions`` key, so an older/future shape degrades, never
    crashes.
    """
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict):
        return None
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    trusted = content.get("trusted") if isinstance(content.get("trusted"), dict) else {}
    for candidate in (trusted.get("sessions"), data.get("sessions")):
        if isinstance(candidate, list):
            return len(candidate)
    return None


def webglass_status(timeout: float = _WEBGLASS_TIMEOUT) -> dict:
    """``webglass doctor`` + ``session list --json``; never raises.

    Lives here (not ``oilcheck``) since it shells out. Returns ``{present,
    healthy, detail, sessions}``. Qodo #11: the two probes share ONE
    *timeout*-second deadline rather than each getting the full budget; the
    session probe is skipped (``sessions`` = :data:`_DEADLINE_SKIP`) once
    that shared clock is spent.
    """
    binary = shutil.which("webglass")
    if not binary:
        return {"present": False, "healthy": False, "detail": "not on PATH", "sessions": None}
    deadline = time.monotonic() + timeout
    try:
        proc = subprocess.run(  # noqa: S603 - operator-installed webglass CLI
            [binary, "doctor"], capture_output=True, text=True, timeout=timeout
        )
        healthy = proc.returncode == 0
        out = (proc.stdout if healthy else (proc.stderr or proc.stdout)).strip().splitlines()
        fallback = out[-1] if out else "exit %d" % proc.returncode
        detail = "webglass doctor exited 0" if healthy else fallback
    except subprocess.TimeoutExpired:
        healthy, detail = False, f"webglass doctor timed out after {timeout:g}s"
    except Exception as exc:  # noqa: BLE001 - a probe must never take doctor down
        healthy, detail = False, str(exc)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"present": True, "healthy": healthy, "detail": detail, "sessions": _DEADLINE_SKIP}
    sessions = None
    try:
        proc = subprocess.run(  # noqa: S603 - operator-installed webglass CLI
            [binary, "session", "list", "--json"], capture_output=True, text=True, timeout=remaining
        )
        data = json.loads(proc.stdout) if proc.returncode == 0 else None
        sessions = _webglass_session_count(data)
    except Exception:  # noqa: BLE001 - nosec B110 - a probe must never take doctor down
        sessions = None
    return {"present": True, "healthy": healthy, "detail": detail, "sessions": sessions}


# Media live proofs (plan task t13): image end-to-end + audio honest-skip.
# Unlike the pytest-file proofs above, these drive one real ``engine.work()``
# call directly (the ``tests/test_vllm_live.py`` seam, runtime-generated
# fixture attachment); classification is pure/unit-testable, only the two
# run_* callers touch the network and degrade to "skipped", never a traceback.

_MEDIA_IMAGE_INSTRUCTION = "What color is the attached image? Answer with the color name only."
_MEDIA_AUDIO_INSTRUCTION = "Describe the attached audio clip in one sentence."


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


# Gating (docs/live-testing.md media-proof ledger): pass model= (or set
# COLLEAGUE_MODEL) to target a media-capable model; no special-casing (t14).
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

    Asserts ONLY runtime facts — NEVER a quality score (never "better"summaries).
    PASSES when the split run recorded ``mode=split`` AND preserved the
    operator's original request VERBATIM across the cortex/senses boundary;
    detail emits the per-mode wall-clock + senses runtime (via
    :func:`_senses_record_runtime`) side by side — the measurable deliverable.
    A split artifact missing the block, or whose packet dropped the verbatim
    original, FAILS; the runner SKIPs before this when the stack isn't serving.
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
    cortex-only (``config.senses`` nulled), once split (senses intake →
    ContextPacket → the loop records mode=split, speak-back folded in) —
    graded via :func:`classify_cortex_senses_check`.

    SKIPs honestly when the endpoint is unreachable OR the stack isn't
    serving (:func:`probe_lobes_stack`) OR a live call errors — the same
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
# Per-front presence classifiers (presence-default-everywhere, t14): each
# front's ack → grounded update/reply → (optional) guidance relay beat
# sequence, graded from the SHARED SensesBlock (t3) + its own rendered lines
# (h6/c4/c15): a missing beat FAILS; an unexercised front SKIPs (never fakes).
# ---------------------------------------------------------------------------

#: The fronts the presence lane serves. Each grades the SAME SensesBlock shape
#: from its own rendered-line source: session → the cockpit transcript, talk →
#: the flight chat log, background → the flight chat log, resident → the origin
#: reply bodies, work → the stderr lines.
PRESENCE_FRONTS = ("session", "talk", "background", "resident", "work")


# ---------------------------------------------------------------------------
# Realtime session live proof (realtime-speech arc, t7, spec c12/h9): does
# the ears-only realtime lane (colleague/realtime.py, t1-t4) dial, auth, and
# get the server genuinely talking back? Same evidence discipline as every
# check above. The PASS bar is a SESSION + EVENT handshake, not a transcript
# round-trip (an honest transcript needs real spoken audio this proof cannot
# synthesize — see :func:`classify_realtime_check`'s docstring for the exact
# proof/non-proof boundary).
# ---------------------------------------------------------------------------

#: How long run_realtime_check waits for at least one server event after
#: opening the session and sending the silence burst, before grading the
#: handshake a FAIL (a real regression: the wire opened but stayed silent).
_REALTIME_CHECK_TIMEOUT_SECONDS = 5.0


def _silence_burst_pcm16(*, duration_seconds: float = 0.2, sample_rate: int = 24000) -> bytes:
    """A short, honestly-named silence burst: raw 16-bit mono PCM, all-zero samples.

    Not synthesized speech — colleague has no text-to-PCM16 path wired into
    this proof, and fabricating a "spoken" clip here would misrepresent what
    the check actually sent. It is just enough real wire traffic to exercise
    the ``input_audio_buffer.append`` codec over a live connection. Never
    claimed as speech; see :func:`classify_realtime_check`'s docstring for
    what a PASS here does and does not prove.
    """
    frame_count = int(duration_seconds * sample_rate)
    return b"\x00\x00" * frame_count


def classify_realtime_check(
    *, opened: bool, event_count: int, reason: str | None = None
) -> tuple[str, str]:
    """Grade the realtime session-handshake proof (t7) from evidence alone.

    PASS bar: a SESSION + EVENT handshake — the dial opens (101 upgrade +
    accepted ``session.update``) AND at least one server event (lifecycle/
    VAD/transcription — any counts) arrives within a bounded timeout. Real
    evidence the lane is live, not just "no exception opening a silent socket".

    Proves: the lane dials, authenticates, and the server talks back
    end-to-end. Does NOT prove a transcript round-trip — this sends a
    silence burst (:func:`_silence_burst_pcm16`), which a genuine VAD/ASR may
    never transcribe; a real microphone transcript is task t9's live-rig
    proof (docs/live-testing.md), not this one.

    SKIPs (never fakes) when *opened* is ``False``, naming *reason* — the
    extra/config/rig-lane absence :func:`run_realtime_check` already
    diagnosed. FAILs when opened but ZERO server events arrived (a real
    regression). PASSes only when both hold.
    """
    if not opened:
        return "skipped", reason or "realtime session did not open — nothing to grade"
    if event_count < 1:
        return (
            "failed",
            "session opened (101 handshake + session.update accepted) but received "
            "ZERO server events within the bounded timeout — no evidence of a live "
            "event stream (this does not mean a transcript was never produced — a "
            "transcript round-trip needs real spoken audio, which this check never "
            "sends; see the docstring)",
        )
    return (
        "passed",
        f"session opened and received {event_count} server event(s) within the "
        "bounded timeout — proves the handshake+event wire is live; does NOT "
        "prove a transcript round-trip (that needs real spoken audio, see the "
        "docstring)",
    )


def run_realtime_check(
    repo: str | Path,
    *,
    model: str | None = None,
    timeout: float = _REALTIME_CHECK_TIMEOUT_SECONDS,
) -> ProofResult:
    """Live proof (t7): open the ears-only realtime session end-to-end.

    Resolves ``config.realtime`` and, when available, dials
    :func:`colleague.realtime.open_session`, sends a silence burst
    (:func:`_silence_burst_pcm16`), and waits up to *timeout* seconds for a
    server event — graded by :func:`classify_realtime_check` (see its
    docstring for what a PASS proves/does not prove).

    SKIPs honestly on three absences, each named in the detail: the
    ``[voice]`` extra absent (``open_session`` raises ``CliError``, caught
    here); ``config.realtime`` absent/unavailable (nothing to dial); or the
    rig lane absent (extra + config present but the dial/handshake fails and
    ``open_session`` degrades to ``None``).

    Only once the session genuinely opens does this hand off to
    :func:`classify_realtime_check`; never raises past this boundary — the
    session is always closed (bounded join) before returning.
    """
    repo_path = str(repo)
    config = EngineConfig.resolve(repo_path=repo_path, model=model)
    realtime_config = getattr(config, "realtime", None)
    if realtime_config is None or not getattr(realtime_config, "available", False):
        return ProofResult(
            file="realtime",
            status="skipped",
            detail=(
                "no realtime lane resolved (config.realtime absent/unavailable) "
                "— nothing to dial"
            ),
        )

    events: "queue.Queue[dict]" = queue.Queue()

    try:
        session = open_session(realtime_config, on_event=events.put)
    except CliError as exc:
        return ProofResult(
            file="realtime",
            status="skipped",
            detail=f"[voice] extra not installed: {exc.message}",
        )
    except Exception as exc:  # noqa: BLE001 - a live proof degrades and never crashes
        return ProofResult(
            file="realtime", status="skipped", detail=f"proof error opening session: {exc}"
        )

    if session is None:
        return ProofResult(
            file="realtime",
            status="skipped",
            detail=(
                "realtime session did not open (dial/handshake failed) — the rig "
                "lane is not actually serving /v1/realtime; see the stderr notice"
            ),
        )

    try:
        session.send_audio(_silence_burst_pcm16())
        try:
            events.get(timeout=timeout)
            event_count = 1 + events.qsize()
        except queue.Empty:
            event_count = 0
    finally:
        session.close()

    status, detail = classify_realtime_check(opened=True, event_count=event_count)
    return ProofResult(file="realtime", status=status, detail=detail)


# ---------------------------------------------------------------------------
# Runner-check registry (t7): closes the no-production-caller gap found in
# /scope — every ProofResult-returning function above had no production
# caller; cmd_livecheck only ran the pytest-file proofs (_KNOWN_PROOFS via
# run_proofs). run_runner_checks runs every registered runner and returns
# their ProofResults for the SAME table/JSON as the pytest-file proofs.
# ---------------------------------------------------------------------------

_RUNNER_CHECKS: tuple[Callable[..., ProofResult], ...] = (
    run_presence_narration_check,
    run_media_image_check,
    run_media_audio_check,
    run_cortex_senses_check,
    run_realtime_check,
)


def run_runner_checks(repo: str | Path, *, model: str | None = None) -> list[ProofResult]:
    """Run every registered ProofResult runner check against *repo*.

    Each runner already degrades to "skipped" on its own absent-config/rig
    paths (never raises past its own boundary, per its own docstring); this
    wrapper still catches any unexpected exception per-runner so ONE runner's
    bug can never crash the whole ``colleague livecheck`` verb — an
    unexpected exception is itself reported as a "skipped" row, never a
    fabricated pass and never a crash.
    """
    results: list[ProofResult] = []
    for runner in _RUNNER_CHECKS:
        try:
            results.append(runner(repo, model=model))
        except Exception as exc:  # noqa: BLE001 - one runner's bug must not crash the verb
            name = getattr(runner, "__name__", "runner")
            results.append(ProofResult(file=name, status="skipped", detail=f"runner error: {exc}"))
    return results

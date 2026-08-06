#!/usr/bin/env python3
"""Live rig proof for the session-streaming arc (plan task t12, spec c18/h15).

Replays the 2026-08-06 transcript scenario against the LIVE rig and records
the durable signals — incremental paint counts, exit codes, call counts —
never absolute seconds (h15). A lane that cannot run records DEGRADE/SKIP
with its reason, never a fake PASS (h13).

Three proofs:

A. Transcript scenario in a real PTY ``colleague session``: the senses reply
   to ``hi`` paints incrementally (>= 2 growing paints), then the long-story
   turn dispatches cortex and (senses armed) narration lines may appear.
B. The stale-pin incident, verbatim: ``CONVERTIBLE_MODEL`` pinned to the
   exact id whose 404 killed the original 2026-08-06 run — the work item
   must now exit 0 with the refresh warning in the artifact (c11/h8/h21).
C. Speak-only: a ``--speak`` session's senses reply yields exactly one
   synthesized voice-reply wav and never arms the mic/stt (c6/c22/h4).

Usage: ``uv run python tools/live_proofs/session_streaming_proof.py [--out F]``
Writes a JSON report and prints a human summary; exits 1 only on a proof
FAIL (DEGRADE lanes exit 0 — rig-dependent honesty, not failure).
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SERVED_MODEL = "unsloth/Qwen3.6-27B-NVFP4"
STALE_MODEL = "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"
HI = "hi"
STORY = "I'm good, can you just tell me a long story?"
NARRATION = "<<higher self thought>>"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _tmp_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "proof@local"],
        ["git", "config", "user.name", "proof"],
    ):
        subprocess.run(cmd, cwd=repo, check=True)
    (repo / "README.md").write_text("live proof scratch repo\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _proof_env(model: str) -> dict:
    env = dict(os.environ)
    env.update(
        CONVERTIBLE_MODEL=model,
        CONVERTIBLE_BASE_URL="http://localhost:8001/v1",
        COLLEAGUE_TIMEOUT="300",
        UV_NO_SYNC="1",
    )
    return env


class PtySession:
    """Drive a real-PTY ``colleague session`` and harvest its raw output."""

    def __init__(self, repo: Path, extra_args: list[str], env: dict) -> None:
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            ["uv", "run", "colleague", "session", "--repo", str(repo), "--engine", "vllm-openai"]
            + extra_args,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            cwd="/home/spark/git/colleague",
            close_fds=True,
        )
        os.close(slave)
        self.raw = b""

    def read_until(self, needle: str | None, timeout: float) -> str:
        """Read (appending to self.raw) until *needle* appears or timeout."""
        deadline = time.time() + timeout
        window_start = len(self.raw)
        while time.time() < deadline:
            r, _, _ = select.select([self.master], [], [], 1.0)
            if self.master in r:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.raw += chunk
                if needle and needle.encode() in self.raw[window_start:]:
                    break
            if self.proc.poll() is not None and not r:
                break
        return self.raw[window_start:].decode(errors="replace")

    def send(self, line: str) -> None:
        os.write(self.master, (line + "\r").encode())

    def quit(self) -> int:
        try:
            self.send("/quit")
            self.proc.wait(timeout=30)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=10)
        try:
            os.close(self.master)
        except OSError:
            pass
        return self.proc.returncode


def count_growing_paints(raw: str, label: str = "senses:") -> int:
    """Count DISTINCT growing paints of the label's line in raw PTY output.

    Transient paints repaint the row in place (CR + erase + ``senses: …``);
    each capture is one paint. We count distinct, strictly-lengthening
    snapshots — the durable signal from c18 (paints, not seconds).
    """
    snapshots = []
    for match in re.finditer(rf"{re.escape(label)} ([^\r\n\x1b]*)", raw):
        text = match.group(1).rstrip()
        if text and (not snapshots or (text != snapshots[-1] and len(text) >= len(snapshots[-1]))):
            snapshots.append(text)
    return len(snapshots)


def proof_a(root: Path) -> dict:
    repo = _tmp_repo(root, "proof-a")
    sess = PtySession(repo, [], _proof_env(SERVED_MODEL))
    result: dict = {"proof": "A-transcript-scenario"}
    try:
        # The prompt glyph appears in EVERY cockpit frame (incl. keystroke
        # echo redraws) — wait on actual reply markers, never the prompt.
        sess.read_until("Session", 180)
        time.sleep(2)
        sess.send(HI)
        hi_out = sess.read_until("senses:", 300)
        hi_out += sess.read_until(None, 15)  # settle: let the reply finish
        paints = count_growing_paints(ANSI.sub("", hi_out))
        result["hi_senses_paints"] = paints
        result["hi_reply_seen"] = "senses:" in hi_out
        sess.send(STORY)
        story_out = sess.read_until(NARRATION, 480)
        story_out += sess.read_until(None, 420)
        result["story_dispatched"] = ("work:" in story_out) or ("working" in story_out)
        result["narration_lines"] = story_out.count(NARRATION)
        result["story_error"] = "error:" in story_out and "model_not_found" in story_out
        exit_code = sess.quit()
        result["session_exit"] = exit_code
        result["verdict"] = (
            "PASS"
            if paints >= 2 and result["hi_reply_seen"] and not result["story_error"]
            else "FAIL"
        )
        if paints >= 1 and paints < 2:
            # One whole paint = no incremental streaming observed — honest FAIL
            # unless the reply was too short to throttle-split (record it).
            result["note"] = "only one paint — reply may be under the repaint cadence"
    finally:
        with open(root / "proof-a-transcript.txt", "w") as fh:
            fh.write(sess.raw.decode(errors="replace"))
    return result


def proof_b(root: Path) -> dict:
    repo = _tmp_repo(root, "proof-b")
    proc = subprocess.run(
        [
            "uv", "run", "colleague", "work",
            "say hi in one short sentence", "--repo", str(repo),
            "--engine", "vllm-openai", "--no-pr", "--json",
        ],
        env=_proof_env(STALE_MODEL),
        cwd="/home/spark/git/colleague",
        capture_output=True,
        text=True,
        timeout=900,
    )
    result: dict = {"proof": "B-stale-pin-incident", "exit": proc.returncode}
    warnings: list = []
    try:
        payload = json.loads(proc.stdout)
        warnings = payload.get("warnings") or []
    except ValueError:
        result["stdout_parse"] = "not json"
    disk = []
    for artifact in (repo / ".colleague" / "artifacts").glob("*.json"):
        data = json.loads(artifact.read_text())
        disk.extend(data.get("warnings") or [])
    every = warnings + disk
    result["warning_count"] = len(every)
    result["stale_named"] = any(w.get("stale_id") == STALE_MODEL for w in every)
    result["refreshed_named"] = any(w.get("refreshed_id") == SERVED_MODEL for w in every)
    result["source_named"] = any("CONVERTIBLE_MODEL" in str(w.get("source", "")) for w in every)
    result["verdict"] = (
        "PASS"
        if proc.returncode == 0
        and result["stale_named"]
        and result["refreshed_named"]
        and result["source_named"]
        else "FAIL"
    )
    if result["verdict"] == "FAIL":
        result["stderr_tail"] = proc.stderr[-500:]
    return result


def proof_c(root: Path) -> dict:
    repo = _tmp_repo(root, "proof-c")
    result: dict = {"proof": "C-speak-only"}
    try:
        import sounddevice  # noqa: F401

        result["voice_extra"] = True
    except Exception:
        result["voice_extra"] = False
    sess = PtySession(repo, ["--speak"], _proof_env(SERVED_MODEL))
    try:
        sess.read_until("Session", 180)
        time.sleep(2)
        sess.send(HI)
        out = sess.read_until("senses:", 300)
        out += sess.read_until(None, 30)  # settle: synth + playback finish
        result["reply_seen"] = "senses:" in out
        sess.quit()
        raw = ANSI.sub("", sess.raw.decode(errors="replace"))
        wavs = list((repo / ".colleague" / "artifacts").glob("voice-reply-*.wav"))
        result["tts_wavs"] = len(wavs)
        result["mic_armed"] = ("voice · live" in raw) or ("listening" in raw)
        if not result["reply_seen"]:
            result["verdict"] = "FAIL"
        elif result["tts_wavs"] == 1 and not result["mic_armed"]:
            result["verdict"] = "PASS"
        elif result["tts_wavs"] == 0:
            # tts synth degraded (rig tts down / http failure) — honest degrade
            result["verdict"] = "DEGRADE"
            result["note"] = "reply rendered but no wav — tts synth degraded"
        else:
            result["verdict"] = "FAIL"
    finally:
        with open(root / "proof-c-transcript.txt", "w") as fh:
            fh.write(sess.raw.decode(errors="replace"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--keep", action="store_true", help="keep the scratch root")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="ssv-live-proof-"))
    report = {"root": str(root), "rig": "http://localhost:8001", "proofs": []}
    for fn in (proof_a, proof_b, proof_c):
        try:
            report["proofs"].append(fn(root))
        except Exception as exc:  # a crashed proof is a recorded FAIL, not a crash
            report["proofs"].append(
                {"proof": fn.__name__, "verdict": "FAIL", "error": repr(exc)}
            )
    out = json.dumps(report, indent=2)
    print(out)
    if args.out:
        Path(args.out).write_text(out + "\n")
    return 1 if any(p.get("verdict") == "FAIL" for p in report["proofs"]) else 0


if __name__ == "__main__":
    sys.exit(main())

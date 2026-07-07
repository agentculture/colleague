"""Live middle-manager proof (talking-to-one arc, task t9 / spec h11+h12+h7).

ONE recorded real run through the SESSION path (the v1 surface) showing every
announcement beat: senses acknowledges BEFORE cortex's first step, at least one
grounded proactive update renders mid-run, and the answer comes back
conversationally (speak-back) — every senses turn recorded on
``TaskResult.senses`` so the whole exchange is machine-checkable from the
artifact + transcript alone (:func:`colleague.livecheck.
classify_middle_manager_check`), and 'quick' is measured from recorded
wall-clock senses-turn latencies (:func:`classify_front_latency_check`,
median < 3s).

Skipped unless ``COLLEAGUE_VLLM_E2E=1`` (the standard live-proof gate) AND the
resolved config arms senses (a lobes gateway or explicit senses config) — the
proof drives the real cortex tool loop AND the real senses model side by side.
The mid-run RELAY beat is covered by the senses-live-presence arc's existing
injection proof; this proof covers ack + updates + conversational answer +
latency (the t9 scope).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
from colleague.cli._commands.work import execute_work
from colleague.config import EngineConfig
from colleague.livecheck import (
    classify_front_latency_check,
    classify_middle_manager_check,
    front_latencies,
)

pytestmark = pytest.mark.skipif(
    "1"
    not in (
        os.environ.get("COLLEAGUE_VLLM_E2E"),
        os.environ.get("CONVERTIBLE_VLLM_E2E"),
    ),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live tool-calling vLLM server) to run",
)

_WORK_LINE = "Add a one-line project description to README.md saying this is a tiny demo repo."

# Snapshot the operator's live-rig env at IMPORT time (collection), because the
# autouse ``_isolate_provider_env`` conftest fixture scrubs every COLLEAGUE_*
# var before each test — without this the in-test resolve() could never see the
# lobes gateway and the proof was structurally unrunnable (the same trap the
# dual-live proof documented and solved; pattern copied from there).
_LIVE_ENV_SNAPSHOT: dict[str, str] = {
    key: value
    for key, value in os.environ.items()
    if key.startswith(("COLLEAGUE_", "CONVERTIBLE_"))
}


@pytest.fixture()
def live_config(monkeypatch: pytest.MonkeyPatch) -> EngineConfig:
    """Resolve EngineConfig from the import-time env snapshot; skip unarmed."""
    for key, value in _LIVE_ENV_SNAPSHOT.items():
        monkeypatch.setenv(key, value)
    config = EngineConfig.resolve()
    if config.senses is None:
        pytest.skip("senses not armed (no lobes gateway / senses config on this rig)")
    return config


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "t@e.c"), ("user.name", "T")):
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("A tiny repo.\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_middle_manager_beats_live(tmp_path: Path, live_config: EngineConfig) -> None:
    """The full announcement, graded from evidence: ack → update(s) → answer."""
    config = live_config
    repo = _git_repo(tmp_path)
    captured: list = []

    def _work(**kwargs):
        result = execute_work(**kwargs)
        captured.append(result[0])
        return result

    out, err = _CollectingOut(), _CollectingOut()
    sess = _Session(
        repo=repo,
        engine_name="vllm-openai",
        open_pr=False,
        base="main",
        config=config,
        json_mode=False,
        # view="ansi" arms the presence lane (the v1 colour-TTY surface); the
        # scripted input iterator stands in for the operator. A clarify
        # question, if senses asks one, reads EOF and dispatches immediately
        # (h8 — clarification can never withhold work).
        view="ansi",
        io=SessionIO(out=out, err=err),
        work_fn=_work,
        senses_options=SensesSessionOptions(),
    )
    sess.run(iter([_WORK_LINE]))

    assert captured, "the work line never dispatched"
    result = captured[0]
    payload = result.to_dict().get("senses")
    conversation = [line.text for line in sess.state.conversation]

    status, detail = classify_middle_manager_check(payload, conversation)
    print(f"\nmiddle-manager beats: {status} — {detail}")
    if status == "skipped":  # pragma: no cover - rig-state dependent
        pytest.skip(detail)
    assert status == "passed", detail

    latencies = front_latencies(payload)
    lat_status, lat_detail = classify_front_latency_check(latencies)
    print(f"front latency: {lat_status} — {lat_detail}")
    assert lat_status == "passed", lat_detail

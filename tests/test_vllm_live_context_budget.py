"""Opt-in live proof of context-overflow graceful degradation (#127, §7).

Sibling to the other ``test_vllm_live_*.py`` files; skipped unless
``COLLEAGUE_VLLM_E2E=1``. The bounded tool-loop degrades on small-context models
two ways (``colleague/context.py`` + ``colleague/loop.py``):

* **Proactive windowing** — before each model turn the running history is trimmed
  to ``context_budget`` tokens, dropping the oldest turns and inserting exactly one
  placeholder (``context._PLACEHOLDER_TEXT``).
* **Reactive trim+retry** — a ``complete()`` error matching
  ``context.is_context_overflow`` shrinks the budget (×0.6) and retries up to
  ``_MAX_OVERFLOW_RETRIES`` times before preserving a partial result.

The mechanics are already deterministic (``tests/test_context_window.py``,
``tests/test_loop_degradation.py``, ``tests/test_e2e_degradation.py`` — the last
drives the full vLLM-engine path with a real-shaped overflow ``HTTPError``,
bounded retry, and a preserved partial). What none of those prove is the **live**
layer: a real served model coping with windowed history, and a real recovery after
an overflow. This file adds exactly that, by spying on the engine's HTTP seam
(``vllm_openai._post_json``) to observe/inject without leaving the production path.

Covered:

* **Proactive (live)** — a small ``context_budget`` + a forced large file read makes
  the loop window real requests: the placeholder appears in an actual chat request
  and the drive degrades gracefully (terminal result, no crash).
* **Reactive (induced, live recovery)** — the procedure's "induced overflow": the
  first chat call raises a real-shaped overflow, the loop trims+retries, and the
  retry RECOVERS against the **real** model.

DETERMINISTIC (cited, not re-proven live): bounded termination
(``_MAX_OVERFLOW_RETRIES``) and non-recoverable partial preservation
(``tests/test_loop_degradation.py``, ``tests/test_e2e_degradation.py``); windowing
primitives + overflow-phrase detection (``tests/test_context_window.py``). A real
server-side 262k overflow is not deliberately induced (unreliable/costly) — the
overflow is injected at the HTTP seam, with recovery served by the real model.

Run it (rig up) like::

    COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live_context_budget.py -v -s
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import colleague.engines.vllm_openai as vllm_openai
from colleague.cli._commands.drive import execute_drive
from colleague.config import EngineConfig
from colleague.context import _PLACEHOLDER_TEXT
from colleague.contract import OK, Task

pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _chat_messages(captured: list[tuple[str, list]]) -> list[list]:
    """The message lists from captured chat-completions calls (not /tokenize)."""
    return [msgs for url, msgs in captured if "/chat/completions" in url]


# ---------------------------------------------------------------------------
# Proactive windowing — a small budget trims real requests and inserts the
# placeholder; the drive degrades gracefully instead of hard-failing.
# ---------------------------------------------------------------------------


def test_live_small_budget_windows_history_with_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    # A CHAIN of files, each naming the next, each padded large. This forces the
    # model into SEQUENTIAL, content-pulling turns no matter which tool it picks:
    # it can't batch the reads (each names the next) and it can't shortcut to a
    # line-count (the "next" instruction lives in the content). After a couple of
    # turns the accumulated big content blows past the small budget, so the loop
    # must drop the oldest turn and insert the placeholder. (Before this, a plain
    # "count the lines" task let the model use run_command(wc) — tiny history, no
    # windowing — which is why the trigger has to be chained, not a single read.)
    pad = "\n".join(f"padding line {i:03d}: the quick brown fox jumps over it" for i in range(120))
    steps = ["step0", "step1", "step2", "step3"]
    for i, name in enumerate(steps):
        nxt = f"next: {steps[i + 1]}.txt" if i + 1 < len(steps) else "STOP"
        (repo / f"{name}.txt").write_text(f"{nxt}\n\n{pad}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add chain files")

    captured: list[tuple[str, list]] = []
    orig_post = vllm_openai._post_json

    def spy(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        # Snapshot a COPY of each message dict: the loop mutates ctx.messages in
        # place (window_messages writes back via [:]), so storing the live list
        # would show every turn its final state.
        msgs = [dict(m) for m in payload.get("messages", []) if isinstance(m, dict)]
        captured.append((url, msgs))
        return orig_post(url, payload, api_key=api_key, timeout=timeout)

    monkeypatch.setattr(vllm_openai, "_post_json", spy)

    # Small budget so a couple of chained reads overflow it and force windowing.
    # Cap steps so a confused-by-trimming model still terminates fast.
    config = EngineConfig.resolve(context_budget_tokens=1000, max_steps=10)
    task = Task.new(
        str(repo),
        "Read step0.txt. Each file's first line names the next file to read "
        "(e.g. 'next: step1.txt'). Follow that chain, reading each named file in "
        "turn, until a file says STOP. Then call finish.",
        engine="vllm-openai",
    )
    result, artifact_path = execute_drive(
        repo=repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=config,
    )

    chat_msgs = _chat_messages(captured)
    sizes = [len(m) for m in chat_msgs]
    print(f"\n[live #127 proactive] drive {result.task_id} -> {artifact_path}")
    print(f"[live #127 proactive] chat-request message counts per turn: {sizes}")
    print(f"[live #127 proactive] steps: {[(s.tool, s.ok) for s in result.steps]}")

    # Graceful degradation: despite aggressive windowing every turn, the drive still
    # completed successfully (it didn't crash, hang, or abort on the trimmed context).
    assert result.status == OK, result.error
    # Windowing fired live: the placeholder landed in a real chat request, proving
    # the loop dropped oldest history to fit the small budget.
    placeholder_seen = any(
        _PLACEHOLDER_TEXT in (m.get("content") or "")
        for msgs in chat_msgs
        for m in msgs
        if isinstance(m, dict)
    )
    assert placeholder_seen, f"no windowing placeholder in any chat request; sizes={sizes}"
    # History stayed bounded: windowing keeps each request to head+placeholder+tail,
    # so the message count never grows with the step count (it would, unwindowed).
    assert sizes and max(sizes) <= 12, f"windowed requests should stay small; sizes={sizes}"


# ---------------------------------------------------------------------------
# Reactive trim+retry — an induced overflow on the first call triggers the
# shrink-and-retry, which recovers against the REAL model.
# ---------------------------------------------------------------------------

_RECOVER_TASK = "Create a file named HELLO.txt containing exactly the text: hello from colleague"


def test_live_induced_overflow_retries_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")

    orig_post = vllm_openai._post_json
    chat_calls = {"n": 0}

    def induce(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        if "/chat/completions" in url:
            chat_calls["n"] += 1
            if chat_calls["n"] == 1:
                # Real-shaped overflow → matches context.is_context_overflow, so the
                # loop trims the budget and retries instead of aborting.
                raise RuntimeError("This model's maximum context length is 4096 tokens")
        return orig_post(url, payload, api_key=api_key, timeout=timeout)

    monkeypatch.setattr(vllm_openai, "_post_json", induce)

    # Pin a positive budget so the reactive shrink-and-retry path engages regardless
    # of the environment — a COLLEAGUE_CONTEXT_BUDGET of 0/negative would disable it.
    config = EngineConfig.resolve(context_budget_tokens=192000, max_steps=8)
    task = Task.new(str(repo), _RECOVER_TASK, engine="vllm-openai")
    result, artifact_path = execute_drive(
        repo=repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=config,
    )
    print(f"\n[live #127 reactive] drive {result.task_id} -> {artifact_path}")
    print(
        f"[live #127 reactive] chat calls: {chat_calls['n']}, steps: "
        f"{[(s.tool, s.ok) for s in result.steps]}"
    )

    # The induced overflow forced a retry (≥2 chat calls)...
    assert chat_calls["n"] >= 2, "the induced overflow did not trigger a retry"
    # ...and the retry recovered against the REAL model: the drive finished OK and
    # the recovered turn actually created HELLO.txt (not merely "some" write).
    assert result.status == OK, result.error
    assert "HELLO.txt" in result.changed_files, result.changed_files
    wrote_hello = [
        s
        for s in result.steps
        if s.tool == "write_file" and s.ok and s.arguments.get("path") == "HELLO.txt"
    ]
    assert wrote_hello, [(s.tool, s.ok, s.arguments.get("path")) for s in result.steps]

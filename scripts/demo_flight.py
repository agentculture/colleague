#!/usr/bin/env python3
"""Reproducible demo of piloting a colleague flight.

Runs the full piloting sequence end-to-end against the in-process bounded loop,
using ONLY files under ``.colleague/`` — no socket, no daemon:

    dispatch  ->  watch the live feed  ->  see it heading the wrong way
              ->  send mid-flight guidance  ->  watch it change course
              ->  cooperative stop  ->  inspect the preserved partial

A single ``complete`` closure plays BOTH the model (the flight) and the pilot
acting between turns (it writes the per-flight control file the way a real pilot
would via ``colleague flight guide`` / ``colleague flight stop``). Deterministic:
no clock, no randomness, no network. Run it directly to see the narrated trace::

    uv run python scripts/demo_flight.py

or import :func:`run_demo` from a test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from colleague import flight
from colleague.contract import Task
from colleague.loop import ModelResponse, ToolCall, run


def _say(line: str) -> None:
    print(line)


def run_demo(repo: Path, *, narrate: bool = False) -> dict:
    """Drive one piloted flight; return a dict summarizing what happened.

    The returned dict has: ``wrong_written`` / ``right_written`` (did the flight
    touch each file), ``guidance_seen_turn`` (the turn index whose prompt carried
    the pilot's guidance), ``stopped_without_finish`` and ``summary`` from the
    preserved partial, and ``files_only_under_colleague`` (the control plane never
    escaped ``.colleague/``).
    """
    task = Task.new(str(repo), "tidy the module", watch=True)
    feed = flight.feed_path(repo, task.id)
    control = flight.control_path(repo, task.id)

    state = {"turn": 0, "guidance_seen_turn": None}

    def complete(messages: list[dict]) -> ModelResponse:
        state["turn"] += 1
        turn = state["turn"]

        # Did this turn's prompt carry the pilot's guidance? (proves the redirect
        # reached the model — it lands at the boundary BEFORE this completion).
        if any("[pilot guidance]" in (m.get("content") or "") for m in messages):
            state["guidance_seen_turn"] = turn

        if turn == 1:
            # The flight heads the WRONG way: it starts editing wrong.txt.
            if narrate:
                _say("  turn 1 — flight starts editing  wrong.txt  (heading the wrong way)")
            # PILOT (watching the feed) redirects via the control file — exactly what
            # `colleague flight guide <id> "edit right.txt instead"` writes.
            flight.append_guidance(
                repo, task.id, "stop touching wrong.txt — edit right.txt instead"
            )
            if narrate:
                feed_lines = feed.read_text().splitlines() if feed.exists() else []
                _say(f"  pilot  — live feed has {len(feed_lines)} record(s); sends GUIDANCE")
            return ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "wrong.txt", "content": "oops\n"})]
            )

        if turn == 2:
            # The guidance was injected at the boundary; the flight changes course.
            if narrate:
                _say("  turn 2 — flight SAW the guidance and changes course -> edits right.txt")
            # PILOT calls it back: `colleague flight stop <id>`.
            flight.write_stop(repo, task.id)
            if narrate:
                _say("  pilot  — course corrected; sends cooperative STOP")
            return ModelResponse(
                tool_calls=[
                    ToolCall("2", "write_file", {"path": "right.txt", "content": "fixed\n"})
                ]
            )

        # Turn 3 is never reached: the boundary check honors the stop first.
        if narrate:
            _say("  turn 3 — (not reached: the pilot's stop ends the flight at the boundary)")
        return ModelResponse(tool_calls=[ToolCall("3", "finish", {"summary": "done"})])

    if narrate:
        _say(f"dispatch — flight {task.id} armed (watch=True)")
        _say(f"           feed:    {feed}")
        _say(f"           control: {control}")

    result = run(complete, task, max_steps=10)

    if narrate:
        _say("")
        _say(
            f"result   — status={result.status} "
            f"stopped_without_finish={result.stopped_without_finish}"
        )
        _say(f"           summary: {result.summary}")
        _say(f"           changed: {result.changed_files}")

    # The control plane never escaped .colleague/ (no socket/daemon, files only).
    flight_dir = flight.flight_dir(repo)
    files_only_under_colleague = str(flight_dir).endswith(str(Path(".colleague") / "flight"))

    return {
        "task_id": task.id,
        "wrong_written": (repo / "wrong.txt").exists(),
        "right_written": (repo / "right.txt").exists(),
        "guidance_seen_turn": state["guidance_seen_turn"],
        "stopped_without_finish": result.stopped_without_finish,
        "summary": result.summary,
        "changed_files": list(result.changed_files),
        "files_only_under_colleague": files_only_under_colleague,
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _say("=== colleague flight — piloting demo ===\n")
        outcome = run_demo(repo, narrate=True)
        _say("")
        ok = (
            outcome["wrong_written"]
            and outcome["right_written"]
            and outcome["guidance_seen_turn"] == 2
            and outcome["stopped_without_finish"]
        )
        _say(
            "=== flight changed course on pilot guidance, then stopped cooperatively"
            f" with a preserved partial: {'OK' if ok else 'FAILED'} ==="
        )


if __name__ == "__main__":
    main()

"""Experiment A — senses fidelity gate (pre-registered runner).

Protocol: docs/experiments/2026-08-05-experiment-a-senses-fidelity.md
(committed BEFORE the first measured run; see deviation d1 on the
three-tier-execution plan for why this is a committed runner script and
not a ``colleague experiment`` invocation).

Drives the PRODUCTION senses talk lane (`colleague.senses.run_senses_talk`)
against the live rig's senses role with the embodiment failure shape:
domain-A (greenhouse) background knowledge, domain-B (colleague systems)
questions, a good worker answer per turn. Emits one JSON line per turn to
stdout and a summary block at the end. Read-only against the repo: no
flight files, no artifacts, no state.
"""

from __future__ import annotations

import json
import sys
import time

from colleague import registry
from colleague.config import EngineConfig
from colleague.senses import run_senses_talk, senses_engine_config

# Domain-A background — the knowledge block senses must NOT recite over the
# current answer (mirrors the embodiment live session's greenhouse seed).
FEED_TAIL = "\n".join(
    [
        "sensor: cactus-shelf offline since 06:40",
        "sensor: fern-bed moisture at 42 percent",
        "lamp: grow-bank B on a 14-hour cycle",
        "irrigation: drip line 3 flow anomaly logged",
        "sensor: cactus-shelf offline since 06:40",
        "sensor: fern-bed moisture at 42 percent",
        "note: misting schedule unchanged this week",
        "lamp: grow-bank B on a 14-hour cycle",
    ]
)

TASK_STATE = (
    "greenhouse watch: cactus-shelf sensor offline; fern-bed 42 percent; "
    "drip line 3 anomaly; grow-bank B 14h cycle"
)

# Six domain-B turns: (operator question, worker answer to relay).
TURNS = [
    (
        "What does the affected-tests gate do when pytest is missing?",
        "The affected-tests gate degrades to skipped when pytest is "
        "unavailable; it never blocks the run.",
    ),
    (
        "How many episodes does an armed --until-done run allow by default?",
        "An armed --until-done run caps at 5 episodes by default; 0 means "
        "unlimited.",
    ),
    (
        "What happens when the approvals file is absent?",
        "An absent approvals.json is a strict no-op: nothing is approved and "
        "nothing is blocked by it.",
    ),
    (
        "Which linters does the lint pre-finish gate run?",
        "The lint gate auto-fixes changed files with the configured linters: "
        "black, isort, ruff, and flake8.",
    ),
    (
        "What is the default engine when COLLEAGUE_ENGINE is unset?",
        "The default engine is vllm-openai; colleague never silently falls "
        "back to mock.",
    ),
    (
        "Where do run artifacts land on disk?",
        "Run artifacts land under the repo's .colleague directory, one JSON "
        "file per work item.",
    ),
]


def main() -> int:
    config = EngineConfig.resolve(repo_path=".")
    senses_config = senses_engine_config(config)
    if senses_config is None:
        print("FATAL: no senses model resolved (lobes unarmed?)", file=sys.stderr)
        return 1
    engine = registry.load("vllm-openai")

    history: list[dict[str, str]] = []
    rows = []
    for i, (question, worker_answer) in enumerate(TURNS, 1):
        t0 = time.monotonic()
        record = run_senses_talk(
            question,
            feed_tail=FEED_TAIL,
            packet=None,
            task_state=TASK_STATE,
            senses_config=senses_config,
            make_complete=engine.make_complete,
            make_count_tokens=engine.make_count_tokens(senses_config),
            history=list(history) or None,
            worker_answer=worker_answer,
        )
        wall_ms = int((time.monotonic() - t0) * 1000)
        if record is None:
            row = {"turn": i, "error": "no record (talk lane unavailable)"}
        else:
            answer = record.get("answer", "")
            row = {
                "turn": i,
                "question": question,
                "worker_answer": worker_answer,
                "answer": answer,
                "verbatim_presence": bool(record.get("verbatim_presence")),
                "knowledge_repetition": bool(record.get("knowledge_repetition")),
                "fallback": bool(record.get("fallback")),
                "degraded": bool(record.get("degraded")),
                "latency_ms": wall_ms,
                "worker_answer_visible": worker_answer in answer,
            }
            history.append({"role": "operator", "content": question})
            history.append({"role": "senses", "content": answer})
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    ok_rows = [r for r in rows if "error" not in r]
    summary = {
        "turns": len(rows),
        "completed": len(ok_rows),
        "visible": sum(1 for r in ok_rows if r["worker_answer_visible"]),
        "fallbacks": sum(1 for r in ok_rows if r["fallback"]),
        "knowledge_repetition": sum(1 for r in ok_rows if r["knowledge_repetition"]),
        "degraded": sum(1 for r in ok_rows if r["degraded"]),
        "median_latency_ms": (
            sorted(r["latency_ms"] for r in ok_rows)[len(ok_rows) // 2] if ok_rows else None
        ),
    }
    print("SUMMARY " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Experiment C — strategist value gate (pre-registered runner).

Protocol: docs/experiments/2026-08-06-experiment-c-strategist-value.md
(committed BEFORE the first measured run; deviation d1 explains the vehicle,
deviation d2 the measured-scope limit).

Two matched arms, four trials each, against the LIVE cortex dial through the
real configurator surface (`colleague.configurator.review_and_queue`):

* ``mismatch`` — the episode digest describes a Python/pytest repo while the
  baseline knowledge block carries Java/Gradle conventions (the misconfigured
  actor #363 §5 says was never tested);
* ``control``  — the knowledge block matches the episode digest.

Counted per trial: proposals (by target), refusals, whether any proposal is a
*valid corrective* (targets the mismatched knowledge/strategist surface),
latency, degradations. Task-outcome improvement is OUT of scope here (d2 /
issue #366: applied content does not yet reach the next episode's surface).
"""

from __future__ import annotations

import json
import sys
import time

from colleague.config import EngineConfig
from colleague.configevents import ConfigEventStream
from colleague.configlifecycle import EpisodeConfigLifecycle, EpisodeConfigSnapshot
from colleague.configurator import (
    ConfiguratorReviewInput,
    resolve_cortex_dial,
    review_and_queue,
)
from colleague.lattice import CapabilityCatalog

CATALOG = CapabilityCatalog(
    tool_ids=("read_file", "write_file", "edit_file", "run_command", "list_dir", "finish")
)

JAVA_KNOWLEDGE = (
    "repo conventions: Java 17, Gradle build, checkstyle mandatory",
    "tests run with ./gradlew test; JUnit 5",
    "source lives under src/main/java",
)

PY_KNOWLEDGE = (
    "repo conventions: Python 3.12, uv-managed, black+flake8",
    "tests run with uv run pytest -q",
    "source lives under the package directory",
)

MISMATCH_DIGEST = (
    "episode summary: the task is in a Python package (pyproject.toml, uv). "
    "The worker edited calc.py and ran 'uv run pytest -q' (4 passed). "
    "Configured knowledge says: Java 17 Gradle repo, checkstyle mandatory, "
    "tests via ./gradlew test, source under src/main/java. "
    "Note: the worker first tried './gradlew test' (command not found) and "
    "looked for src/main/java (no such directory) before recovering."
)

CONTROL_DIGEST = (
    "episode summary: the task is in a Python package (pyproject.toml, uv). "
    "The worker edited calc.py and ran 'uv run pytest -q' (4 passed). "
    "Configured knowledge says: Python 3.12 uv-managed repo, black+flake8, "
    "tests via uv run pytest -q. No tooling friction was observed."
)

CORRECTIVE_TARGETS = {
    "worker.knowledge",
    "senses.knowledge",
    "worker.prompt.strategist",
}

TRIALS = 4


def main() -> int:
    config = EngineConfig.resolve(repo_path=".")
    cortex_config = resolve_cortex_dial(config)
    if cortex_config is None:
        print("FATAL: no cortex dial resolvable (lobes unarmed?)", file=sys.stderr)
        return 1

    rows = []
    for arm, knowledge, digest in (
        ("mismatch", JAVA_KNOWLEDGE, MISMATCH_DIGEST),
        ("control", PY_KNOWLEDGE, CONTROL_DIGEST),
    ):
        for trial in range(1, TRIALS + 1):
            lifecycle = EpisodeConfigLifecycle(
                EpisodeConfigSnapshot(knowledge_entries=knowledge),
                catalog=CATALOG,
            )
            stream = ConfigEventStream()
            t0 = time.monotonic()
            result = review_and_queue(
                ConfiguratorReviewInput(digest=digest),
                catalog=CATALOG,
                lifecycle=lifecycle,
                stream=stream,
                cortex_config=cortex_config,
                engine_name="vllm-openai",
            )
            wall_ms = int((time.monotonic() - t0) * 1000)
            proposed_targets = [ev.target for ev in stream.replay() if ev.kind == "proposed"]
            row = {
                "arm": arm,
                "trial": trial,
                "proposed": result.proposed,
                "verified": result.verified,
                "refused": result.refused,
                "degraded": result.degraded,
                "degraded_reason": result.degraded_reason,
                "corrective": any(t in CORRECTIVE_TARGETS for t in proposed_targets),
                "targets": proposed_targets,
                "latency_ms": wall_ms,
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    for arm in ("mismatch", "control"):
        arm_rows = [r for r in rows if r["arm"] == arm]
        summary = {
            "arm": arm,
            "trials": len(arm_rows),
            "detections": sum(1 for r in arm_rows if r["corrective"]),
            "interventions": sum(1 for r in arm_rows if r["proposed"]),
            "refusals": sum(r["refused"] for r in arm_rows),
            "degraded": sum(1 for r in arm_rows if r["degraded"]),
            "median_latency_ms": sorted(r["latency_ms"] for r in arm_rows)[len(arm_rows) // 2],
        }
        print("ARM " + json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

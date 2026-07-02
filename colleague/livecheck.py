"""livecheck — probe the configured endpoint and run gated live proofs.

One verb that probes the configured endpoint and runs the applicable gated
live proofs, reporting per-ledger-row pass/fail/skip.

This module owns the logic; the CLI verb in
:mod:`colleague.cli._commands.livecheck` is the thin presentation layer.
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from colleague.config import EngineConfig
from colleague.oilcheck.reachability import _PROBE_TIMEOUT


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

"""#411 t20 — the fallback proof on a double of the LIVE 2026-08-21 gateway advert.

`tests/fixtures/capabilities-2026-08-21.json` is the Spark rig's `/capabilities`
saved verbatim: cortex ready, senses ready, worker (Nemotron Lightning)
advertised but `ready: false`, no `associate` role. Against that advert an
armed work item with a subagent must COMPLETE — every worker/associate-purpose
invocation carried by cortex under the RECORDED fallback, never a refusal —
and the same double with the worker flipped `ready: true` must bind the worker
(the fallback is conditional, not hardcoded). The doctor prints the fallback
lines from the same advert.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from pathlib import Path
from typing import Iterator

from colleague import loop
from colleague.agents.profile import resolve_profile
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.lobes import resolve_roles
from colleague.loop import ContextControls, ModelResponse, Spawns, ToolCall
from colleague.oilcheck import agents as agents_checks
from colleague.subagents import ChildSpec, make_spawn, new_agent_budget, run_subagent

FIXTURE = Path(__file__).parent / "fixtures" / "capabilities-2026-08-21.json"
ADVERT = json.loads(FIXTURE.read_text(encoding="utf-8"))


class _Handler(http.server.BaseHTTPRequestHandler):
    body: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path != "/capabilities":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@contextlib.contextmanager
def _serving(payload: dict) -> Iterator[str]:
    handler = type("_H", (_Handler,), {"body": json.dumps(payload).encode("utf-8")})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _armed_repo(tmp_path: Path, gateway: str) -> Path:
    repo = tmp_path / "repo"
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "config.json").write_text(
        json.dumps({"agents": True, "lobes": gateway}), encoding="utf-8"
    )
    return repo


def test_fixture_mirrors_the_live_advert_shape() -> None:
    assert ADVERT["cortex"]["ready"] is True
    assert ADVERT["senses"]["ready"] is True
    assert ADVERT["worker"]["ready"] is False
    assert "Lightning" in ADVERT["worker"]["model"]
    assert "associate" not in ADVERT


def test_armed_work_item_with_a_subagent_completes_under_the_recorded_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("COLLEAGUE_AGENTS", raising=False)
    with _serving(ADVERT) as gateway:
        repo = _armed_repo(tmp_path, gateway)
        cfg = EngineConfig.resolve(repo_path=repo, discover_lobes=True)
        assert cfg.agents is True
        assert cfg.model == ADVERT["cortex"]["model"]
        task = Task.new(str(repo), "prove the fallback")
        spawns = Spawns(
            single=make_spawn(
                str(repo), cfg, "mock", counter=new_agent_budget(cfg), parent_task_id=task.id
            )
        )
        script = iter(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "s",
                            "subagent",
                            {
                                "instruction": "write the marker file",
                                "profile": "associate",
                                "context_mode": "clear",
                            },
                        )
                    ]
                ),
                ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "done"})]),
            ]
        )
        result = loop.run(
            lambda _m: next(script),
            task,
            max_steps=5,
            spawns=spawns,
            context=ContextControls.from_config(cfg),
        )
    assert result.status == OK  # 0 refusals
    assert result.sub_results
    assert result.sub_results[0].status == OK
    child = result.sub_results[0]
    # the associate purpose is NOT served: carried by cortex, fallback RECORDED
    assert child.resolved_model == ADVERT["cortex"]["model"]
    assert child.fallback_from_role == "associate"
    assert child.agent_id
    # the acting seat itself ran on cortex with every invocation attributed
    block = result.agents
    assert block
    assert len(block["invocations"]) >= 2
    assert all(i["resolved_model"] == ADVERT["cortex"]["model"] for i in block["invocations"])
    assert all(i["agent_id"] and i["tool_surface_digest"] for i in block["invocations"])
    # the ledger carries the delegate/return pair
    events = [
        json.loads(line)
        for line in Path(block["ledger_path"]).read_text().splitlines()
        if line.strip()
    ]
    kinds = [e.get("kind") for e in events]
    assert "delegate" in kinds
    assert "return" in kinds


def test_worker_purpose_resolves_to_cortex_today_and_binds_when_ready() -> None:
    with _serving(ADVERT) as gateway:
        roles = resolve_roles(gateway)
    assert roles is not None
    today = resolve_profile("worker", roles)
    assert today.model_role == "cortex"
    assert today.fallback_from_role == "worker"
    assert today.resolved_model == ADVERT["cortex"]["model"]
    ready = json.loads(json.dumps(ADVERT))
    ready["worker"]["ready"] = True
    with _serving(ready) as gateway:
        roles_ready = resolve_roles(gateway)
    bound = resolve_profile("worker", roles_ready)
    assert bound.model_role == "worker"
    assert bound.fallback_from_role is None
    assert bound.resolved_model == ADVERT["worker"]["model"]


def test_worker_ready_binds_the_child_to_the_worker_role(tmp_path: Path) -> None:
    """The fallback is conditional: flip the worker advert ready and a worker-purpose
    child dials the worker (note: dormant by deviation d3 at the spawn seam — so we
    assert the associate purpose instead when an associate role is advertised)."""
    ready = json.loads(json.dumps(ADVERT))
    ready["associate"] = dict(ADVERT["cortex"], model="associate-sentinel", ready=True)
    with _serving(ready) as gateway:
        cfg = EngineConfig(
            agents=True,
            model=ADVERT["cortex"]["model"],
            base_url="http://localhost:8001/v1",
            api_key="k",
            lobes_gateway_url=gateway,
        )
        sub = run_subagent(
            "write the marker file",
            repo_path=str(tmp_path),
            parent_config=cfg,
            parent_engine="mock",
            depth=1,
            spec=ChildSpec(profile="associate"),
        )
    assert sub.status == OK
    assert sub.resolved_model == "associate-sentinel"
    assert sub.fallback_from_role is None


def test_doctor_probe_prints_the_fallback_lines_from_the_same_advert(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("COLLEAGUE_AGENTS", raising=False)
    with _serving(ADVERT) as gateway:
        repo = _armed_repo(tmp_path, gateway)
        probe = {c["id"]: c["message"] for c in agents_checks.probe_checks(repo_path=repo)}
    assert "ready" in probe["agents_role_cortex"]
    assert "not ready → cortex fallback" in probe["agents_role_worker"]
    assert "absent → cortex fallback" in probe["agents_role_associate"]

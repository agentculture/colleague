"""Cross-role delegation (#411, plan task t14): a child may bind a different
lobes role, carry its own context, and be bracketed by ledger events.

Pins, per the acceptance criteria:

(a) UNARMED (``agents`` False, or no ``profile``): the child config is
    byte-identical to today's ``dataclasses.replace(model=…)`` path.
(b) ARMED + a gateway double advertising a ready ``associate`` role at its
    OWN endpoint origin: the child dials the role's endpoint, carries the
    role's model and advertised context, and gets ``api_key=None`` because the
    origin differs (same-origin key hygiene, #348).
(c) ARMED + today's advert (no ``associate``, ``worker`` ready:false): the
    child resolves to cortex under a RECORDED fallback
    (``SubResult.fallback_from_role``); the dormant ``worker`` purpose (d3)
    never binds even when the role is ready.
(d) ``context_mode="clear"``: the child's ``Task.context`` carries the
    handover summary (t10) built from the parent's task ledger; delegate/
    return events bracket the spawn.
(e) an invalid ``context_mode`` / an unknown ``profile`` is refused whole.
(f) the mock engine path honours the fields end-to-end (``tests/
    test_subagent_e2e.py`` style), and the batch path threads them per item.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.server
import json
import threading
from pathlib import Path
from typing import Iterator

import pytest

from colleague.agents.state.ledger import TaskLedger, read_ledger
from colleague.config import EngineConfig
from colleague.contract import OK, SubResult, Task, TaskResult, Usage
from colleague.subagents import (
    ChildSpec,
    _child_config_for_profile,
    _resolve_child_binding,
    default_parent_profile,
    make_batch_spawn,
    make_spawn,
    run_subagent,
)

# ---------------------------------------------------------------------------
# A lobes gateway double (the tests/test_config_lobes.py ``_serving`` pattern).
# ---------------------------------------------------------------------------

_CORTEX_MODEL = "cross-role-cortex-sentinel"
_SENSES_MODEL = "cross-role-senses-sentinel"
_WORKER_MODEL = "cross-role-worker-sentinel"
_ASSOCIATE_MODEL = "cross-role-associate-sentinel"
_MAIN_ENDPOINT = "http://localhost:8000"
_ASSOCIATE_ENDPOINT = "http://127.0.0.1:9999"


def _role(model: str, endpoint: str, context: int, ready: bool) -> dict:
    return {
        "model": model,
        "endpoint": endpoint,
        "path": "/v1/chat/completions",
        "context": context,
        "ready": ready,
        "responsibilities": [],
        "forbidden_responsibilities": [],
    }


#: Today's advert (2026-08-21 re-probe shape): cortex + senses ready, worker
#: advertised but NOT ready, no associate.
TODAY_PAYLOAD = {
    "cortex": _role(_CORTEX_MODEL, _MAIN_ENDPOINT, 131072, True),
    "senses": _role(_SENSES_MODEL, _MAIN_ENDPOINT, 32768, True),
    "worker": _role(_WORKER_MODEL, _MAIN_ENDPOINT, 65536, False),
}

#: A future advert: the reserved fast-coder ``associate`` role is READY at its
#: OWN endpoint origin; ``worker`` is ready too (to prove d3 dormancy).
ASSOCIATE_PAYLOAD = dict(
    TODAY_PAYLOAD,
    worker=_role(_WORKER_MODEL, _MAIN_ENDPOINT, 65536, True),
    associate=_role(_ASSOCIATE_MODEL, _ASSOCIATE_ENDPOINT, 262144, True),
)


class _CapabilitiesHandler(http.server.BaseHTTPRequestHandler):
    body: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802
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
def _serving(payload: object) -> Iterator[str]:
    handler_cls = type(
        "_ScopedHandler",
        (_CapabilitiesHandler,),
        {"body": json.dumps(payload).encode("utf-8")},
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _armed_parent(gateway: str | None, **over) -> EngineConfig:
    kwargs = dict(
        agents=True,
        model=_CORTEX_MODEL,
        base_url=_MAIN_ENDPOINT + "/v1",
        api_key="parent-secret",
        context_budget_tokens=40000,
        lobes_gateway_url=gateway,
    )
    kwargs.update(over)
    return EngineConfig(**kwargs)


class _Capture:
    """A fake engine that records the (task, config) it was handed and returns
    a clean TaskResult — no network, so the vllm-openai name can be proven
    without a rig."""

    def __init__(self) -> None:
        self.calls: list[tuple[Task, EngineConfig]] = []

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        self.calls.append((task, config))
        return TaskResult(
            task_id=task.id,
            status=OK,
            summary="captured",
            changed_files=["a.py"],
            usage=Usage(),
        )


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    from colleague import subagents as mod

    monkeypatch.setattr(mod.registry, "load", lambda name: cap)
    return cap


# ---------------------------------------------------------------------------
# (e) refusals are deterministic and whole.
# ---------------------------------------------------------------------------


def test_child_spec_defaults_are_byte_identical() -> None:
    spec = ChildSpec()
    assert spec.profile is None
    assert spec.context_mode == "inherit"


@pytest.mark.parametrize("bad", ["", "reset", "CLEAR", "fresh"])
def test_invalid_context_mode_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="context_mode"):
        ChildSpec(context_mode=bad)


@pytest.mark.parametrize("bad", ["bogus", "gpt-foo", "embedder", "stt", ""])
def test_unknown_profile_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="profile"):
        ChildSpec(profile=bad)


@pytest.mark.parametrize(
    "ok", ["talker", "worker", "thinker_coder", "associate", "cortex", "senses", "muse"]
)
def test_purpose_and_bare_role_profiles_accepted(ok: str) -> None:
    assert ChildSpec(profile=ok).profile == ok


# ---------------------------------------------------------------------------
# (a) unarmed → byte-identical to today's replace(model=…).
# ---------------------------------------------------------------------------


def test_unarmed_child_config_identical_to_replace(tmp_path: Path, capture: _Capture) -> None:
    parent = EngineConfig(model="X", base_url="http://h:1/v1", api_key="k")
    for spec in (None, ChildSpec(), ChildSpec(profile="associate")):
        # agents=False → the profile is inert (strict no-op).
        run_subagent(
            "t",
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="mock",
            depth=1,
            spec=spec,
        )
    for _task, cfg in capture.calls:
        expected = dataclasses.replace(
            parent,
            model="X",
            role=None,
            chain_episode=False,
            chain_prior_changed=(),
            until_done=False,
            config_lifecycle=None,
        )
        # Compare the serialized snapshot + the fields replace() governs.
        assert cfg.to_dict() == expected.to_dict()
        assert cfg.base_url == parent.base_url
        assert cfg.api_key == parent.api_key
        assert cfg.refresh_seat == parent.refresh_seat
        assert cfg.context_budget_tokens == parent.context_budget_tokens
    # Unarmed SubResult carries none of the armed-only fields.
    sub = run_subagent(
        "t", repo_path=str(tmp_path), parent_config=parent, parent_engine="mock", depth=1
    )
    assert sub.agent_id is None
    assert sub.resolved_model is None
    assert sub.fallback_from_role is None
    assert set(sub.to_dict()) == {
        "task_id",
        "engine",
        "model",
        "status",
        "summary",
        "changed_files",
        "usage",
    }


def test_armed_without_profile_is_the_existing_path(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed_parent(None)
    sub = run_subagent(
        "t", repo_path=str(tmp_path), parent_config=parent, parent_engine="mock", depth=1
    )
    _task, cfg = capture.calls[0]
    assert cfg.base_url == parent.base_url
    assert cfg.api_key == parent.api_key
    assert cfg.model == parent.model
    assert sub.agent_id is None
    assert sub.resolved_model is None


def test_binding_is_none_when_unarmed() -> None:
    assert _resolve_child_binding(EngineConfig(), ChildSpec(profile="associate")) is None
    assert _resolve_child_binding(_armed_parent(None), ChildSpec()) is None


# ---------------------------------------------------------------------------
# (b) armed + a ready associate at its own origin → cross-role dial.
# ---------------------------------------------------------------------------


def test_cross_role_dial_to_associate_on_vllm_openai(tmp_path: Path, capture: _Capture) -> None:
    with _serving(ASSOCIATE_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        sub = run_subagent(
            "port the helper",
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="vllm-openai",
            depth=1,
            spec=ChildSpec(profile="associate"),
        )
    task, cfg = capture.calls[0]
    # The role dial: the associate's OWN endpoint + the /v1 shape, not the parent's.
    assert cfg.base_url == _ASSOCIATE_ENDPOINT + "/v1"
    assert cfg.model == _ASSOCIATE_MODEL
    # Same-origin key hygiene (#348): the origin differs → never the parent's key.
    assert cfg.api_key is None
    # Own context: the role advert's window, not the parent's budget.
    assert cfg.context_budget_tokens == 262144
    # Seat hygiene per the t9 contract: no stale-pin refresh seat, no delta sink.
    assert cfg.refresh_seat is None
    assert cfg.on_delta is None
    assert cfg.chain_episode is False
    assert cfg.until_done is False
    # The parent object is untouched.
    assert parent.api_key == "parent-secret"
    assert parent.base_url == _MAIN_ENDPOINT + "/v1"
    # The SubResult carries the identity.
    assert sub.engine == "vllm-openai"
    assert sub.model == _ASSOCIATE_MODEL
    assert sub.resolved_model == _ASSOCIATE_MODEL
    assert sub.agent_id
    assert sub.agent_id.endswith(task.id)
    assert sub.fallback_from_role is None
    d = sub.to_dict()
    assert d["agent_id"] == sub.agent_id
    assert d["resolved_model"] == _ASSOCIATE_MODEL
    assert "fallback_from_role" not in d
    assert SubResult.from_dict(d) == sub


def test_cross_role_dial_to_associate_on_mock(tmp_path: Path) -> None:
    """The REAL mock engine runs the cross-role child (shape parity, the
    all-engines rule): it ignores base_url but the SubResult shape is the same."""
    with _serving(ASSOCIATE_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        sub = run_subagent(
            "write the marker file",
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="mock",
            depth=1,
            spec=ChildSpec(profile="associate"),
        )
    assert sub.status == OK
    assert sub.changed_files == ["colleague-mock.md"]
    assert sub.model == _ASSOCIATE_MODEL
    assert sub.resolved_model == _ASSOCIATE_MODEL
    assert sub.agent_id
    assert sub.fallback_from_role is None


def test_same_origin_role_keeps_parent_key() -> None:
    """A role whose dial shares the parent's origin inherits the api_key —
    the positive half of #348 (cortex here dials the parent's own endpoint)."""
    with _serving(ASSOCIATE_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        spec = ChildSpec(profile="thinker_coder")
        binding = _resolve_child_binding(parent, spec)
        assert binding is not None
        cfg = _child_config_for_profile(parent, spec, binding)
    assert cfg.base_url == _MAIN_ENDPOINT + "/v1"
    assert cfg.api_key == "parent-secret"
    assert cfg.model == _CORTEX_MODEL
    assert cfg.context_budget_tokens == 131072
    assert binding.fallback_from_role is None


def test_explicit_spec_budget_wins_over_advert() -> None:
    """An explicit per-item / width-scaled budget (t12) still wins over the
    advertised window — explicit beats derived, the repo's precedence rule."""
    with _serving(ASSOCIATE_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        spec = ChildSpec(profile="associate", context_budget_tokens=12345, max_steps=7)
        binding = _resolve_child_binding(parent, spec)
        cfg = _child_config_for_profile(parent, spec, binding)
    assert cfg.context_budget_tokens == 12345
    assert cfg.max_steps == 7


# ---------------------------------------------------------------------------
# (c) today's advert → recorded fallback to cortex; worker stays dormant (d3).
# ---------------------------------------------------------------------------


def test_absent_associate_falls_back_to_cortex_recorded(tmp_path: Path, capture: _Capture) -> None:
    with _serving(TODAY_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        sub = run_subagent(
            "routine coding",
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="mock",
            depth=1,
            spec=ChildSpec(profile="associate"),
        )
    _task, cfg = capture.calls[0]
    assert cfg.model == _CORTEX_MODEL
    assert cfg.base_url == _MAIN_ENDPOINT + "/v1"
    assert cfg.api_key == "parent-secret"  # same origin as the parent
    assert cfg.context_budget_tokens == 131072  # cortex's advertised window
    assert sub.resolved_model == _CORTEX_MODEL
    assert sub.fallback_from_role == "associate"
    assert sub.to_dict()["fallback_from_role"] == "associate"


def test_worker_purpose_is_dormant_even_when_role_ready(tmp_path: Path, capture: _Capture) -> None:
    """Deviation d3: the worker role is NEVER bound by a spawn; a worker-purpose
    child resolves to cortex under the recorded fallback even though the
    future advert says the worker is ready."""
    with _serving(ASSOCIATE_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        sub = run_subagent(
            "read-only survey",
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="mock",
            depth=1,
            spec=ChildSpec(profile="worker"),
        )
    _task, cfg = capture.calls[0]
    assert cfg.model == _CORTEX_MODEL
    assert sub.fallback_from_role == "worker"
    assert sub.resolved_model == _CORTEX_MODEL


def test_gateway_absent_degrades_to_parent_model_recorded(
    tmp_path: Path, capture: _Capture
) -> None:
    """No gateway URL (or an unreachable one): the child runs on the parent's
    main model/endpoint with the fallback recorded — never a refusal."""
    for gateway in (None, "http://127.0.0.1:9/"):
        capture.calls.clear()
        parent = _armed_parent(gateway, model="main-model")
        sub = run_subagent(
            "t",
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="mock",
            depth=1,
            spec=ChildSpec(profile="associate"),
        )
        _task, cfg = capture.calls[0]
        assert cfg.model == "main-model"
        assert cfg.base_url == parent.base_url
        assert cfg.api_key == parent.api_key
        assert cfg.context_budget_tokens == parent.context_budget_tokens
        assert sub.resolved_model == "main-model"
        assert sub.fallback_from_role == "associate"
        assert sub.agent_id


# ---------------------------------------------------------------------------
# (d) context_mode=clear → handover summary; delegate/return bracket the spawn.
# ---------------------------------------------------------------------------


def _seed_ledger(path: Path, task_id: str) -> TaskLedger:
    ledger = TaskLedger(path, task_id=task_id)
    ledger.append("operator_request", {"ref": "op:1", "text": "Build the widget end to end"})
    ledger.append("acceptance", {"id": "a1", "text": "widget renders"})
    ledger.append("changed_path", {"path": "src/widget.py"})
    return ledger


def test_clear_child_receives_handover_summary(tmp_path: Path, capture: _Capture) -> None:
    ledger_file = tmp_path / ".colleague" / "ledger" / "parent1.jsonl"
    _seed_ledger(ledger_file, "parent1")
    parent = _armed_parent(None)
    parent.agents_ledger_path = str(ledger_file)  # t15 will set this on the loop's config
    sub = run_subagent(
        "review the widget",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        spec=ChildSpec(
            profile="thinker_coder", context_mode="clear", parent_profile="thinker_coder"
        ),
    )
    task, _cfg = capture.calls[0]
    # The objective (instruction) is verbatim; the context is the handover packet.
    assert task.instruction == "review the widget"
    assert task.context.startswith("# Handover summary")
    assert "Build the widget end to end" in task.context
    assert "widget renders" in task.context
    assert "src/widget.py" in task.context

    # delegate BEFORE / return AFTER bracket the spawn on the parent's ledger.
    read = read_ledger(ledger_file)
    kinds = [e.kind for e in read.events]
    assert kinds[-2:] == ["delegate", "return"]
    delegate, ret = read.events[-2], read.events[-1]
    assert delegate.data["id"] == sub.task_id == delegate.data["delegation_id"]
    assert delegate.data["child_ref"] == f"sub/{sub.task_id}"
    assert delegate.data["profile"] == "thinker_coder"
    assert delegate.data["context_mode"] == "clear"
    assert delegate.data["from_profile"] == "thinker_coder"
    assert delegate.data["agent_id"] == sub.agent_id
    assert ret.data["id"] == sub.task_id
    assert ret.data["status"] == OK
    assert ret.data["changed_files"] == 1
    # The delegation is closed (no dangling open loop) in the replayed snapshot.
    assert all(d["returned"] for d in read.snapshot.delegations)
    assert not [o for o in read.snapshot.open_loops if o.get("kind") == "delegate"]


def test_inherit_child_gets_no_handover_and_no_ledger_events(
    tmp_path: Path, capture: _Capture
) -> None:
    ledger_file = tmp_path / ".colleague" / "ledger" / "parent2.jsonl"
    _seed_ledger(ledger_file, "parent2")
    before = len(read_ledger(ledger_file).events)
    parent = _armed_parent(None)
    parent.agents_ledger_path = str(ledger_file)
    run_subagent(
        "t",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        spec=ChildSpec(profile="thinker_coder"),  # inherit
    )
    task, _cfg = capture.calls[0]
    assert task.context == ""  # inherit = today's behaviour (no packet)
    # Armed + ledger present → delegate/return still bracket (identity lane).
    assert len(read_ledger(ledger_file).events) == before + 2
    # Unarmed → NO ledger events at all, ever.
    capture.calls.clear()
    plain = EngineConfig()
    plain.agents_ledger_path = str(ledger_file)
    run_subagent("t", repo_path=str(tmp_path), parent_config=plain, parent_engine="mock", depth=1)
    assert len(read_ledger(ledger_file).events) == before + 2


def test_clear_without_readable_ledger_gets_minimal_handover(
    tmp_path: Path, capture: _Capture
) -> None:
    parent = _armed_parent(None)  # no agents_ledger_path at all
    run_subagent(
        "audit the thing",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        spec=ChildSpec(profile="thinker_coder", context_mode="clear"),
    )
    task, _cfg = capture.calls[0]
    assert task.context.startswith("# Handover summary")
    assert "audit the thing" in task.context
    assert "no task ledger" in task.context


# ---------------------------------------------------------------------------
# (f) spawn closures + batch items thread the fields; mock engine end to end.
# ---------------------------------------------------------------------------


def test_make_spawn_threads_profile_and_context_mode(tmp_path: Path, capture: _Capture) -> None:
    with _serving(ASSOCIATE_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        spawn = make_spawn(str(tmp_path), parent, "mock", parent_profile="thinker_coder")
        # The legacy positional call shape is untouched …
        sub0 = spawn("plain", None, None, None)
        # … and the new kwargs ride along.
        sub1 = spawn("fast", profile="associate", context_mode="clear")
    assert sub0.agent_id is None
    assert sub1.model == _ASSOCIATE_MODEL
    assert sub1.agent_id
    _t0, cfg0 = capture.calls[0]
    t1, cfg1 = capture.calls[1]
    assert cfg0.model == _CORTEX_MODEL
    assert cfg0.api_key == "parent-secret"
    assert cfg1.base_url == _ASSOCIATE_ENDPOINT + "/v1"
    assert cfg1.api_key is None
    assert t1.context.startswith("# Handover summary")


def test_batch_items_carry_profile_and_context_mode(tmp_path: Path, capture: _Capture) -> None:
    import subprocess  # noqa: S404 - test-only git setup

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    with _serving(ASSOCIATE_PAYLOAD) as gateway:
        parent = _armed_parent(gateway)
        batch = make_batch_spawn(str(repo), parent, "mock", parent_profile="thinker_coder")
        results = batch(
            [
                {"instruction": "one", "profile": "associate"},
                {"instruction": "two", "profile": "thinker_coder", "context_mode": "clear"},
                {"instruction": "three"},
            ]
        )
    children = results[:-1]
    assert [c.resolved_model for c in children] == [_ASSOCIATE_MODEL, _CORTEX_MODEL, None]
    assert children[0].agent_id
    assert children[1].agent_id
    assert children[2].agent_id is None
    cfgs = [c for _t, c in capture.calls]
    assert cfgs[0].base_url == _ASSOCIATE_ENDPOINT + "/v1"
    assert cfgs[0].api_key is None
    assert cfgs[1].api_key == "parent-secret"
    assert capture.calls[1][0].context.startswith("# Handover summary")
    assert capture.calls[2][0].context == ""


def test_batch_item_invalid_context_mode_refused(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed_parent(None)
    batch = make_batch_spawn(str(tmp_path), parent, "mock")
    with pytest.raises(ValueError, match="context_mode"):
        batch([{"instruction": "x", "context_mode": "reset"}])


def test_default_parent_profile() -> None:
    assert default_parent_profile(EngineConfig()) is None
    assert default_parent_profile(_armed_parent(None)) == "thinker_coder"
    cfg = _armed_parent(None)
    cfg.agents_profile = "associate"
    assert default_parent_profile(cfg) == "associate"


def test_grandchild_spawn_inherits_profile_as_parent_profile(
    tmp_path: Path, capture: _Capture
) -> None:
    """A child's own nested spawn closure carries the CHILD's profile as the
    grandchild's ``parent_profile`` (lineage one hop at a time)."""
    ledger_file = tmp_path / ".colleague" / "ledger" / "p3.jsonl"
    _seed_ledger(ledger_file, "p3")
    parent = _armed_parent(None)
    parent.agents_ledger_path = str(ledger_file)
    run_subagent(
        "t",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        spec=ChildSpec(profile="talker"),
    )
    _task, child_cfg = capture.calls[0]
    # The child's closure: spawn a grandchild and look at its delegate event's
    # from_profile — it must name the child's profile ("talker"), not the root's.
    child_cfg.agents_ledger_path = str(ledger_file)
    child_cfg.subagent_spawn("grandchild", profile="thinker_coder")
    events = read_ledger(ledger_file).events
    delegates = [e for e in events if e.kind == "delegate"]
    assert delegates[-1].data["from_profile"] == "talker"

"""Delegation bounds are ENFORCED on the spawn path (#411 t11; Qodo, PR #414).

``colleague.agents.delegation.validate_delegation`` owned the arithmetic —
child tools ``⊆`` parent tools, child ceiling ``≤`` parent ceiling — but
nothing on the spawn path called it, so an armed parent could hand a child a
WIDER surface than it holds itself by naming a different profile.

Pinned here:

(a) a WIDENING delegation is refused whole — no child work, no ``delegate``
    event on the parent's ledger;
(b) a NARROWING delegation still runs (the mechanism only refuses widening);
(c) a bare lobes-role profile INHERITS the parent's purpose instead of
    silently defaulting to the full ``thinker_coder`` surface;
(d) an authority ceiling may not rise (a read-only-role parent);
(e) UNARMED and armed-without-profile paths are untouched.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from colleague.agents.runtime import agent_engine_config, seat_ceiling
from colleague.agents.state.ledger import TaskLedger, read_ledger
from colleague.agents.tools import PURPOSE_TOOLS
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult, Usage
from colleague.loop import resolve_role
from colleague.subagents import ChildSpec, SubagentError, run_subagent
from colleague.tools import ToolExecutor, curate_schemas


class _Capture:
    """A fake engine recording every (task, config) it is handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[Task, EngineConfig]] = []

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        self.calls.append((task, config))
        return TaskResult(
            task_id=task.id, status=OK, summary="captured", changed_files=[], usage=Usage()
        )


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    from colleague import subagents as mod

    monkeypatch.setattr(mod.registry, "load", lambda name: cap)
    return cap


def _armed(purpose: str | None = None, **over) -> EngineConfig:
    """An armed parent seat running on *purpose* (no gateway: the main-seat floor)."""
    config = EngineConfig(agents=True, model="parent-model", lobes_gateway_url=None, **over)
    if purpose is not None:
        setattr(config, "agents_profile", purpose)
    return config


def effective_surface(config: EngineConfig, repo: Path) -> set[str]:
    """What a seat can ACTUALLY reach: the offered schemas ∩ what the executor
    allows. Purpose names lie (an empty purpose set once meant "no narrowing",
    so the tools-off talker ran on the full registry); this does not.
    """
    role = resolve_role(config, str(repo))
    offered = {schema["function"]["name"] for schema in curate_schemas(role)}
    executor = ToolExecutor(str(repo), allowlist=role)
    allowed = getattr(executor, "_allowlist", None)
    return offered if allowed is None else offered & set(allowed)


def _spawn(tmp_path: Path, parent: EngineConfig, spec: ChildSpec, role: str | None = None):
    return run_subagent(
        "do the thing",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        role=role,
        spec=spec,
    )


# ---------------------------------------------------------------------------
# (a) widening refuses whole
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wider", ["thinker_coder", "associate"])
def test_worker_parent_cannot_delegate_a_wider_surface(
    tmp_path: Path, capture: _Capture, wider: str
) -> None:
    """The dormant ``worker`` holds no ``write_file``/``edit_file``; a child of
    its may not carry them either."""
    parent = _armed("worker")
    with pytest.raises(SubagentError) as excinfo:
        _spawn(tmp_path, parent, ChildSpec(profile=wider))
    message = str(excinfo.value)
    assert "delegation refused" in message
    assert "write_file" in message and "edit_file" in message
    assert capture.calls == []  # refused BEFORE any child work


def test_refused_delegation_writes_no_ledger_event(tmp_path: Path, capture: _Capture) -> None:
    """A refused delegation records nothing: no ``delegate``, no ``return``."""
    ledger_file = tmp_path / ".colleague" / "ledger" / "p1.jsonl"
    ledger = TaskLedger(ledger_file, task_id="p1")
    ledger.append("operator_request", {"ref": "op:1", "text": "build the widget"})
    parent = _armed("worker")
    parent.agents_ledger_path = str(ledger_file)
    with pytest.raises(SubagentError):
        _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"))
    kinds = [event.kind for event in read_ledger(ledger_file).events]
    assert "delegate" not in kinds and "return" not in kinds


# ---------------------------------------------------------------------------
# (b) narrowing still runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("narrower", ["worker", "talker"])
def test_narrowing_delegation_is_allowed(tmp_path: Path, capture: _Capture, narrower: str) -> None:
    parent = _armed("thinker_coder")
    sub = _spawn(tmp_path, parent, ChildSpec(profile=narrower))
    assert sub.status == OK
    assert len(capture.calls) == 1
    _task, child_cfg = capture.calls[0]
    assert getattr(child_cfg, "agents_profile") == narrower
    # The EFFECTIVE surface, not the purpose name: a name-level assertion
    # passes vacuously for the talker (∅ ⊆ anything) while the seat really
    # held every write tool.
    child_surface = effective_surface(child_cfg, tmp_path)
    parent_surface = effective_surface(parent, tmp_path)
    assert child_surface <= parent_surface
    assert {"write_file", "edit_file"} & child_surface == set()
    assert set(PURPOSE_TOOLS[narrower]) <= set(PURPOSE_TOOLS["thinker_coder"])


def test_same_purpose_delegation_is_allowed(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed("worker")
    sub = _spawn(tmp_path, parent, ChildSpec(profile="worker"))
    assert sub.status == OK


# ---------------------------------------------------------------------------
# (c) a bare role name switches the MODEL, never the surface
# ---------------------------------------------------------------------------


def test_bare_role_profile_inherits_the_parent_purpose(tmp_path: Path, capture: _Capture) -> None:
    """``profile="cortex"`` under a ``worker`` parent must not hand the child
    the full ``thinker_coder`` surface via the acting-seat default."""
    parent = _armed("worker")
    _spawn(tmp_path, parent, ChildSpec(profile="cortex"))
    _task, child_cfg = capture.calls[0]
    assert getattr(child_cfg, "agents_profile") == "worker"


# ---------------------------------------------------------------------------
# (d) the authority ceiling may not rise
# ---------------------------------------------------------------------------


def test_seat_ceiling_ranks_read_only_lowest() -> None:
    assert seat_ceiling(EngineConfig(), "explorer") == "read_only"
    assert seat_ceiling(EngineConfig()) == "repo_patch_publish"


def test_no_publish_rung_is_dead_in_production() -> None:
    """HONEST: ``no_pr`` is a CLI arg turned into ``open_pr``; nothing in
    ``colleague/`` ever sets it on an ``EngineConfig``, so the middle rung is
    unreachable today and the enum collapses to read_only vs publish. The
    attribute has to be conjured for the rung to fire — that is the point of
    this test, not coverage of a live path (follow-up: carry publish intent
    onto the seat)."""
    from dataclasses import fields

    assert "no_pr" not in {f.name for f in fields(EngineConfig)}
    conjured = EngineConfig()
    setattr(conjured, "no_pr", True)
    assert seat_ceiling(conjured) == "repo_patch_no_publish"


def test_read_only_parent_cannot_delegate_a_writing_child(
    tmp_path: Path, capture: _Capture
) -> None:
    parent = _armed("thinker_coder", role="explorer")
    with pytest.raises(SubagentError) as excinfo:
        _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"))
    assert "exceeds the parent's 'read_only'" in str(excinfo.value)
    assert capture.calls == []


def test_read_only_parent_may_delegate_a_read_only_child(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed("thinker_coder", role="explorer")
    sub = _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"), role="explorer")
    assert sub.status == OK
    _task, child_cfg = capture.calls[0]
    assert seat_ceiling(child_cfg, "explorer") == "read_only"
    assert "write_file" not in effective_surface(child_cfg, tmp_path)


# ---------------------------------------------------------------------------
# (e) unarmed / armed-without-profile are untouched
# ---------------------------------------------------------------------------


def test_unarmed_parent_is_never_validated(tmp_path: Path, capture: _Capture) -> None:
    """Unarmed, a profile is inert and no bound is computed — byte-identical."""
    parent = EngineConfig(model="parent-model")
    setattr(parent, "agents_profile", "worker")
    sub = _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"))
    assert sub.status == OK


def test_armed_without_profile_is_never_validated(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed("worker")
    sub = _spawn(tmp_path, parent, ChildSpec())
    assert sub.status == OK


# ---------------------------------------------------------------------------
# The effective surface is what the seat can reach — purpose names lie.
# ---------------------------------------------------------------------------


def test_talker_seat_is_really_tools_off(tmp_path: Path) -> None:
    """``TALKER_TOOLS`` is the EMPTY set; an empty purpose surface must mean
    NO tools, not "no narrowing" (which handed the talker the full registry
    while its ledger manifest claimed the empty set)."""
    talker = _armed("talker")
    assert effective_surface(talker, tmp_path) == set()


def test_talker_child_cannot_smuggle_write_tools(tmp_path: Path, capture: _Capture) -> None:
    """A ``talker`` child of ANY parent reaches no write tool — the delegation
    is ranked at ∅, so the seat must really be ∅."""
    parent = _armed("thinker_coder")
    _spawn(tmp_path, parent, ChildSpec(profile="talker"))
    _task, child_cfg = capture.calls[0]
    assert effective_surface(child_cfg, tmp_path) == set()


def test_worker_seat_holds_no_code_authoring_pair(tmp_path: Path) -> None:
    # t5 (q9/q10): the worker delegates BY PURPOSE now — subagent/subagents
    # leave its surface, replaced by the six purpose tools.
    surface = effective_surface(_armed("worker"), tmp_path)
    assert "read_file" in surface and "code_survey" in surface
    assert "subagent" not in surface and "subagents" not in surface
    assert "write_file" not in surface and "edit_file" not in surface


# ---------------------------------------------------------------------------
# A spawn that names NO profile is still bounded (the check is gated on
# ARMING, not on a declared profile — otherwise the model skips it by
# omitting one argument).
# ---------------------------------------------------------------------------


def test_profileless_child_inherits_the_parent_surface(tmp_path: Path, capture: _Capture) -> None:
    """A profileless child inherits the parent's purpose (worker), narrowed to
    the parent's surface — EXCEPT the six purpose tools (t15/actingsurface,
    q9): a spawned child never holds a purpose tool, no matter which purpose
    it inherited, so its effective surface is the parent's minus those six."""
    from colleague.purpose_schemas import PURPOSE_TOOL_NAMES

    parent = _armed("worker")
    _spawn(tmp_path, parent, ChildSpec())
    _task, child_cfg = capture.calls[0]
    assert getattr(child_cfg, "agents_profile") == "worker"
    assert effective_surface(child_cfg, tmp_path) == effective_surface(parent, tmp_path) - set(
        PURPOSE_TOOL_NAMES
    )


def test_profileless_grandchild_inherits_too(tmp_path: Path, capture: _Capture) -> None:
    """Depth 2: the closure a child builds for ITS children carries the purpose."""
    parent = _armed("worker")
    _spawn(tmp_path, parent, ChildSpec())
    _task, child_cfg = capture.calls[0]
    child_cfg.subagent_spawn("grandchild")
    _gtask, grandchild_cfg = capture.calls[1]
    assert getattr(grandchild_cfg, "agents_profile") == "worker"
    assert "write_file" not in effective_surface(grandchild_cfg, tmp_path)


def test_bounds_are_enforced_at_depth_two(tmp_path: Path, capture: _Capture) -> None:
    """A widening grandchild refuses exactly like a widening child."""
    parent = _armed("thinker_coder")
    _spawn(tmp_path, parent, ChildSpec(profile="worker"))
    _task, child_cfg = capture.calls[0]
    with pytest.raises(SubagentError, match="delegation refused"):
        child_cfg.subagent_spawn("grandchild", profile="thinker_coder")


# ---------------------------------------------------------------------------
# Ordering + auditability
# ---------------------------------------------------------------------------


def test_refusal_does_not_burn_a_budget_slot(tmp_path: Path, capture: _Capture) -> None:
    """The check runs BEFORE the global charge: ``_AgentBudget``'s documented
    invariant is that its count equals the agents that actually ran."""
    from colleague.subagents import new_agent_budget

    budget = new_agent_budget()
    parent = _armed("worker")
    for _ in range(3):
        with pytest.raises(SubagentError):
            run_subagent(
                "x",
                repo_path=str(tmp_path),
                parent_config=parent,
                parent_engine="mock",
                depth=1,
                counter=budget,
                spec=ChildSpec(profile="thinker_coder"),
            )
    assert budget.count == 0
    assert capture.calls == []


def test_delegate_event_records_what_was_validated(tmp_path: Path, capture: _Capture) -> None:
    """A ledger replay can audit the bounds decision, not just trust it."""
    ledger_file = tmp_path / ".colleague" / "ledger" / "p2.jsonl"
    ledger = TaskLedger(ledger_file, task_id="p2")
    ledger.append("operator_request", {"ref": "op:1", "text": "build the widget"})
    parent = _armed("thinker_coder")
    parent.agents_ledger_path = str(ledger_file)
    _spawn(tmp_path, parent, ChildSpec(profile="worker"))
    delegate = [e for e in read_ledger(ledger_file).events if e.kind == "delegate"][-1]
    assert delegate.data["requested_tools"] == sorted(PURPOSE_TOOLS["worker"])
    assert delegate.data["authority_ceiling"] == "repo_patch_publish"


# ---------------------------------------------------------------------------
# The unarmed path is not merely OK — the validator is never called.
# ---------------------------------------------------------------------------


def test_unarmed_never_calls_the_validator(
    tmp_path: Path, capture: _Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colleague.agents import delegation as delegation_mod

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("validate_delegation called on the unarmed path")

    monkeypatch.setattr(delegation_mod, "validate_delegation", _boom)
    parent = EngineConfig(model="parent-model")
    setattr(parent, "agents_profile", "worker")
    assert _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder")).status == OK


def test_the_batch_path_validates_every_item_before_any_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One widening item refuses the WHOLE batch before a worktree exists —
    never midway, which would delete already-finished siblings' branches."""
    from colleague import subagents as mod

    created: list[str] = []
    monkeypatch.setattr(
        mod.worktrees,
        "worktree_add",
        lambda *a, **k: created.append("made") or (_ for _ in ()).throw(AssertionError()),
    )
    parent = _armed("worker")
    with pytest.raises(SubagentError, match="batch item 1"):
        mod._run_batch(
            [
                {"instruction": "a"},
                {"instruction": "b", "profile": "thinker_coder"},
                {"instruction": "c"},
            ],
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="mock",
            depth=1,
        )
    assert created == []


# ---------------------------------------------------------------------------
# The seat builder must carry the purpose (the pending #412 fold trap).
# ---------------------------------------------------------------------------


def test_agent_engine_config_carries_the_purpose(tmp_path: Path) -> None:
    from colleague.agents.profile import AgentProfile

    profile = AgentProfile(
        agent_id="a1",
        purpose="worker",
        model_role="cortex",
        resolved_model="m",
        tool_profile="worker",
        authority_profile="repo_patch_publish",
        parent_agent_id=None,
        task_id="t1",
        fallback_from_role="worker",
    )
    seat = agent_engine_config(_armed("thinker_coder"), profile, object())
    assert getattr(seat, "agents_profile") == "worker"
    assert "write_file" not in effective_surface(seat, tmp_path)


# ---------------------------------------------------------------------------
# (f) purpose-tool exemption (t8, q3): a purpose delegation's FIXED child
# surface is exempt from the parent ⊆ check; a manual delegation carrying the
# SAME wider surface stays subject to it.
# ---------------------------------------------------------------------------


def test_cortex_without_web_calls_code_survey_allowed(tmp_path: Path, capture: _Capture) -> None:
    """cortex (thinker_coder) holds no raw 'web' (replace-not-add, spec c/q3
    decision) — a purpose-tool child (role='scout', whose own allow-list
    includes 'web') still runs end to end through ``run_subagent``: its
    child surface is FIXED by the tool, never requested from the parent."""
    from colleague.agents.tools import tools_for_purpose

    parent = _armed("thinker_coder")
    assert "web" not in tools_for_purpose("thinker_coder")
    sub = _spawn(
        tmp_path,
        parent,
        ChildSpec(purpose="code_survey", charges_budget=False),
        role="scout",
    )
    assert sub.status == OK
    assert len(capture.calls) == 1


def test_manual_scout_delegation_requesting_web_still_refused(tmp_path: Path) -> None:
    """The SAME scout surface (curate_schemas('scout'), which includes 'web')
    requested WITHOUT the ``purpose`` flag — i.e. a MANUAL ``subagent``/
    ``subagents`` delegation — stays subject to the ⊆ check and is refused:
    the purpose exemption never leaks into a manual delegation. Exercises the
    real production :func:`colleague.subagents._delegation_bounds`."""
    from colleague.agents.tools import tools_for_purpose
    from colleague.subagents import _child_requested_tools, _delegation_bounds

    parent = _armed("thinker_coder")
    manual_spec = ChildSpec(purpose=None)
    scout_tools = _child_requested_tools(
        dataclasses.replace(manual_spec, purpose="code_survey"), "thinker_coder", "scout"
    )
    assert "web" in scout_tools  # the scout role's own surface offers it

    _child_purpose, _ceiling, requested_tools, verdict = _delegation_bounds(
        parent, manual_spec, instruction="do the thing", depth=1, role="scout"
    )
    assert requested_tools == tuple(sorted(tools_for_purpose("thinker_coder")))
    assert "web" not in requested_tools  # today's manual path never carries it
    assert verdict.allowed is True  # ⊆ holds vacuously — the real gap this
    # test documents: use ``validate_delegation`` directly, forcing the same
    # scout surface onto a manual (unflagged) request, to prove the ⊆ rule
    # itself still refuses it once 'web' IS on a manual request.
    from colleague.agents.delegation import DelegationRequest, validate_delegation
    from colleague.agents.runtime import seat_ceiling

    manual_req = DelegationRequest(
        delegation_id="",
        from_agent="thinker_coder",
        requested_agent_profile="scout",
        objective="do the thing",
        acceptance="",
        requested_tools=scout_tools,
        authority_ceiling=seat_ceiling(parent, "scout"),
        depth=1,
        purpose=None,
    )
    manual_verdict = validate_delegation(
        manual_req,
        parent_effective_tools=tools_for_purpose("thinker_coder"),
        parent_ceiling=seat_ceiling(parent, getattr(parent, "role", None)),
    )
    assert manual_verdict.allowed is False
    assert "web" in (manual_verdict.reason or "")

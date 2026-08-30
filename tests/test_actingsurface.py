"""``colleague/actingsurface.py`` — the depth-aware curation seam that closes
deviation d14 (workforce t15, docs/specs/2026-08-28-purpose-tools-associate-seat.md
claims c4/h4, c23/h21, h1, decisions q9/q10/q11).

d14: a bare ``colleague work`` (no ``--role``, unarmed) resolved
``role=None`` in ``colleague.loop.resolve_role``, so the engines curated the
FULL pre-arc surface (``web``/``subagent``/``subagents``, no purpose tools) —
contradicting the spec's own headline claim that the armed rig's bare run
offers the six purpose tools and withholds raw ``web``. This module fixes it
at the ONE seam ``resolve_role`` applies last: the top-level acting seat
(depth 0, whether ``role`` is ``None`` or an explicit ``--role writer``) now
resolves to the writer role's already-swapped surface, and any spawned child
(depth >= 1) is stripped of every purpose-tool name (q9), regardless of which
role/purpose named it.

**Arm 4 (plan t11) reversed half the swap on the ACTING seat and was
REJECTED on measured evidence:** the raw ``subagent``/``subagents`` went back
to depth 0 alongside the typed purposes to test whether their ABSENCE, not the
typed form, suppressed delegation. The 21-run arm matrix called the raw pair
ZERO times (A4: 0/3 delegation; every delegation that occurred was
``code_survey``), so the acting seat is purpose-only again. The depth >= 1
strip the arm widened (:data:`colleague.actingsurface.CHILD_FORBIDDEN_TOOLS`)
is KEPT as defence in depth: a child can never hold the raw pair, whatever the
seat's allow-list later carries.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.config import EngineConfig
from colleague.contract import Task
from colleague.engines.mock import MockEngine
from colleague.loop import resolve_role
from colleague.purpose_schemas import PURPOSE_TOOL_NAMES
from colleague.roles import BUILTIN_ROLES
from colleague.subagents import ChildSpec, run_subagent
from colleague.tools import ToolError, ToolExecutor, curate_schemas

_RAW_DELEGATION_TOOLS = {"web", "subagent", "subagents"}


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


# ---------------------------------------------------------------------------
# (a) A bare unarmed run on mock: offered names carry the six purposes and
#     none of web/subagent/subagents — the schema half of the fix. Arm 4 (t11)
#     restored the raw pair HERE and was rejected on measured evidence, so
#     they are absent again.
# ---------------------------------------------------------------------------


def test_bare_unarmed_run_offers_purpose_tools_not_raw_delegation(git_repo: Path) -> None:
    role = resolve_role(EngineConfig(), str(git_repo))
    offered = {s["function"]["name"] for s in curate_schemas(role)}
    assert set(PURPOSE_TOOL_NAMES) <= offered
    assert offered.isdisjoint(_RAW_DELEGATION_TOOLS - {"web"})  # subagent/subagents gone
    # web itself is hidden without webglass/COLLEAGUE_WEB=0 regardless — the
    # DROP this fix proves is subagent/subagents, always, and web whenever
    # it would otherwise be offered.
    assert "web" not in offered


def test_bare_unarmed_mock_run_end_to_end_never_sees_subagent(git_repo: Path) -> None:
    """The real end-to-end path (no ``--role`` on the CLI/config): the mock
    engine's own ``resolve_role`` call (all-engines rule) resolves the SAME
    writer-carveout role, so ``role_res.to_dict()`` never advertises an
    unrestricted surface."""
    result = MockEngine().work(Task.new(str(git_repo), "add a note"), EngineConfig())
    assert result.status in ("ok", "incomplete")


# ---------------------------------------------------------------------------
# (b) The bare seat's ToolExecutor REFUSES web/subagent/subagents by
#     allowlist — the refusal half, symmetric with the schema half. Arm 4
#     (t11) briefly allow-listed the raw pair on the acting seat; the arm was
#     rejected on measured evidence, so all three are refused again.
# ---------------------------------------------------------------------------


def test_bare_seat_executor_refuses_raw_delegation_tools(git_repo: Path) -> None:
    role = resolve_role(EngineConfig(), str(git_repo))
    executor = ToolExecutor(str(git_repo), allowlist=role)
    for name in ("web", "subagent", "subagents"):
        with pytest.raises(ToolError, match="not allowed for this role"):
            executor.execute(name, {})


def test_explicit_writer_role_executor_refuses_raw_delegation_tools_too(git_repo: Path) -> None:
    role = resolve_role(EngineConfig(role="writer"), str(git_repo))
    executor = ToolExecutor(str(git_repo), allowlist=role)
    for name in ("web", "subagent", "subagents"):
        with pytest.raises(ToolError, match="not allowed for this role"):
            executor.execute(name, {})


# ---------------------------------------------------------------------------
# (c) Children: a read-only code_survey/scout child keeps web and holds no
#     purpose tool; a handover_to_colleague (writer) child at depth 1 holds
#     neither purposes nor web/subagent/subagents — a BOUNDED writer.
# ---------------------------------------------------------------------------


def test_code_survey_scout_child_is_offered_web_and_no_purpose_tools(git_repo: Path) -> None:
    class _Capture:
        def work(self, task, config):
            from colleague.contract import TaskResult

            self.config = config
            return TaskResult(task_id=task.id, status="ok", steps=[], summary="", changed_files=[])

    import colleague.registry as registry

    cap = _Capture()
    real_load = registry.load
    registry.load = lambda name: cap  # type: ignore[assignment]
    try:
        run_subagent(
            "survey the repo",
            repo_path=str(git_repo),
            parent_config=EngineConfig(),
            parent_engine="mock",
            depth=1,
            role="scout",
            spec=ChildSpec(purpose="code_survey", charges_budget=False),
        )
    finally:
        registry.load = real_load

    child_role = resolve_role(cap.config, str(git_repo))
    offered = {s["function"]["name"] for s in curate_schemas(child_role)}
    assert "web" in offered
    assert offered.isdisjoint(set(PURPOSE_TOOL_NAMES))


def test_handover_writer_child_at_depth_one_is_a_bounded_writer(git_repo: Path) -> None:
    """A ``handover_to_colleague``-shaped child (role='writer', depth 1) keeps
    the writer allow-list's t5 swap (no web/subagent/subagents) but never the
    purpose tools themselves (q9) — narrower than the top-level acting seat,
    which the same role name DOES offer purposes to. The raw pair is stripped
    here by :data:`colleague.actingsurface.CHILD_FORBIDDEN_TOOLS` (plan t11,
    KEPT) independently of the seat's own allow-list."""

    class _Capture:
        def work(self, task, config):
            from colleague.contract import TaskResult

            self.config = config
            return TaskResult(task_id=task.id, status="ok", steps=[], summary="", changed_files=[])

    import colleague.registry as registry

    cap = _Capture()
    real_load = registry.load
    registry.load = lambda name: cap  # type: ignore[assignment]
    try:
        run_subagent(
            "implement the change",
            repo_path=str(git_repo),
            parent_config=EngineConfig(),
            parent_engine="mock",
            depth=1,
            role="writer",
            spec=ChildSpec(),
        )
    finally:
        registry.load = real_load

    child_role = resolve_role(cap.config, str(git_repo))
    offered = {s["function"]["name"] for s in curate_schemas(child_role)}
    assert offered.isdisjoint(set(PURPOSE_TOOL_NAMES))
    assert offered.isdisjoint({"web", "subagent", "subagents"})
    # Still a writer otherwise: write_file/edit_file/finish remain.
    assert {"write_file", "edit_file", "finish"} <= offered


def test_manual_roleless_child_at_depth_one_defaults_to_bounded_writer(git_repo: Path) -> None:
    """A manual subagent spawned with NO role (today's roleless default) is
    ALSO the bounded writer at depth >= 1 — never the raw, unfiltered
    surface a bare TOP-LEVEL run would have gotten before this fix."""

    class _Capture:
        def work(self, task, config):
            from colleague.contract import TaskResult

            self.config = config
            return TaskResult(task_id=task.id, status="ok", steps=[], summary="", changed_files=[])

    import colleague.registry as registry

    cap = _Capture()
    real_load = registry.load
    registry.load = lambda name: cap  # type: ignore[assignment]
    try:
        run_subagent(
            "do the thing",
            repo_path=str(git_repo),
            parent_config=EngineConfig(),
            parent_engine="mock",
            depth=1,
            role=None,
            spec=ChildSpec(),
        )
    finally:
        registry.load = real_load

    child_role = resolve_role(cap.config, str(git_repo))
    assert child_role is not None
    offered = {s["function"]["name"] for s in curate_schemas(child_role)}
    assert offered.isdisjoint(set(PURPOSE_TOOL_NAMES))
    assert offered.isdisjoint({"web", "subagent", "subagents"})


# ---------------------------------------------------------------------------
# (d) A thought->action->evaluation worker surface (still depth 0 — the
#     ACTING dial is repointed at the worker seat, config.role stays unset)
#     has purposes.
# ---------------------------------------------------------------------------


def test_tae_worker_seat_offers_purpose_tools(git_repo: Path) -> None:
    config = EngineConfig(thought_action_evaluation=True)
    role = resolve_role(config, str(git_repo))
    offered = {s["function"]["name"] for s in curate_schemas(role)}
    assert set(PURPOSE_TOOL_NAMES) <= offered
    assert offered.isdisjoint({"subagent", "subagents"})


# ---------------------------------------------------------------------------
# child_depth / is_top_level primitives
# ---------------------------------------------------------------------------


def test_child_depth_defaults_to_zero_when_unstamped() -> None:
    from colleague import actingsurface

    assert actingsurface.child_depth(EngineConfig()) == 0
    assert actingsurface.is_top_level(EngineConfig())


def test_child_depth_reads_the_stamped_attribute() -> None:
    from colleague import actingsurface

    config = EngineConfig()
    setattr(config, "child_depth", 2)
    assert actingsurface.child_depth(config) == 2
    assert not actingsurface.is_top_level(config)


def test_strip_child_forbidden_tools_is_a_noop_without_them() -> None:
    from colleague import actingsurface

    role = BUILTIN_ROLES["scout"]
    assert actingsurface.strip_child_forbidden_tools(role) is role
    assert actingsurface.strip_child_forbidden_tools(None) is None


def test_strip_child_forbidden_tools_removes_the_restored_raw_delegation() -> None:
    """Arm 4's confinement (plan t11), KEPT after the arm itself was rejected
    on measured evidence: whatever the ACTING seat's allow-list carries, the
    depth >= 1 strip removes the raw ``subagent``/``subagents`` along with the
    purpose tools. Arm 4 put the raw pair on the writer role and this strip is
    what stopped it leaking down the tree; the seat is purpose-only again, so
    the guarantee is pinned here against a role that DOES carry the raw pair —
    the allow-list-independent confinement, not an artefact of today's writer.
    """
    from dataclasses import replace

    from colleague import actingsurface

    writer = BUILTIN_ROLES["writer"]
    # Today's writer no longer carries the raw pair (arm 4 rejected)...
    assert set(writer.tool_allowlist).isdisjoint(actingsurface.CHILD_FORBIDDEN_TOOLS)
    # ...so pin the confinement against a seat that does.
    armed = replace(
        writer,
        tool_allowlist=writer.tool_allowlist + actingsurface.CHILD_FORBIDDEN_TOOLS,
    )
    stripped = actingsurface.strip_child_forbidden_tools(armed)
    assert set(stripped.tool_allowlist).isdisjoint(_RAW_DELEGATION_TOOLS)
    assert set(stripped.tool_allowlist).isdisjoint(set(PURPOSE_TOOL_NAMES))

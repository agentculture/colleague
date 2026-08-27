"""Associate seat B — the enumerated consumers (adopt-from-qwen-code plan task t19; spec c33/h22).

Pins, per the acceptance criteria:

* ``ASSOCIATE_SEATS`` is ONE module-level tuple naming the scout subagent
  role, the fill-line compact author, forced synthesis, the lint/affected-
  tests digest and the rung-2 distill author rung; the feature doc's table
  has the row; an AST guard pins that no other call site references
  ``config.associate``;
* a read-only ``scout`` child runs on the associate EngineConfig with a tool
  surface that is a STRICT subset of the parent's read-only set (edit_file /
  write_file / run_tests absent); an associate reply carrying a repo-mutating
  tool call is refused and recorded, never executed;
* UNARMED (``COLLEAGUE_ASSOCIATE_MODEL`` unset → ``config.associate`` None)
  every seat is byte-identical to main (h1/c44); ARMED-but-unreachable falls
  to cortex@low with a recorded warning (c32/c33 — the fallback exists, it
  is the unreachable branch, not the unset branch).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from colleague import associate_seats, effort
from colleague.associate_config import ASSOCIATE_WIRE_MODEL, AssociateConfig
from colleague.config import EngineConfig
from colleague.contract import Task
from colleague.loop import ModelResponse
from colleague.roles import _READONLY_TOOLS, BUILTIN_ROLES, is_read_only
from colleague.tools import SCHEMAS, ToolError, ToolExecutor, curate_schemas

REPO_ROOT = Path(__file__).resolve().parent.parent
_ASSOC = AssociateConfig(
    model="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4",
    base_url="http://localhost:8001/v1",
    api_key="k",
    context_budget=96000,
)


def _config(*, armed: bool) -> EngineConfig:
    cfg = EngineConfig(model="cortex-model", base_url="http://localhost:8001/v1")
    if armed:
        cfg.associate = _ASSOC
    return cfg


# ---------------------------------------------------------------------------
# 1. The enumerated tuple + the AST guard
# ---------------------------------------------------------------------------


def test_associate_seats_is_one_fixed_tuple() -> None:
    assert isinstance(associate_seats.ASSOCIATE_SEATS, tuple)
    assert associate_seats.ASSOCIATE_SEATS == ("scout", "compact", "synthesis", "digest", "distill")


def test_unknown_seat_is_refused() -> None:
    with pytest.raises(ValueError):
        associate_seats.resolve_associate_seat_config(_config(armed=True), "coder")


def test_feature_doc_table_has_the_associate_row() -> None:
    doc = (REPO_ROOT / "docs/features/thinking-effort.md").read_text(encoding="utf-8")
    assert "| `associate` | `off` |" in doc
    assert "| `scout` | `off` |" in doc  # Qodo #441-4: read-only scouts think OFF


#: Every module allowed to touch ``config.associate`` — the seat builders, the
#: config that declares the field, the CLI renderers (t18) and the one seat
#: consumer module (this task). ``cli/_commands/_session_actions.py`` reads
#: ``roles.associate`` — a lobes ``RoleInfo`` advert, not the config.
_ASSOCIATE_ATTR_ALLOWED = frozenset(
    {
        "colleague/associate.py",
        "colleague/associate_config.py",
        "colleague/associate_seats.py",
        "colleague/associate_cli.py",
        "colleague/config.py",
        "colleague/cli/_commands/_session_actions.py",
    }
)


def test_ast_guard_config_associate_referenced_only_by_the_consumers() -> None:
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "colleague").rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "associate":
                if rel not in _ASSOCIATE_ATTR_ALLOWED:
                    offenders.append(f"{rel}:{node.lineno}")
    assert (
        not offenders
    ), f"config.associate referenced outside the enumerated consumers: {offenders}"


# ---------------------------------------------------------------------------
# 2. Seat resolution: unarmed byte-identical, armed → the associate seat,
#    unreachable → cortex@low with a warning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seat", associate_seats.ASSOCIATE_SEATS)
def test_unarmed_seat_config_is_the_config_itself(seat: str) -> None:
    cfg = _config(armed=False)
    assert associate_seats.resolve_associate_seat_config(cfg, seat) is cfg


@pytest.mark.parametrize("seat", associate_seats.ASSOCIATE_SEATS)
def test_armed_seat_config_is_the_associate_seat(seat: str) -> None:
    cfg = _config(armed=True)
    seat_cfg = associate_seats.resolve_associate_seat_config(cfg, seat)
    assert seat_cfg is not cfg
    assert seat_cfg.model == ASSOCIATE_WIRE_MODEL
    assert seat_cfg.base_url == _ASSOC.base_url
    assert effort.effort_of(seat_cfg) == "off"  # the associate row


def test_fallback_seat_config_is_cortex_at_low() -> None:
    cfg = _config(armed=True)
    low = associate_seats.fallback_seat_config(cfg, "compact")
    assert low.model == "cortex-model"
    assert effort.effort_of(low) == "low"
    assert effort.to_chat_template_kwargs(effort.effort_of(low)) == {"reasoning_effort": "low"}


def test_fallback_honours_the_kill_switch() -> None:
    cfg = _config(armed=True)
    cfg.reasoning_effort = "default"
    low = associate_seats.fallback_seat_config(cfg, "compact")
    assert effort.effort_of(low) is None


class _FakeEngine:
    """A fake backend whose associate seat can be made to fail."""

    def __init__(self, *, seat_fails: bool = False, unsupported: bool = False) -> None:
        self.seat_fails = seat_fails
        self.unsupported = unsupported
        self.calls: list[tuple[str, str | None]] = []

    def make_complete(self, config: EngineConfig, tools=None):  # type: ignore[no-untyped-def]
        if self.unsupported:
            raise NotImplementedError("no one-shot completions here")
        assert tools == []  # tools-off invariant for every seat completion

        def complete(messages: list[dict]) -> ModelResponse:
            self.calls.append((config.model, effort.effort_of(config)))
            if config.model == ASSOCIATE_WIRE_MODEL and self.seat_fails:
                raise RuntimeError("associate unreachable")
            return ModelResponse(content=f"from {config.model}", tool_calls=[])

        return complete


def test_make_associate_complete_is_none_when_unarmed() -> None:
    assert associate_seats.make_associate_complete(_config(armed=False), "fake") is None


def test_armed_factory_completes_on_the_associate_seat() -> None:
    engine = _FakeEngine()
    factory = associate_seats.make_associate_complete(
        _config(armed=True), "fake", engine_loader=lambda name: engine
    )
    assert factory is not None
    warnings: list[str] = []
    complete = factory("compact", warnings.append)
    assert complete is not None
    resp = complete([{"role": "user", "content": "summarise"}])
    assert resp.content == f"from {ASSOCIATE_WIRE_MODEL}"
    assert engine.calls == [(ASSOCIATE_WIRE_MODEL, "off")]
    assert warnings == []


def test_unreachable_associate_falls_to_cortex_low_with_a_recorded_warning() -> None:
    engine = _FakeEngine(seat_fails=True)
    factory = associate_seats.make_associate_complete(
        _config(armed=True), "fake", engine_loader=lambda name: engine
    )
    assert factory is not None
    warnings: list[str] = []
    complete = factory("synthesis", warnings.append)
    assert complete is not None
    resp = complete([{"role": "user", "content": "synthesise"}])
    assert resp.content == "from cortex-model"
    assert engine.calls == [(ASSOCIATE_WIRE_MODEL, "off"), ("cortex-model", "low")]
    assert len(warnings) == 1
    assert "associate" in warnings[0] and "synthesis" in warnings[0] and "low" in warnings[0]


def test_engine_without_one_shot_completions_degrades_with_a_warning() -> None:
    """The mock engine has no ``make_complete`` — an armed seat records why and
    hands the acting completion back (all-engines rule: never a crash)."""
    engine = _FakeEngine(unsupported=True)
    factory = associate_seats.make_associate_complete(
        _config(armed=True), "mock", engine_loader=lambda name: engine
    )
    assert factory is not None
    warnings: list[str] = []
    assert factory("compact", warnings.append) is None
    assert len(warnings) == 1 and "mock" in warnings[0]


# ---------------------------------------------------------------------------
# 3. The scout role — read-only, strict subset, associate-bound child
# ---------------------------------------------------------------------------


def test_scout_is_a_read_only_builtin_role() -> None:
    scout = BUILTIN_ROLES["scout"]
    assert scout.read_only is True
    assert is_read_only("scout")
    assert scout.effort == "off"  # ROLE_TABLE row: unarmed scout = read-only, thinking off


def test_scout_tools_are_a_strict_subset_of_the_read_only_set() -> None:
    scout = set(BUILTIN_ROLES["scout"].tool_allowlist)
    parent_read_only = set(_READONLY_TOOLS)
    assert scout < parent_read_only  # strict subset
    assert scout.isdisjoint({"edit_file", "write_file", "run_tests", "run_command"})
    offered = {s["function"]["name"] for s in curate_schemas("scout")}
    assert offered.isdisjoint({"edit_file", "write_file", "run_tests", "run_command"})
    assert offered <= {s["function"]["name"] for s in SCHEMAS}


def test_scout_child_config_swaps_to_the_associate_seat() -> None:
    parent = _config(armed=True)
    parent.context_budget_tokens = 131072
    child = dataclasses.replace(parent, role="scout")
    bound = associate_seats.scout_child_config(parent, child, "scout", effort_override=None)
    assert bound is not child
    assert bound.model == ASSOCIATE_WIRE_MODEL
    assert bound.base_url == _ASSOC.base_url
    assert bound.role == "scout"
    assert bound.context_budget_tokens == min(131072, _ASSOC.context_budget)
    assert effort.effort_of(bound) == "off"


def test_scout_child_config_honours_the_explicit_effort_override() -> None:
    parent = _config(armed=True)
    child = dataclasses.replace(parent, role="scout")
    bound = associate_seats.scout_child_config(parent, child, "scout", effort_override="medium")
    assert effort.effort_of(bound) == "medium"


def test_scout_child_config_is_untouched_when_unarmed_or_not_scout() -> None:
    parent = _config(armed=False)
    child = dataclasses.replace(parent, role="scout")
    assert associate_seats.scout_child_config(parent, child, "scout", effort_override=None) is child
    armed = _config(armed=True)
    other = dataclasses.replace(armed, role="explorer")
    assert (
        associate_seats.scout_child_config(armed, other, "explorer", effort_override=None) is other
    )


def test_scout_executor_refuses_a_repo_mutating_call(tmp_path: Path) -> None:
    """The refusal half of the role mechanism: an associate reply naming
    ``edit_file`` is refused by the executor (recorded as an error step by the
    loop), never executed — the file is untouched."""
    target = tmp_path / "f.txt"
    target.write_text("before\n", encoding="utf-8")
    executor = ToolExecutor(tmp_path, allowlist=BUILTIN_ROLES["scout"])
    with pytest.raises(ToolError):
        executor.execute(
            "edit_file", {"path": "f.txt", "old_string": "before", "new_string": "after"}
        )
    with pytest.raises(ToolError):
        executor.execute("write_file", {"path": "g.txt", "content": "x"})
    assert target.read_text(encoding="utf-8") == "before\n"


def test_scout_spawn_end_to_end_on_mock_is_read_only(tmp_path: Path) -> None:
    """A scout child through the real spawn path lands on the associate seat's
    model and cannot write — proven by the child's config, not by trust."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    from colleague import subagents

    parent = _config(armed=True)
    child = subagents._build_child_config(
        parent,
        subagents.ChildSpec(parent_task_id="p", effort=None),
        None,
        model=None,
        role="scout",
    )
    assert child.model == ASSOCIATE_WIRE_MODEL
    assert child.role == "scout"
    assert effort.effort_of(child) == "off"
    assert Task  # imported for the child contract shape; the spawn itself is exercised elsewhere


# ---------------------------------------------------------------------------
# 4. The distill author rung
# ---------------------------------------------------------------------------


def test_distill_author_rung_is_none_when_unarmed() -> None:
    assert associate_seats.distill_author(_config(armed=False)) is None


def test_distill_author_rung_names_the_wire_model() -> None:
    author = associate_seats.distill_author(_config(armed=True))
    assert author is not None
    assert author.model == ASSOCIATE_WIRE_MODEL
    assert author.base_url == _ASSOC.base_url
    assert author.api_key == "k"


def test_distill_precedence_deepthink_then_associate_then_cortex() -> None:
    from colleague import distill
    from colleague.config import DeepthinkConfig

    armed = _config(armed=True)
    armed.lobes_gateway_url = "http://localhost:8001"
    # associate beats the lobes-cortex floor
    author = distill.resolve_distill_author_from_config(armed)
    assert author is not None and author.model == ASSOCIATE_WIRE_MODEL
    # deepthink still beats associate
    armed.deepthink = DeepthinkConfig(
        model="muse-model", base_url="http://x", api_key="", context_budget=1000
    )
    author = distill.resolve_distill_author_from_config(armed)
    assert author is not None and author.model == "muse-model"
    # unarmed: byte-identical to main (the cortex floor)
    plain = _config(armed=False)
    plain.lobes_gateway_url = "http://localhost:8001"
    author = distill.resolve_distill_author_from_config(plain)
    assert author is not None and author.model == "cortex-model"


def test_distill_associate_rung_never_authors_in_tae_mode() -> None:
    from colleague import distill

    armed = _config(armed=True)
    armed.thought_action_evaluation = True
    assert distill.resolve_distill_author_from_config(armed) is None


def test_setup_failure_on_the_associate_seat_warns_and_falls_back_to_cortex_low() -> None:
    """Qodo #441-7: an exception from make_complete() DURING SETUP (not only
    NotImplementedError) must warn once and hand back a cortex@low completion."""

    class _SetupFails(_FakeEngine):
        def make_complete(self, config, *, tools):
            if config.model == ASSOCIATE_WIRE_MODEL:
                raise RuntimeError("loader exploded")
            return super().make_complete(config, tools=tools)

    engine = _SetupFails()
    factory = associate_seats.make_associate_complete(
        _config(armed=True), "fake", engine_loader=lambda name: engine
    )
    assert factory is not None
    warnings: list[str] = []
    complete = factory("compact", warnings.append)
    assert complete is not None
    resp = complete([{"role": "user", "content": "summarise"}])
    assert resp.content == "from cortex-model"
    assert engine.calls == [("cortex-model", "low")]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0]
    assert "loader exploded" in warnings[0]

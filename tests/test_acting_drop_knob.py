"""The acting-seat-scoped tool drop knob (plan t8, the surface lever's
instrument).

``COLLEAGUE_TOOLS_LEGACY`` is REJECTED as the instrument: it is role-blind
(``curate_schemas`` consults it for EVERY role) and strips the scout child too
(8 tools -> 6). This knob is the replacement — a NAMED drop-set applied at
depth 0 only, threaded through ``tools.narrow_role_by_tool_set`` (the same
composed value that feeds ``curate_schemas`` AND ``ToolExecutor``'s refusal
half), so the acting seat loses the named tools while a spawned child keeps
them.

Acceptance (verbatim from the working instruction):

1. with the knob naming ``grep_search`` and ``glob``, the acting seat's
   rendered surface lacks both while a scout child's rendered surface still
   holds them;
2. with the knob unset, every rendered surface is byte-identical to today for
   every role;
3. the drop applies at depth 0 only and flows through the single composed
   value that feeds ``curate_schemas`` AND ``ToolExecutor``'s refusal half —
   no second refusal mechanism.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import actingsurface
from colleague.config import EngineConfig
from colleague.loop import resolve_role
from colleague.roles import BUILTIN_ROLES
from colleague.tools import ToolError, ToolExecutor, curate_schemas, narrow_role_by_tool_set

#: The knob's env name (the acting-seat-scoped drop-set).
DROP_ENV = "COLLEAGUE_ACTING_DROP_TOOLS"


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


def _offered(role) -> set[str]:
    return {s["function"]["name"] for s in curate_schemas(role)}


# ---------------------------------------------------------------------------
# (1) The acting seat loses the named tools; a scout child keeps them.
# ---------------------------------------------------------------------------


def test_acting_seat_drops_named_tools(monkeypatch: pytest.MonkeyPatch, git_repo: Path) -> None:
    monkeypatch.setenv(DROP_ENV, "grep_search,glob")
    role = resolve_role(EngineConfig(), str(git_repo))
    offered = _offered(role)
    assert "grep_search" not in offered
    assert "glob" not in offered
    # The rest of the acting seat's surface is untouched.
    assert {"read_file", "write_file", "edit_file", "finish"} <= offered


def test_scout_child_keeps_named_tools(monkeypatch: pytest.MonkeyPatch, git_repo: Path) -> None:
    """The drop is depth-0-only: a spawned scout child (depth 1) still holds
    ``grep_search``/``glob`` — the very delegate the knob is meant to make
    attractive is not crippled by it."""
    monkeypatch.setenv(DROP_ENV, "grep_search,glob")
    config = EngineConfig(role="scout")
    setattr(config, "child_depth", 1)
    role = resolve_role(config, str(git_repo))
    offered = _offered(role)
    assert "grep_search" in offered
    assert "glob" in offered


def test_explicit_writer_acting_seat_drops_named_tools(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """An explicit ``--role writer`` acting seat (depth 0) drops the named
    tools too — the knob is seat-scoped, not role-name-scoped."""
    monkeypatch.setenv(DROP_ENV, "grep_search,glob")
    role = resolve_role(EngineConfig(role="writer"), str(git_repo))
    offered = _offered(role)
    assert "grep_search" not in offered
    assert "glob" not in offered


# ---------------------------------------------------------------------------
# (2) Unset knob: every rendered surface is byte-identical to today.
# ---------------------------------------------------------------------------


def test_unset_knob_is_byte_identical_for_every_role(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    monkeypatch.delenv(DROP_ENV, raising=False)
    for name in BUILTIN_ROLES:
        config = EngineConfig(role=name)
        role = resolve_role(config, str(git_repo))
        assert _offered(role) == _offered(BUILTIN_ROLES[name])
    # The bare acting seat (role None, depth 0) resolves to the writer surface.
    bare = resolve_role(EngineConfig(), str(git_repo))
    assert _offered(bare) == _offered(BUILTIN_ROLES["writer"])


def test_unset_knob_child_surfaces_byte_identical(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    monkeypatch.delenv(DROP_ENV, raising=False)
    for name in BUILTIN_ROLES:
        config = EngineConfig(role=name)
        setattr(config, "child_depth", 1)
        role = resolve_role(config, str(git_repo))
        # A depth-1 child is the role's surface minus the never-inheritable
        # names: the purpose tools (q9) and the raw subagent/subagents
        # (plan t11's confinement, kept as defence in depth).
        assert _offered(role) == _offered(
            actingsurface.strip_child_forbidden_tools(BUILTIN_ROLES[name])
        )


# ---------------------------------------------------------------------------
# (3) The drop flows through the single composed value: curate_schemas AND
#     ToolExecutor's refusal half — no second refusal mechanism.
# ---------------------------------------------------------------------------


def test_acting_seat_executor_refuses_dropped_tools(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """The SAME composed value that hides the schema also refuses dispatch —
    the executor's existing ``allowlist=`` seam, never a second mechanism."""
    monkeypatch.setenv(DROP_ENV, "grep_search,glob")
    role = resolve_role(EngineConfig(), str(git_repo))
    executor = ToolExecutor(str(git_repo), allowlist=role)
    for name in ("grep_search", "glob"):
        with pytest.raises(ToolError, match="not allowed for this role"):
            executor.execute(name, {})


def test_drop_applies_at_depth_zero_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """``curate_for_depth`` is the ONE seam that knows the depth: the drop is
    applied at depth 0 and is a no-op at depth >= 1."""
    monkeypatch.setenv(DROP_ENV, "grep_search,glob")
    writer = BUILTIN_ROLES["writer"]
    seat = EngineConfig()
    child = EngineConfig()
    setattr(child, "child_depth", 1)
    # Depth 0: the drop is applied — a NEW role (the writer holds no purpose
    # tools, so the only change is the drop), not the original.
    seat_role = actingsurface.curate_for_depth(writer, seat)
    assert seat_role is not writer
    assert "grep_search" not in seat_role.tool_allowlist
    assert "glob" not in seat_role.tool_allowlist
    # Depth >= 1: the drop is NOT applied — the child's surface is the writer's
    # purpose-stripped surface, which STILL holds grep_search/glob.
    child_role = actingsurface.curate_for_depth(writer, child)
    assert "grep_search" in child_role.tool_allowlist
    assert "glob" in child_role.tool_allowlist


def test_narrow_role_by_tool_set_drop_param() -> None:
    """The drop is threaded through ``narrow_role_by_tool_set`` (the named
    drop-set), not a new narrowing engine."""
    writer = BUILTIN_ROLES["writer"]
    narrowed = narrow_role_by_tool_set(writer, drop=("grep_search", "glob"))
    assert "grep_search" not in narrowed.tool_allowlist
    assert "glob" not in narrowed.tool_allowlist
    # Everything else survives.
    assert "read_file" in narrowed.tool_allowlist
    assert "write_file" in narrowed.tool_allowlist


def test_narrow_role_by_tool_set_drop_is_noop_when_empty() -> None:
    """An empty drop-set returns the role unchanged (byte-identical)."""
    writer = BUILTIN_ROLES["writer"]
    assert narrow_role_by_tool_set(writer, drop=()) is writer
    assert narrow_role_by_tool_set(writer) is writer


def test_narrow_role_by_tool_set_drop_with_none_role() -> None:
    """``role=None`` + a non-empty drop narrows the FULL surface down to
    everything-but-the-drop (a synthetic non-read-only role)."""
    from colleague.tools import TOOL_NAMES

    narrowed = narrow_role_by_tool_set(None, drop=("grep_search", "glob"))
    assert narrowed is not None
    assert "grep_search" not in narrowed.tool_allowlist
    assert "glob" not in narrowed.tool_allowlist
    assert set(narrowed.tool_allowlist) == set(TOOL_NAMES) - {"grep_search", "glob"}
    assert narrowed.read_only is False


def test_drop_set_computed_once_and_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    """The drop-set is read ONCE and the SAME composed value feeds both halves
    — the offered schema and the executor's refusal half never diverge."""
    monkeypatch.setenv(DROP_ENV, "grep_search,glob")
    drop = actingsurface.acting_drop_set()
    assert drop == ("grep_search", "glob")
    # The composed value is the single return of resolve_role; both halves
    # consume it.
    role = narrow_role_by_tool_set(BUILTIN_ROLES["writer"], drop=drop)
    offered = _offered(role)
    executor = ToolExecutor("/tmp", allowlist=role)
    assert "grep_search" not in offered
    assert "glob" not in offered
    for name in ("grep_search", "glob"):
        with pytest.raises(ToolError, match="not allowed for this role"):
            executor.execute(name, {})


def test_acting_drop_set_parses_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DROP_ENV, " grep_search , glob , read_file ")
    assert actingsurface.acting_drop_set() == ("grep_search", "glob", "read_file")


def test_acting_drop_set_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DROP_ENV, raising=False)
    assert actingsurface.acting_drop_set() == ()


def test_narrow_role_none_applies_drop_after_tool_set() -> None:
    """``role=None`` + a non-empty ``tool_set`` AND ``drop``: the drop-set is
    applied AFTER the intersection (Qodo #450 / comment 3887387007 — the drop
    was silently ignored), preserving ``tool_set`` order."""
    narrowed = narrow_role_by_tool_set(
        None,
        tool_set=("read_file", "grep_search", "write_file"),
        drop=("grep_search",),
    )
    assert narrowed is not None
    assert "grep_search" not in narrowed.tool_allowlist
    assert narrowed.tool_allowlist == ("read_file", "write_file")
    assert narrowed.read_only is False

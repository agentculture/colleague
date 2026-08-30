"""The acting-seat-scoped tool ADD knob (the surface lever's arm instrument,
spec c3/D3).

The mirror of ``COLLEAGUE_ACTING_DROP_TOOLS`` (plan t8): a NAMED add-set
applied at depth 0 only, at the ONE seam that already knows the depth
(:func:`colleague.actingsurface.curate_for_depth`), so the acting seat GAINS
the named tools while a spawned child never does. Unlike the drop knob (which
threads through ``tools.narrow_role_by_tool_set``), the add is a plain
``dataclasses.replace`` that appends the new names to the role's allow-list —
and it is an ARM instrument, not a gate: an unknown name (one that does not
exist in ``tools.SCHEMAS``) is ignored and recorded nowhere.

Acceptance (verbatim from the working instruction):

1. ``actingsurface.acting_add_set()`` reads ``COLLEAGUE_ACTING_ADD_TOOLS``
   (comma-separated, order-preserving, de-duplicated; unset/blank = ``()``)
   and ``curate_for_depth`` applies it at depth 0 AFTER the drop knob, adding
   only names that exist in ``tools.SCHEMAS``;
2. a depth-1 child never gains the added names (``strip_child_forbidden_tools``
   still removes ``subagent``/``subagents``);
3. with the knob unset every existing test in
   ``tests/test_acting_drop_knob.py`` and
   ``tests/test_purpose_tools_byte_identical.py`` passes unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import actingsurface
from colleague.config import EngineConfig
from colleague.loop import resolve_role
from colleague.roles import BUILTIN_ROLES
from colleague.tools import SCHEMAS, ToolExecutor, curate_schemas

#: The knob's env name (the acting-seat-scoped add-set).
ADD_ENV = "COLLEAGUE_ACTING_ADD_TOOLS"

#: A name that exists in ``tools.SCHEMAS`` but is NOT on the writer seat's
#: allow-list (dropped by plan t5's purpose swap) — the clean "add" candidate.
ADD_NAME = "web"


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
# (1) The acting seat gains the named tools; a child never does.
# ---------------------------------------------------------------------------


def test_acting_seat_adds_named_tools(monkeypatch: pytest.MonkeyPatch, git_repo: Path) -> None:
    monkeypatch.setenv(ADD_ENV, ADD_NAME)
    role = resolve_role(EngineConfig(), str(git_repo))
    offered = _offered(role)
    assert ADD_NAME in offered
    # The rest of the acting seat's surface is untouched.
    assert {"read_file", "write_file", "edit_file", "finish"} <= offered


def test_explicit_writer_acting_seat_adds_named_tools(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """An explicit ``--role writer`` acting seat (depth 0) gains the named
    tool too — the knob is seat-scoped, not role-name-scoped."""
    monkeypatch.setenv(ADD_ENV, ADD_NAME)
    role = resolve_role(EngineConfig(role="writer"), str(git_repo))
    offered = _offered(role)
    assert ADD_NAME in offered


def test_child_never_gains_added_names(monkeypatch: pytest.MonkeyPatch, git_repo: Path) -> None:
    """The add is depth-0-only: a spawned child (depth 1) never gains the added
    name — even the raw ``subagent``/``subagents`` names, which
    ``strip_child_forbidden_tools`` removes regardless of the add knob."""
    monkeypatch.setenv(ADD_ENV, "subagent,subagents")
    config = EngineConfig(role="scout")
    setattr(config, "child_depth", 1)
    role = resolve_role(config, str(git_repo))
    offered = _offered(role)
    assert "subagent" not in offered
    assert "subagents" not in offered


def test_add_applies_at_depth_zero_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """``curate_for_depth`` is the ONE seam that knows the depth: the add is
    applied at depth 0 and is a no-op at depth >= 1."""
    monkeypatch.setenv(ADD_ENV, ADD_NAME)
    writer = BUILTIN_ROLES["writer"]
    seat = EngineConfig()
    child = EngineConfig()
    setattr(child, "child_depth", 1)
    # Depth 0: the add is applied — a NEW role (the writer holds no ``web``,
    # so the only change is the add), not the original.
    seat_role = actingsurface.curate_for_depth(writer, seat)
    assert seat_role is not writer
    assert ADD_NAME in seat_role.tool_allowlist
    # Depth >= 1: the add is NOT applied — the child's surface is the writer's
    # purpose-stripped surface, which never holds ``web``.
    child_role = actingsurface.curate_for_depth(writer, child)
    assert ADD_NAME not in child_role.tool_allowlist


def test_add_applied_after_drop(monkeypatch: pytest.MonkeyPatch, git_repo: Path) -> None:
    """The add is applied at depth 0 AFTER the drop knob: a dropped name stays
    gone and an added name is gained, in one resolution."""
    monkeypatch.setenv("COLLEAGUE_ACTING_DROP_TOOLS", "glob")
    monkeypatch.setenv(ADD_ENV, ADD_NAME)
    role = resolve_role(EngineConfig(), str(git_repo))
    offered = _offered(role)
    assert "glob" not in offered
    assert ADD_NAME in offered


def test_unknown_add_name_is_ignored(monkeypatch: pytest.MonkeyPatch, git_repo: Path) -> None:
    """An add name that does not exist in ``tools.SCHEMAS`` is ignored and
    recorded nowhere — the knob is an arm instrument, never a gate."""
    monkeypatch.setenv(ADD_ENV, "no_such_tool")
    role = resolve_role(EngineConfig(), str(git_repo))
    offered = _offered(role)
    assert "no_such_tool" not in offered
    # The surface is byte-identical to the unarmed writer seat.
    assert offered == _offered(BUILTIN_ROLES["writer"])


def test_add_only_names_that_exist_in_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only names present in ``tools.SCHEMAS`` are added; a mix of known and
    unknown adds the known one and silently drops the unknown."""
    monkeypatch.setenv(ADD_ENV, f"{ADD_NAME},no_such_tool")
    writer = BUILTIN_ROLES["writer"]
    seat = EngineConfig()
    seat_role = actingsurface.curate_for_depth(writer, seat)
    assert ADD_NAME in seat_role.tool_allowlist
    assert "no_such_tool" not in seat_role.tool_allowlist
    assert set(s["function"]["name"] for s in SCHEMAS) >= {ADD_NAME}


# ---------------------------------------------------------------------------
# (2) Unset knob: every rendered surface is byte-identical to today.
# ---------------------------------------------------------------------------


def test_unset_knob_is_byte_identical_for_every_role(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    monkeypatch.delenv(ADD_ENV, raising=False)
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
    monkeypatch.delenv(ADD_ENV, raising=False)
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
# (3) The add flows through the single composed value: curate_schemas AND
#     ToolExecutor's dispatch half — no second mechanism.
# ---------------------------------------------------------------------------


def test_acting_seat_executor_allows_added_tools(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """The SAME composed value that offers the schema also dispatches it — the
    executor's existing ``allowlist=`` seam, never a second mechanism."""
    monkeypatch.setenv(ADD_ENV, ADD_NAME)
    role = resolve_role(EngineConfig(), str(git_repo))
    executor = ToolExecutor(str(git_repo), allowlist=role)
    # The added name is on the allow-list, so it is NOT refused as
    # "not allowed for this role" (it may still fail on its own dispatch, but
    # the role gate passes).
    assert ADD_NAME in role.tool_allowlist
    assert ADD_NAME in executor._allowlist


def test_add_set_computed_once_and_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    """The add-set is read ONCE and the SAME composed value feeds both halves —
    the offered schema and the executor's dispatch half never diverge."""
    monkeypatch.setenv(ADD_ENV, ADD_NAME)
    add = actingsurface.acting_add_set()
    assert add == (ADD_NAME,)
    # The composed value is the single return of resolve_role; both halves
    # consume it.
    role = resolve_role(EngineConfig(), "/tmp")
    offered = _offered(role)
    executor = ToolExecutor("/tmp", allowlist=role)
    assert ADD_NAME in offered
    assert ADD_NAME in executor._allowlist


def test_acting_add_set_parses_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADD_ENV, " web , subagent , read_file ")
    assert actingsurface.acting_add_set() == ("web", "subagent", "read_file")


def test_acting_add_set_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADD_ENV, "web,web,subagent")
    assert actingsurface.acting_add_set() == ("web", "subagent")


def test_acting_add_set_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ADD_ENV, raising=False)
    assert actingsurface.acting_add_set() == ()


def test_acting_add_set_empty_when_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADD_ENV, "   ,  ")
    assert actingsurface.acting_add_set() == ()

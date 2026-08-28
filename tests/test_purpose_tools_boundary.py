"""Purpose-tools boundary guards (plan task t13, spec c1/h1).

Pure ``ast`` structural guards — no imports from the loop — proving four
honesty conditions about the four modules this arc introduced
(``colleague/purpose_schemas.py``, ``colleague/efforttables.py``,
``colleague/distilleffort.py``, ``colleague/cli/_commands/_effort_groups.py``):

1. **The existing thinking-effort AST guard
   (``tests/test_thinking_effort_boundary.py``) already covers the new
   modules** — its ``_effort_assignments`` scanner walks EVERY file under
   ``colleague/`` (``COLLEAGUE_DIR.rglob("*.py")``), so the four new modules
   were already in scope the moment they landed; none of the four is in that
   test's ``_SANCTIONED_ASSIGN_FILES`` allow-list (a stated reason: none of
   them is a seat BUILDER — ``efforttables.py``/``distilleffort.py`` are pure
   table/precedence-resolution helpers that return a rung as a plain string,
   ``purpose_schemas.py`` reads a resolved rung to pass to the spawn call, and
   ``_effort_groups.py`` is a display/mutation-of-``reasoning_effort_seats``
   surface for the CLI — none of the four ever assigns
   ``config.reasoning_effort`` / ``config.reasoning_effort_seat`` directly),
   and this module re-asserts that fact directly against the four files (not
   only via the rglob side-effect) so a future edit that adds an assignment
   to one of them fails HERE with a purpose-tools-specific message, not only
   in the pre-existing generic guard.
2. **The existing associate-seat AST guard
   (``tests/test_associate_seats.py::test_ast_guard_config_associate_referenced_
   only_by_the_consumers``) already covers the new modules** the same way
   (full ``colleague/`` rglob); none of the four references ``config.associate``
   — a stated reason: purpose tools resolve effort via
   :data:`colleague.efforttables.PURPOSE_TABLE`/``ASSOCIATE_SEAT_TABLE``, never
   by reading ``config.associate`` themselves (the associate *seat* itself is
   swapped in by ``associate_seats.scout_child_config``, one of the already-
   enumerated consumers) — re-asserted directly here.
3. **No per-turn path assigns effort** — mirrors
   ``test_thinking_effort_boundary.py``'s forbidden-file pin
   (``loop.py``/``senses_loop.py``), extended to confirm the new modules are
   not themselves reachable from a per-turn call site that would make them a
   de facto per-turn assignment path (structurally: none of the four imports
   ``colleague.loop`` or ``colleague.senses_loop``, so they cannot BE the
   per-turn path in disguise).
4. **``purpose_schemas.py`` imports no ``worktrees``/``subprocess``** (a grep
   guard restated here at the boundary-test level; ``tests/
   test_purpose_executor.py::test_purpose_schemas_imports_no_worktree_or_
   subprocess_machinery`` already covers this at the unit level — this is the
   SAME assertion, kept here too so the boundary suite is self-contained).
5. **No purpose schema carries an ``effort``/``model``/``engine``/``role``
   property** — the model can never pick a rung, a backend, or a role through
   a purpose tool's arguments (c24/h27); restated here as a boundary
   assertion (``tests/test_purpose_schemas.py::test_no_forbidden_properties_
   in_any_purpose_schema`` already covers it at the unit level).

Each of 1-2 also carries a NON-VACUOUS twin (mirroring
``test_effort_assign_guard_is_not_vacuous`` /
``test_no_router_guard_is_not_vacuous``): the local scanner used here
actually flags a planted violation, so the "none of the four offends" result
above cannot be a scanner that silently finds nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLEAGUE_DIR = REPO_ROOT / "colleague"

#: The four modules this arc introduced (purpose-tools-associate-seat, plan
#: tasks t1/t3/t4/t10) — named here so a reader sees, in one place, every
#: module this task's guards are about.
NEW_MODULES: "tuple[str, ...]" = (
    "colleague/purpose_schemas.py",
    "colleague/efforttables.py",
    "colleague/distilleffort.py",
    "colleague/cli/_commands/_effort_groups.py",
)

#: Mirrors ``test_thinking_effort_boundary.py``'s ``_EFFORT_ATTRS``.
_EFFORT_ATTRS = frozenset({"reasoning_effort", "reasoning_effort_seat"})

#: Mirrors ``test_associate_seats.py``'s allow-listed consumers of
#: ``config.associate`` — the enumerated set none of the four new modules is on.
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

#: The two per-turn paths that must never assign effort (mirrors
#: ``_FORBIDDEN_ASSIGN_FILES`` in ``test_thinking_effort_boundary.py``).
_PER_TURN_PATHS = frozenset({"colleague/loop.py", "colleague/senses_loop.py"})


def _tree(rel: str) -> ast.AST:
    return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _effort_assignments(tree: ast.AST) -> "list[str]":
    """Every ASSIGNMENT to an effort attribute (line-numbered) — same shape
    as ``test_thinking_effort_boundary.py``'s scanner."""
    offenders: "list[str]" = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in _EFFORT_ATTRS:
                    offenders.append(f"line {node.lineno}: {target.attr} = ...")
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else None)
            )
            if name != "setattr" or not node.args:
                continue
            attr = node.args[1]
            if isinstance(attr, ast.Constant) and attr.value in _EFFORT_ATTRS:
                offenders.append(f"line {node.lineno}: setattr(..., {attr.value!r}, ...)")
    return offenders


def _associate_attr_refs(tree: ast.AST) -> "list[int]":
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "associate"
    ]


# ---------------------------------------------------------------------------
# 1. The four new modules are outside the effort-assign sanctioned set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", NEW_MODULES)
def test_new_module_assigns_no_effort_attribute(rel: str) -> None:
    """None of the four new modules ASSIGNS ``reasoning_effort``/
    ``reasoning_effort_seat`` — they read/resolve/return rungs as plain
    values (:func:`colleague.efforttables.resolve_purpose_effort` etc.), the
    seat BUILDERS (``associate.py``, the five seat builders, ``config.py``)
    are the only sanctioned assigners, per ``test_thinking_effort_boundary.
    py``'s already-covering rglob guard — restated here module-by-module."""
    offenders = _effort_assignments(_tree(rel))
    assert not offenders, (
        f"{rel} assigns the thinking-effort rung — it is a table/resolution "
        f"helper, not a seat builder (c1/h1):\n" + "\n".join(offenders)
    )


def test_new_module_effort_scanner_is_not_vacuous() -> None:
    """Non-vacuous twin: the local scanner actually catches a planted
    per-module effort assignment, so the all-pass result above is not a
    silently-broken scanner."""
    snippet = (
        "def build(config):\n"
        "    config.reasoning_effort_seat = 'low'\n"
        "    setattr(config, 'reasoning_effort', 'off')\n"
    )
    offenders = _effort_assignments(ast.parse(snippet))
    assert len(offenders) == 2


# ---------------------------------------------------------------------------
# 2. The four new modules never reference config.associate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", NEW_MODULES)
def test_new_module_references_no_config_associate(rel: str) -> None:
    """None of the four new modules is on ``test_associate_seats.py``'s
    enumerated ``config.associate`` consumer list, and indeed references no
    ``.associate`` attribute at all: purpose tools resolve their rung from
    :data:`colleague.efforttables.PURPOSE_TABLE`/``ASSOCIATE_SEAT_TABLE`` —
    the associate SEAT swap itself stays inside ``associate_seats.py`` (an
    already-enumerated consumer), never duplicated here."""
    assert rel not in _ASSOCIATE_ATTR_ALLOWED, (
        f"{rel} must stay OFF the config.associate consumer allow-list "
        "(purpose tools resolve effort via efforttables, not config.associate)"
    )
    offenders = _associate_attr_refs(_tree(rel))
    assert not offenders, f"{rel} references config.associate at line(s) {offenders}"


def test_new_module_associate_scanner_is_not_vacuous() -> None:
    """Non-vacuous twin for the ``.associate`` scanner."""
    snippet = "def f(config):\n    return config.associate\n"
    assert _associate_attr_refs(ast.parse(snippet)) == [2]


# ---------------------------------------------------------------------------
# 3. None of the four new modules imports the per-turn paths (so none of
#    them can quietly BE a per-turn effort-assignment path)
# ---------------------------------------------------------------------------


def _imported_modules(tree: ast.AST) -> "set[str]":
    names: "set[str]" = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("rel", NEW_MODULES)
def test_new_module_does_not_import_a_per_turn_path(rel: str) -> None:
    imported = _imported_modules(_tree(rel))
    for forbidden in _PER_TURN_PATHS:
        forbidden_module = forbidden.removeprefix("colleague/").removesuffix(".py")
        forbidden_dotted = f"colleague.{forbidden_module}"
        assert forbidden_dotted not in imported and forbidden_module not in imported, (
            f"{rel} imports the per-turn path {forbidden} — a new module must never "
            "become a de facto per-turn effort-assignment path (c1/h1)"
        )


# ---------------------------------------------------------------------------
# 4. purpose_schemas.py imports no worktrees/subprocess (restated grep guard)
# ---------------------------------------------------------------------------


def test_purpose_schemas_imports_no_worktrees_or_subprocess() -> None:
    source = (COLLEAGUE_DIR / "purpose_schemas.py").read_text(encoding="utf-8")
    for banned in ("import subprocess", "colleague.worktrees", "from colleague import worktrees"):
        assert banned not in source, f"purpose_schemas.py must not reference {banned!r}"


# ---------------------------------------------------------------------------
# 5. No purpose schema carries an effort/model/engine/role property
# ---------------------------------------------------------------------------


def test_no_purpose_schema_has_a_model_choosing_property() -> None:
    from colleague.purpose_schemas import PURPOSE_SCHEMAS

    forbidden = {"effort", "model", "engine", "role"}
    for name, schema in PURPOSE_SCHEMAS.items():
        properties = set(schema["function"]["parameters"]["properties"])
        offending = properties & forbidden
        assert not offending, f"{name}'s schema exposes {offending} — the model must never pick one"

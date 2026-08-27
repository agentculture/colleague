"""Per-seat thinking-effort boundary guard (#416 t9, spec c3/h3, c1/h1).

Proves the honesty condition structurally, with pure stdlib (``ast``) — no
imports from the loop:

* **Effort is assigned only where a seat is BUILT.** The per-seat rung
  (``reasoning_effort_seat``) and the global knob (``reasoning_effort``) are
  written ONLY in the sanctioned set: ``config.py`` (resolve), ``effort.py``
  (the tables/fragment), ``roles.py`` (Role.effort), the five seat builders
  (``deepthink.py``, ``senses.py``, ``tae_loop.py``, ``agents/runtime.py``),
  the ``subagents.py`` child builds, and ``design.py`` (the design
  call-site seat builder, #416 t6). Nothing under the loop's per-turn
  path — ``loop.py`` step handling, ``senses_loop.py`` moves — writes or
  rewrites it. A per-turn effort choice would be the same excluded router
  that ``tests/test_agents_boundary.py``'s no-router guard pins (s6).
* **Non-vacuous twin** (mirrors ``test_no_router_guard_is_not_vacuous``): the
  scanner flags a planted per-turn assignment, so the guard above cannot pass
  vacuously.

The guard is deliberately sober: it flags an *assignment* to the effort
attributes (``config.reasoning_effort = ...`` / ``setattr(cfg,
"reasoning_effort_seat", ...)``), not a *read* — the seat builders and the
vLLM driver read the rung all the time, and reads are the sanctioned shape.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLEAGUE_DIR = REPO_ROOT / "colleague"

#: The ONLY files that may ASSIGN the effort attributes (c3/h3).
#:
#: ``config.py`` — resolve() sets the global knob + per-seat overrides;
#: ``effort.py`` — the tables/fragment module (no config import, t1);
#: ``roles.py`` — Role.effort field + overlay parsing (t5);
#: the five seat builders — ``deepthink.py``, ``senses.py``, ``tae_loop.py``,
#: ``agents/runtime.py`` (t4) and the ``subagents.py`` child builds (t5);
#: ``cli/_commands/config.py`` — the config-show read surface (prints, never
#: re-resolves).
#:
#: NOT on the list: ``loop.py`` (step handling), ``senses_loop.py`` (moves),
#: ``engines/vllm_openai.py`` (the driver READS the rung; it never writes it).
_SANCTIONED_ASSIGN_FILES = frozenset(
    {
        "colleague/config.py",
        "colleague/effort.py",
        "colleague/roles.py",
        "colleague/deepthink.py",
        "colleague/senses.py",
        "colleague/tae_loop.py",
        "colleague/agents/runtime.py",
        "colleague/subagents.py",
        "colleague/cli/_commands/config.py",
        "colleague/design.py",
        # adopt-from-qwen-code t18: the associate seat builder.
        "colleague/associate.py",
    }
)

#: The per-turn paths that must NEVER assign effort (c3/h3).
_FORBIDDEN_ASSIGN_FILES = frozenset(
    {
        "colleague/loop.py",
        "colleague/senses_loop.py",
    }
)

#: Attribute names that carry the effort rung.
_EFFORT_ATTRS = frozenset({"reasoning_effort", "reasoning_effort_seat"})


def _colleague_py_files() -> list[Path]:
    return sorted(p for p in COLLEAGUE_DIR.rglob("*.py") if p.is_file())


def _effort_assignments(tree: ast.AST) -> list[str]:
    """Every ASSIGNMENT to an effort attribute in *tree* (line-numbered).

    Flags, soberly:

    * ``<target>.reasoning_effort = ...`` / ``<target>.reasoning_effort_seat =
      ...`` (ast.Assign with an Attribute target), and
    * ``setattr(<cfg>, "reasoning_effort", ...)`` /
      ``setattr(<cfg>, "reasoning_effort_seat", ...)`` (the seat builders'
      dynamic-attribute convention — a plain attribute, not a dataclass
      field, so it rides ``dataclasses.replace`` copies exactly like
      ``role``/``worker``).

    Reads (``config.reasoning_effort``) are NOT flagged — the sanctioned
    shape is "set once where the seat is built, read anywhere".
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in _EFFORT_ATTRS:
                    offenders.append(f"  line {node.lineno}: {target.attr} = ...")
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
                offenders.append(f"  line {node.lineno}: setattr(..., {attr.value!r}, ...)")
    return offenders


def test_effort_assigned_only_in_sanctioned_files() -> None:
    """``reasoning_effort`` / ``reasoning_effort_seat`` is ASSIGNED only in the
    sanctioned set — config.py, effort.py, roles.py, the five seat builders
    and the subagents.py child builds (c3/h3).

    The loop's per-turn path (loop.py step handling, senses_loop moves) never
    writes or rewrites the rung: a per-turn effort choice would be a router,
    the same excluded shape tests/test_agents_boundary.py pins (s6).
    """
    offenders: list[str] = []
    for path in _colleague_py_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _FORBIDDEN_ASSIGN_FILES:
            # Hard fail on the per-turn paths, whatever the scanner finds.
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for off in _effort_assignments(tree):
                offenders.append(f"  {rel}{off}")
            continue
        if rel not in _SANCTIONED_ASSIGN_FILES:
            # Any OTHER file assigning effort is a drift too (the sanctioned
            # set is closed — adding a writer means editing this test).
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for off in _effort_assignments(tree):
                offenders.append(f"  {rel}{off}")
    assert not offenders, (
        "the thinking-effort rung is assigned outside the sanctioned set "
        "(config.py / effort.py / roles.py / the five seat builders / "
        "subagents.py child builds) — effort is set where a seat is BUILT, "
        "never per turn (c3/h3):\n" + "\n".join(offenders)
    )


def test_no_per_turn_path_assigns_effort() -> None:
    """The per-turn paths specifically — loop.py step handling and
    senses_loop.py moves — carry ZERO effort assignments (c3/h3).

    A separate, explicit pin on the two forbidden files so a future edit
    that moves the sanctioned set cannot silently re-allow them.
    """
    offenders: list[str] = []
    for rel in sorted(_FORBIDDEN_ASSIGN_FILES):
        path = REPO_ROOT / rel
        assert path.is_file(), f"per-turn path {rel} is missing — the guard is stale"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for off in _effort_assignments(tree):
            offenders.append(f"  {rel}{off}")
    assert not offenders, (
        "a per-turn path (loop.py step handling / senses_loop moves) writes "
        "the thinking-effort rung — the loop never changes it per turn "
        "(c3/h3):\n" + "\n".join(offenders)
    )


def test_effort_assign_guard_is_not_vacuous() -> None:
    """Positive control (the non-vacuous twin, mirroring
    ``test_no_router_guard_is_not_vacuous``): the scanner actually detects a
    planted per-turn effort assignment — both the plain-attribute form and
    the ``setattr`` form the seat builders use — so the guards above cannot
    pass vacuously.
    """
    snippet = (
        "def step(task, config):\n"
        "    config.reasoning_effort = 'xhigh'\n"
        "    setattr(config, 'reasoning_effort_seat', 'off')\n"
        "    return config.reasoning_effort  # a read — must NOT be flagged\n"
    )
    tree = ast.parse(snippet)
    offenders = _effort_assignments(tree)
    assert (
        len(offenders) == 2
    ), f"guard must flag exactly the two planted assignments (not the read): {offenders!r}"
    assert any("reasoning_effort =" in o for o in offenders)
    assert any("setattr" in o and "reasoning_effort_seat" in o for o in offenders)

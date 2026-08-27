"""Boundary guards for the model-bound agents package (#411, plan task t18).

Proves the c41/h28 and c22/h26 claims structurally, with pure stdlib
(``ast`` + grep) — no imports from ``colleague/loop.py``:

* (a) **No vendor model names** anywhere under ``colleague/agents/`` — the
  package names seats by lobes *role*, never by model family (c41/h28).
* (b) **No router** — no function under ``colleague/agents/`` or in
  ``colleague/loop.py`` reads ``task.instruction`` / ``task.context`` to
  choose a model (c22/h26). The AST guard is deliberately sober and
  explicit: it flags a function whose name contains ``route`` /
  ``select_model`` / ``pick_model`` taking an ``instruction`` /
  ``task_text`` argument, and any call that passes instruction text into
  a model/role-returning function. It does NOT flag ``resolve_profile``
  (which takes ``purpose`` + ``roles``) or ``resolve_role`` (which takes
  ``config`` + ``repo_path``). The only model switch is a
  ``DelegationRequest``.
* (c) The ``_SUBPROCESS_ALLOWED`` / ``_THREADS_ALLOWED`` allow-lists in
  ``tests/test_boundary.py`` are unchanged (pinned here, AST-extracted).
* (d) The TAE schemas (``Thought`` / ``ActionProposal`` / ``Evaluation`` /
  ``LedgerEntry``) are unchanged or additively versioned: the pinned field
  sets may only GROW, and the schema-version constants stay at 1.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "colleague" / "agents"
LOOP_PY = REPO_ROOT / "colleague" / "loop.py"
BOUNDARY_TEST = REPO_ROOT / "tests" / "test_boundary.py"

# ---------------------------------------------------------------------------
# (a) Vendor-name grep guard
# ---------------------------------------------------------------------------

_VENDOR_NAME_RE = re.compile(r"gemma|qwen|nemotron|lightning", re.IGNORECASE)


def _agent_py_files() -> list[Path]:
    return sorted(p for p in AGENTS_DIR.rglob("*.py") if p.is_file())


def test_no_vendor_model_names_under_agents() -> None:
    """No file under colleague/agents/ names a vendor model family (c41/h28).

    The reference topology is named by lobes role (talker=senses,
    worker=worker, thinker_coder=cortex, associate=associate); a vendor
    model id may only appear as *trace data* filled from the gateway's
    advert at resolution time — never as a constant in this package.
    """
    offenders: list[str] = []
    for path in _agent_py_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _VENDOR_NAME_RE.search(line):
                offenders.append(f"  {path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()!r}")
    assert not offenders, (
        "vendor model names found under colleague/agents/ — the package must "
        "name seats by lobes role, never by model family (c41/h28):\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# (b) No-router AST guard
# ---------------------------------------------------------------------------

#: Function names that would signal a model ROUTER (spec q5: an enumerated
#: purpose→role table, not a router).
_ROUTER_NAME_RE = re.compile(r"route|select_model|pick_model", re.IGNORECASE)

#: Argument names that would carry the task's instruction text.
_INSTRUCTION_ARG_NAMES = frozenset({"instruction", "task_text"})

#: Call-argument names that would carry the task's instruction text.
_INSTRUCTION_CALL_ARG_NAMES = frozenset({"instruction", "task_text", "task_instruction"})


def _routing_name(name: str) -> bool:
    """True when *name* looks like a model/role ROUTER (route/select_model/pick_model)."""
    return bool(_ROUTER_NAME_RE.search(name))


def _instruction_text_arg(node: ast.AST) -> bool:
    """True when *node* is an argument that carries the task's instruction text.

    Explicitly: a keyword named ``instruction`` / ``task_text`` /
    ``task_instruction``, a string literal, or an attribute access whose
    attribute is ``instruction`` / ``task_text`` (e.g. ``task.instruction``).
    """
    if isinstance(node, ast.keyword) and node.arg in _INSTRUCTION_CALL_ARG_NAMES:
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Attribute) and node.attr in ("instruction", "task_text"):
        return True
    return False


def _instruction_arg_violations(tree: ast.AST) -> list[str]:
    """Every call in *tree* that passes instruction text into a model/role
    (routing-named) function — the no-router proof (c22/h26)."""
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else None)
        )
        if name is None or not _routing_name(name):
            continue
        for arg in node.args:
            if _instruction_text_arg(arg):
                violations.append(f"  line {node.lineno}: {name}(...) takes instruction text")
                break
        for kw in node.keywords:
            if _instruction_text_arg(kw):
                violations.append(f"  line {node.lineno}: {name}({kw.arg}=...)")
                break
    return violations


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_no_routing_function_takes_instruction_text() -> None:
    """No function under colleague/agents/ or in loop.py whose name contains
    ``route`` / ``select_model`` / ``pick_model`` takes an argument named
    ``instruction`` / ``task_text`` (c22/h26).

    Sober by construction: ``resolve_profile`` (purpose + roles) and
    ``resolve_role`` (config + repo_path) are NOT flagged — they take no
    instruction text and their names carry no router marker.
    """
    offenders: list[str] = []
    for path in _agent_py_files() + [LOOP_PY]:
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _routing_name(node.name):
                continue
            arg_names = {a.arg for a in node.args.args}
            arg_names.update(k.arg for k in node.args.kwonlyargs if k.arg)
            if node.args.vararg:
                arg_names.add(node.args.vararg.arg)
            if node.args.kwarg:
                arg_names.add(node.args.kwarg.arg)
            bad = arg_names & _INSTRUCTION_ARG_NAMES
            if bad:
                offenders.append(
                    f"  {path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    f"def {node.name}() takes {sorted(bad)}"
                )
    assert not offenders, (
        "a model/role router reads the task's instruction text — the only "
        "model switch is a DelegationRequest (c22/h26):\n" + "\n".join(offenders)
    )


def test_no_call_passes_instruction_text_into_a_model_or_role_function() -> None:
    """No call in colleague/agents/ or loop.py passes ``task.instruction`` /
    ``task.context`` (or any instruction text) into a function whose name
    returns a model/role (c22/h26)."""
    offenders: list[str] = []
    for path in _agent_py_files() + [LOOP_PY]:
        tree = _parse(path)
        for violation in _instruction_arg_violations(tree):
            offenders.append(f"  {path.relative_to(REPO_ROOT)}{violation}")
    assert not offenders, (
        "instruction text is routed into a model/role choice — the only "
        "model switch is a DelegationRequest (c22/h26):\n" + "\n".join(offenders)
    )


def test_no_router_guard_is_not_vacuous() -> None:
    """Positive control: the AST guard actually detects a planted router.

    A synthetic snippet with ``def pick_model(instruction: str)`` and a
    ``route_model(task.instruction)`` call must be flagged — so the two
    guards above cannot pass vacuously.
    """
    snippet = (
        "def pick_model(instruction: str) -> str:\n"
        "    return 'x'\n"
        "\n"
        "def run(task):\n"
        "    return route_model(task.instruction)\n"
    )
    tree = ast.parse(snippet)

    flagged_params = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and _routing_name(node.name):
            if {a.arg for a in node.args.args} & _INSTRUCTION_ARG_NAMES:
                flagged_params = True
    assert flagged_params, "guard must flag a routing-named def taking instruction text"

    violations = _instruction_arg_violations(tree)
    assert any(
        "route_model" in v for v in violations
    ), f"guard must flag a call passing task.instruction into a router: {violations!r}"


# ---------------------------------------------------------------------------
# (c) tests/test_boundary.py allow-lists unchanged
# ---------------------------------------------------------------------------

_PINNED_SUBPROCESS_ALLOWED = frozenset(
    {
        "colleague/hooks.py",
        "colleague/tools.py",
        "colleague/handoff.py",
        "colleague/neighbours.py",
        "colleague/culture.py",
        "colleague/devague.py",
        "colleague/worktrees.py",
        "colleague/lint.py",
        "colleague/resident/steward.py",
        "colleague/affectedtests.py",
        "colleague/background.py",
        "colleague/memory.py",
        "colleague/coherence.py",
        "colleague/livecheck.py",
        "colleague/experiment.py",
        "colleague/strive.py",
        "colleague/correction.py",
        # search-tools arc (task t5): grep_search's ripgrep fast path shells
        # out to the operator-installed `rg` CLI; the stdlib walker is the
        # fallback — reasons pinned in test_boundary.py.
        "colleague/search_tools.py",
    }
)

_PINNED_THREADS_ALLOWED = frozenset(
    {
        "colleague/subagents.py",
        "colleague/cli/_commands/_input_line.py",
        "colleague/realtime.py",
    }
)


def _pinned_frozenset(tree: ast.AST, name: str) -> frozenset[str]:
    """Extract the module-level ``name: frozenset[str] = frozenset({...})``
    literal from *tree* (AST — no import of the boundary test)."""
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.target.id == name:
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "frozenset"
            ):
                elements = value.args[0]
                if isinstance(elements, ast.Set):
                    return frozenset(e.value for e in elements.elts)
            raise AssertionError(f"{name} is not a plain frozenset literal")
    raise AssertionError(f"{name} not found at module level in tests/test_boundary.py")


def test_boundary_subprocess_allowlist_unchanged() -> None:
    """tests/test_boundary.py's _SUBPROCESS_ALLOWED is byte-for-byte the pinned
    set — the subprocess confinement boundary has not drifted (c22/h26)."""
    tree = _parse(BOUNDARY_TEST)
    assert _pinned_frozenset(tree, "_SUBPROCESS_ALLOWED") == _PINNED_SUBPROCESS_ALLOWED


def test_boundary_threads_allowlist_unchanged() -> None:
    """tests/test_boundary.py's _THREADS_ALLOWED is byte-for-byte the pinned
    set — the thread confinement boundary has not drifted (c22/h26)."""
    tree = _parse(BOUNDARY_TEST)
    assert _pinned_frozenset(tree, "_THREADS_ALLOWED") == _PINNED_THREADS_ALLOWED


# ---------------------------------------------------------------------------
# (d) TAE schemas unchanged or additively versioned
# ---------------------------------------------------------------------------

#: Pinned v1 field sets. The ratchet: the CURRENT set may only GROW (an
#: additive, versioned field); a missing or renamed field fails.
_PINNED_TAE_FIELDS = {
    "Thought": frozenset(
        {
            "thought_id",
            "intent",
            "why",
            "supersedes",
            "observation_refs",
            "constraints",
            "success_conditions",
            "uncertainties",
            "version",
        }
    ),
    "ActionProposal": frozenset(
        {
            "thought_id",
            "action_id",
            "proposed_action",
            "expected_effect",
            "evidence_refs",
            "consequential",
        }
    ),
    "Evaluation": frozenset(
        {
            "thought_id",
            "action_id",
            "verdict",
            "route",
            "reason",
            "evidence_gaps",
            "version",
        }
    ),
    "LedgerEntry": frozenset(
        {
            "kind",
            "thought_id",
            "action_id",
            "detail",
            "seat",
            "model",
            "seq",
        }
    ),
}


def test_tae_field_sets_unchanged_or_additive() -> None:
    """Thought / ActionProposal / Evaluation / LedgerEntry keep every pinned v1
    field — a field may be ADDED (with a visible schema-version bump) but never
    removed or renamed (c23/h27)."""
    from colleague.actionproposal import ActionProposal
    from colleague.evaluation import Evaluation
    from colleague.ledger import LedgerEntry
    from colleague.thought import Thought

    current = {
        "Thought": frozenset(f.name for f in dataclasses.fields(Thought)),
        "ActionProposal": frozenset(f.name for f in dataclasses.fields(ActionProposal)),
        "Evaluation": frozenset(f.name for f in dataclasses.fields(Evaluation)),
        "LedgerEntry": frozenset(f.name for f in dataclasses.fields(LedgerEntry)),
    }
    for name, pinned in _PINNED_TAE_FIELDS.items():
        missing = pinned - current[name]
        assert not missing, (
            f"{name} lost pinned v1 field(s) {sorted(missing)} — the TAE schema "
            f"must be unchanged or additively versioned (c23/h27); current: {sorted(current[name])}"
        )


def test_tae_schema_versions_stay_at_v1() -> None:
    """The TAE schema-version constants are still 1 — a future change is a
    deliberate, visible bump, never a silent drift (c23/h27)."""
    from colleague.evaluation import EVALUATION_SCHEMA_VERSION
    from colleague.ledger import LEDGER_SCHEMA_VERSION
    from colleague.thought import THOUGHT_SCHEMA_VERSION

    assert THOUGHT_SCHEMA_VERSION == 1
    assert EVALUATION_SCHEMA_VERSION == 1
    assert LEDGER_SCHEMA_VERSION == 1

"""Boundary + docs-drift guard for the dual-model deepthink escalation surface
(plan task t8, spec c7/h15/h3).

``colleague/deepthink.py`` is the ONE seam that turns a question into a
bounded, tools-off completion against the operator-declared deepthink model
(:func:`colleague.deepthink.run_deepthink`). The design invariant recorded in
that module's own docstring is that it is reachable from EXACTLY four
enumerated points, and that ``colleague/loop.py`` / ``colleague/tools.py``
NEVER import it directly -- they only ever receive the bound
``make_deepthink_run(config, engine_name)`` callable injected by the two
engines (``colleague/engines/mock.py`` / ``colleague/engines/vllm_openai.py``).
That invariant is asserted here structurally (AST-based, not just a docstring
claim), so a future change that quietly adds a fifth caller -- or has
``loop.py``/``tools.py`` reach for the seam directly instead of taking the
injected binding -- fails this test immediately.

Four groups:

1. **Import allow-list** -- only ``colleague/engines/mock.py``,
   ``colleague/engines/vllm_openai.py``, and ``colleague/cli/_commands/plan.py``
   may import ``colleague.deepthink`` (any import form); ``colleague/loop.py``
   and ``colleague/tools.py`` are asserted NOT to.
2. **AST-detector unit pin** -- the detector recognises every import FORM the
   spec calls out (absolute, aliased, ``from colleague import deepthink``, and
   the relative dotted forms), on synthetic source, so group 1 cannot pass
   vacuously because the detector itself is blind to a particular form.
3. **Tools-off sweep** -- every ``make_complete`` call reachable through the
   deepthink paths (``run_deepthink`` itself, and plan.py's
   ``_route_proposals_through_deepthink`` helper) passes an explicit
   ``tools=[]`` keyword -- the structural "cannot call a tool or finish"
   invariant. Plan.py's OWN main-model ``make_complete`` call
   (``run_plan_request``) is asserted to remain tools-DEFAULT, so the scoped
   check above cannot be trivially satisfied by asserting over the whole file.
4. **Docs drift** -- ONE module-level list of the four escalation-point
   descriptors drives both the reasoning above and an assertion that
   ``docs/features/deepthink.md`` still names every point, plus the honest
   "not a router" / "N-model" / "byte-identical" wording, and that
   ``CLAUDE.md``'s out-of-scope section still excludes the multi-backend
   router / routing policy.

This file deliberately does not re-test ``tests/test_deepthink_guards.py``'s
(t9's) byte-identical / degradation-ladder behavior, nor
``tests/test_deepthink.py``'s / ``tests/test_loop_deepthink.py``'s unit
coverage of ``run_deepthink`` itself -- it is purely a boundary + drift guard.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Resolve the repo root / package directory relative to this test file.
# ---------------------------------------------------------------------------

_REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_PACKAGE_DIR: Path = _REPO_ROOT / "colleague"


def _all_py_sources() -> list[Path]:
    """Return every ``*.py`` file under the colleague package."""
    return sorted(_PACKAGE_DIR.rglob("*.py"))


# ---------------------------------------------------------------------------
# ONE module-level list of the four enumerated escalation-point descriptors.
# Both the import-allow-list reasoning (below) and the docs-drift assertions
# are driven from this single source so the test itself cannot silently
# drift from what it checks.
# ---------------------------------------------------------------------------

_ESCALATION_SURFACE: tuple[dict[str, object], ...] = (
    {
        "point": "tool",
        "doc_phrase": "`deepthink` loop tool",
        # The bound DeepthinkRun realizing this point is built in the engines;
        # the dispatch itself (colleague/tools.py) takes the binding injected,
        # never imports the seam.
        "importers": ("colleague/engines/mock.py", "colleague/engines/vllm_openai.py"),
    },
    {
        "point": "plan_proposal",
        "doc_phrase": "Plan-mode proposals",
        "importers": ("colleague/cli/_commands/plan.py",),
    },
    {
        "point": "acceptance_selfcheck",
        "doc_phrase": "Acceptance self-check",
        # Same binding as "tool" -- built once per work item in the engines and
        # handed to ContextControls; colleague/loop.py never imports the seam.
        "importers": ("colleague/engines/mock.py", "colleague/engines/vllm_openai.py"),
    },
    {
        "point": "testintegrity_reviewer_default",
        "doc_phrase": "Test-integrity reviewer default",
        # colleague/config.py's _resolve_testintegrity_reviewer_model is purely
        # config-level -- it carries only a model name and never touches the
        # deepthink seam, so this point has NO importer.
        "importers": (),
    },
)


def _all_importers(surface: tuple[dict[str, object], ...]) -> frozenset[str]:
    result: set[str] = set()
    for point in surface:
        result.update(point["importers"])  # type: ignore[arg-type]
    return frozenset(result)


_ALLOWED_DEEPTHINK_IMPORTERS: frozenset[str] = _all_importers(_ESCALATION_SURFACE)


# ---------------------------------------------------------------------------
# AST-based "does this module import colleague.deepthink" detector.
#
# Recognises every import FORM named in the task: an absolute import (plain or
# aliased), ``from colleague.deepthink import ...``, ``from colleague import
# deepthink``, and the relative dotted forms (``from ..deepthink import ...``,
# resolved against the importing module's OWN package so it works regardless
# of how deep the importing module is nested).
# ---------------------------------------------------------------------------


def _dotted_module_name(py_file: Path) -> str:
    """The dotted module name of *py_file*, relative to the repo root."""
    rel = py_file.relative_to(_REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _current_package(py_file: Path, dotted: str) -> str:
    """The dotted package *py_file* lives in (itself, for a package ``__init__.py``)."""
    if py_file.name == "__init__.py":
        return dotted
    if "." not in dotted:
        return ""
    return dotted.rsplit(".", 1)[0]


def _resolve_relative_base(package: str, level: int) -> str:
    """The dotted base a ``from <level dots><module> import ...`` targets.

    Mirrors Python's own relative-import resolution: ``level=1`` means "the
    current package itself"; each further dot goes up one more package.
    """
    parts = package.split(".") if package else []
    trim = level - 1
    parts = parts[: max(0, len(parts) - trim)]
    return ".".join(parts)


def _tree_imports_deepthink(tree: ast.AST, package: str) -> bool:
    """True if *tree* (parsed from a module living in *package*) imports
    ``colleague.deepthink`` in any recognised form."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "colleague.deepthink":
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                mod = node.module or ""
                if mod == "colleague.deepthink":
                    return True
                if mod == "colleague" and any(alias.name == "deepthink" for alias in node.names):
                    return True
            else:
                base = _resolve_relative_base(package, node.level)
                if node.module:
                    full = f"{base}.{node.module}" if base else node.module
                    if full == "colleague.deepthink":
                        return True
                else:
                    if base == "colleague" and any(
                        alias.name == "deepthink" for alias in node.names
                    ):
                        return True
    return False


def _file_imports_deepthink(py_file: Path) -> bool:
    """True if the source file at *py_file* imports ``colleague.deepthink``."""
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))
    dotted = _dotted_module_name(py_file)
    package = _current_package(py_file, dotted)
    return _tree_imports_deepthink(tree, package)


# ---------------------------------------------------------------------------
# Group 2 -- unit pin on the detector itself, so group 1/3 below cannot pass
# vacuously because the detector is blind to a particular import form.
# ---------------------------------------------------------------------------


class TestDeepthinkImportDetectionHelper:
    """The AST detector recognises every import form named in the task."""

    #: Parsed as if the source lived at colleague/engines/<synthetic>.py, so
    #: the relative-import case ("from ..deepthink import ...") resolves the
    #: same way it would for the real colleague/engines/mock.py.
    _PACKAGE = "colleague.engines"

    @pytest.mark.parametrize(
        "source",
        [
            "import colleague.deepthink\n",
            "import colleague.deepthink as dt\n",
            "from colleague.deepthink import make_deepthink_run\n",
            "from colleague import deepthink\n",
            "from ..deepthink import make_deepthink_run\n",
        ],
        ids=[
            "import-absolute",
            "import-absolute-aliased",
            "from-absolute-module",
            "from-colleague-import-deepthink",
            "from-relative-dotted",
        ],
    )
    def test_recognises_every_import_form(self, source: str) -> None:
        tree = ast.parse(source)
        assert _tree_imports_deepthink(
            tree, self._PACKAGE
        ), f"detector failed to recognise import form:\n{source}"

    def test_unrelated_imports_are_not_flagged(self) -> None:
        tree = ast.parse(
            "from colleague import registry\n"
            "import colleague.tools\n"
            "from colleague.contract import Task\n"
        )
        assert not _tree_imports_deepthink(tree, self._PACKAGE)


# ---------------------------------------------------------------------------
# Group 1 -- only the enumerated modules import colleague.deepthink; loop.py
# and tools.py, specifically, never do (the injected-binding invariant).
# ---------------------------------------------------------------------------


class TestDeepthinkImportAllowList:
    """colleague.deepthink is imported ONLY by its enumerated callers."""

    def test_only_allow_listed_modules_import_deepthink(self) -> None:
        deepthink_src = _PACKAGE_DIR / "deepthink.py"
        importers: set[str] = set()
        for py_file in _all_py_sources():
            if py_file == deepthink_src:
                continue  # the seam module itself is excluded from the scan
            if _file_imports_deepthink(py_file):
                importers.add(str(py_file.relative_to(_PACKAGE_DIR.parent)))

        unexpected = importers - _ALLOWED_DEEPTHINK_IMPORTERS
        assert not unexpected, (
            "colleague.deepthink is imported outside the enumerated escalation "
            f"surface (allowed: {sorted(_ALLOWED_DEEPTHINK_IMPORTERS)}):\n"
            + "\n".join(f"  {rel}" for rel in sorted(unexpected))
        )

    def test_allow_listed_modules_actually_import_deepthink(self) -> None:
        """Guard the allow-list itself against dead entries (mirrors the
        "sanctioned but does not import" check in tests/test_boundary.py)."""
        for rel in sorted(_ALLOWED_DEEPTHINK_IMPORTERS):
            py_file = _PACKAGE_DIR.parent / rel
            assert py_file.is_file(), f"expected source file not found: {py_file}"
            assert _file_imports_deepthink(py_file), (
                f"{rel} is listed as an allowed deepthink importer but no longer "
                "imports colleague.deepthink -- update _ESCALATION_SURFACE, "
                "the escalation surface drifted"
            )

    def test_loop_and_tools_never_import_deepthink(self) -> None:
        """The injected-binding invariant, named explicitly (not just implied
        by the allow-list above): loop.py and tools.py receive the bound
        DeepthinkRun via make_deepthink_run(config, engine_name) -- called
        only by the engines -- and must never import the seam themselves."""
        for rel in ("colleague/loop.py", "colleague/tools.py"):
            py_file = _PACKAGE_DIR.parent / rel
            assert py_file.is_file(), f"expected source file not found: {py_file}"
            assert not _file_imports_deepthink(py_file), (
                f"{rel} must never import colleague.deepthink -- it receives the "
                "bound DeepthinkRun via injection only (make_deepthink_run is "
                "called only by colleague/engines/mock.py and "
                "colleague/engines/vllm_openai.py)"
            )


# ---------------------------------------------------------------------------
# Group 3 -- every deepthink completion is tools-off (an explicit tools=[]).
# ---------------------------------------------------------------------------


def _find_function(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _make_complete_calls(node: ast.AST) -> list[ast.Call]:
    """Every ``Call`` node inside *node* whose callee is (an attribute or bare
    name) ``make_complete``."""
    calls: list[ast.Call] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name == "make_complete":
            calls.append(sub)
    return calls


def _call_has_empty_tools_kwarg(call: ast.Call) -> bool:
    """True if *call* passes an explicit ``tools=[]`` keyword argument."""
    for kw in call.keywords:
        if kw.arg == "tools" and isinstance(kw.value, ast.List) and not kw.value.elts:
            return True
    return False


class TestDeepthinkCallsAreToolsOff:
    """Every make_complete call reachable through the deepthink paths passes
    an explicit tools=[] -- the structural "cannot call a tool" invariant."""

    def test_run_deepthink_call_site_is_tools_off(self) -> None:
        source = (_PACKAGE_DIR / "deepthink.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="colleague/deepthink.py")
        run_deepthink_fn = _find_function(tree, "run_deepthink")

        calls = _make_complete_calls(run_deepthink_fn)
        assert calls, (
            "run_deepthink no longer calls make_complete -- the deepthink "
            "boundary drifted, re-check colleague/deepthink.py"
        )
        assert all(_call_has_empty_tools_kwarg(c) for c in calls), (
            "every make_complete call inside run_deepthink must pass an "
            "explicit tools=[] -- deepthink is ALWAYS tools-off"
        )

    def test_plan_deepthink_routing_call_site_is_tools_off(self) -> None:
        plan_path = _PACKAGE_DIR / "cli" / "_commands" / "plan.py"
        source = plan_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename="colleague/cli/_commands/plan.py")
        route_fn = _find_function(tree, "_route_proposals_through_deepthink")

        calls = _make_complete_calls(route_fn)
        assert calls, (
            "_route_proposals_through_deepthink no longer calls make_complete -- "
            "the plan-mode deepthink routing boundary drifted"
        )
        assert any(_call_has_empty_tools_kwarg(c) for c in calls), (
            "the deepthink-routed make_complete call inside "
            "_route_proposals_through_deepthink must pass an explicit tools=[]"
        )

    def test_plan_main_model_path_stays_tools_default(self) -> None:
        """Sanity/anti-false-positive pin: run_plan_request's OWN make_complete
        call (the main-model path, config-only, no dt_config) is legitimately
        tools-default -- proving the scoped checks above cannot accidentally
        pass by asserting over the whole file instead of the deepthink-only
        helper."""
        plan_path = _PACKAGE_DIR / "cli" / "_commands" / "plan.py"
        source = plan_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename="colleague/cli/_commands/plan.py")
        run_request_fn = _find_function(tree, "run_plan_request")

        calls = _make_complete_calls(run_request_fn)
        assert calls, "run_plan_request no longer calls make_complete directly"
        assert any(not _call_has_empty_tools_kwarg(c) for c in calls), (
            "run_plan_request's main-model make_complete call is expected to "
            "use the default tool surface (no tools=[] kwarg) -- if this "
            "changed, re-check the deepthink tools-off scoping above for a "
            "false positive/negative"
        )


# ---------------------------------------------------------------------------
# Group 4 -- docs drift: the feature doc names every enumerated point + the
# honest wording; CLAUDE.md's out-of-scope section still excludes the router.
# ---------------------------------------------------------------------------

_DEEPTHINK_DOC_PATH: Path = _REPO_ROOT / "docs" / "features" / "deepthink.md"
_CLAUDE_MD_PATH: Path = _REPO_ROOT / "CLAUDE.md"

#: Honest-line phrases the feature doc must still carry (checked
#: case-insensitively so incidental re-capitalization doesn't false-positive).
_HONEST_LINE_PHRASES: tuple[str, ...] = ("not a router", "n-model", "byte-identical")


def _normalized(text: str) -> str:
    """Collapse whitespace runs to a single space.

    Markdown prose reflows across lines (e.g. CLAUDE.md's "a multi-backend"
    / "router / routing policy" wraps across two source lines) -- a raw
    substring check would false-negative on an incidental line-wrap that
    changes nothing about the meaning. Collapsing whitespace makes the check
    robust to that.
    """
    return re.sub(r"\s+", " ", text)


class TestDeepthinkDocsDriftGuard:
    """docs/features/deepthink.md and CLAUDE.md stay honest about the surface."""

    def test_feature_doc_names_every_enumerated_escalation_point(self) -> None:
        doc_text = _normalized(_DEEPTHINK_DOC_PATH.read_text(encoding="utf-8"))
        missing = [
            point["doc_phrase"]
            for point in _ESCALATION_SURFACE
            if point["doc_phrase"] not in doc_text  # type: ignore[operator]
        ]
        assert not missing, (
            "docs/features/deepthink.md no longer names every enumerated "
            f"escalation point (from _ESCALATION_SURFACE); missing: {missing}"
        )

    def test_feature_doc_carries_the_honest_not_a_router_wording(self) -> None:
        doc_text = _normalized(_DEEPTHINK_DOC_PATH.read_text(encoding="utf-8")).lower()
        missing = [phrase for phrase in _HONEST_LINE_PHRASES if phrase not in doc_text]
        assert not missing, (
            "docs/features/deepthink.md dropped honest-line wording it must keep: " f"{missing}"
        )

    def test_claude_md_out_of_scope_still_excludes_the_router(self) -> None:
        claude_text = _normalized(_CLAUDE_MD_PATH.read_text(encoding="utf-8"))
        assert "multi-backend router / routing policy" in claude_text, (
            "CLAUDE.md's out-of-scope section must still name the excluded "
            "multi-backend router / routing policy -- the dual-model deepthink "
            "escalation is a fixed, enumerated surface, never a general router"
        )

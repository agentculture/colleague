"""Structural pins for the opt-in cortex configurator (plan task t11,
acceptance criterion 1) — TEST-FIRST.

Two structural claims, each pinned two ways (a behavioral-shaped API check
plus an AST-level import/call-site check, mirroring how
``tests/test_senses_moves.py`` pins senses_moves' own structural boundary):

1. **Nothing cortex-authored ever reaches the worker's message history.**
   ``colleague/configurator.py`` exposes no function that accepts or returns
   a worker-history-shaped ``list[dict]`` (the ``messages``/``history``
   parameter name colleague/loop.py's conversation uses), AND
   ``colleague/loop.py`` never imports ``colleague/configurator.py`` at all
   — the dependency points the other way (chain/session wiring calls INTO
   the configurator, between episodes).

2. **The acting completion seam is never wrapped.** Every ``make_complete(``
   call site in ``colleague/configurator.py`` passes ``tools=[]`` literally
   (an explicit empty list, never a non-empty list, never a bare variable
   that could carry a real tool schema) — the same tools-off-always pin
   ``colleague/deepthink.py`` and ``colleague/senses_loop.py`` uphold for
   their own second-model completions. The module also never references an
   engine's ``make_complete`` RESULT as something to wrap/decorate (no
   subclassing/monkeypatching of ``Engine``, no function that takes a
   ``complete``/``CompleteFn`` callable as an argument and returns a new
   callable wrapping it).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import colleague.configurator as configurator_module
import colleague.loop as loop_module

_CONFIGURATOR_SRC = Path(configurator_module.__file__)
_LOOP_SRC = Path(loop_module.__file__)

# Worker-history-shaped parameter names colleague/loop.py's conversation
# surface uses (its CompleteFn signature, ContextControls, etc.) — a public
# configurator function accepting any of these would be a live write path
# into the worker's own conversation.
_HISTORY_PARAM_NAMES = frozenset({"history", "messages", "conversation"})


def _public_functions(module) -> "list[tuple[str, object]]":
    return [
        (name, obj)
        for name, obj in vars(module).items()
        if inspect.isfunction(obj)
        and obj.__module__ == module.__name__
        and not name.startswith("_")
    ]


def _module_source_and_tree(path: Path) -> "tuple[str, ast.Module]":
    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(path))


# ---------------------------------------------------------------------------
# Pin 1a — no public configurator function accepts/returns a history-shaped
# parameter
# ---------------------------------------------------------------------------


class TestNoWorkerHistoryWritePath:
    def test_no_public_function_accepts_a_history_shaped_parameter(self) -> None:
        offenders = []
        for name, fn in _public_functions(configurator_module):
            params = set(inspect.signature(fn).parameters)
            hit = params & _HISTORY_PARAM_NAMES
            if hit:
                offenders.append(f"{name}({sorted(hit)})")
        assert offenders == [], (
            "colleague/configurator.py must accept no worker-history-shaped "
            f"parameter on any public function; found: {offenders}"
        )

    def test_dataclasses_carry_no_history_shaped_field(self) -> None:
        """The module's own dataclasses (ConfiguratorReviewInput, the review
        result, the window result) are the actual data surface a caller
        threads through — none of them may carry a history-shaped field
        either, or a message list could ride in through a field instead of a
        parameter."""
        import dataclasses

        offenders = []
        for name, obj in vars(configurator_module).items():
            if not (isinstance(obj, type) and dataclasses.is_dataclass(obj)):
                continue
            field_names = {f.name for f in dataclasses.fields(obj)}
            hit = field_names & _HISTORY_PARAM_NAMES
            if hit:
                offenders.append(f"{name}({sorted(hit)})")
        assert (
            offenders == []
        ), f"configurator dataclasses must carry no history field; found: {offenders}"

    # -- 1b: loop.py never imports configurator (AST-level, mirrors
    # test_senses_moves.py's no-ToolExecutor pin) ----------------------------

    def test_loop_module_never_imports_configurator(self) -> None:
        source, tree = _module_source_and_tree(_LOOP_SRC)
        modules: "set[str]" = set()
        imported_names: "set[str]" = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
        assert "colleague.configurator" not in modules, (
            "colleague/loop.py must never import colleague.configurator — the "
            "dependency points the other way (chain/session wiring calls INTO "
            "the configurator, between episodes; the loop only ever consults "
            "the config_lifecycle it is handed)."
        )
        assert "configurator" not in imported_names
        # A lazy, function-local import would still show up in the AST walk
        # above (ast.walk descends into every function body too), so this
        # single check already covers both module-level and lazy imports.

    def test_loop_module_source_never_mentions_configurator_module_path(self) -> None:
        """Belt-and-suspenders raw-source check: no executable reference to
        the configurator module path anywhere in loop.py (a prose mention in
        a comment/docstring, e.g. explaining the boundary, is fine — only an
        actual import-shaped reference is checked above; this just confirms
        there is no sneaky dynamic-import string either)."""
        source = _LOOP_SRC.read_text(encoding="utf-8")
        assert "importlib" not in source or "colleague.configurator" not in source


# ---------------------------------------------------------------------------
# Pin 2 — the acting completion seam is never wrapped; every make_complete
# call in configurator.py is tools=[] literally
# ---------------------------------------------------------------------------


class TestActingCompletionSeamNeverWrapped:
    def test_every_make_complete_call_passes_tools_empty_list_literal(self) -> None:
        source, tree = _module_source_and_tree(_CONFIGURATOR_SRC)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "make_complete"
        ]
        assert calls, "expected at least one make_complete( call site in colleague/configurator.py"
        for call in calls:
            tools_kw = next((kw for kw in call.keywords if kw.arg == "tools"), None)
            assert (
                tools_kw is not None
            ), f"make_complete( call at line {call.lineno} must pass tools= explicitly"
            assert isinstance(tools_kw.value, ast.List), (
                f"make_complete( call at line {call.lineno} must pass tools=[] "
                "literally (tools-off always)"
            )
            assert len(tools_kw.value.elts) == 0, (
                f"make_complete( call at line {call.lineno} must pass tools=[] "
                "literally (tools-off always)"
            )

    def test_module_never_subclasses_or_monkeypatches_engine(self) -> None:
        """Every class this module defines is a plain data holder (its
        dataclasses) — none subclasses anything (in particular no ``Engine``
        wrapper) and none defines its own ``make_complete``/``work`` method
        that could stand in for — or wrap — the acting engine's own."""
        source, tree = _module_source_and_tree(_CONFIGURATOR_SRC)
        class_defs = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        offenders = []
        for node in class_defs:
            if node.bases:
                offenders.append(f"{node.name} subclasses {[ast.dump(b) for b in node.bases]}")
            method_names = {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            wrapping = method_names & {"make_complete", "work", "drive", "complete"}
            if wrapping:
                offenders.append(f"{node.name} defines {sorted(wrapping)}")
        assert offenders == [], (
            "colleague/configurator.py must define no Engine-like wrapper class; "
            f"found: {offenders}"
        )
        assert "setattr(" not in source.replace(" ", "")
        assert ".make_complete =" not in source

    def test_module_never_imports_the_tool_schema_or_executor(self) -> None:
        """Mirrors colleague/senses_moves.py's own no-ToolExecutor pin: the
        configurator's one completion is tools-off, so it has no legitimate
        reason to import anything tool-shaped."""
        source, tree = _module_source_and_tree(_CONFIGURATOR_SRC)
        modules: "set[str]" = set()
        imported_names: "set[str]" = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
        assert "colleague.tools" not in modules
        assert "ToolExecutor" not in imported_names
        assert "SCHEMAS" not in imported_names

    def test_module_source_has_no_forbidden_networking_or_thread_primitives(self) -> None:
        """This new module belongs to the same no-socket/no-daemon/no-thread
        convention every other pure module in this repo does (already swept
        by tests/test_boundary.py's parametrized checks — this just names it
        explicitly, mirroring that file's flight.py/deepthink.py precedent)."""
        source = _CONFIGURATOR_SRC.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import asyncio",
            "import threading",
            "concurrent.futures",
            "import subprocess",
        ):
            assert forbidden not in source, f"colleague/configurator.py must not use {forbidden!r}"

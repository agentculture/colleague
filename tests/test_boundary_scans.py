"""Boundary scan tests — the source-tree scans split out of ``test_boundary.py``.

Split from :mod:`tests.test_boundary` (plan ``hard-1000-line-file-limit``, task
t12) purely to keep that file under the 1000-line hard limit. NOTHING here
changes: the checks, their names and their assertions are byte-identical to
what lived at the tail of ``test_boundary.py``.

The two allow-list frozensets (``_SUBPROCESS_ALLOWED`` / ``_THREADS_ALLOWED``)
deliberately did NOT move — ``tests/test_agents_boundary.py`` AST-extracts them
from ``tests/test_boundary.py`` by path, and six other test modules import them
from there. The shared scaffolding below is imported from the original module
rather than duplicated, for the same reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_boundary import _ASYNC_EXEMPT_PREFIX, _PACKAGE_DIR, _all_py_sources

# ---------------------------------------------------------------------------
# STRUCTURAL — the TAUI cockpit is imported from agentfront, not duplicated.
# After issue #249 the generic cockpit modules live in ``agentfront.taui``;
# colleague keeps only the thin adapter (``colleague.tui.from_work``) and the
# live raw-terminal driver (``colleague.tui.render.driver``, which agentfront
# does not ship). No colleague module may import any *other* ``colleague.tui.*``
# submodule — they no longer exist, and a stray reference would mean the
# migration left a duplicated module behind.
# ---------------------------------------------------------------------------

#: The only ``colleague.tui`` submodules a consumer may import (the survivors).
_ALLOWED_COLLEAGUE_TUI_IMPORTS = frozenset({"from_work", "render.driver"})

_COLLEAGUE_TUI_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+colleague\.tui\.([a-zA-Z0-9_.]+)", re.MULTILINE
)


def test_colleague_tui_imports_only_the_surviving_adapter_and_driver() -> None:
    """No colleague module imports a deleted ``colleague.tui.*`` module.

    Consumers must reach the generic cockpit through ``agentfront.taui.*``; the
    only colleague-owned cockpit code left is the ``from_work`` adapter and the
    ``render.driver`` live loop. Files inside ``colleague/tui/`` are exempt (they
    are the surviving package itself).
    """
    tui_dir = _PACKAGE_DIR / "tui"
    violations: list[str] = []
    for py_file in _all_py_sources():
        if tui_dir in py_file.parents:
            continue  # the surviving package itself
        source = py_file.read_text(encoding="utf-8")
        for match in _COLLEAGUE_TUI_IMPORT_RE.finditer(source):
            submodule = match.group(1)
            # Normalize e.g. "render.driver" / "from_work" — a deeper path like
            # "render.driver" must match an allow-listed prefix exactly or as a
            # dotted child (render.driver.run is imported as render.driver).
            allowed = any(
                submodule == ok or submodule.startswith(ok + ".")
                for ok in _ALLOWED_COLLEAGUE_TUI_IMPORTS
            )
            if not allowed:
                lineno = source[: match.start()].count("\n") + 1
                rel = py_file.relative_to(_PACKAGE_DIR.parent)
                violations.append(f"  {rel}:{lineno}: imports colleague.tui.{submodule}")

    assert not violations, (
        "colleague modules must import the generic cockpit from agentfront.taui, "
        "not a duplicated colleague.tui.* module (only from_work + render.driver "
        "survive):\n" + "\n".join(violations)
    )


def test_new_cockpit_helpers_are_not_under_colleague_tui_and_shadow_no_renderer() -> None:
    """#285 t10: the new pure cockpit helpers (``cockpit_run.py`` / ``icons.py``)
    live at the colleague top level, NOT under ``colleague/tui/`` (which keeps
    ONLY its two #249 survivors), and ``cockpit_run.py`` imports nothing from the
    ``agentfront`` render paths — so a cited run-state / ledger fact is
    copy-derived from the shared pure helper, never a fork or shadow of an
    agentfront renderer (the #249 rule)."""
    pkg = _PACKAGE_DIR

    # The new helpers exist at the top level and are NOT shadowed under colleague/tui/.
    for name in ("cockpit_run.py", "icons.py"):
        assert (pkg / name).is_file(), f"colleague/{name} must exist at the top level"
        assert not (
            pkg / "tui" / name
        ).exists(), f"colleague/{name} must NOT live under colleague/tui/ (keeps the #249 boundary)"

    # colleague/tui/ keeps ONLY its two #249 survivors (excluding package __init__.py).
    tui_dir = pkg / "tui"
    survivors = {
        p.relative_to(tui_dir).as_posix() for p in tui_dir.rglob("*.py") if p.name != "__init__.py"
    }
    assert survivors == {"from_work.py", "render/driver.py"}, (
        "colleague/tui/ must keep ONLY the two #249 survivors (from_work.py + "
        f"render/driver.py); found: {sorted(survivors)}"
    )

    # cockpit_run.py imports nothing from agentfront (render-path independence).
    src = (pkg / "cockpit_run.py").read_text(encoding="utf-8")
    assert (
        "import agentfront" not in src and "from agentfront" not in src
    ), "colleague/cockpit_run.py must import nothing from agentfront render paths (#285 t1/t10)"


# ---------------------------------------------------------------------------
# STRUCTURAL — agent_lifecycle imports are confined to colleague/resident/
# (plan task t13 / spec R4). This is the package-source-level companion to
# tests/test_zero_deps.py's runtime `test_resident_core_import_clean` /
# `test_appserver_needs_the_resident_extra` checks: those prove WHAT gets
# imported at runtime; this pins WHERE `agent_lifecycle` is referenced in
# source at all, so a future module outside colleague/resident/ (e.g. a base
# CLI verb) could never start depending on the opt-in seam without this test
# catching it immediately, even before a runtime import-graph check would.
# ---------------------------------------------------------------------------

_AGENT_LIFECYCLE_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+agent_lifecycle\b|from\s+agent_lifecycle\b)", re.MULTILINE
)


class TestAgentLifecycleConfinement:
    """``agent_lifecycle`` (the plan-t13 resident/appserver seam) is imported
    ONLY under ``colleague/resident/`` — never by a base-path module."""

    @pytest.mark.parametrize(
        "py_file",
        _all_py_sources(),
        ids=lambda p: str(p.relative_to(_PACKAGE_DIR.parent)),
    )
    def test_agent_lifecycle_only_imported_under_resident(self, py_file: Path) -> None:
        rel = str(py_file.relative_to(_PACKAGE_DIR.parent))
        if rel.startswith(_ASYNC_EXEMPT_PREFIX):
            return  # colleague/resident/ is the sanctioned consumer of the seam

        source = py_file.read_text(encoding="utf-8")
        violations = [
            f"  {rel}:{lineno}: {line.rstrip()!r}"
            for lineno, line in enumerate(source.splitlines(), start=1)
            if _AGENT_LIFECYCLE_IMPORT_RE.search(line)
        ]
        assert not violations, (
            "agent_lifecycle imported outside colleague/resident/ — the base install "
            "must stay dep-free (the [resident]/[culture] extras are opt-in):\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# STRUCTURAL — no colleague module imports cultureagent (colleague#291 c8/h17).
# cultureagent depends on colleague (wraps ColleagueHarness as its backend);
# a reverse import would create a cycle — this test pins the boundary.
# ---------------------------------------------------------------------------

_CULTUREAGENT_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+cultureagent\b|from\s+cultureagent\b)", re.MULTILINE
)


def test_no_colleague_module_imports_cultureagent() -> None:
    """No colleague module imports cultureagent — colleague#291 boundary c8.

    cultureagent depends on colleague (wraps ColleagueHarness as its 5th
    backend); a reverse import would create a cycle.  This test statically
    walks every colleague source file's import statements and asserts NONE
    imports cultureagent (any form: ``import cultureagent``,
    ``from cultureagent...``).  Spec: colleague#291 boundary c8/h17.
    """
    violations: list[str] = []
    for py_file in _all_py_sources():
        rel = str(py_file.relative_to(_PACKAGE_DIR.parent))
        source = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(source.splitlines(), start=1):
            if _CULTUREAGENT_IMPORT_RE.search(line):
                violations.append(f"  {rel}:{lineno}: {line.rstrip()!r}")

    assert not violations, (
        "cultureagent imported in colleague source — this creates a cycle since "
        "cultureagent depends on colleague (colleague#291 boundary c8):\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# STRUCTURAL — eidetic verb allow-list pinned (plan t19, spec c10/h10/c11/h11).
# The memory module exposes exactly two verbs: recall and remember.  No other
# eidetic verb (export, delete, search, …) may be reachable from any module
# in the package.  This test proves the allow-list is a frozenset of exactly
# those two strings.
# ---------------------------------------------------------------------------


def test_memory_allowed_verbs_is_pinned_frozenset() -> None:
    """ALLOWED_VERBS is a frozenset containing exactly {recall, remember} — c10/h10.

    The constant must be a frozenset (immutable, hashable) so it cannot be
    mutated at runtime, and its contents must match the spec exactly.
    """
    from colleague.memory import ALLOWED_VERBS

    assert isinstance(ALLOWED_VERBS, frozenset), (
        "ALLOWED_VERBS must be a frozenset (immutable) — " f"got {type(ALLOWED_VERBS).__name__}"
    )
    assert ALLOWED_VERBS == frozenset({"recall", "remember"}), (
        f"ALLOWED_VERBS must be exactly frozenset({{'recall', 'remember'}}), "
        f"got {ALLOWED_VERBS!r}"
    )


def test_memory_allowed_verbs_contains_recall() -> None:
    """'recall' is in the allow-list — the search verb is reachable."""
    from colleague.memory import ALLOWED_VERBS

    assert "recall" in ALLOWED_VERBS


def test_memory_allowed_verbs_contains_remember() -> None:
    """'remember' is in the allow-list — the store verb is reachable."""
    from colleague.memory import ALLOWED_VERBS

    assert "remember" in ALLOWED_VERBS


def test_memory_allowed_verbs_excludes_export() -> None:
    """'export' is NOT in the allow-list — no data-export verb is reachable."""
    from colleague.memory import ALLOWED_VERBS

    assert "export" not in ALLOWED_VERBS


def test_memory_allowed_verbs_excludes_delete() -> None:
    """'delete' is NOT in the allow-list — no destructive verb is reachable."""
    from colleague.memory import ALLOWED_VERBS

    assert "delete" not in ALLOWED_VERBS


def test_memory_allowed_verbs_excludes_search() -> None:
    """'search' is NOT in the allow-list — only 'recall' is the search verb."""
    from colleague.memory import ALLOWED_VERBS

    assert "search" not in ALLOWED_VERBS

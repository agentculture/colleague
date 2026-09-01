"""Importability check gate (#482) — py_compile + subprocess import smoke.

Sibling to :mod:`colleague.affectedtests` and :mod:`colleague.lint` in
structure: pure stdlib, best-effort, returns an :class:`ImportCheckReport`
(never ``None``, never raises out of the public function).

Motivation
----------
Issue #482: run ``cc5d1f1a2c5f`` landed a branch whose changed modules did not
actually *import* — a hallucinated ``from colleague.hooks import Policy`` and a
lost ``ToolCall`` re-export that broke ``colleague/engines/vllm_transport.py``.
Neither ``black``/``isort``/``flake8`` nor a syntax-only ``py_compile`` catches
a missing symbol at import time; only actually importing the module does.

Two-stage check, per changed ``*.py`` file
-------------------------------------------
1. ``py_compile.compile(path, doraise=True)`` — a fast syntax gate.
2. A **subprocess** ``python -c "import <dotted.module.name>"`` — the actual
   import smoke.  This step is the one that catches #482's shape: a module
   that compiles fine but raises ``ImportError``/``AttributeError`` at import
   time because a symbol it references no longer exists.

Worktree resolution (c20) — READ THIS BEFORE CHANGING THE SUBPROCESS CALL
--------------------------------------------------------------------------
colleague is frequently used to edit **its own installed package** (colleague
editing colleague).  If the import-smoke subprocess resolves ``colleague`` off
the ambient ``sys.path`` (site-packages / an editable install pointing
elsewhere), it can import the **installed** copy instead of the **worktree**
copy under test — and pass vacuously even though the worktree copy is broken.
That defeats the whole point of this gate.

The fix: the subprocess is launched with ``cwd=repo_path`` (the affectedtests
precedent, ``affectedtests.py`` run_affected_tests) AND with *repo_path*
inserted at ``sys.path[0]`` via ``PYTHONPATH`` in the child's environment,
ahead of anything else already on the path.  ``sys.path[0]`` wins module
resolution over site-packages, so the worktree copy of a same-named top-level
package is what actually gets imported.  ``tests/test_importcheck.py`` proves
this is not vacuous: it makes an installed ``colleague`` package differ from
the worktree copy and asserts the *worktree* version's ``ImportError`` text is
what gets reported.

Off-knob
--------
``COLLEAGUE_IMPORT_CHECK=0`` disables the gate entirely — a module-level check
at the top of :func:`run_import_check` returns a ``status="skipped"`` report
immediately, before any subprocess is spawned.  Non-``.py`` changes and an
empty change list are also a strict no-op (``status="skipped"``/``"no-op"``).

This is a sanctioned ``subprocess`` consumer — see
``tests/test_boundary.py::_SUBPROCESS_ALLOWED``.
"""

from __future__ import annotations

import os
import py_compile
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Subprocess ceiling — an import that hangs (e.g. a module that blocks at
# import time) must never wedge the caller.
_IMPORT_TIMEOUT = 30


@dataclass
class ImportCheckFinding:
    """One module's import-check failure.

    ``module`` is the dotted module name derived from its repo-relative path;
    ``path`` is that repo-relative path; ``stage`` is ``"compile"`` or
    ``"import"``; ``error`` is the exception text (compiler message, or the
    subprocess's captured stderr/traceback tail).
    """

    module: str
    path: str
    stage: str
    error: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "path": self.path,
            "stage": self.stage,
            "error": self.error,
        }


@dataclass
class ImportCheckReport:
    """Outcome of the importability-check gate.

    ``status`` is one of ``"passed"`` / ``"failed"`` / ``"skipped"``.
    ``checked`` lists the repo-relative ``*.py`` paths that were actually
    smoke-imported; ``findings`` names every module that failed to import
    (empty on a passing run); ``reason`` carries the skip cause.
    """

    status: str
    checked: list[str] = field(default_factory=list)
    findings: list[ImportCheckFinding] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked": list(self.checked),
            "findings": [f.to_dict() for f in self.findings],
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportCheckReport":
        return cls(
            status=str(data.get("status", "skipped")),
            checked=list(data.get("checked", [])),
            findings=[
                ImportCheckFinding(**f) if isinstance(f, dict) else f
                for f in data.get("findings", [])
            ],
            reason=data.get("reason"),
        )

    def summary_line(self) -> str:
        """One-line human summary for stderr, mirroring affectedtests' style."""
        if self.status == "skipped":
            return f"import-check: skipped — {self.reason or 'unavailable'}"
        if self.status == "passed":
            return f"import-check: passed — {len(self.checked)} file(s)"
        names = ", ".join(f"{f.module} ({f.stage})" for f in self.findings)
        return f"import-check: failed — {len(self.findings)}/{len(self.checked)} file(s): {names}"


def _is_disabled() -> bool:
    return os.environ.get("COLLEAGUE_IMPORT_CHECK") == "0"


def _module_name(rel: str) -> Optional[str]:
    """Map a repo-relative ``*.py`` path to its dotted module name.

    ``colleague/plan/cli_driver.py`` -> ``colleague.plan.cli_driver``;
    ``colleague/cli/__init__.py`` -> ``colleague.cli`` (a package).  Returns
    ``None`` for a path that plainly isn't an importable module (e.g. outside
    any package — no ``__init__.py`` chain is validated here; the subprocess
    import itself is the real check and degrades that case to a finding).
    """
    p = Path(rel)
    if p.suffix != ".py":
        return None
    parts = list(p.parts)
    parts[-1] = p.stem
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def _py_compile_check(abs_path: Path) -> Optional[str]:
    """Return an error string on a syntax failure, else ``None``."""
    try:
        py_compile.compile(str(abs_path), doraise=True)
    except py_compile.PyCompileError as exc:
        return str(exc)
    except (OSError, ValueError, SyntaxError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _import_smoke(repo_path: Path, module: str) -> Optional[str]:
    """Run the actual subprocess import smoke for *module*.

    Returns an error string (the subprocess's captured output) on failure,
    else ``None`` on a clean import.  The child's ``PYTHONPATH`` is
    *repo_path* prepended ahead of everything already on the path — this is
    what makes resolution win against an installed same-named package (c20);
    ``cwd=repo_path`` mirrors the affectedtests precedent
    (``affectedtests.py`` run_affected_tests, cwd=repo_path).
    """
    env = dict(os.environ)
    repo_str = str(repo_path)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo_str if not existing else repo_str + os.pathsep + existing
    code = f"import {module}"
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, no shell, trusted env
            [sys.executable, "-c", code],
            cwd=repo_str,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=_IMPORT_TIMEOUT,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()
        return tail or f"exit code {proc.returncode}"
    return None


def run_import_check(
    repo_path: str | Path,
    changed_files: list[str],
) -> ImportCheckReport:
    """Run the importability-check gate over *changed_files*.

    For each changed ``*.py`` file (relative to *repo_path*): a fast
    ``py_compile`` syntax check, then a subprocess import smoke of its dotted
    module name with *repo_path* forced ahead of the child's import path
    (see the module docstring's "Worktree resolution" section).

    Strict no-op (``status="skipped"``) when: the ``COLLEAGUE_IMPORT_CHECK=0``
    knob is set, *changed_files* is empty, or none of *changed_files* end in
    ``.py``.  Never raises — any unexpected error degrades to a ``"skipped"``
    report naming the reason, so a broken gate can never block a handoff.
    """
    try:
        if _is_disabled():
            return ImportCheckReport(status="skipped", reason="COLLEAGUE_IMPORT_CHECK=0")

        py_files = [f for f in changed_files if f.endswith(".py")]
        if not py_files:
            return ImportCheckReport(status="skipped", reason="no changed .py files")

        repo = Path(repo_path).resolve()
        checked: list[str] = []
        findings: list[ImportCheckFinding] = []

        for rel in py_files:
            abs_path = repo / rel
            if not abs_path.is_file():
                findings.append(
                    ImportCheckFinding(
                        module=rel,
                        path=rel,
                        stage="compile",
                        error="file not found in worktree",
                    )
                )
                continue

            checked.append(rel)

            compile_error = _py_compile_check(abs_path)
            if compile_error is not None:
                findings.append(
                    ImportCheckFinding(module=rel, path=rel, stage="compile", error=compile_error)
                )
                continue

            module = _module_name(rel)
            if module is None:
                # Not a plausibly-importable path (e.g. a script outside any
                # package layout); py_compile already validated syntax, so
                # there's nothing further to smoke-import.
                continue

            import_error = _import_smoke(repo, module)
            if import_error is not None:
                findings.append(
                    ImportCheckFinding(module=module, path=rel, stage="import", error=import_error)
                )

        if not checked and not findings:
            return ImportCheckReport(status="skipped", reason="no checkable .py files")

        status = "failed" if findings else "passed"
        return ImportCheckReport(status=status, checked=checked, findings=findings)
    except Exception as exc:  # pragma: no cover - defensive: never raise out
        return ImportCheckReport(
            status="skipped", reason=f"import-check gate error: {type(exc).__name__}: {exc}"
        )

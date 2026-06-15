"""Guard test: colleague.plan modules introduce no third-party imports (R7 analogue).

Asserts:
1. Importing every colleague.plan.* module introduces no third-party top-level
   module into sys.modules (only stdlib + colleague).
2. No colleague/plan/*.py source contains "import devague" or "from devague"
   (plan mode is native-first; it never imports devague).
"""

import re
import sys
from pathlib import Path

# Known import-system builtins (not in sys.stdlib_module_names but safe).
_KNOWN_IMPORT_BUILTINS = {
    "importlib",
    "importlib_metadata",
    "_frozen_importlib",
    "_frozen_importlib_external",
    "_bootstrap",
    "pip",
    "pkg_resources",
    "__main__",
    "__path__",
    "site",
    "sitecustomize",
    "usercustomize",
}

# The plan-mode modules to guard.
_PLAN_MODULES = [
    "colleague.plan.frame",
    "colleague.plan.convergence",
    "colleague.plan.checkpoint",
    "colleague.plan.reviewer",
    "colleague.plan.trigger",
    "colleague.plan.pushback",
    "colleague.plan.spec_stage",
    "colleague.plan.plan_stage",
    "colleague.plan.workforce",
    "colleague.plan.orchestrator",
    "colleague.plan.cli_driver",
]


def _third_party_modules_introduced(action):
    """Run *action* and return any third-party top-level modules it imports.

    Snapshots sys.modules before/after, reduces new entries to their top-level
    name, and filters out stdlib, colleague, and known import-system builtins.
    """
    before = set(sys.modules.keys())
    action()
    new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}

    third_party = []
    for name in sorted(new_top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_colleague = name.startswith("colleague")
        is_builtin = name in _KNOWN_IMPORT_BUILTINS or name.startswith("_")
        if not (is_stdlib or is_colleague or is_builtin):
            third_party.append(name)
    return third_party


def test_plan_modules_no_third_party_imports():
    """Importing every colleague.plan.* module introduces no third-party imports."""

    def _import_plan_modules():
        for mod in _PLAN_MODULES:
            __import__(mod)  # noqa: F841

    third_party = _third_party_modules_introduced(_import_plan_modules)
    assert not third_party, (
        f"Plan modules introduced third-party imports: {sorted(third_party)}. "
        "Expected only stdlib, colleague, or builtins."
    )


def test_plan_sources_no_devague_import():
    """No colleague/plan/*.py source contains 'import devague' or 'from devague'."""
    plan_dir = Path(__file__).resolve().parents[1] / "colleague" / "plan"
    assert plan_dir.is_dir(), f"plan package dir not found at {plan_dir}"

    devague_pattern = re.compile(r"\bimport\s+devague\b|from\s+devague\b")

    violations = []
    for py_file in sorted(plan_dir.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), start=1):
            if devague_pattern.search(line):
                rel = py_file.relative_to(plan_dir.parent.parent)
                violations.append(f"{rel}:{lineno}: {line.rstrip()!r}")

    assert (
        not violations
    ), "devague import found in plan-mode source (plan mode is native-first):\n" + "\n".join(
        violations
    )

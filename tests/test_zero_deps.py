"""
Guard test enforcing zero runtime dependencies (R7).

Asserts:
1. pyproject.toml's [project].dependencies is empty.
2. Importing convertible modules introduces no third-party top-level imports.
"""

import sys
import tomllib
from pathlib import Path


def test_pyproject_dependencies_empty():
    """Assert [project].dependencies == [] in pyproject.toml."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert pyproject_path.exists(), f"pyproject.toml not found at {pyproject_path}"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    dependencies = data.get("project", {}).get("dependencies", [])
    assert dependencies == [], f"Expected [project].dependencies == [], got {dependencies}"


def test_no_third_party_imports():
    """
    Assert importing convertible modules introduces no third-party top-level imports.

    Approach:
    1. Snapshot sys.modules before any convertible import.
    2. Import convertible and core submodules.
    3. Diff sys.modules; extract top-level names (first component before '.').
    4. Assert every new top-level name is either in sys.stdlib_module_names,
       starts with 'convertible', or is a known import-system builtin.
    """
    # Snapshot before imports.
    before = set(sys.modules.keys())

    # Import the modules as specified in the task.
    import convertible  # noqa: F401
    import convertible.cli  # noqa: F401

    # GPS (issue #22): the telemetry facade and the loop/CLI that use it must
    # stay import-clean — the OpenTelemetry SDK is imported lazily inside
    # convertible.telemetry._otel, never at module load. This assertion holds
    # even when the [otel] extra IS installed (as it is in dev/CI): it is the
    # guard that the deferral is real.
    import convertible.cli._commands.telemetry  # noqa: F401
    import convertible.commands  # noqa: F401
    import convertible.configdir  # noqa: F401
    import convertible.culture  # noqa: F401
    import convertible.hooks  # noqa: F401
    import convertible.layers  # noqa: F401
    import convertible.loop  # noqa: F401
    import convertible.neighbours  # noqa: F401
    import convertible.telemetry  # noqa: F401

    # Diff and extract top-level module names.
    after = set(sys.modules.keys())
    new_modules = after - before

    # Extract top-level names (first component before '.').
    top_level = set()
    for mod_name in new_modules:
        if mod_name:
            top = mod_name.split(".")[0]
            top_level.add(top)

    # Known import-system builtins (not in stdlib_module_names but safe).
    # These include importlib internals and setup/packaging artifacts.
    known_builtins = {
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

    # Validate each top-level name.
    third_party = []
    for name in sorted(top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_convertible = name.startswith("convertible")
        is_builtin = name in known_builtins or name.startswith("_")

        if not (is_stdlib or is_convertible or is_builtin):
            third_party.append(name)

    msg = (
        f"Third-party imports detected: {sorted(third_party)}. "
        "Expected only stdlib, convertible, or builtins."
    )
    assert not third_party, msg

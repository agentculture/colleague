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
    import convertible.devague  # noqa: F401
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


def test_per_model_hooks_import_clean(tmp_path):
    """
    Assert per-model hooks resolution path (h9) introduces no third-party imports.

    Exercises convertible.hooks.load_hooks with a per-model overlay:
    1. Build a tmp repo with base .convertible/hooks.json and per-model overlay.
    2. Snapshot sys.modules, call load_hooks with model="test/model".
    3. Assert no third-party modules leaked.
    """
    # Build a repo structure with base and per-model hooks files.
    repo = tmp_path / "test_repo"
    repo.mkdir()
    repo_config = repo / ".convertible"
    repo_config.mkdir()

    # Create base hooks.json.
    base_hooks = repo_config / "hooks.json"
    base_hooks.write_text('{"hooks": {"task_start": [{"command": "echo base"}]}}')

    # Create per-model overlay: .convertible/test-model/hooks.json
    model_dir = repo_config / "test-model"
    model_dir.mkdir()
    model_hooks = model_dir / "hooks.json"
    model_hooks.write_text('{"hooks": {"pre_tool": [{"matcher": ".*", "command": "echo model"}]}}')

    # Snapshot before load_hooks call.
    before = set(sys.modules.keys())

    # Import and call load_hooks with a model; uses configdir + layers internally.
    from convertible.hooks import load_hooks

    config = load_hooks(repo, model="test/model")

    # Verify the overlay was loaded by checking entry counts.
    assert config.hooks_for("task_start"), "Base hooks should be present"
    assert config.hooks_for("pre_tool", tool="any_tool"), "Model overlay hooks should be present"

    # Diff modules and check for third-party.
    after = set(sys.modules.keys())
    new_modules = after - before

    top_level = set()
    for mod_name in new_modules:
        if mod_name:
            top = mod_name.split(".")[0]
            top_level.add(top)

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

    third_party = []
    for name in sorted(top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_convertible = name.startswith("convertible")
        is_builtin = name in known_builtins or name.startswith("_")

        if not (is_stdlib or is_convertible or is_builtin):
            third_party.append(name)

    msg = (
        f"Per-model hooks resolution leaked third-party imports: {sorted(third_party)}. "
        "Expected only stdlib, convertible, or builtins."
    )
    assert not third_party, msg


def test_per_model_hooks_strict_no_op(tmp_path):
    """
    Assert per-model hooks are strict no-op (h2) when overlay is absent.

    When load_hooks is called with a model but no overlay file exists,
    the returned HookConfig must be identical to base-only load.
    """
    repo = tmp_path / "test_repo"
    repo.mkdir()
    repo_config = repo / ".convertible"
    repo_config.mkdir()

    # Create base hooks.json with multiple events.
    base_hooks = repo_config / "hooks.json"
    base_hooks.write_text(
        '{"hooks": {'
        '"task_start": [{"command": "echo start"}], '
        '"pre_tool": [{"matcher": "run_command", "command": "echo pre"}], '
        '"post_tool": [{"command": "echo post"}]'
        "}}"
    )

    from convertible.hooks import load_hooks

    # Load base-only (no model).
    config_base = load_hooks(repo)

    # Load with model that has no overlay — should return identical result.
    config_with_missing_model = load_hooks(repo, model="nonexistent/model")

    # Compare all_entries() to assert identical composition.
    base_entries = config_base.all_entries()
    model_entries = config_with_missing_model.all_entries()

    assert len(base_entries) == len(
        model_entries
    ), "Entry counts should match when overlay is absent"

    for base_entry, model_entry in zip(base_entries, model_entries):
        assert base_entry.event == model_entry.event
        assert base_entry.matcher == model_entry.matcher
        assert base_entry.command == model_entry.command

    # Also compare hooks_for results for each event.
    for event in ["task_start", "pre_tool", "post_tool"]:
        base_hooks = config_base.hooks_for(event)
        model_hooks = config_with_missing_model.hooks_for(event)

        assert len(base_hooks) == len(model_hooks)
        for base_h, model_h in zip(base_hooks, model_hooks):
            assert base_h.event == model_h.event
            assert base_h.matcher == model_h.matcher
            assert base_h.command == model_h.command


def test_no_socket_daemon_mcp_surface():
    """
    Assert convertible/ package has no socket/daemon/mcp.json surface (h9).

    Scans every Python source file in convertible/ and asserts:
    1. No module imports socket.
    2. No code references "mcp.json" as a string.
    3. No daemon/fork behavior (search disabled via doc convention).
    """
    import re

    convertible_dir = Path(__file__).resolve().parents[1] / "convertible"
    assert convertible_dir.is_dir(), f"convertible package dir not found at {convertible_dir}"

    socket_pattern = re.compile(r"\b(import socket|from socket\b)")
    mcp_json_pattern = re.compile(r'"mcp\.json"|\'mcp\.json\'')

    violations = []

    # Scan every .py file in convertible/
    for py_file in sorted(convertible_dir.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")

        # Check for socket imports.
        if socket_pattern.search(content):
            violations.append(f"{py_file.relative_to(convertible_dir)}: socket import detected")

        # Check for mcp.json references.
        if mcp_json_pattern.search(content):
            violations.append(
                f"{py_file.relative_to(convertible_dir)}: mcp.json reference detected"
            )

    msg = "No-socket/daemon/mcp surface violations:\n" + "\n".join(violations) if violations else ""
    assert not violations, msg

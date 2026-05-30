"""
Guard test enforcing zero runtime dependencies (R7).

Asserts:
1. pyproject.toml's [project].dependencies is empty.
2. Importing convertible modules introduces no third-party top-level imports.
3. The per-model hooks resolution path stays import-clean and is a strict no-op
   without an overlay; the package opens no socket / daemon / mcp.json surface.
"""

import sys
import tomllib
from pathlib import Path

# Known import-system builtins (not in sys.stdlib_module_names but safe):
# importlib internals and setup/packaging artifacts.
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


def _third_party_modules_introduced(action):
    """Run ``action`` and return any third-party top-level modules it imports.

    Snapshots ``sys.modules`` before/after, reduces new entries to their
    top-level name (first component before ``.``), and filters out stdlib,
    ``convertible`` itself, and known import-system builtins. Shared by the
    import-cleanliness guards so the snapshot/diff/classify logic lives once.
    """
    before = set(sys.modules.keys())
    action()
    new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}

    third_party = []
    for name in sorted(new_top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_convertible = name.startswith("convertible")
        is_builtin = name in _KNOWN_IMPORT_BUILTINS or name.startswith("_")
        if not (is_stdlib or is_convertible or is_builtin):
            third_party.append(name)
    return third_party


def test_pyproject_dependencies_empty():
    """Assert [project].dependencies == [] in pyproject.toml."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert pyproject_path.exists(), f"pyproject.toml not found at {pyproject_path}"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    dependencies = data.get("project", {}).get("dependencies", [])
    assert dependencies == [], f"Expected [project].dependencies == [], got {dependencies}"


def test_no_third_party_imports():
    """Importing convertible modules introduces no third-party top-level imports.

    GPS (issue #22): the telemetry facade and the loop/CLI that use it must stay
    import-clean — the OpenTelemetry SDK is imported lazily inside
    convertible.telemetry._otel, never at module load. This holds even when the
    [otel] extra IS installed (as in dev/CI): it is the guard that the deferral
    is real.
    """

    def _import_core():
        import convertible  # noqa: F401
        import convertible.cli  # noqa: F401
        import convertible.cli._commands.telemetry  # noqa: F401
        import convertible.commands  # noqa: F401
        import convertible.configdir  # noqa: F401
        import convertible.culture  # noqa: F401
        import convertible.devague  # noqa: F401
        import convertible.hooks  # noqa: F401
        import convertible.layers  # noqa: F401
        import convertible.loop  # noqa: F401
        import convertible.neighbours  # noqa: F401
        import convertible.policy  # noqa: F401
        import convertible.subagents  # noqa: F401
        import convertible.telemetry  # noqa: F401

    third_party = _third_party_modules_introduced(_import_core)
    assert not third_party, (
        f"Third-party imports detected: {sorted(third_party)}. "
        "Expected only stdlib, convertible, or builtins."
    )


def test_per_model_hooks_import_clean(tmp_path):
    """Per-model hooks resolution (h9) introduces no third-party imports."""
    repo = tmp_path / "test_repo"
    (repo / ".convertible").mkdir(parents=True)
    (repo / ".convertible" / "hooks.json").write_text(
        '{"hooks": {"task_start": [{"command": "echo base"}]}}'
    )
    model_dir = repo / ".convertible" / "test-model"
    model_dir.mkdir()
    (model_dir / "hooks.json").write_text(
        '{"hooks": {"pre_tool": [{"matcher": ".*", "command": "echo model"}]}}'
    )

    def _load_with_overlay():
        from convertible.hooks import load_hooks

        config = load_hooks(repo, model="test/model")
        # Confirm the overlay actually loaded, so we measure the real path.
        assert config.hooks_for("task_start"), "Base hooks should be present"
        assert config.hooks_for("pre_tool", tool="any_tool"), "Model overlay should be present"

    third_party = _third_party_modules_introduced(_load_with_overlay)
    assert not third_party, (
        f"Per-model hooks resolution leaked third-party imports: {sorted(third_party)}. "
        "Expected only stdlib, convertible, or builtins."
    )


def test_per_model_hooks_strict_no_op(tmp_path):
    """Per-model hooks are a strict no-op (h2) when the overlay is absent."""
    repo = tmp_path / "test_repo"
    (repo / ".convertible").mkdir(parents=True)
    (repo / ".convertible" / "hooks.json").write_text(
        '{"hooks": {'
        '"task_start": [{"command": "echo start"}], '
        '"pre_tool": [{"matcher": "run_command", "command": "echo pre"}], '
        '"post_tool": [{"command": "echo post"}]'
        "}}"
    )

    from convertible.hooks import load_hooks

    config_base = load_hooks(repo)
    config_with_missing_model = load_hooks(repo, model="nonexistent/model")

    base_entries = config_base.all_entries()
    model_entries = config_with_missing_model.all_entries()
    assert len(base_entries) == len(model_entries), "Entry counts should match when overlay absent"
    for base_entry, model_entry in zip(base_entries, model_entries):
        assert base_entry.event == model_entry.event
        assert base_entry.matcher == model_entry.matcher
        assert base_entry.command == model_entry.command

    for event in ["task_start", "pre_tool", "post_tool"]:
        base = config_base.hooks_for(event)
        model = config_with_missing_model.hooks_for(event)
        assert len(base) == len(model)
        for base_h, model_h in zip(base, model):
            assert base_h.event == model_h.event
            assert base_h.matcher == model_h.matcher
            assert base_h.command == model_h.command


def test_no_socket_daemon_mcp_surface():
    """convertible/ has no socket/daemon/mcp.json surface (h9)."""
    import re

    convertible_dir = Path(__file__).resolve().parents[1] / "convertible"
    assert convertible_dir.is_dir(), f"convertible package dir not found at {convertible_dir}"

    socket_pattern = re.compile(r"\b(import socket|from socket\b)")
    mcp_json_pattern = re.compile(r'"mcp\.json"|\'mcp\.json\'')

    violations = []
    for py_file in sorted(convertible_dir.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        if socket_pattern.search(content):
            violations.append(f"{py_file.relative_to(convertible_dir)}: socket import detected")
        if mcp_json_pattern.search(content):
            violations.append(
                f"{py_file.relative_to(convertible_dir)}: mcp.json reference detected"
            )

    msg = "No-socket/daemon/mcp surface violations:\n" + "\n".join(violations) if violations else ""
    assert not violations, msg

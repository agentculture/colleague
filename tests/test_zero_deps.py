"""
Guard test enforcing the single-base-dependency posture (R7, post-agentfront).

Colleague's agent-first CLI is rendered from an imported agentfront App registry
(the "import, don't duplicate" migration). agentfront is the ONE sanctioned base
runtime dependency — its core is pure-stdlib (zero third-party transitively), so
the zero-deps posture holds: this guard allow-lists exactly ``agentfront`` and
fails on any other third-party leak.

Asserts:
1. pyproject.toml's [project].dependencies is exactly ["agentfront>=…"].
2. Importing colleague modules introduces no third-party top-level imports
   other than the sanctioned ``agentfront``.
3. The [mcp] extra is declared and opt-in; the base import path loads no ``mcp``
   SDK (the MCP server runs only when the extra is installed and started).
4. The per-model hooks resolution path stays import-clean and is a strict no-op
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
    ``colleague`` itself, and known import-system builtins. Shared by the
    import-cleanliness guards so the snapshot/diff/classify logic lives once.
    """
    before = set(sys.modules.keys())
    action()
    new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}

    third_party = []
    for name in sorted(new_top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_colleague = name.startswith("colleague")
        is_builtin = name in _KNOWN_IMPORT_BUILTINS or name.startswith("_")
        # agentfront is the ONE sanctioned base runtime dependency: colleague's
        # CLI is rendered from its App registry, so importing it anywhere in
        # colleague is legitimate, not a leak. Its own core is pure-stdlib, so
        # allowing it does not admit any transitive third-party.
        is_sanctioned_base = name == "agentfront"
        if not (is_stdlib or is_colleague or is_builtin or is_sanctioned_base):
            third_party.append(name)
    return third_party


def test_base_dependency_is_exactly_agentfront():
    """Assert [project].dependencies is exactly the one sanctioned base dep.

    The "import, don't duplicate" migration takes agentfront as colleague's ONE
    base runtime dependency (its core is pure-stdlib, so zero third-party flows
    transitively). The base install must pull exactly ``agentfront`` and nothing
    else — any second base dependency is a zero-deps-posture breach.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert pyproject_path.exists(), f"pyproject.toml not found at {pyproject_path}"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    dependencies = data.get("project", {}).get("dependencies", [])
    assert (
        len(dependencies) == 1
    ), f"Expected exactly one base dependency (agentfront), got {dependencies}"
    dep = dependencies[0]
    assert dep.startswith("agentfront"), f"The sole base dependency must be agentfront, got {dep!r}"
    # Pin a tested floor (the consumer CLI API landed in 0.14.0).
    assert ">=" in dep, f"agentfront must pin a version floor (>=), got {dep!r}"


def test_mcp_extra_declared_and_opt_in():
    """The [mcp] extra pins the mcp SDK and is NOT a base dependency.

    The MCP server bonus ships behind an opt-in extra so a base install binds no
    socket and runs no daemon. The mcp SDK must appear ONLY under
    [project.optional-dependencies].mcp — never in [project].dependencies.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    extras = project.get("optional-dependencies", {})
    mcp_extra = extras.get("mcp")
    assert mcp_extra is not None, "Expected a [project.optional-dependencies].mcp extra"
    assert any(
        "mcp" in pin for pin in mcp_extra
    ), f"[mcp] extra must pin the mcp SDK, got {mcp_extra}"

    # mcp must never be a base dependency.
    base = project.get("dependencies", [])
    assert not any(
        pin.startswith("mcp") for pin in base
    ), f"the mcp SDK must be an opt-in extra, never a base dependency; base={base}"


def test_base_import_does_not_load_mcp():
    """Importing colleague's CLI path loads no ``mcp`` SDK (opt-in server only).

    agentfront imports the mcp SDK lazily, only inside ``App.mcp_server()``. The
    base colleague import path (CLI build + dispatch) must therefore never pull
    ``mcp`` into ``sys.modules`` — the server runs only when the [mcp] extra is
    installed and ``colleague mcp serve`` is explicitly invoked. This guard is
    meaningful because the dev env DOES install mcp (dev group), so it proves
    laziness, not mere absence of the package.
    """

    def _import_cli_path():
        import colleague.cli  # noqa: F401

    before = set(sys.modules.keys())
    _import_cli_path()
    newly = {n.split(".")[0] for n in (set(sys.modules.keys()) - before)}
    assert "mcp" not in newly, (
        "Importing colleague.cli pulled the mcp SDK — it must stay lazy "
        "(only App.mcp_server() / `colleague mcp serve` may import mcp)."
    )


def test_culture_extra_declared():
    """The [culture] extra declares the resident deps (agent-lifecycle + agentirc-cli).

    The resident runtime needs the agent-lifecycle seam and the agentirc-cli wire,
    but they must ship ONLY as the opt-in [culture] extra — never as base
    dependencies (test_base_dependency_is_exactly_agentfront guards the base).
    This asserts the extra exists and names both packages, so the install path
    `pip install colleague[culture]` resolves them.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    extras = data.get("project", {}).get("optional-dependencies", {})
    culture = extras.get("culture")
    assert culture is not None, "Expected a [project.optional-dependencies].culture extra"
    joined = " ".join(culture)
    assert "agent-lifecycle" in joined, f"[culture] must pin agent-lifecycle, got {culture}"
    assert "agentirc-cli" in joined, f"[culture] must pin agentirc-cli, got {culture}"


def test_resident_core_import_clean():
    """The resident's import-clean core pulls no third-party, even with [culture] installed.

    colleague.resident (the package boundary) and colleague.resident.steward (the
    single subprocess consumer) hold no agent_lifecycle / agentirc import at module
    load — those live only in the async seam adapters (harness/transport/supervisor)
    and load lazily when the resident runs. This is the [culture] analogue of the
    [otel] / [tui] deferral guards: it proves the boundary is real.
    """

    def _import_resident_core():
        import colleague.resident  # noqa: F401
        import colleague.resident.steward  # noqa: F401

    third_party = _third_party_modules_introduced(_import_resident_core)
    assert not third_party, (
        f"Resident core introduced third-party imports: {sorted(third_party)}. "
        "agent_lifecycle / agentirc must load lazily inside the seam adapters, "
        "never at colleague.resident or colleague.resident.steward module load."
    )


def test_no_third_party_imports():
    """Importing colleague modules introduces no third-party top-level imports.

    GPS (issue #22): the telemetry facade and the loop/CLI that use it must stay
    import-clean — the OpenTelemetry SDK is imported lazily inside
    colleague.telemetry._otel, never at module load. This holds even when the
    [otel] extra IS installed (as in dev/CI): it is the guard that the deferral
    is real.
    """

    def _import_core():
        import colleague  # noqa: F401
        import colleague.cli  # noqa: F401
        import colleague.cli._commands.roles  # noqa: F401
        import colleague.cli._commands.telemetry  # noqa: F401
        import colleague.commands  # noqa: F401
        import colleague.configdir  # noqa: F401
        import colleague.culture  # noqa: F401
        import colleague.devague  # noqa: F401
        import colleague.flight  # noqa: F401
        import colleague.hooks  # noqa: F401
        import colleague.layers  # noqa: F401
        import colleague.lint  # noqa: F401
        import colleague.loop  # noqa: F401
        import colleague.neighbours  # noqa: F401
        import colleague.policy  # noqa: F401
        import colleague.roles  # noqa: F401
        import colleague.subagents  # noqa: F401
        import colleague.telemetry  # noqa: F401

    third_party = _third_party_modules_introduced(_import_core)
    assert not third_party, (
        f"Third-party imports detected: {sorted(third_party)}. "
        "Expected only stdlib, colleague, or builtins."
    )


def test_per_model_hooks_import_clean(tmp_path):
    """Per-model hooks resolution (h9) introduces no third-party imports."""
    repo = tmp_path / "test_repo"
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "hooks.json").write_text(
        '{"hooks": {"task_start": [{"command": "echo base"}]}}'
    )
    model_dir = repo / ".colleague" / "test-model"
    model_dir.mkdir()
    (model_dir / "hooks.json").write_text(
        '{"hooks": {"pre_tool": [{"matcher": ".*", "command": "echo model"}]}}'
    )

    def _load_with_overlay():
        from colleague.hooks import load_hooks

        config = load_hooks(repo, model="test/model")
        # Confirm the overlay actually loaded, so we measure the real path.
        assert config.hooks_for("task_start"), "Base hooks should be present"
        assert config.hooks_for("pre_tool", tool="any_tool"), "Model overlay should be present"

    third_party = _third_party_modules_introduced(_load_with_overlay)
    assert not third_party, (
        f"Per-model hooks resolution leaked third-party imports: {sorted(third_party)}. "
        "Expected only stdlib, colleague, or builtins."
    )


def test_per_model_hooks_strict_no_op(tmp_path):
    """Per-model hooks are a strict no-op (h2) when the overlay is absent."""
    repo = tmp_path / "test_repo"
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "hooks.json").write_text(
        '{"hooks": {'
        '"task_start": [{"command": "echo start"}], '
        '"pre_tool": [{"matcher": "run_command", "command": "echo pre"}], '
        '"post_tool": [{"command": "echo post"}]'
        "}}"
    )

    from colleague.hooks import load_hooks

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
    """colleague/ has no socket/daemon/mcp.json surface (h9)."""
    import re

    colleague_dir = Path(__file__).resolve().parents[1] / "colleague"
    assert colleague_dir.is_dir(), f"colleague package dir not found at {colleague_dir}"

    socket_pattern = re.compile(r"\b(import socket|from socket\b)")
    mcp_json_pattern = re.compile(r'"mcp\.json"|\'mcp\.json\'')

    violations = []
    for py_file in sorted(colleague_dir.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        if socket_pattern.search(content):
            violations.append(f"{py_file.relative_to(colleague_dir)}: socket import detected")
        if mcp_json_pattern.search(content):
            violations.append(f"{py_file.relative_to(colleague_dir)}: mcp.json reference detected")

    msg = "No-socket/daemon/mcp surface violations:\n" + "\n".join(violations) if violations else ""
    assert not violations, msg


def test_tui_core_no_third_party_imports():
    """Importing the surviving colleague TUI modules introduces no third-party
    top-level imports beyond the sanctioned ``agentfront`` base dep.

    After issue #249 the generic cockpit modules live in ``agentfront.taui``
    (imported, not duplicated); colleague keeps only the thin TaskResult-coupled
    adapter (``from_work``) and the live raw-terminal driver (``render.driver``,
    which agentfront does not ship). agentfront is the ONE allowed base dep, and
    its core is pure-stdlib, so this surface stays import-clean even with the
    [tui] extra installed — the ``_third_party_modules_introduced`` helper
    allow-lists exactly ``agentfront``.
    """

    def _import_tui_core():
        import colleague.tui.from_work  # noqa: F401
        import colleague.tui.render.driver  # noqa: F401

    third_party = _third_party_modules_introduced(_import_tui_core)
    assert not third_party, (
        f"TUI surface introduced third-party imports: {sorted(third_party)}. "
        "Only stdlib + the sanctioned agentfront base dep are allowed; the "
        "generic cockpit lives in agentfront.taui (imported, not duplicated)."
    )


def test_tui_core_no_forbidden_stdlib_imports():
    """TUI core source does not import rich, textual, or network/daemon stdlib.

    The renderer is hand-rolled ANSI (honesty h11/c6): no network calls, no
    subprocess, no socket, no daemon. Verifies the source directly so the
    check is independent of the runtime environment.
    """
    import re

    tui_dir = Path(__file__).resolve().parents[1] / "colleague" / "tui"
    assert tui_dir.is_dir(), f"colleague/tui dir not found at {tui_dir}"

    # Third-party renderer packages must never appear in TUI core source.
    third_party_pattern = re.compile(r"^\s*(import|from)\s+(rich|textual)\b", re.MULTILINE)
    # Network / daemon / subprocess stdlib must not appear in TUI core source.
    forbidden_stdlib_pattern = re.compile(
        r"^\s*(import|from)\s+(urllib|socket|http|subprocess)\b", re.MULTILINE
    )

    violations = []
    for py_file in sorted(tui_dir.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        rel = py_file.relative_to(tui_dir)
        if third_party_pattern.search(content):
            violations.append(f"tui/{rel}: imports rich or textual (must be lazy/in wheel)")
        if forbidden_stdlib_pattern.search(content):
            violations.append(
                f"tui/{rel}: imports urllib/socket/http/subprocess "
                "(no network/daemon in TUI core)"
            )

    msg = "TUI core source has forbidden imports:\n" + "\n".join(violations) if violations else ""
    assert not violations, msg

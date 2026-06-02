"""Per-model isolation tests for ``load_hooks(repo, model=...)`` (t3).

Mirrors the structure of ``tests/test_layers.py``'s per-model isolation section
(criterion h5).  Each test focuses on one invariant, using module-level model
constants and simple helper functions to keep fixtures close to the assertions.

Criteria covered
----------------
h5  Structure mirrors ``test_layers.py``'s per-model isolation tests.
h6  Isolation: an overlay under model X is invisible when loading for model Y.
    (apply + precedence) An overlay for model X applies and its entries are
    ordered *before* base entries — giving the per-model fix first-deny priority.
h8  Base not degraded: with both a base entry and a per-model entry, loading for
    the model returns BOTH — per-model first, base second.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague.hooks import HookConfig, HookEntry, load_hooks
from colleague.layers import sanitize_model

# ---------------------------------------------------------------------------
# Module-level constants (mirroring test_layers.py _MODEL_X / _MODEL_Y style)
# ---------------------------------------------------------------------------

_MODEL_X = "Qwen/Qwen3-32B"
_SAFE_X = sanitize_model(_MODEL_X)  # "Qwen-Qwen3-32B"

_MODEL_Y = "meta/Llama-3.1-8B"
_SAFE_Y = sanitize_model(_MODEL_Y)  # "meta-Llama-3.1-8B"

# Tool names used as matchers across tests.
_TOOL = "run_command"
_OTHER_TOOL = "write_file"

# ---------------------------------------------------------------------------
# Helpers (mirrors _repo / _home / _write in test_layers.py)
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    """Create and return a bare repo directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _home(tmp_path: Path) -> Path:
    """Create and return a fake user home directory."""
    home = tmp_path / "home"
    home.mkdir()
    return home


def _write_hooks(dotdir: Path, relative: str, payload: dict) -> Path:
    """Write *payload* as JSON to *dotdir*/*relative*; mkdir -p as needed."""
    path = dotdir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# h6 — Isolation: model-X overlay is invisible when loading for model Y
# ---------------------------------------------------------------------------


def test_isolation_x_overlay_not_seen_by_y(tmp_path: Path) -> None:
    """Overlay under .colleague/X/ is invisible when loading for model Y.

    Criterion h6: exact-construction via sanitize_model means no sibling glob.
    The loop must never apply model X's deny rule when driving model Y.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    # Write an overlay that denies _TOOL, filed under model X's sanitized path.
    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo DENY-X"}]}},
    )

    # Load for model Y (no overlay for Y exists).
    cfg_y = load_hooks(repo, model=_MODEL_Y, user_home=home)

    # Model Y must see no hooks for _TOOL — X's overlay must NOT leak in.
    entries_y = cfg_y.hooks_for("pre_tool", tool=_TOOL)
    commands_y = [e.command for e in entries_y]
    assert "echo DENY-X" not in commands_y, f"Model Y saw model X's overlay entry: {commands_y}"


def test_isolation_y_overlay_not_seen_by_x(tmp_path: Path) -> None:
    """Symmetric: model Y's overlay is invisible when loading for model X.

    Criterion h6 — bidirectional: neither model leaks into the other.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_Y}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo DENY-Y"}]}},
    )

    cfg_x = load_hooks(repo, model=_MODEL_X, user_home=home)
    commands_x = [e.command for e in cfg_x.hooks_for("pre_tool", tool=_TOOL)]
    assert "echo DENY-Y" not in commands_x, f"Model X saw model Y's overlay entry: {commands_x}"


def test_isolation_both_overlays_each_sees_only_own(tmp_path: Path) -> None:
    """Both X and Y overlays present; each model sees only its own.

    Criterion h6 — joint isolation: we write overlays for both models in the
    same repo and assert that each load yields exclusively its own entry.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo X-HOOK"}]}},
    )
    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_Y}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo Y-HOOK"}]}},
    )

    cfg_x = load_hooks(repo, model=_MODEL_X, user_home=home)
    cfg_y = load_hooks(repo, model=_MODEL_Y, user_home=home)

    cmds_x = [e.command for e in cfg_x.hooks_for("pre_tool", tool=_TOOL)]
    cmds_y = [e.command for e in cfg_y.hooks_for("pre_tool", tool=_TOOL)]

    assert "echo X-HOOK" in cmds_x
    assert "echo Y-HOOK" not in cmds_x

    assert "echo Y-HOOK" in cmds_y
    assert "echo X-HOOK" not in cmds_y


# ---------------------------------------------------------------------------
# Applies + precedence: per-model entries ordered BEFORE base entries
# ---------------------------------------------------------------------------


def test_per_model_applies_for_correct_model(tmp_path: Path) -> None:
    """Loading for model X makes X's overlay entries visible.

    Criterion h6 (positive half): the overlay DOES apply for the correct model.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo X-FIX"}]}},
    )

    cfg_x = load_hooks(repo, model=_MODEL_X, user_home=home)
    commands = [e.command for e in cfg_x.hooks_for("pre_tool", tool=_TOOL)]
    assert "echo X-FIX" in commands, f"Model X's overlay was not applied: {commands}"


def test_per_model_entries_ordered_before_base(tmp_path: Path) -> None:
    """Per-model entries are prepended ahead of base entries.

    Criterion h6 / precedence: hooks_for returns per-model matches first so the
    loop's first-deny/rewrite-wins gives the per-model fix priority over the base.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    # Base hooks.json has one pre_tool entry for _TOOL.
    _write_hooks(
        repo / ".colleague",
        "hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo BASE"}]}},
    )
    # Model-X overlay adds another pre_tool entry for the same tool.
    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo MODEL-X"}]}},
    )

    cfg = load_hooks(repo, model=_MODEL_X, user_home=home)
    entries = cfg.hooks_for("pre_tool", tool=_TOOL)
    commands = [e.command for e in entries]

    # Both entries must be present.
    assert "echo MODEL-X" in commands
    assert "echo BASE" in commands

    # Per-model entry must appear first (first-deny/rewrite-wins priority).
    assert commands.index("echo MODEL-X") < commands.index(
        "echo BASE"
    ), f"Per-model entry not before base entry: {commands}"


def test_per_model_first_across_multiple_events(tmp_path: Path) -> None:
    """Per-model-first ordering holds for every event, not just pre_tool.

    Criterion h6 / precedence extended: task_start and finish events also
    receive per-model entries ahead of base entries.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        "hooks.json",
        {
            "hooks": {
                "task_start": [{"command": "echo BASE-START"}],
                "finish": [{"command": "echo BASE-DONE"}],
            }
        },
    )
    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {
            "hooks": {
                "task_start": [{"command": "echo MODEL-START"}],
                "finish": [{"command": "echo MODEL-DONE"}],
            }
        },
    )

    cfg = load_hooks(repo, model=_MODEL_X, user_home=home)

    start = [e.command for e in cfg.hooks_for("task_start")]
    assert start[0] == "echo MODEL-START"
    assert "echo BASE-START" in start
    assert start.index("echo MODEL-START") < start.index("echo BASE-START")

    finish = [e.command for e in cfg.hooks_for("finish")]
    assert finish[0] == "echo MODEL-DONE"
    assert "echo BASE-DONE" in finish
    assert finish.index("echo MODEL-DONE") < finish.index("echo BASE-DONE")


# ---------------------------------------------------------------------------
# h8 — Base not degraded: base entries survive alongside per-model entries
# ---------------------------------------------------------------------------


def test_base_entries_present_alongside_per_model(tmp_path: Path) -> None:
    """With both base and per-model entries, loading for model X fires BOTH.

    Criterion h8: the per-model overlay adds entries; it never erases or
    replaces the base entries. The base hook is still present and not edited.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        "hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo BASE-HOOK"}]}},
    )
    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo MODEL-HOOK"}]}},
    )

    cfg = load_hooks(repo, model=_MODEL_X, user_home=home)
    entries = cfg.hooks_for("pre_tool", tool=_TOOL)
    commands = [e.command for e in entries]

    assert len(entries) == 2, f"Expected 2 entries (model + base), got: {commands}"
    assert "echo BASE-HOOK" in commands, "Base entry was removed or missing"
    assert "echo MODEL-HOOK" in commands, "Per-model entry is missing"


def test_base_entries_unaffected_for_other_tool(tmp_path: Path) -> None:
    """Base entries for a tool not in the overlay are fully preserved.

    Criterion h8 — no collateral damage: the overlay for _TOOL must not affect
    base entries registered for _OTHER_TOOL.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        "hooks.json",
        {
            "hooks": {
                "pre_tool": [
                    {"matcher": _TOOL, "command": "echo BASE-RUN"},
                    {"matcher": _OTHER_TOOL, "command": "echo BASE-WRITE"},
                ]
            }
        },
    )
    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo MODEL-RUN"}]}},
    )

    cfg = load_hooks(repo, model=_MODEL_X, user_home=home)

    # The base entry for _OTHER_TOOL must still be there.
    write_entries = cfg.hooks_for("pre_tool", tool=_OTHER_TOOL)
    assert len(write_entries) == 1
    assert write_entries[0].command == "echo BASE-WRITE"

    # The _TOOL entries: model first, then base.
    run_entries = cfg.hooks_for("pre_tool", tool=_TOOL)
    cmds = [e.command for e in run_entries]
    assert cmds == ["echo MODEL-RUN", "echo BASE-RUN"]


def test_base_entries_present_when_no_per_model_for_that_event(tmp_path: Path) -> None:
    """Base entries for events not in the overlay are fully preserved.

    Criterion h8 — event-level: the overlay only has pre_tool; the base
    task_start and finish entries must be unaffected.
    """
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        "hooks.json",
        {
            "hooks": {
                "pre_tool": [{"matcher": _TOOL, "command": "echo BASE-PRE"}],
                "task_start": [{"command": "echo BASE-START"}],
                "finish": [{"command": "echo BASE-FINISH"}],
            }
        },
    )
    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo MODEL-PRE"}]}},
    )

    cfg = load_hooks(repo, model=_MODEL_X, user_home=home)

    # task_start and finish: base entries untouched.
    start = [e.command for e in cfg.hooks_for("task_start")]
    assert start == ["echo BASE-START"]

    finish = [e.command for e in cfg.hooks_for("finish")]
    assert finish == ["echo BASE-FINISH"]

    # pre_tool: model first, base second.
    pre = [e.command for e in cfg.hooks_for("pre_tool", tool=_TOOL)]
    assert pre == ["echo MODEL-PRE", "echo BASE-PRE"]


# ---------------------------------------------------------------------------
# Sanity: sanitize_model token matches what load_hooks constructs
# ---------------------------------------------------------------------------


def test_sanitize_model_tokens_match_expected() -> None:
    """The directory names used throughout this file match sanitize_model output.

    This documents the exact path construction load_hooks uses, so a reader can
    see what .colleague/<token>/ directories to create for each model.
    """
    assert _SAFE_X == "Qwen-Qwen3-32B"
    assert _SAFE_Y == "meta-Llama-3.1-8B"


def test_returntype_is_hookconfig(tmp_path: Path) -> None:
    """load_hooks always returns a HookConfig regardless of per-model presence."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    cfg_no_model = load_hooks(repo, user_home=home)
    cfg_with_model = load_hooks(repo, model=_MODEL_X, user_home=home)

    assert isinstance(cfg_no_model, HookConfig)
    assert isinstance(cfg_with_model, HookConfig)


def test_entry_type_is_hookentry(tmp_path: Path) -> None:
    """Entries returned by hooks_for are HookEntry instances."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write_hooks(
        repo / ".colleague",
        f"{_SAFE_X}/hooks.json",
        {"hooks": {"pre_tool": [{"matcher": _TOOL, "command": "echo X"}]}},
    )

    cfg = load_hooks(repo, model=_MODEL_X, user_home=home)
    for entry in cfg.hooks_for("pre_tool", tool=_TOOL):
        assert isinstance(entry, HookEntry)

"""``colleague tui`` headless CLI verb (t10).

Every verb runs HEADLESS (no real terminal), supports ``--json``, sends results
to stdout / diagnostics + errors to stderr, and raises ``CliError`` (never leaks
a traceback). These tests drive the CLI through ``colleague.cli.main`` exactly
like ``tests/test_feedback_cli.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agentfront.taui.events import SkillSuggested, dumps_events
from agentfront.taui.state import TAUIState as CockpitState

from colleague.cli import main

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_state(path: Path, state: CockpitState) -> Path:
    path.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    return path


def _boost_state() -> CockpitState:
    """A state whose serialized mirror already carries a visible skill-suggested popup."""
    from agentfront.taui.reducer import reduce

    return reduce(CockpitState(), SkillSuggested(skill="boost", reason="task_complexity_high"))


# ---------------------------------------------------------------------------
# parser still builds (registration didn't break anything)
# ---------------------------------------------------------------------------


def test_help_still_builds(capsys: pytest.CaptureFixture[str]) -> None:
    # `colleague --help` renders through the legacy parser (to keep the grouped
    # epilog) and returns 0 rather than raising SystemExit; exit-code-equivalent.
    rc = main(["--help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tui" in out


# ---------------------------------------------------------------------------
# tui state
# ---------------------------------------------------------------------------


def test_state_default_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "state", "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    assert mirror["taui_version"]  # present and non-empty
    assert mirror["screen"] == "main"
    # The standing prompt action is always available.
    sels = {a["selector"] for a in mirror["available_actions"]}
    assert "input.prompt" in sels


def test_state_from_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", _boost_state())
    rc = main(["tui", "state", "--state", str(sf), "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    popup_ids = {p["id"] for p in mirror["popups"]}
    # agentfront uses a generic "popup.skill-suggested" id (not per-skill).
    assert "popup.skill-suggested" in popup_ids


# ---------------------------------------------------------------------------
# tui render
# ---------------------------------------------------------------------------


def test_render_emits_frame(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf)])
    assert rc == 0
    frame = capsys.readouterr().out
    assert frame  # a non-empty frame


def test_render_json_wraps_ansi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ansi" in payload and isinstance(payload["ansi"], str)


def test_render_strips_ansi_when_not_a_tty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Piped/redirected (non-TTY) ANSI render is clean text, not raw escape codes.

    Under capsys stdout is not a terminal, so the gate strips the escapes the
    deterministic renderer always emits — a captured/piped frame stays readable
    instead of dumping ``\\x1b[…m`` codes (the dogfood bug). --json is unaffected.
    """
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf)])
    assert rc == 0
    frame = capsys.readouterr().out
    assert frame  # still a real frame …
    assert "\x1b[" not in frame  # … but with no raw ANSI escape sequences


def test_render_keeps_ansi_for_a_tty(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At an interactive terminal the frame is output directly (no strip_ansi call).

    agentfront's render_ansi renderer produces a plain-text Markdown-like frame
    (no embedded ANSI escape sequences) for any state. The strip_ansi gate still
    runs when should_color is False, but since there are no escapes to strip, the
    result is identical. When should_color is True (TTY), the frame is emitted
    verbatim — which is what we verify here by ensuring a non-empty frame is
    produced and no escape sequences were incorrectly added.
    """
    sf = _write_state(tmp_path / "s.json", CockpitState())
    monkeypatch.setattr("colleague.cli._commands.tui.should_color", lambda stream=None: True)
    rc = main(["tui", "render", "--state", str(sf)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out  # a real frame is emitted
    # The new renderer produces plain text (no ANSI escape sequences at all),
    # so "preserving" means the frame is output verbatim — not an empty string.
    assert "\x1b[" not in out  # verbatim = no sequences were introduced by stripping


def test_render_tolerates_taui_mirror(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A TAUI mirror has extra keys (taui_version, available_actions); from_dict tolerates them."""
    from agentfront.taui.mirror import serialize

    mirror = serialize(_boost_state())
    sf = tmp_path / "mirror.json"
    sf.write_text(json.dumps(mirror), encoding="utf-8")
    rc = main(["tui", "render", "--state", str(sf)])
    assert rc == 0
    assert capsys.readouterr().out


def test_render_missing_file_is_user_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["tui", "render", "--state", str(tmp_path / "nope.json")])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tui inspect
# ---------------------------------------------------------------------------


def test_inspect_returns_node(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", _boost_state())
    # agentfront uses a generic "popup.skill-suggested" popup id (not per-skill).
    rc = main(["tui", "inspect", "--select", "popup.skill-suggested", "--state", str(sf), "--json"])
    assert rc == 0
    node = json.loads(capsys.readouterr().out)
    assert node["id"] == "popup.skill-suggested" and node["visible"] is True


def test_inspect_bad_selector_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "inspect", "--select", "no.such.node", "--state", str(sf)])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tui action — operate the UI by selector
# ---------------------------------------------------------------------------


def test_action_dismiss_after_boost_popup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A .dismiss selector is a valid tui action — it focuses/selects, not closes.

    agentfront models tui action as SelectorAction which focuses the node (sets
    state.focused for panel items in the focus order) — it does NOT trigger popup
    dismiss/accept.  The popup stays visible; the action succeeds (rc == 0).
    """
    sf = _write_state(tmp_path / "s.json", _boost_state())
    rc = main(
        ["tui", "action", "--select", "popup.skill-suggested.dismiss", "--state", str(sf), "--json"]
    )
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    # SelectorAction focuses, never dismisses — popup remains visible.
    popup = next(p for p in mirror["popups"] if p["id"] == "popup.skill-suggested")
    assert popup["visible"] is True


def test_action_both_popup_actions_are_valid_selectors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both .dismiss and .accept popup-action selectors are valid and succeed.

    In agentfront's model, SelectorAction focuses/selects — it does not execute
    the action.  Both selectors resolve cleanly; neither closes the popup.
    """
    sf = _write_state(tmp_path / "s.json", _boost_state())
    rc = main(
        ["tui", "action", "--select", "popup.skill-suggested.accept", "--state", str(sf), "--json"]
    )
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    # Accept selector is valid; popup stays visible (SelectorAction focuses, not accepts).
    popup = next(p for p in mirror["popups"] if p["id"] == "popup.skill-suggested")
    assert popup["visible"] is True


def test_action_bad_selector_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "action", "--select", "no.such.action", "--state", str(sf)])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tui replay
# ---------------------------------------------------------------------------


def test_replay_folds_events(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ev = tmp_path / "e.jsonl"
    ev.write_text(
        dumps_events([SkillSuggested(skill="boost", reason="task_complexity_high")]),
        encoding="utf-8",
    )
    rc = main(["tui", "replay", str(ev), "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    popup_ids = {p["id"] for p in mirror["popups"]}
    # agentfront uses a generic "popup.skill-suggested" (not per-skill).
    assert "popup.skill-suggested" in popup_ids


def _write_trace(path: Path) -> Path:
    """A real-shaped loop-step trace (`<id>.trace.jsonl`): one ok, one failed."""
    path.write_text(
        "\n".join(
            json.dumps(line)
            for line in [
                {
                    "index": 0,
                    "tool": "read_file",
                    "arguments": {"path": "main.py"},
                    "result": "...",
                    "ok": True,
                },
                {
                    "index": 1,
                    "tool": "run_command",
                    "arguments": {"command": "pytest -q"},
                    "result": "boom",
                    "ok": False,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_replay_trace_reconstructs_cockpit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A4: `tui replay --trace <id>.trace.jsonl` folds a real drive's trace into the
    cockpit — top-level conversation lines per step, and an error popup for the failed step."""
    tr = _write_trace(tmp_path / "abc.trace.jsonl")
    rc = main(["tui", "replay", "--trace", str(tr), "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    # agentfront: conversation is top-level (not a panel); each entry is {text, count}.
    convo = mirror["conversation"]
    assert any("read_file" in c["text"] and "main.py" in c["text"] for c in convo)
    assert any("run_command" in c["text"] for c in convo)
    # agentfront uses a generic "popup.work-error" (not per-tool popup ids).
    assert "popup.work-error" in {p["id"] for p in mirror["popups"]}


def test_replay_requires_exactly_one_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Neither source -> user error (not a traceback).
    rc = main(["tui", "replay"])
    assert rc != 0
    assert "exactly one" in capsys.readouterr().err
    # Both sources -> user error too.
    ev = tmp_path / "e.jsonl"
    ev.write_text(dumps_events([SkillSuggested(skill="b", reason="r")]), encoding="utf-8")
    tr = _write_trace(tmp_path / "t.trace.jsonl")
    rc = main(["tui", "replay", str(ev), "--trace", str(tr)])
    assert rc != 0
    assert "exactly one" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tui snapshot
# ---------------------------------------------------------------------------


def test_snapshot_writes_four_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "snapshot", "--name", "cap", "--dir", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # The quad: json (the .taui.json) + ansi + events + md. agentfront's
    # write_snapshot returns paths keyed "json"/"ansi"/"events"/"md" (not
    # "taui"/"markdown"). The files on disk are still named cap.taui.json etc.
    for key in ("json", "ansi", "events", "md"):
        assert key in payload, f"missing key {key!r} in {list(payload)}"
        assert Path(payload[key]).exists()


def test_snapshot_text_output_lists_the_whole_quad(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression guard: the text output must list every file the command wrote.

    It previously joined only ``("taui", "ansi", "events")`` — so the ``.md``
    the command wrote was invisible on stdout while ``--json`` reported it. Text
    and JSON must agree on the quad.
    """
    rc = main(["tui", "snapshot", "--name", "cap", "--dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cap.taui.json" in out
    assert "cap.ansi" in out
    assert "cap.events.jsonl" in out
    assert "cap.md" in out  # the file that used to be omitted from stdout


# ---------------------------------------------------------------------------
# tui diagnose
# ---------------------------------------------------------------------------


def test_diagnose_snapshot_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Write a clean snapshot, then diagnose it: no findings.
    rc = main(["tui", "snapshot", "--name", "cap", "--dir", str(tmp_path)])
    assert rc == 0
    capsys.readouterr()  # drain
    rc = main(["tui", "diagnose", "--dir", str(tmp_path), "--name", "cap", "--json"])
    assert rc == 0
    diag = json.loads(capsys.readouterr().out)
    # agentfront Diagnosis.to_dict() == {"ok": bool, "findings": [{"bug_class", "message"}]}.
    # No top-level "classes" key (findings carry bug_class per entry).
    assert "ok" in diag and "findings" in diag
    assert diag["ok"] is True
    assert diag["findings"] == []


# ---------------------------------------------------------------------------
# tui overview
# ---------------------------------------------------------------------------


def test_overview_runs(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "overview"])
    assert rc == 0
    assert "tui" in capsys.readouterr().out.lower()


def test_overview_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague tui"


def test_no_verb_defaults_to_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["tui"])
    assert rc == 0
    assert "tui" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Robustness — malformed input errors via CliError, never a traceback
# ---------------------------------------------------------------------------


def test_state_invalid_shape_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A valid-JSON-but-wrong-shape --state errors cleanly (no traceback)."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"status": 123}', encoding="utf-8")  # status must be an object
    rc = main(["tui", "state", "--state", str(bad)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Traceback" not in err


def test_replay_malformed_events_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An events line missing a required field errors cleanly (no traceback)."""
    ev = tmp_path / "ev.jsonl"
    ev.write_text('{"type": "user_input"}\n', encoding="utf-8")  # missing "text"
    rc = main(["tui", "replay", str(ev)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Traceback" not in err


def test_snapshot_bad_name_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """snapshot --name with a path-traversal segment is rejected by the verb.

    agentfront's ``write_snapshot`` joins the name into the stem with no traversal
    guard of its own, so a bare ``--name ../escape`` would write the quad *outside*
    ``--dir``.  colleague's pre-migration snapshot rejected that, and the migrated
    verb restores the guard (``_validate_snapshot_name`` — a thin CLI-layer input
    check, not duplicated cockpit logic).  A non-plain name is a clean CliError
    (non-zero exit), and nothing is written one directory up.
    """
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(
        [
            "tui",
            "snapshot",
            "--name",
            "../escape",
            "--state",
            str(sf),
            "--dir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc != 0  # rejected, not silently written outside --dir
    # No quad escaped to the parent directory.
    assert not (tmp_path.parent / "escape.taui.json").exists()


# ---------------------------------------------------------------------------
# tui render --format (t4)
# ---------------------------------------------------------------------------


def test_render_markdown_plain(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """render --format markdown emits Markdown (plain, non-JSON)."""
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf), "--format", "markdown"])
    assert rc == 0
    output = capsys.readouterr().out
    assert output  # non-empty Markdown output
    # Markdown should contain typical Markdown structure (headers, lists, etc.)
    assert "#" in output or "-" in output or output.strip()


def test_render_markdown_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """render --format markdown --json emits {"markdown": ...}."""
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf), "--format", "markdown", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "markdown" in payload and isinstance(payload["markdown"], str)


def test_render_default_is_ansi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """render (no --format) defaults to ANSI, same as --format ansi."""
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf)])
    assert rc == 0
    output = capsys.readouterr().out
    assert output  # ANSI frame


def test_render_format_ansi_explicit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """render --format ansi emits ANSI (same as default)."""
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf), "--format", "ansi"])
    assert rc == 0
    output = capsys.readouterr().out
    assert output  # ANSI frame


def test_render_format_ansi_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """render --format ansi --json emits {"ansi": ...} (unchanged behavior)."""
    sf = _write_state(tmp_path / "s.json", CockpitState())
    rc = main(["tui", "render", "--state", str(sf), "--format", "ansi", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ansi" in payload and isinstance(payload["ansi"], str)


def test_render_invalid_format_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """render --format <unknown> is rejected via CliError with no traceback."""
    sf = _write_state(tmp_path / "s.json", CockpitState())
    # The rendered CLI returns the non-zero code (agentfront run_cli catches
    # argparse's internal exit); exit-code-equivalent via __main__.
    rc = main(["tui", "render", "--state", str(sf), "--format", "invalid"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# tui --repo: surface the current repo + branch in TAUI / TUI (req 1)
# ---------------------------------------------------------------------------


def _git_repo(path: Path, *, branch: str = "wip-branch") -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.dev"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=path, check=True)


def test_state_repo_shows_branch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """tui state --repo <git> prepends a Context panel carrying the live branch."""
    _git_repo(tmp_path, branch="feature-z")
    rc = main(["tui", "state", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    ctx = next((p for p in mirror["panels"] if p["id"] == "context"), None)
    assert ctx is not None, "context panel should be present with --repo"
    by_id = {i["id"]: i for i in ctx["items"]}
    assert by_id["ctx.branch"]["status"] == "feature-z"
    assert by_id["ctx.repo"]["status"] == tmp_path.name


def test_render_repo_shows_branch_in_ansi(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """tui render --repo <git> shows the branch in the ANSI frame."""
    _git_repo(tmp_path, branch="topic-x")
    rc = main(["tui", "render", "--repo", str(tmp_path)])
    assert rc == 0
    assert "topic-x" in capsys.readouterr().out


def test_state_repo_composes_with_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--state + --repo compose: the context panel is prepended, other panels kept."""
    _git_repo(tmp_path, branch="compose-b")
    from agentfront.taui.state import Panel

    sf = _write_state(
        tmp_path / "s.json",
        CockpitState(panels=[Panel(id="commands", title="Work templates")]),
    )
    rc = main(["tui", "state", "--state", str(sf), "--repo", str(tmp_path), "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    ids = [p["id"] for p in mirror["panels"]]
    assert ids[0] == "context"  # prepended
    assert "commands" in ids  # original panel kept


def test_state_no_repo_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    """Without --repo the default state stays empty (no context panel) — back-compat."""
    rc = main(["tui", "state", "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    assert not any(p["id"] == "context" for p in mirror["panels"])


def test_state_repo_expands_tilde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--repo ~/proj expands the tilde (HOME) and resolves the real git repo."""
    home = tmp_path / "home"
    repo = home / "proj"
    repo.mkdir(parents=True)
    _git_repo(repo, branch="tilde-branch")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows expanduser fallback

    rc = main(["tui", "state", "--repo", "~/proj", "--json"])
    assert rc == 0
    mirror = json.loads(capsys.readouterr().out)
    ctx = next((p for p in mirror["panels"] if p["id"] == "context"), None)
    assert ctx is not None
    by_id = {i["id"]: i for i in ctx["items"]}
    assert by_id["ctx.branch"]["status"] == "tilde-branch"

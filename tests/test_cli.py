"""Smoke tests for the colleague CLI entry point and its verbs."""

from __future__ import annotations

import argparse
import json

import pytest

from colleague import __version__
from colleague.cli import _build_parser, main
from colleague.explain import known_paths


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_args_non_tty_prints_help(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force the non-interactive branch so this is deterministic regardless of
    # pytest's capture mode: under `pytest -s` from a real terminal stdin/stdout
    # would be TTYs and bare invocation would otherwise open the session loop
    # (and block on input()). Non-interactive must fall back to usage, preserving
    # the discoverable surface for scripts and agents.
    monkeypatch.setattr("colleague.cli._stdio_is_interactive", lambda: False)
    rc = main([])
    assert rc == 0
    assert "usage: colleague" in capsys.readouterr().out


def test_no_args_tty_opens_session(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # At an interactive terminal, bare `colleague` opens the session harness.
    # Force the interactive branch via the isolated seam, and stub input() to a
    # quit token so the session renders its palette header then exits cleanly.
    monkeypatch.setattr("colleague.cli._stdio_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "q")
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "colleague session" in out


def test_unknown_command_errors(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --- whoami ---------------------------------------------------------------


def test_whoami_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["whoami"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nick: colleague" in out
    assert "mesh backend: claude" in out
    # The drive identity — the delegate a bare drive would actually run — is the
    # trust signal an agent checks before outsourcing.
    assert "work engine:" in out
    assert "work model:" in out


def test_whoami_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["nick"] == "colleague"
    assert payload["version"] == __version__
    assert payload["backend"] == "claude"
    # Drive identity is resolved live, never the unrelated persona backend.
    assert payload["work_engine"]  # non-empty: a real engine name
    assert "work_model" in payload


def test_whoami_json_drive_identity_matches_engine_resolution(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The probe must agree with the actual drive resolution: with the mock
    # engine selected, work_engine is 'mock' and work_model is null (mock
    # calls no model — reporting a model id would be a lie).
    monkeypatch.setenv("COLLEAGUE_ENGINE", "mock")
    rc = main(["whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["work_engine"] == "mock"
    assert payload["work_model"] is None


# --- learn ----------------------------------------------------------------


def test_learn_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn"])
    assert rc == 0
    out = capsys.readouterr().out
    assert len(out) >= 200
    assert "colleague" in out
    assert "Exit-code policy" in out
    assert "--json" in out
    assert "explain" in out
    # reoriented for collaborating agents: foreground ask-colleague + work + skills.
    assert "ask-colleague" in out
    assert "work" in out
    assert ".colleague/skills/" in out
    # positively pin the new harness identity (not just the removal below).
    assert "swappable" in out
    assert "coder-agent" in out
    # per-model overlay <model> is the *sanitized* token, not the raw id — say so,
    # else an agent creates a literal .colleague/<org>/<model>/ that never loads.
    assert "filename-safe" in out
    assert "Qwen/Qwen3-32B -> Qwen-Qwen3-32B" in out
    # the "become a template" framing is intentionally gone.
    assert "clonable" not in out.lower()
    assert "scaffold" not in out.lower()
    # mirror the CI `afi rubric gate` learnability markers so a missing one
    # fails here (locally) before it fails in CI.
    low = out.lower()
    for marker in ("purpose", "commands", "exit", "--json", "explain"):
        assert marker in low, f"learn output missing rubric marker: {marker}"


def test_learn_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "colleague"
    assert payload["version"] == __version__
    assert payload["json_support"] is True
    # collaboration + skills guidance are first-class in the payload.
    assert "work_with" in payload
    assert "teach_with_skills" in payload
    assert payload["work_with"]["verbs"][0]["verb"].startswith("ask-colleague")
    # the overlay <model> placeholder is documented as sanitized in the payload too.
    assert "filename-safe" in payload["teach_with_skills"]["model_placeholder"]


# --- explain --------------------------------------------------------------


def test_explain_root(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain"])
    assert rc == 0
    assert "# colleague" in capsys.readouterr().out


def test_explain_self(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "colleague"])
    assert rc == 0
    assert capsys.readouterr().out.startswith("#")


def test_explain_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"] == ["whoami"]
    assert "colleague whoami" in payload["markdown"]


def test_explain_unknown_path_errors(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "nonexistent"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "hint:" in captured.err


def test_every_catalog_path_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    for path in known_paths():
        rc = main(["explain", *path])
        assert rc == 0, f"explain {' '.join(path)} failed"
        capsys.readouterr()


def test_explain_root_hints_topic_arg(capsys: pytest.CaptureFixture[str]) -> None:
    """Bare `explain` tells a new user the per-topic form exists; --json stays raw."""
    assert main(["explain"]) == 0
    assert "colleague explain <topic>" in capsys.readouterr().out

    assert main(["explain", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # The machine contract is the raw catalog markdown — no human tip injected.
    assert "colleague explain <topic>" not in payload["markdown"]


# --- quickstart -----------------------------------------------------------


def test_quickstart_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["quickstart"]) == 0
    out = capsys.readouterr().out
    assert "# colleague quickstart" in out  # the markdown heading, not just the word
    # The ordered first-run path is present.
    assert "colleague doctor" in out
    assert "colleague backends list" in out


def test_quickstart_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["quickstart", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"]
    assert all({"title", "command", "why"} <= set(s) for s in payload["steps"])


# --- small UX tweaks (from the dogfood) -----------------------------------


def test_backends_list_has_header(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["backends", "list"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "NAME\tTARGET"
    assert "mock" in out


def test_config_show_no_file_is_explicit(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "show", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "config_file: (none" in out  # explicit, not a bare "none"


def _subparsers_action(parser: argparse.ArgumentParser):
    """The parser's ``_SubParsersAction`` (its sub-commands), or ``None`` if it has none."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def test_every_verb_has_explain_and_action_nouns_have_overview() -> None:
    """Reverse-coverage of the explain catalog (the agent-first rubric): every
    registered CLI verb must have an ``explain`` entry, and every *action-noun*
    (a verb that has its own sub-actions, e.g. ``commands`` / ``hooks`` / ``tui``)
    must expose an ``overview`` sub-action and carry catalog entries for both the
    noun and ``<noun> overview``. Guards against a new verb/noun shipping
    undocumented — the existing test only checks the catalog is self-consistent."""
    catalog = set(known_paths())
    top = _subparsers_action(_build_parser())
    assert top is not None, "the CLI must register sub-commands"

    for verb, verb_parser in top.choices.items():
        assert (verb,) in catalog, f"CLI verb {verb!r} has no `explain {verb}` entry"

        noun = _subparsers_action(verb_parser)
        if noun is None:
            continue  # a leaf verb (drive, session, doctor, …) needs no overview
        assert "overview" in noun.choices, f"action-noun {verb!r} must expose `overview`"
        assert (verb, "overview") in catalog, f"missing `explain {verb} overview` entry"

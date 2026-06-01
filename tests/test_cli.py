"""Smoke tests for the convertible CLI entry point and its verbs."""

from __future__ import annotations

import argparse
import json

import pytest

from convertible import __version__
from convertible.cli import _build_parser, main
from convertible.explain import known_paths


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
    monkeypatch.setattr("convertible.cli._stdio_is_interactive", lambda: False)
    rc = main([])
    assert rc == 0
    assert "usage: convertible" in capsys.readouterr().out


def test_no_args_tty_opens_session(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # At an interactive terminal, bare `convertible` opens the session harness.
    # Force the interactive branch via the isolated seam, and stub input() to a
    # quit token so the session renders its palette header then exits cleanly.
    monkeypatch.setattr("convertible.cli._stdio_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "q")
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "convertible session" in out


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
    assert "nick: convertible" in out
    assert "backend: claude" in out
    assert "model:" in out


def test_whoami_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["nick"] == "convertible"
    assert payload["version"] == __version__
    assert payload["backend"] == "claude"


# --- learn ----------------------------------------------------------------


def test_learn_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn"])
    assert rc == 0
    out = capsys.readouterr().out
    assert len(out) >= 200
    assert "convertible" in out
    assert "Exit-code policy" in out
    assert "--json" in out
    assert "explain" in out


def test_learn_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "convertible"
    assert payload["version"] == __version__
    assert payload["json_support"] is True


# --- explain --------------------------------------------------------------


def test_explain_root(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain"])
    assert rc == 0
    assert "# convertible" in capsys.readouterr().out


def test_explain_self(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "convertible"])
    assert rc == 0
    assert capsys.readouterr().out.startswith("#")


def test_explain_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"] == ["whoami"]
    assert "convertible whoami" in payload["markdown"]


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

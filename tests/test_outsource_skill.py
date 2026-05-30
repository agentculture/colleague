"""Offline guards for the `outsource` skill (no live model).

These exercise the parts of the skill that do NOT invoke a drive: the prompt
templates render, the wrapper resolves verbs/flags, and the error paths exit
before `resolve_convertible` is ever reached. The live 27B behavior is proven by
dogfooding, not in CI.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "outsource"
SCRIPT = SKILL / "scripts" / "outsource.sh"
PROMPTS = SKILL / "prompts"

VERBS = ("explore", "review", "write")


def _render(name: str, arg: str, base: str) -> str:
    """Mirror the wrapper's render_prompt substitution."""
    tpl = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    return tpl.replace("$ARGUMENTS", arg).replace("$BASE", base)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def test_skill_layout_exists() -> None:
    assert (SKILL / "SKILL.md").is_file()
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK), "outsource.sh must be executable"
    for verb in VERBS:
        assert (PROMPTS / f"{verb}.md").is_file(), f"missing prompt: {verb}.md"


@pytest.mark.parametrize("name", VERBS)
def test_prompt_renders_arguments(name: str) -> None:
    out = _render(name, "INVESTIGATE_ME", "trunk")
    assert "INVESTIGATE_ME" in out
    assert "$ARGUMENTS" not in out


@pytest.mark.parametrize("name", ["explore", "review"])
def test_readonly_prompts_carry_a_guard(name: str) -> None:
    out = _render(name, "x", "main").lower()
    assert "read-only" in out
    assert "do not" in out and "modify" in out


def test_review_prompt_uses_the_base_diff() -> None:
    out = _render("review", "x", "develop")
    assert "develop...HEAD" in out
    assert "$BASE" not in out


def test_help_lists_the_verbs() -> None:
    r = _run("--help")
    assert r.returncode == 0
    for verb in VERBS:
        assert verb in r.stdout


def test_help_documents_the_default_model() -> None:
    r = _run("--help")
    assert "mmangkad/Qwen3.6-27B-NVFP4" in r.stdout


def test_unknown_verb_errors_with_hint() -> None:
    r = _run("frobnicate", "x")
    assert r.returncode == 2
    assert "unknown verb" in r.stderr


def test_no_args_errors() -> None:
    r = _run()
    assert r.returncode == 2


def test_missing_description_errors() -> None:
    r = _run("explore")
    assert r.returncode == 2
    assert "needs a description" in r.stderr


def test_wrapper_prints_drive_summary_with_a_fake_convertible(tmp_path) -> None:
    """End-to-end wrapper path (resolve -> render -> drive -> print_result) with a
    stubbed `convertible` that echoes a canned TaskResult. Guards the result
    extraction (in particular: print_result must read the piped JSON from stdin,
    not have it shadowed by a heredoc)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "convertible"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "echo '{\"status\": \"ok\", \"summary\": \"FAKE_SUMMARY_OK\", "
        '"changed_files": ["x.py"], "branch": "convertible/abc123"}\'\n'
    )
    fake.chmod(0o755)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo)],
        capture_output=True, text=True, env=env, check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "FAKE_SUMMARY_OK" in r.stdout
    assert "x.py" in r.stdout
    assert "convertible/abc123" in r.stdout

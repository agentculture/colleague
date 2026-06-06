"""``colleague learn-from`` — CLI verb, session slash, and stage-2 (mock) tests.

The deterministic adapter core is covered in ``tests/test_learn_from.py``; this
file exercises the CLI surface (``from colleague.cli import main``), the
``/learn-from`` session slash, and the stage-2 LLM adapt pass via the offline
``mock`` backend (the contract reference).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from colleague.cli import main
from colleague.cli._commands.session import run_session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKILL = "---\nname: foo\ndescription: Foo skill summary\n---\n# Foo\nFoo body.\n"


def _make_skill_file(repo: Path, name: str, text: str = _SKILL) -> Path:
    skill_dir = repo / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return skill_dir / "SKILL.md"


def _dest(repo: Path, name: str) -> Path:
    return repo / ".colleague" / "skills" / f"{name}.md"


def _session_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=True,
    )


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
# CLI verb — stage 1 (copy-only / dry-run)
# ---------------------------------------------------------------------------


def test_dry_run_json_discovers_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_skill_file(tmp_path, "foo")
    rc = main(["learn-from", "claude", "--repo", str(tmp_path), "--dry-run", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "claude"
    assert payload["dry_run"] is True
    assert payload["skills"][0]["name"] == "foo"
    assert payload["skills"][0]["action"] == "would-create"
    assert payload["stage2"]["ran"] is False
    assert not _dest(tmp_path, "foo").exists()


def test_copy_only_creates_and_is_loadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_skill_file(tmp_path, "foo")
    rc = main(["learn-from", "claude", "--repo", str(tmp_path), "--copy-only", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skills"][0]["action"] == "created"
    assert payload["stage2"]["ran"] is False  # copy-only skips stage 2

    dest = _dest(tmp_path, "foo")
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert "<!-- learned-from:" in text
    assert "adapt: pending" in text
    # The adapted doc's catalog summary is the source description.
    from colleague.layers import _first_summary_line

    assert _first_summary_line(text) == "Foo skill summary"


def test_idempotent_second_run_skips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_skill_file(tmp_path, "foo")
    main(["learn-from", "claude", "--repo", str(tmp_path), "--copy-only"])
    capsys.readouterr()
    rc = main(["learn-from", "claude", "--repo", str(tmp_path), "--copy-only", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skills"][0]["action"] == "skipped"


def test_force_updates_colleague_owned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_skill_file(tmp_path, "foo")
    main(["learn-from", "claude", "--repo", str(tmp_path), "--copy-only"])
    dest = _dest(tmp_path, "foo")
    dest.write_text(dest.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    capsys.readouterr()
    rc = main(["learn-from", "claude", "--repo", str(tmp_path), "--copy-only", "--force", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skills"][0]["action"] == "updated"


def test_hand_authored_is_protected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_skill_file(tmp_path, "foo")
    dest = _dest(tmp_path, "foo")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("# hand authored, no marker\n", encoding="utf-8")
    rc = main(["learn-from", "claude", "--repo", str(tmp_path), "--copy-only", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skills"][0]["action"] == "protected"
    # The hand-authored content is left intact.
    assert dest.read_text(encoding="utf-8") == "# hand authored, no marker\n"


def test_name_filter_and_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_skill_file(tmp_path, "foo")
    _make_skill_file(tmp_path, "bar")
    rc = main(
        ["learn-from", "claude", "foo", "missing", "--repo", str(tmp_path), "--copy-only", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    actions = {s["name"]: s["action"] for s in payload["skills"]}
    assert actions["foo"] == "created"
    assert actions["missing"] == "not-found"
    assert "bar" not in actions  # filtered out
    assert not _dest(tmp_path, "bar").exists()


def test_unknown_source_is_user_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn-from", "codex", "--repo", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown source" in err
    assert "claude" in err  # remediation lists known sources


def test_missing_repo_is_user_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn-from", "claude", "--repo", "/no/such/repo/here"])
    assert rc == 1
    assert "not a directory" in capsys.readouterr().err


def test_no_claude_skills_is_clean_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["learn-from", "claude", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to learn" in out


def test_round_trip_skills_list_sees_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """After learn-from, `colleague skills list` resolves the adapted skill."""
    _make_skill_file(tmp_path, "foo")
    main(["learn-from", "claude", "--repo", str(tmp_path), "--copy-only"])
    capsys.readouterr()
    rc = main(["skills", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    names = [s["name"] for s in payload["skills"]]
    assert "foo" in names


# ---------------------------------------------------------------------------
# Stage 2 — LLM adapt via the offline mock backend
# ---------------------------------------------------------------------------


def test_stage2_runs_via_mock_and_marks_adapted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_skill_file(tmp_path, "foo")
    rc = main(["learn-from", "claude", "--repo", str(tmp_path), "--engine", "mock", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage2"]["ran"] is True
    assert payload["stage2"]["engine"] == "mock"
    assert "foo" in payload["stage2"]["adapted"]
    # The deterministic post-adapt stamp flips the marker.
    text = _dest(tmp_path, "foo").read_text(encoding="utf-8")
    assert "adapt: claude->colleague" in text
    assert "adapt: pending" not in text


# ---------------------------------------------------------------------------
# Session slash — /learn-from
# ---------------------------------------------------------------------------


def test_session_slash_learn_from_creates_skill(tmp_path: Path) -> None:
    _make_skill_file(tmp_path, "foo")
    out = _CollectingOut()
    rc = run_session(
        _session_args(tmp_path),
        input_fn=iter(["/learn-from claude", "q"]),
        out=out,
        _color=False,
    )
    assert rc == 0
    # The in-session slash runs the deterministic copy (copy-only).
    assert _dest(tmp_path, "foo").exists()


def test_session_slash_learn_from_dry_run_writes_nothing(tmp_path: Path) -> None:
    _make_skill_file(tmp_path, "foo")
    out = _CollectingOut()
    rc = run_session(
        _session_args(tmp_path),
        input_fn=iter(["/learn-from claude --dry-run", "q"]),
        out=out,
        _color=False,
    )
    assert rc == 0
    assert not _dest(tmp_path, "foo").exists()

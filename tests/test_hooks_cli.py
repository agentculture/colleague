"""``colleague hooks`` CLI noun group — list and overview (t6) + per-model (t5).

Acceptance criteria (original, t6):
1. ``colleague hooks list --json`` emits structured JSON with a ``hooks`` key.
2. ``colleague hooks overview`` exits 0 and describes the noun.
3. ``colleague hooks overview --json`` has the expected subject.
4. Bare ``colleague hooks`` falls back to overview (non-empty output, exit 0).

Acceptance criteria (t5 — per-model --model option):
5. ``colleague hooks list --model X --json`` lists per-model entries before base
   entries, each tagged with a ``scope`` key (``per-model`` or ``base``).
6. ``colleague hooks list`` (no ``--model``) is byte-identical to today — JSON
   output unchanged, no ``scope`` key injected.
7. ``colleague explain hooks`` documents the per-model overlay path and
   per-model-first precedence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main


def _make_hooks_json(repo: Path, hooks: dict) -> None:
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(hooks))


# ---------------------------------------------------------------------------
# hooks list
# ---------------------------------------------------------------------------


def test_hooks_list_json_empty_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Empty repo → empty list, valid JSON shape."""
    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "hooks" in payload
    assert isinstance(payload["hooks"], list)


def test_hooks_list_json_with_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Repo with configured hooks → list contains those hooks."""
    _make_hooks_json(
        tmp_path,
        {
            "hooks": {
                "pre_tool": [{"matcher": "run_command", "command": "echo pre"}],
                "finish": [{"command": "echo done"}],
            }
        },
    )
    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["hooks"]) == 2
    events = [h["event"] for h in payload["hooks"]]
    assert "pre_tool" in events
    assert "finish" in events


def test_hooks_list_json_entry_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Each entry has ``event``, ``matcher``, and ``command`` keys."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo hi"}]}},
    )
    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["hooks"]) == 1
    entry = payload["hooks"][0]
    assert entry["event"] == "pre_tool"
    assert entry["matcher"] == "run_command"
    assert entry["command"] == "echo hi"


def test_hooks_list_text_no_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Text mode with no hooks emits a notice to stdout, exit 0."""
    rc = main(["hooks", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()  # not empty


def test_hooks_list_text_with_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Text mode with hooks includes the event name in output."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"task_start": [{"command": "echo start"}]}},
    )
    rc = main(["hooks", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "task_start" in out


# ---------------------------------------------------------------------------
# hooks overview
# ---------------------------------------------------------------------------


def test_hooks_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["hooks", "overview"])
    assert rc == 0
    assert "colleague hooks" in capsys.readouterr().out


def test_hooks_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["hooks", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague hooks"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_hooks_bare_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    """Bare 'colleague hooks' (no sub-verb) should print an overview."""
    rc = main(["hooks"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


# ---------------------------------------------------------------------------
# t5: hooks list --model <m>
# ---------------------------------------------------------------------------


def _make_per_model_hooks_json(repo: Path, model_slug: str, hooks: dict) -> None:
    """Write a per-model hooks.json under .colleague/<model_slug>/hooks.json."""
    dotdir = repo / ".colleague" / model_slug
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(hooks))


def test_hooks_list_model_json_per_model_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--model X: per-model entries appear before base entries; scope tags present."""
    # Base hooks
    _make_hooks_json(
        tmp_path,
        {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo base"}]}},
    )
    # Per-model hooks for model "mymodel"
    _make_per_model_hooks_json(
        tmp_path,
        "mymodel",
        {"hooks": {"pre_tool": [{"matcher": "write_file", "command": "echo model"}]}},
    )

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--model", "mymodel", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    hooks = payload["hooks"]
    assert len(hooks) == 2  # 1 per-model + 1 base

    # Per-model entry is first
    assert hooks[0]["scope"] == "per-model"
    assert hooks[0]["command"] == "echo model"
    assert hooks[0]["event"] == "pre_tool"

    # Base entry is second
    assert hooks[1]["scope"] == "base"
    assert hooks[1]["command"] == "echo base"
    assert hooks[1]["event"] == "pre_tool"


def test_hooks_list_model_scope_tags_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every entry in --model output has a ``scope`` key."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"finish": [{"command": "echo done"}]}},
    )
    _make_per_model_hooks_json(
        tmp_path,
        "somemodel",
        {"hooks": {"task_start": [{"command": "echo start"}]}},
    )

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--model", "somemodel", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    for entry in payload["hooks"]:
        assert "scope" in entry, f"Missing scope on {entry}"
        assert entry["scope"] in ("per-model", "base")


def test_hooks_list_model_base_only_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--model X with no per-model file: all entries get scope=base."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"finish": [{"command": "echo done"}]}},
    )

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--model", "unknown-model", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    assert len(payload["hooks"]) == 1
    assert payload["hooks"][0]["scope"] == "base"


def test_hooks_list_no_model_no_scope_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --model, JSON output has NO ``scope`` key (byte-identical to today)."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo pre"}]}},
    )

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    assert "hooks" in payload
    for entry in payload["hooks"]:
        assert "scope" not in entry, "scope must not appear when --model is omitted"


def test_hooks_list_model_text_mode_shows_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--model in text mode: output includes per-model label."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"finish": [{"command": "echo done"}]}},
    )
    _make_per_model_hooks_json(
        tmp_path,
        "mymodel",
        {"hooks": {"finish": [{"command": "echo override"}]}},
    )

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--model", "mymodel"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "per-model" in out
    assert "base" in out


def test_hooks_list_model_sanitized_slug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Model names with / or special chars are sanitized to the right directory."""
    from colleague.layers import sanitize_model

    model = "Qwen/Qwen3-32B"
    slug = sanitize_model(model)

    _make_per_model_hooks_json(
        tmp_path,
        slug,
        {"hooks": {"task_start": [{"command": "echo qwen"}]}},
    )

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--model", model, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    assert any(e["scope"] == "per-model" for e in payload["hooks"])


# ---------------------------------------------------------------------------
# t5: explain hooks documents per-model overlay
# ---------------------------------------------------------------------------


def test_explain_hooks_documents_per_model_overlay(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``colleague explain hooks`` mentions the per-model overlay path and precedence."""
    rc = main(["explain", "hooks"])
    assert rc == 0
    out = capsys.readouterr().out
    # Must mention the per-model overlay path pattern
    assert ".colleague/<model>/hooks.json" in out
    # Must mention per-model-first precedence
    assert "per-model" in out.lower()

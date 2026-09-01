"""Tests for colleague/samplingfile.py — tracked models.json loader (t3).

Acceptance criteria (verbatim from the confirmed plan):
1. colleague/samplingfile.py reads .colleague/models.json across configdir
   roots; a missing or malformed file is a clean no-op, never a refusal.
2. Merge granularity is per model key, so a repo-level file naming one model
   does not erase a user-level row for a different model — asserted with
   both files present.
3. colleague/artifact.py's auto-written .gitignore allow-lists models.json
   beside commands/ and skills/, asserted against a freshly written file.
4. A work item dispatched into a throwaway worktree resolves the operator
   repo's declared rows, asserted by a test that runs one in a worktree.
5. An operator config predating this arc resolves to the same values it does
   today.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from colleague.artifact import failed_result, write
from colleague.samplingfile import load_models_file
from colleague.worktrees import worktree_add


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Criterion 1: missing / malformed is a clean no-op, never a refusal.
# ---------------------------------------------------------------------------


def test_missing_file_is_empty_no_op(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()

    assert load_models_file(repo, user_home=user_home) == {}


def test_malformed_json_is_clean_no_op(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()

    _write_json(repo / ".colleague" / "models.json", {})  # placeholder for perms
    (repo / ".colleague" / "models.json").write_text("{not valid json", encoding="utf-8")

    assert load_models_file(repo, user_home=user_home) == {}


def test_non_object_top_level_is_clean_no_op(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()

    _write_json(repo / ".colleague" / "models.json", [])  # a JSON array, not object

    assert load_models_file(repo, user_home=user_home) == {}


def test_malformed_single_model_row_is_skipped_others_kept(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()

    _write_json(
        repo / ".colleague" / "models.json",
        {
            "good-model": {"thinking": {"temperature": 1.0}},
            "bad-model": "not-an-object",
        },
    )

    result = load_models_file(repo, user_home=user_home)
    assert result == {"good-model": {"thinking": {"temperature": 1.0}}}


# ---------------------------------------------------------------------------
# Criterion 2: merge granularity is PER MODEL KEY.
# ---------------------------------------------------------------------------


def test_merge_granularity_is_per_model_key(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()

    # Repo-level file names only "model-a".
    _write_json(
        repo / ".colleague" / "models.json",
        {"model-a": {"thinking": {"temperature": 1.0, "top_p": 0.95}}},
    )
    # User-level file names only "model-b" (a DIFFERENT model).
    _write_json(
        user_home / ".colleague" / "models.json",
        {"model-b": {"default": {"temperature": 0.6}}},
    )

    result = load_models_file(repo, user_home=user_home)

    # Both rows survive the merge — the repo file naming model-a did not
    # erase the user-level row for model-b.
    assert result == {
        "model-a": {"thinking": {"temperature": 1.0, "top_p": 0.95}},
        "model-b": {"default": {"temperature": 0.6}},
    }


def test_repo_model_entry_wins_over_user_for_same_model(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()

    _write_json(
        repo / ".colleague" / "models.json",
        {"shared-model": {"thinking": {"temperature": 1.0}}},
    )
    _write_json(
        user_home / ".colleague" / "models.json",
        {"shared-model": {"thinking": {"temperature": 0.0}}},
    )

    result = load_models_file(repo, user_home=user_home)
    assert result == {"shared-model": {"thinking": {"temperature": 1.0}}}


# ---------------------------------------------------------------------------
# Criterion 3: artifact.py's self-written .gitignore allow-lists models.json.
# ---------------------------------------------------------------------------


def test_self_ignore_gitignore_allow_lists_models_json(tmp_path: Path) -> None:
    out = tmp_path / ".colleague"
    write(failed_result("t1", "boom"), out)
    lines = (out / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "!models.json" in lines
    assert "!commands/" in lines
    assert "!skills/" in lines


# ---------------------------------------------------------------------------
# Criterion 4: a work item dispatched into a throwaway worktree resolves the
# operator repo's declared rows.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture()
def git_repo_with_models_json(tmp_path: Path) -> Path:
    """A git repo with an initial commit that TRACKS .colleague/models.json."""
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")

    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _write_json(
        repo / ".colleague" / "models.json",
        {"operator-model": {"thinking": {"temperature": 1.0, "top_k": 20}}},
    )

    _git(repo, "add", "README.md", ".colleague/models.json")
    _git(repo, "commit", "-m", "init")
    return repo


def test_worktree_resolves_operator_repo_declared_rows(
    git_repo_with_models_json: Path, tmp_path: Path
) -> None:
    user_home = tmp_path / "home"
    user_home.mkdir()

    wt_path = worktree_add(str(git_repo_with_models_json), "t3-worktree-check")

    # models.json is a TRACKED file — a work item's throwaway worktree at HEAD
    # carries it along, unlike the (gitignored) rest of .colleague/.
    assert (Path(wt_path) / ".colleague" / "models.json").is_file()

    result = load_models_file(wt_path, user_home=user_home)
    assert result == {"operator-model": {"thinking": {"temperature": 1.0, "top_k": 20}}}


# ---------------------------------------------------------------------------
# Criterion 5: a pre-arc operator config (no models.json at all) resolves to
# the same (empty) values it does today.
# ---------------------------------------------------------------------------


def test_repo_predating_arc_resolves_to_empty_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".colleague").mkdir()
    (repo / ".colleague" / "config.json").write_text(
        json.dumps({"model": "some-model"}), encoding="utf-8"
    )
    user_home = tmp_path / "home"
    user_home.mkdir()

    # No models.json anywhere — a repo that predates this arc.
    assert load_models_file(repo, user_home=user_home) == {}

"""Tests for the shared hook key-derivation helpers in ``convertible.hooks``.

``referenced_repo_files`` is the single source of truth that enforcement, the
``hooks approve`` verb, and the ``hooks list`` display all use to map a hook
command (or a script path) to canonical repo-relative approval keys — so an
approval written by one is recognised by the others.
"""

from __future__ import annotations

from convertible.hooks import canonical_hook_key, referenced_repo_files


def test_referenced_repo_files_finds_existing_file(tmp_path):
    script = tmp_path / "scripts" / "lint.sh"
    script.parent.mkdir(parents=True)
    script.write_text("echo")
    refs = referenced_repo_files("bash scripts/lint.sh --fix", tmp_path)
    assert [rel for rel, _ in refs] == ["scripts/lint.sh"]
    assert refs[0][1] == script.resolve()


def test_referenced_repo_files_normalizes_dot_slash(tmp_path):
    script = tmp_path / "lint.sh"
    script.write_text("echo")
    refs = referenced_repo_files("./lint.sh", tmp_path)
    assert [rel for rel, _ in refs] == ["lint.sh"]  # canonical, no leading ./


def test_referenced_repo_files_skips_nonfiles_and_flags(tmp_path):
    assert referenced_repo_files("echo hello --flag", tmp_path) == []


def test_referenced_repo_files_skips_outside_repo(tmp_path):
    outside = tmp_path.parent / "outside.sh"
    outside.write_text("echo")
    try:
        # An absolute path outside the repo root is not a repo-file reference.
        assert referenced_repo_files(f"bash {outside}", tmp_path) == []
    finally:
        outside.unlink()


def test_referenced_repo_files_shlex_error_is_empty(tmp_path):
    assert referenced_repo_files('echo "unbalanced', tmp_path) == []


def test_canonical_hook_key_normalizes(tmp_path):
    assert canonical_hook_key(tmp_path, "./scripts/lint.sh") == "scripts/lint.sh"
    assert canonical_hook_key(tmp_path, "lint.sh") == "lint.sh"


def test_canonical_hook_key_rejects_escape(tmp_path):
    assert canonical_hook_key(tmp_path / "repo", "../outside.sh") is None

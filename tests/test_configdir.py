"""Config directory loader: resolve .convertible/ at repo and user levels (t1).

Tests the module-level API:
- USER_CONFIG_DIR constant
- config_roots(repo_path, *, user_home=None) -> list[Path]
- resolve_file(repo_path, relative, *, user_home=None) -> Path | None
- collect_files(repo_path, subdir, *, suffix="", user_home=None) -> dict[str, Path]

Acceptance:
1. Repo-level .convertible/ shadows user-level entries by name.
2. Absent .convertible/ returns empty results, never raises.
"""

from __future__ import annotations

from pathlib import Path

from convertible.configdir import USER_CONFIG_DIR, collect_files, config_roots, resolve_file


def test_user_config_dir_constant() -> None:
    """USER_CONFIG_DIR is Path.home() / '.convertible'."""
    assert USER_CONFIG_DIR == Path.home() / ".convertible"


def test_config_roots_both_present_repo_first(tmp_path) -> None:
    """With both repo and user .convertible/, config_roots returns repo then user."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()
    user_config = user_home / ".convertible"
    user_config.mkdir()

    roots = config_roots(repo_path, user_home=user_home)
    assert roots == [repo_config, user_config]


def test_config_roots_repo_only(tmp_path) -> None:
    """With only repo .convertible/, config_roots returns just the repo one."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()

    roots = config_roots(repo_path, user_home=user_home)
    assert roots == [repo_config]


def test_config_roots_user_only(tmp_path) -> None:
    """With only user .convertible/, config_roots returns just the user one."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()
    user_config = user_home / ".convertible"
    user_config.mkdir()

    roots = config_roots(repo_path, user_home=user_home)
    assert roots == [user_config]


def test_config_roots_neither_present(tmp_path) -> None:
    """With neither repo nor user .convertible/, config_roots returns empty list."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()

    roots = config_roots(repo_path, user_home=user_home)
    assert roots == []


def test_config_roots_repo_not_dir_ignored(tmp_path) -> None:
    """If repo .convertible/ is not a directory, it's excluded."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".convertible").touch()  # file, not dir

    user_home = tmp_path / "home"
    user_home.mkdir()
    user_config = user_home / ".convertible"
    user_config.mkdir()

    roots = config_roots(repo_path, user_home=user_home)
    assert roots == [user_config]


def test_resolve_file_from_repo(tmp_path) -> None:
    """resolve_file finds a file in repo .convertible/ first."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()
    repo_file = repo_config / "commands"
    repo_file.mkdir()
    (repo_file / "test.txt").write_text("repo")

    user_home = tmp_path / "home"
    user_home.mkdir()
    user_config = user_home / ".convertible"
    user_config.mkdir()
    user_file = user_config / "commands"
    user_file.mkdir()
    (user_file / "test.txt").write_text("user")

    result = resolve_file(repo_path, "commands/test.txt", user_home=user_home)
    assert result == repo_file / "test.txt"
    assert result.read_text() == "repo"


def test_resolve_file_from_user_when_repo_absent(tmp_path) -> None:
    """resolve_file falls back to user .convertible/ if repo doesn't have the file."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()
    user_config = user_home / ".convertible"
    user_config.mkdir()
    user_file = user_config / "commands"
    user_file.mkdir()
    (user_file / "test.txt").write_text("user")

    result = resolve_file(repo_path, "commands/test.txt", user_home=user_home)
    assert result == user_file / "test.txt"
    assert result.read_text() == "user"


def test_resolve_file_not_found_returns_none(tmp_path) -> None:
    """resolve_file returns None if the file exists nowhere."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()

    result = resolve_file(repo_path, "commands/missing.txt", user_home=user_home)
    assert result is None


def test_resolve_file_no_config_dirs_returns_none(tmp_path) -> None:
    """resolve_file returns None if no .convertible/ directories exist."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()

    result = resolve_file(repo_path, "commands/test.txt", user_home=user_home)
    assert result is None


def test_collect_files_repo_shadows_user(tmp_path) -> None:
    """collect_files shadows user-level files with repo-level ones by stem."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()
    repo_cmds = repo_config / "commands"
    repo_cmds.mkdir()
    (repo_cmds / "cmd1.txt").write_text("repo1")
    (repo_cmds / "shared.txt").write_text("repo_shared")

    user_home = tmp_path / "home"
    user_home.mkdir()
    user_config = user_home / ".convertible"
    user_config.mkdir()
    user_cmds = user_config / "commands"
    user_cmds.mkdir()
    (user_cmds / "cmd2.txt").write_text("user2")
    (user_cmds / "shared.txt").write_text("user_shared")

    result = collect_files(repo_path, "commands", user_home=user_home)
    # Should have all three stems, but 'shared' points to repo version
    assert set(result.keys()) == {"cmd1", "cmd2", "shared"}
    assert result["cmd1"].read_text() == "repo1"
    assert result["cmd2"].read_text() == "user2"
    assert result["shared"].read_text() == "repo_shared"


def test_collect_files_no_suffix(tmp_path) -> None:
    """collect_files without suffix filters all files."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()
    repo_cmds = repo_config / "commands"
    repo_cmds.mkdir()
    (repo_cmds / "cmd1.txt").write_text("1")
    (repo_cmds / "cmd2.json").write_text("2")
    (repo_cmds / "cmd3").write_text("3")

    user_home = tmp_path / "home"
    user_home.mkdir()

    result = collect_files(repo_path, "commands", user_home=user_home)
    assert set(result.keys()) == {"cmd1", "cmd2", "cmd3"}


def test_collect_files_with_suffix_filter(tmp_path) -> None:
    """collect_files filters by suffix when provided."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()
    repo_cmds = repo_config / "commands"
    repo_cmds.mkdir()
    (repo_cmds / "cmd1.txt").write_text("1")
    (repo_cmds / "cmd2.json").write_text("2")
    (repo_cmds / "cmd3.txt").write_text("3")

    user_home = tmp_path / "home"
    user_home.mkdir()

    result = collect_files(repo_path, "commands", suffix=".txt", user_home=user_home)
    assert set(result.keys()) == {"cmd1", "cmd3"}
    assert result["cmd1"].read_text() == "1"
    assert result["cmd3"].read_text() == "3"


def test_collect_files_empty_when_subdir_absent(tmp_path) -> None:
    """collect_files returns {} if the subdir doesn't exist anywhere."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()

    result = collect_files(repo_path, "commands", user_home=user_home)
    assert result == {}


def test_collect_files_no_config_dirs(tmp_path) -> None:
    """collect_files returns {} if no .convertible/ directories exist."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    user_home = tmp_path / "home"
    user_home.mkdir()

    result = collect_files(repo_path, "commands", user_home=user_home)
    assert result == {}


def test_collect_files_only_direct_children(tmp_path) -> None:
    """collect_files only includes direct children of subdir, not nested files."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo_config = repo_path / ".convertible"
    repo_config.mkdir()
    repo_cmds = repo_config / "commands"
    repo_cmds.mkdir()
    (repo_cmds / "cmd1.txt").write_text("1")
    nested = repo_cmds / "nested"
    nested.mkdir()
    (nested / "cmd2.txt").write_text("2")

    user_home = tmp_path / "home"
    user_home.mkdir()

    result = collect_files(repo_path, "commands", user_home=user_home)
    assert set(result.keys()) == {"cmd1"}

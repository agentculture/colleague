"""Tests for colleague/roles — typed-subagent role model, built-ins, and loader."""

from __future__ import annotations

import pytest

from colleague.roles import BUILTIN_ROLES, Role, default_role, load_role

# ---------------------------------------------------------------------------
# AC1: Role dataclass fields + five built-in roles
# ---------------------------------------------------------------------------


class TestRoleDataclass:
    def test_role_fields(self) -> None:
        role = Role(
            name="test",
            prompt_fragment="prompt",
            tool_allowlist=("read_file",),
            skill_subset=("skill_a",),
            read_only=True,
        )
        assert role.name == "test"
        assert role.prompt_fragment == "prompt"
        assert role.tool_allowlist == ("read_file",)
        assert role.skill_subset == ("skill_a",)
        assert role.read_only is True

    def test_role_frozen(self) -> None:
        role = Role(
            name="test",
            prompt_fragment="p",
            tool_allowlist=(),
            skill_subset=None,
            read_only=False,
        )
        with pytest.raises(Exception):
            role.name = "other"  # type: ignore[misc]

    def test_builtin_roles_count(self) -> None:
        assert len(BUILTIN_ROLES) == 5

    def test_builtin_role_names(self) -> None:
        expected = {"explorer", "planner", "reviewer", "validator", "writer"}
        assert set(BUILTIN_ROLES.keys()) == expected

    def test_builtin_roles_are_role_instances(self) -> None:
        for role in BUILTIN_ROLES.values():
            assert isinstance(role, Role)


# ---------------------------------------------------------------------------
# AC2: Read-only roles exclude write tools
# ---------------------------------------------------------------------------


class TestReadOnlyRoles:
    _READONLY_NAMES = ("explorer", "planner", "reviewer", "validator")
    _WRITE_TOOLS = {"write_file", "edit_file", "run_command"}

    @pytest.mark.parametrize("role_name", _READONLY_NAMES)
    def test_read_only_flag(self, role_name: str) -> None:
        role = BUILTIN_ROLES[role_name]
        assert role.read_only is True

    @pytest.mark.parametrize("role_name", _READONLY_NAMES)
    def test_no_write_tools_in_allowlist(self, role_name: str) -> None:
        role = BUILTIN_ROLES[role_name]
        allow = set(role.tool_allowlist)
        assert allow.isdisjoint(self._WRITE_TOOLS), (
            f"{role_name} allowlist contains write tools: " f"{allow & self._WRITE_TOOLS}"
        )

    def test_validator_includes_run_tests(self) -> None:
        role = BUILTIN_ROLES["validator"]
        assert "run_tests" in role.tool_allowlist

    def test_validator_read_only(self) -> None:
        role = BUILTIN_ROLES["validator"]
        assert role.read_only is True


# ---------------------------------------------------------------------------
# AC3: Writer role offers full surface (derived from SCHEMAS)
# ---------------------------------------------------------------------------


class TestWriterRole:
    def test_writer_not_read_only(self) -> None:
        assert BUILTIN_ROLES["writer"].read_only is False

    def test_writer_allowlist_equals_schemas(self) -> None:
        from colleague.tools import SCHEMAS

        schema_names = {s["function"]["name"] for s in SCHEMAS}
        writer_names = set(BUILTIN_ROLES["writer"].tool_allowlist)
        assert writer_names == schema_names

    def test_writer_allowlist_stays_in_sync(self) -> None:
        """If SCHEMAS grows, writer's allowlist must grow too."""
        from colleague.tools import SCHEMAS

        schema_names = {s["function"]["name"] for s in SCHEMAS}
        writer_names = set(BUILTIN_ROLES["writer"].tool_allowlist)
        # Every schema tool must be in the writer allowlist.
        assert schema_names.issubset(writer_names)
        # And the writer allowlist must not contain tools outside SCHEMAS
        # (except "run_tests" which is a future tool the validator references).
        extra = writer_names - schema_names
        assert extra <= {"run_tests"}, f"writer allowlist has unexpected extras: {extra}"


# ---------------------------------------------------------------------------
# AC4: load_role resolution
# ---------------------------------------------------------------------------


class TestLoadRole:
    def test_load_builtin_explorer(self, tmp_path: pytest.TempPathFactory) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        role = load_role("explorer", str(repo), "gpt-4")
        assert role is not None
        assert role.name == "explorer"
        assert role.read_only is True

    def test_load_builtin_writer(self, tmp_path: pytest.TempPathFactory) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        role = load_role("writer", str(repo), "gpt-4")
        assert role is not None
        assert role.read_only is False

    def test_load_unknown_role_returns_none(self, tmp_path: pytest.TempPathFactory) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        role = load_role("nonexistent", str(repo), "gpt-4")
        assert role is None

    def test_load_custom_file_overrides_prompt(self, tmp_path: pytest.TempPathFactory) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        agents_dir = repo / ".colleague" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "explorer.md").write_text("custom prompt here")

        role = load_role("explorer", str(repo), "gpt-4")
        assert role is not None
        assert role.prompt_fragment == "custom prompt here"

    def test_load_model_overlay_shadows_base(self, tmp_path: pytest.TempPathFactory) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        # Base file
        base_dir = repo / ".colleague" / "agents"
        base_dir.mkdir(parents=True)
        (base_dir / "explorer.md").write_text("base prompt")

        # Model overlay (exact path, no globbing)
        model_dir = repo / ".colleague" / "gpt-4" / "agents"
        model_dir.mkdir(parents=True)
        (model_dir / "explorer.md").write_text("model overlay prompt")

        role = load_role("explorer", str(repo), "gpt-4")
        assert role is not None
        assert role.prompt_fragment == "model overlay prompt"

    def test_load_model_overlay_uses_sanitized_model(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        # Model with slashes gets sanitized to dashes
        model_dir = repo / ".colleague" / "Qwen-Qwen3-32B" / "agents"
        model_dir.mkdir(parents=True)
        (model_dir / "planner.md").write_text("sanitized model prompt")

        role = load_role("planner", str(repo), "Qwen/Qwen3-32B")
        assert role is not None
        assert role.prompt_fragment == "sanitized model prompt"

    def test_load_no_sibling_globbing(self, tmp_path: pytest.TempPathFactory) -> None:
        """A file in a sibling model dir must NOT be picked up."""
        repo = tmp_path / "repo"
        repo.mkdir()
        # Put a file in a *different* model's dir
        sibling_dir = repo / ".colleague" / "other-model" / "agents"
        sibling_dir.mkdir(parents=True)
        (sibling_dir / "explorer.md").write_text("sibling prompt")

        # Requesting gpt-4 should NOT find the sibling file
        role = load_role("explorer", str(repo), "gpt-4")
        assert role is not None
        # Should fall back to built-in prompt, not the sibling
        assert role.prompt_fragment != "sibling prompt"

    def test_load_fallback_to_builtin_when_no_file(self, tmp_path: pytest.TempPathFactory) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        # No .colleague/agents at all
        role = load_role("reviewer", str(repo), "gpt-4")
        assert role is not None
        assert role.name == "reviewer"
        assert role.read_only is True

    @pytest.mark.parametrize(
        "bad_name", ["../../etc/passwd", "a/b", "name.md", "..", "", "foo/../bar"]
    )
    def test_name_traversal_rejected(self, bad_name: str, tmp_path) -> None:
        """A role name is never a path: a separator/dot/.. is refused (returns None),
        so it can never be interpolated into a path to read an arbitrary file."""
        repo = tmp_path / "repo"
        repo.mkdir()
        assert load_role(bad_name, str(repo), "gpt-4") is None

    def test_symlinked_role_file_outside_colleague_is_refused(self, tmp_path) -> None:
        """Defense-in-depth: even a valid name must not read a role file that
        RESOLVES outside .colleague/ — a symlink planted in the config dir could
        otherwise pull an arbitrary file into the system prompt. The read is refused
        and the loader falls back to the built-in prompt."""
        repo = tmp_path / "repo"
        (repo / ".colleague" / "agents").mkdir(parents=True)
        secret = tmp_path / "secret.md"
        secret.write_text("SUPER SECRET CONTENTS")
        link = repo / ".colleague" / "agents" / "explorer.md"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        role = load_role("explorer", str(repo), "gpt-4")
        # The symlinked-out file must NOT become the prompt; fall back to built-in.
        assert role is not None
        assert "SUPER SECRET" not in role.prompt_fragment


# ---------------------------------------------------------------------------
# AC5: default_role yields full-surface writer
# ---------------------------------------------------------------------------


class TestDefaultRole:
    def test_default_is_writer(self) -> None:
        role = default_role()
        assert role.name == "writer"
        assert role.read_only is False

    def test_default_allowlist_equals_schemas(self) -> None:
        from colleague.tools import SCHEMAS

        schema_names = {s["function"]["name"] for s in SCHEMAS}
        default_names = set(default_role().tool_allowlist)
        assert default_names == schema_names

    def test_default_skill_subset_is_none(self) -> None:
        role = default_role()
        assert role.skill_subset is None


# ---------------------------------------------------------------------------
# Review fix: every role must offer `finish`; read-only roles are pure-read
# ---------------------------------------------------------------------------


class TestFinishAndPureRead:
    """A curated read-only child needs `finish` to complete cleanly, and a
    read-only role must not carry a write-capable shell-out tool."""

    @pytest.mark.parametrize("role_name", sorted(BUILTIN_ROLES))
    def test_every_role_can_finish(self, role_name: str) -> None:
        role = BUILTIN_ROLES[role_name]
        assert "finish" in role.tool_allowlist, (
            f"{role_name} cannot finish — a curated child with no `finish` "
            f"would always burn to budget exhaustion"
        )

    @pytest.mark.parametrize("role_name", ("explorer", "planner", "reviewer", "validator"))
    def test_readonly_roles_are_pure_read(self, role_name: str) -> None:
        # No write tools AND no write-capable shell-out CLIs, so a read-only
        # role provably cannot mutate the tree by any offered tool.
        forbidden = {"write_file", "edit_file", "run_command", "culture", "devague"}
        allow = set(BUILTIN_ROLES[role_name].tool_allowlist)
        assert not (allow & forbidden), (
            f"{role_name} allowlist carries a write-capable tool: " f"{allow & forbidden}"
        )

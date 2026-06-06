"""Tests for colleague/learn_from.py — the learn-from adapter core."""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.learn_from import (
    PROVENANCE_PREFIX,
    ClaudeSkill,
    adapt_skills,
    discover_claude_skills,
    estimate_runnable,
    load_claude_skill,
    parse_frontmatter,
    render_colleague_skill,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_file(tmp_path: Path, name: str, text: str) -> Path:
    """Create a SKILL.md under <tmp_path>/.claude/skills/<name>/SKILL.md."""
    skill_dir = tmp_path / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(text, encoding="utf-8")
    return skill_file


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    """parse_frontmatter: YAML frontmatter parsing with block scalars."""

    def test_simple_key_value(self) -> None:
        text = "---\nname: foo\ndescription: bar\n---\nbody text\n"
        meta, body = parse_frontmatter(text)
        assert meta == {"name": "foo", "description": "bar"}
        assert body == "body text"

    def test_block_scalar_fold(self) -> None:
        """Block scalar > folds multi-line into a single line with collapsed whitespace."""
        text = (
            "---\n"
            "name: run-tests\n"
            "description: >\n"
            "  Run pytest with parallel execution and coverage. Use when running\n"
            '  tests, verifying changes, or the user says "run tests".\n'
            "---\n"
            "# Run Tests\n"
            "Body here\n"
        )
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "run-tests"
        desc = meta["description"]
        # Must be a single line, no newlines, collapsed whitespace
        assert "\n" not in desc
        assert "Run pytest with parallel execution and coverage." in desc
        assert body == "# Run Tests\nBody here"

    def test_block_scalar_literal(self) -> None:
        """Literal | preserves newlines."""
        text = (
            "---\n"
            "name: literal-skill\n"
            "description: |\n"
            "  Line one\n"
            "  Line two\n"
            "---\n"
            "body\n"
        )
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "literal-skill"
        assert meta["description"] == "Line one\nLine two"
        assert body == "body"

    def test_quoted_scalar_stripped(self) -> None:
        """Strip matching surrounding quotes from simple scalar values."""
        text = "---\n" 'name: "quoted-name"\n' "description: 'single-quoted'\n" "---\n" "body\n"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "quoted-name"
        assert meta["description"] == "single-quoted"

    def test_no_frontmatter(self) -> None:
        """No leading --- => ({}, text)."""
        text = "# Hello\nSome body\n"
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_unterminated_frontmatter(self) -> None:
        """Unterminated --- => treat whole text as body."""
        text = "---\nname: foo\ndescription: bar\nbody text\n"
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_block_scalar_fold_minus(self) -> None:
        """Block scalar >- folds and strips trailing newline."""
        text = "---\n" "description: >-\n" "  First line\n" "  Second line\n" "---\n" "body\n"
        meta, body = parse_frontmatter(text)
        desc = meta["description"]
        assert "\n" not in desc
        assert desc == "First line Second line"

    def test_block_scalar_literal_minus(self) -> None:
        """Literal |- preserves newlines but strips trailing newline."""
        text = "---\n" "description: |-\n" "  Line one\n" "  Line two\n" "---\n" "body\n"
        meta, body = parse_frontmatter(text)
        assert meta["description"] == "Line one\nLine two"

    def test_leading_blank_lines_before_frontmatter(self) -> None:
        """Leading blank lines before --- are skipped."""
        text = "\n\n---\nname: foo\n---\nbody\n"
        meta, body = parse_frontmatter(text)
        assert meta == {"name": "foo"}
        assert body == "body"

    def test_utf8_bom(self) -> None:
        """UTF-8 BOM is stripped before parsing."""
        text = "\ufeff---\nname: bom-test\n---\nbody\n"
        meta, body = parse_frontmatter(text)
        assert meta == {"name": "bom-test"}
        assert body == "body"


# ---------------------------------------------------------------------------
# render_colleague_skill
# ---------------------------------------------------------------------------


class TestRenderColleagueSkill:
    """render_colleague_skill: deterministic markdown output."""

    def _make_skill(
        self,
        name: str = "test-skill",
        description: str = "A test skill",
        body: str = "Some body text",
    ) -> ClaudeSkill:
        return ClaudeSkill(
            name=name,
            description=description,
            body=body,
            source=Path("/fake/path/SKILL.md"),
            scripts_dir=None,
        )

    def test_first_line_is_description(self) -> None:
        """Output's first non-empty non-# line equals the description."""
        from colleague.layers import _first_summary_line

        skill = self._make_skill()
        rendered = render_colleague_skill(skill)
        assert _first_summary_line(rendered) == skill.description

    def test_provenance_marker_present(self) -> None:
        """The provenance comment line is present."""
        skill = self._make_skill()
        rendered = render_colleague_skill(skill)
        assert PROVENANCE_PREFIX in rendered

    def test_name_heading_present(self) -> None:
        """# <name> heading is in the output."""
        skill = self._make_skill(name="my-skill")
        rendered = render_colleague_skill(skill)
        assert "# my-skill" in rendered

    def test_body_survives(self) -> None:
        """The body text survives in the output."""
        skill = self._make_skill(body="Important instructions here")
        rendered = render_colleague_skill(skill)
        assert "Important instructions here" in rendered

    def test_idempotent(self) -> None:
        """render_colleague_skill twice => identical bytes."""
        skill = self._make_skill()
        r1 = render_colleague_skill(skill)
        r2 = render_colleague_skill(skill)
        assert r1 == r2

    def test_ends_with_single_newline(self) -> None:
        """Output ends with exactly one trailing newline."""
        skill = self._make_skill()
        rendered = render_colleague_skill(skill)
        assert rendered.endswith("\n")
        assert not rendered.endswith("\n\n")

    def test_empty_description_uses_body_first_line(self) -> None:
        """When description is empty, body's first non-heading line is used."""
        skill = ClaudeSkill(
            name="no-desc",
            description="",
            body="# Title\nThis is the real description.\nMore body.",
            source=Path("/fake/SKILL.md"),
            scripts_dir=None,
        )
        rendered = render_colleague_skill(skill)
        # The first summary line should be "This is the real description."
        from colleague.layers import _first_summary_line

        assert _first_summary_line(rendered) == "This is the real description."

    def test_scripts_path_in_provenance(self) -> None:
        """When scripts_dir is set, it appears in the provenance comment."""
        skill = ClaudeSkill(
            name="with-scripts",
            description="Has scripts",
            body="Body",
            source=Path("/fake/SKILL.md"),
            scripts_dir=Path("/fake/scripts"),
        )
        rendered = render_colleague_skill(skill)
        assert "scripts: /fake/scripts" in rendered

    def test_no_scripts_dash_in_provenance(self) -> None:
        """When scripts_dir is None, '-' appears in the provenance comment."""
        skill = self._make_skill()
        rendered = render_colleague_skill(skill)
        assert "scripts: -" in rendered


# ---------------------------------------------------------------------------
# load_claude_skill
# ---------------------------------------------------------------------------


class TestLoadClaudeSkill:
    """load_claude_skill: reads SKILL.md and returns ClaudeSkill."""

    def test_basic_load(self, tmp_path: Path) -> None:
        text = "---\nname: my-skill\ndescription: A skill\n---\nBody\n"
        _make_skill_file(tmp_path, "my-skill", text)
        skill = load_claude_skill(tmp_path / ".claude" / "skills" / "my-skill")
        assert skill is not None
        assert skill.name == "my-skill"
        assert skill.description == "A skill"
        assert skill.body == "Body"

    def test_name_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        """When frontmatter has no name, fall back to directory name."""
        text = "---\ndescription: No name here\n---\nBody\n"
        _make_skill_file(tmp_path, "fallback-name", text)
        skill = load_claude_skill(tmp_path / ".claude" / "skills" / "fallback-name")
        assert skill is not None
        assert skill.name == "fallback-name"

    def test_missing_skill_file(self, tmp_path: Path) -> None:
        """Return None when SKILL.md is missing."""
        skill_dir = tmp_path / ".claude" / "skills" / "missing"
        skill_dir.mkdir(parents=True, exist_ok=True)
        result = load_claude_skill(skill_dir)
        assert result is None

    def test_scripts_dir_detected(self, tmp_path: Path) -> None:
        """scripts_dir is set when <skill_dir>/scripts exists."""
        text = "---\nname: scripted\n---\nBody\n"
        _make_skill_file(tmp_path, "scripted", text)
        scripts_dir = tmp_path / ".claude" / "skills" / "scripted" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        skill = load_claude_skill(tmp_path / ".claude" / "skills" / "scripted")
        assert skill is not None
        assert skill.scripts_dir is not None
        assert skill.scripts_dir == scripts_dir


# ---------------------------------------------------------------------------
# estimate_runnable
# ---------------------------------------------------------------------------


class TestEstimateRunnable:
    """estimate_runnable: heuristic from body text."""

    def _make_skill(self, body: str) -> ClaudeSkill:
        return ClaudeSkill(
            name="test",
            description="desc",
            body=body,
            source=Path("/fake/SKILL.md"),
            scripts_dir=None,
        )

    def test_scripts_reference_is_instructional_only(self) -> None:
        """Body referencing scripts/ => instructional-only."""
        skill = self._make_skill("Run scripts/deploy.sh to deploy.")
        assert estimate_runnable(skill) == "instructional-only"

    def test_sh_reference_is_instructional_only(self) -> None:
        """Body referencing .sh => instructional-only."""
        skill = self._make_skill("Execute build.sh to compile.")
        assert estimate_runnable(skill) == "instructional-only"

    def test_python3_reference_is_instructional_only(self) -> None:
        """Body referencing python3 => instructional-only."""
        skill = self._make_skill("Run python3 script.py to test.")
        assert estimate_runnable(skill) == "instructional-only"

    def test_dot_slash_reference_is_instructional_only(self) -> None:
        """Body referencing ./ => instructional-only."""
        skill = self._make_skill("Run ./run.sh to start.")
        assert estimate_runnable(skill) == "instructional-only"

    def test_skill_tool_reference_is_instructional_only(self) -> None:
        """Body referencing 'Skill tool' => instructional-only."""
        skill = self._make_skill("Use the Skill tool to run this.")
        assert estimate_runnable(skill) == "instructional-only"

    def test_slash_command_reference_is_instructional_only(self) -> None:
        """Body referencing 'slash command' => instructional-only."""
        skill = self._make_skill("Use the slash command /deploy.")
        assert estimate_runnable(skill) == "instructional-only"

    def test_leading_slash_token_is_instructional_only(self) -> None:
        """Body referencing /think => instructional-only."""
        skill = self._make_skill("Use /think to reason.")
        assert estimate_runnable(skill) == "instructional-only"

    def test_pure_prose_is_full(self) -> None:
        """Pure instructional prose => full."""
        skill = self._make_skill(
            body="This skill helps you write better code by following good habits."
        )
        assert estimate_runnable(skill) == "full"

    def test_command_mention_is_partial(self) -> None:
        """Mentions running commands generally => partial."""
        skill = self._make_skill("You can run the command to execute the task.")
        assert estimate_runnable(skill) == "partial"


# ---------------------------------------------------------------------------
# discover_claude_skills
# ---------------------------------------------------------------------------


class TestDiscoverClaudeSkills:
    """discover_claude_skills: finds SKILL.md files."""

    def test_discovers_skills(self, tmp_path: Path) -> None:
        _make_skill_file(tmp_path, "alpha", "---\nname: alpha\n---\n")
        _make_skill_file(tmp_path, "beta", "---\nname: beta\n---\n")
        result = discover_claude_skills(tmp_path)
        assert "alpha" in result
        assert "beta" in result
        assert len(result) == 2

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        result = discover_claude_skills(tmp_path)
        assert result == {}

    def test_sorted_order(self, tmp_path: Path) -> None:
        _make_skill_file(tmp_path, "zzz", "---\n---\n")
        _make_skill_file(tmp_path, "aaa", "---\n---\n")
        result = discover_claude_skills(tmp_path)
        assert list(result.keys()) == ["aaa", "zzz"]


# ---------------------------------------------------------------------------
# adapt_skills
# ---------------------------------------------------------------------------


class TestAdaptSkills:
    """adapt_skills: the main entry point."""

    def _setup(self, tmp_path: Path) -> Path:
        """Set up a fake repo with .claude/skills."""
        _make_skill_file(tmp_path, "foo", "---\nname: foo\ndescription: Foo skill\n---\nFoo body\n")
        return tmp_path

    def test_first_run_creates(self, tmp_path: Path) -> None:
        """First run => 'created' and the dest file exists."""
        self._setup(tmp_path)
        results = adapt_skills(tmp_path, source="claude")
        assert len(results) == 1
        assert results[0].action == "created"
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        assert dest.exists()

    def test_second_run_skipped(self, tmp_path: Path) -> None:
        """Second run => 'skipped' (byte-identical)."""
        self._setup(tmp_path)
        adapt_skills(tmp_path, source="claude")
        results = adapt_skills(tmp_path, source="claude")
        assert len(results) == 1
        assert results[0].action == "skipped"

    def test_dry_run_would_create(self, tmp_path: Path) -> None:
        """dry_run=True on a fresh repo => 'would-create' and NO file written."""
        self._setup(tmp_path)
        results = adapt_skills(tmp_path, source="claude", dry_run=True)
        assert len(results) == 1
        assert results[0].action == "would-create"
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        assert not dest.exists()

    def test_names_filter(self, tmp_path: Path) -> None:
        """names=['foo'] filters to only that skill."""
        self._setup(tmp_path)
        _make_skill_file(tmp_path, "bar", "---\nname: bar\n---\nBar body\n")
        results = adapt_skills(tmp_path, source="claude", names=["foo"])
        assert len(results) == 1
        assert results[0].name == "foo"

    def test_not_found(self, tmp_path: Path) -> None:
        """names=['missing'] => 'not-found'."""
        self._setup(tmp_path)
        results = adapt_skills(tmp_path, source="claude", names=["missing"])
        assert len(results) == 1
        assert results[0].action == "not-found"

    def test_unknown_source_raises(self, tmp_path: Path) -> None:
        """Unknown source => ValueError."""
        with pytest.raises(ValueError, match="unknown source"):
            adapt_skills(tmp_path, source="unknown")

    def test_hand_authored_protected(self, tmp_path: Path) -> None:
        """A hand-authored dest (no marker) is 'protected' unless force."""
        self._setup(tmp_path)
        # First create the file
        adapt_skills(tmp_path, source="claude")
        # Now overwrite with hand-authored content (no provenance marker)
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        dest.write_text("# Hand authored\nSome content\n", encoding="utf-8")
        results = adapt_skills(tmp_path, source="claude")
        assert len(results) == 1
        assert results[0].action == "protected"

    def test_hand_authored_force_updates(self, tmp_path: Path) -> None:
        """force=True overwrites hand-authored dest."""
        self._setup(tmp_path)
        adapt_skills(tmp_path, source="claude")
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        dest.write_text("# Hand authored\nSome content\n", encoding="utf-8")
        results = adapt_skills(tmp_path, source="claude", force=True)
        assert len(results) == 1
        assert results[0].action == "updated"

    def test_colleague_owned_differs_skipped(self, tmp_path: Path) -> None:
        """Colleague-owned dest that differs is 'skipped' with note."""
        self._setup(tmp_path)
        adapt_skills(tmp_path, source="claude")
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        # Modify but keep provenance marker
        content = dest.read_text(encoding="utf-8")
        dest.write_text(content + "\n# modified\n", encoding="utf-8")
        results = adapt_skills(tmp_path, source="claude")
        assert len(results) == 1
        assert results[0].action == "skipped"
        assert "differs; pass --force" in results[0].note

    def test_dry_run_colleague_owned_differs_would_skip(self, tmp_path: Path) -> None:
        """dry_run on a colleague-owned dest that differs (no force) => 'would-skip'."""
        self._setup(tmp_path)
        adapt_skills(tmp_path, source="claude")
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        dest.write_text(dest.read_text(encoding="utf-8") + "\n# modified\n", encoding="utf-8")
        results = adapt_skills(tmp_path, source="claude", dry_run=True)
        assert len(results) == 1
        assert results[0].action == "would-skip"

    def test_colleague_owned_force_updates(self, tmp_path: Path) -> None:
        """force=True updates colleague-owned dest."""
        self._setup(tmp_path)
        adapt_skills(tmp_path, source="claude")
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        content = dest.read_text(encoding="utf-8")
        dest.write_text(content + "\n# modified\n", encoding="utf-8")
        results = adapt_skills(tmp_path, source="claude", force=True)
        assert len(results) == 1
        assert results[0].action == "updated"

    def test_dry_run_would_skip(self, tmp_path: Path) -> None:
        """dry_run=True on identical dest => 'would-skip'."""
        self._setup(tmp_path)
        adapt_skills(tmp_path, source="claude")
        results = adapt_skills(tmp_path, source="claude", dry_run=True)
        assert len(results) == 1
        assert results[0].action == "would-skip"

    def test_dry_run_would_update(self, tmp_path: Path) -> None:
        """dry_run=True with force on differing dest => 'would-update'."""
        self._setup(tmp_path)
        adapt_skills(tmp_path, source="claude")
        dest = tmp_path / ".colleague" / "skills" / "foo.md"
        content = dest.read_text(encoding="utf-8")
        dest.write_text(content + "\n# modified\n", encoding="utf-8")
        results = adapt_skills(tmp_path, source="claude", dry_run=True, force=True)
        assert len(results) == 1
        assert results[0].action == "would-update"

    def test_results_sorted_by_name(self, tmp_path: Path) -> None:
        """Results are sorted by name."""
        _make_skill_file(tmp_path, "zzz", "---\nname: zzz\n---\nBody\n")
        _make_skill_file(tmp_path, "aaa", "---\nname: aaa\n---\nBody\n")
        results = adapt_skills(tmp_path, source="claude")
        names = [r.name for r in results]
        assert names == sorted(names)

    def test_malicious_name_cannot_escape_skills_dir(self, tmp_path: Path) -> None:
        """A crafted frontmatter name with path traversal stays inside .colleague/skills/.

        Guards against path injection (S2083): the untrusted SKILL.md ``name`` is
        sanitized to a single safe stem before building the output path.
        """
        _make_skill_file(tmp_path, "evil", "---\nname: ../../pwned\n---\nBody\n")
        results = adapt_skills(tmp_path, source="claude")
        skills_dir = (tmp_path / ".colleague" / "skills").resolve()
        for r in results:
            written = Path(r.dest).resolve()
            assert written.parent == skills_dir, f"escaped: {written}"
        # Nothing was written outside the skills dir.
        assert not (tmp_path / "pwned.md").exists()
        assert not (tmp_path.parent / "pwned.md").exists()

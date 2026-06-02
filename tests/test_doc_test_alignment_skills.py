"""Tests for check (c): skill_descriptions — skills SKILL.md vs scripts alignment.

TDD order: CATCH test written first (fails before implementation lands).

Covers:
- CATCH: SKILL.md claims scripts/bump.py but the file is absent → error, exit 1.
- PASS: SKILL.md claims scripts/check.sh and the file exists + is executable → no error.
- Pure-doc: no scripts/ dir and no script claims → info/passed, exit 0.
- Folded-scalar description parses (reuses the spine parser).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "doc-test-alignment"
SCRIPTS_DIR = SKILL_ROOT / "scripts"
CHECKS_DIR = SCRIPTS_DIR / "checks"
ENTRY_SH = SCRIPTS_DIR / "check.sh"

REPO_ROOT = Path(__file__).resolve().parents[1]

MODULE_PATH = CHECKS_DIR / "skill_descriptions.py"


# ---------------------------------------------------------------------------
# Module-loading helpers
# ---------------------------------------------------------------------------


def _load_module(path: Path, name: str) -> ModuleType:
    """Load a .py file as a module without it being on sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None, f"Could not create spec for {path}"
    mod = importlib.util.module_from_spec(spec)
    # Ensure scripts dir is on sys.path so intra-skill sibling imports work.
    scripts_str = str(SCRIPTS_DIR)
    if scripts_str not in sys.path:
        sys.path.insert(0, scripts_str)
    # Also ensure the checks package parent is on sys.path.
    checks_parent = str(SCRIPTS_DIR)
    if checks_parent not in sys.path:
        sys.path.insert(0, checks_parent)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _skill_check() -> ModuleType:
    return _load_module(MODULE_PATH, "checks.skill_descriptions")


def _run_check(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ENTRY_SH), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake repo with pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fake"\n')
    return tmp_path


def _make_skill(
    repo: Path,
    name: str,
    skill_md_text: str,
    scripts: dict[str, str] | None = None,
    executable_scripts: list[str] | None = None,
) -> Path:
    """Create a .claude/skills/<name>/ tree under *repo*.

    scripts: {relative_path: content} — files to create under skills/<name>/
    executable_scripts: list of script paths (relative to skills/<name>/) to chmod +x
    """
    skill_dir = repo / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_md_text, encoding="utf-8")

    if scripts:
        for rel_path, content in scripts.items():
            full = skill_dir / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")

    if executable_scripts:
        for rel_path in executable_scripts:
            full = skill_dir / rel_path
            full.chmod(full.stat().st_mode | 0o111)

    return skill_dir


# ---------------------------------------------------------------------------
# CATCH test — written FIRST; must fail before implementation
# ---------------------------------------------------------------------------


class TestCatchMissingScript:
    """SKILL.md references scripts/bump.py but the file does not exist → error."""

    SKILL_MD = """\
---
name: fake-bump
description: Bump the version by running scripts/bump.py.
---

# fake-bump

Run `scripts/bump.py` to bump the version.
"""

    def test_missing_script_reference_is_error(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        _make_skill(
            repo,
            "fake-bump",
            self.SKILL_MD,
            # scripts/ directory exists but bump.py is NOT there
            scripts={"scripts/.gitkeep": ""},
        )

        mod = _skill_check()
        results = mod.run(repo)

        assert isinstance(results, list)
        assert len(results) >= 1

        error_checks = [c for c in results if c["severity"] == "error" and not c["passed"]]
        assert (
            error_checks
        ), "Expected at least one error check for missing scripts/bump.py, got: " + repr(results)
        # The error message must name the missing path
        messages = " ".join(c["message"] for c in error_checks)
        assert (
            "bump.py" in messages or "scripts/bump.py" in messages
        ), f"Expected 'bump.py' in error messages, got: {messages}"

    def test_missing_script_cli_exits_1(self, tmp_path: Path) -> None:
        """--only skills with a missing script claim exits 1 (aligned=False)."""
        repo = _make_fake_repo(tmp_path)
        _make_skill(
            repo,
            "fake-bump",
            self.SKILL_MD,
            scripts={"scripts/.gitkeep": ""},
        )

        result = _run_check("--only", "skills", "--json", "--repo", str(repo))
        assert result.returncode == 1, (
            f"Expected exit 1 for missing script, got {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        data = json.loads(result.stdout)
        assert data["aligned"] is False
        error_checks = [c for c in data["checks"] if c["severity"] == "error" and not c["passed"]]
        assert error_checks


# ---------------------------------------------------------------------------
# PASS tests — existing, executable script references
# ---------------------------------------------------------------------------


class TestPassExistingScript:
    """SKILL.md references scripts/check.sh and the file exists + is executable."""

    SKILL_MD = """\
---
name: well-aligned
description: Run scripts/check.sh to verify alignment.
---

# well-aligned

## How to run

```bash
scripts/check.sh --repo .
```
"""

    def test_existing_executable_script_no_error(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        _make_skill(
            repo,
            "well-aligned",
            self.SKILL_MD,
            scripts={"scripts/check.sh": "#!/usr/bin/env bash\necho ok\n"},
            executable_scripts=["scripts/check.sh"],
        )

        mod = _skill_check()
        results = mod.run(repo)

        assert isinstance(results, list)
        error_checks = [c for c in results if c["severity"] == "error" and not c["passed"]]
        assert not error_checks, f"Expected no errors for well-aligned skill, got: {error_checks}"

    def test_existing_executable_script_cli_exits_0(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        _make_skill(
            repo,
            "well-aligned",
            self.SKILL_MD,
            scripts={"scripts/check.sh": "#!/usr/bin/env bash\necho ok\n"},
            executable_scripts=["scripts/check.sh"],
        )

        result = _run_check("--only", "skills", "--json", "--repo", str(repo))
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        data = json.loads(result.stdout)
        assert data["aligned"] is True

    def test_existing_non_executable_script_is_error(self, tmp_path: Path) -> None:
        """A referenced script that exists but is not executable → error."""
        repo = _make_fake_repo(tmp_path)
        skill_dir = _make_skill(
            repo,
            "well-aligned",
            self.SKILL_MD,
            scripts={"scripts/check.sh": "#!/usr/bin/env bash\necho ok\n"},
            # NOT listed in executable_scripts — file exists but not +x
        )
        # Ensure not executable (in case umask is permissive)
        script = skill_dir / "scripts" / "check.sh"
        script.chmod(0o644)

        mod = _skill_check()
        results = mod.run(repo)

        error_checks = [c for c in results if c["severity"] == "error" and not c["passed"]]
        assert error_checks, "Expected an error for non-executable entry-point, got: " + repr(
            results
        )


# ---------------------------------------------------------------------------
# Pure-doc skill — no scripts/, no script claims
# ---------------------------------------------------------------------------


class TestPureDocSkill:
    """A skill with no scripts/ dir and no scripts/<path> claims → info/passed."""

    SKILL_MD_NO_CLAIMS = """\
---
name: pure-doc
description: A reference guide with no executable scripts.
---

# pure-doc

This skill has no scripts. It is pure documentation.
"""

    def test_pure_doc_skill_info_passed(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        # No scripts/ directory, no script claims in SKILL.md
        _make_skill(repo, "pure-doc", self.SKILL_MD_NO_CLAIMS)

        mod = _skill_check()
        results = mod.run(repo)

        assert isinstance(results, list)
        assert len(results) >= 1

        # Every result must be passed (no errors)
        for c in results:
            assert c["passed"] is True, f"Expected all passed for pure-doc skill, got failed: {c}"

        # Must include at least one info check
        info_checks = [c for c in results if c["severity"] == "info"]
        assert info_checks, f"Expected at least one info check, got: {results}"

    def test_pure_doc_skill_cli_exits_0(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        _make_skill(repo, "pure-doc", self.SKILL_MD_NO_CLAIMS)

        result = _run_check("--only", "skills", "--json", "--repo", str(repo))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["aligned"] is True


# ---------------------------------------------------------------------------
# Folded-scalar description parsing
# ---------------------------------------------------------------------------


class TestFoldedScalarDescription:
    """Folded description: > in SKILL.md frontmatter must parse correctly."""

    SKILL_MD_FOLDED = """\
---
name: folded-skill
description: >
  Run scripts/folded_entry.py to do
  something useful across multiple lines.
---

# folded-skill

Invoke `scripts/folded_entry.py` for the main operation.
"""

    def test_folded_description_claims_parsed(self, tmp_path: Path) -> None:
        """A scripts/<path> literal in a folded description must still be detected."""
        repo = _make_fake_repo(tmp_path)
        # scripts/folded_entry.py is MISSING — should be detected as error
        _make_skill(repo, "folded-skill", self.SKILL_MD_FOLDED)

        mod = _skill_check()
        results = mod.run(repo)

        error_checks = [c for c in results if c["severity"] == "error" and not c["passed"]]
        assert error_checks, (
            "Expected error for missing scripts/folded_entry.py "
            "(referenced in folded description), got: " + repr(results)
        )
        messages = " ".join(c["message"] for c in error_checks)
        assert "folded_entry.py" in messages or "scripts/folded_entry.py" in messages


# ---------------------------------------------------------------------------
# Internal failure guard — run() must never raise
# ---------------------------------------------------------------------------


class TestRunNeverRaises:
    def test_empty_skills_dir(self, tmp_path: Path) -> None:
        """repo with .claude/skills/ present but empty → no exception, empty list OK."""
        repo = _make_fake_repo(tmp_path)
        (repo / ".claude" / "skills").mkdir(parents=True, exist_ok=True)

        mod = _skill_check()
        # Must not raise
        results = mod.run(repo)
        assert isinstance(results, list)

    def test_no_skills_dir(self, tmp_path: Path) -> None:
        """repo with no .claude/skills/ dir → no exception."""
        repo = _make_fake_repo(tmp_path)

        mod = _skill_check()
        results = mod.run(repo)
        assert isinstance(results, list)

    def test_skill_with_no_skill_md(self, tmp_path: Path) -> None:
        """A skills/<name>/ dir with no SKILL.md → no exception."""
        repo = _make_fake_repo(tmp_path)
        skill_dir = repo / ".claude" / "skills" / "no-skill-md"
        skill_dir.mkdir(parents=True)
        # No SKILL.md at all

        mod = _skill_check()
        results = mod.run(repo)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Check ID and NAME constant
# ---------------------------------------------------------------------------


class TestModuleContract:
    def test_name_constant(self) -> None:
        mod = _skill_check()
        assert hasattr(mod, "NAME")
        assert mod.NAME == "skills"

    def test_run_callable(self) -> None:
        mod = _skill_check()
        assert callable(mod.run)

    def test_check_ids_contain_skills(self, tmp_path: Path) -> None:
        """All check IDs emitted by this module should contain 'skills'."""
        repo = _make_fake_repo(tmp_path)
        mod = _skill_check()
        results = mod.run(repo)
        for c in results:
            assert "skills" in c["id"], f"Expected 'skills' in check id, got: {c['id']!r}"


class TestCrossSkillReferenceNotAttributed:
    """A skill that documents a SIBLING skill's `.claude/skills/<other>/scripts/...`
    command must NOT be flagged for not having that script itself (regression:
    assign-to-workforce references `.claude/skills/cicd/scripts/workflow.sh`).
    """

    def test_sibling_script_path_is_not_a_claim(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        # The skill under test owns scripts/own.sh and only *mentions* a sibling's script.
        _make_skill(
            repo,
            "mover",
            "---\nname: mover\ndescription: a mover\n---\n\n"
            "Run `scripts/own.sh`. Afterwards run "
            "`bash .claude/skills/cicd/scripts/workflow.sh open`.\n",
            scripts={"scripts/own.sh": "#!/bin/sh\necho hi\n"},
            executable_scripts=["scripts/own.sh"],
        )
        mod = _skill_check()
        results = mod.run(repo)
        # No error: the sibling's workflow.sh is not attributed to 'mover'.
        errors = [c for c in results if c["severity"] == "error" and not c["passed"]]
        assert errors == [], f"cross-skill ref wrongly flagged: {errors!r}"

    def test_same_skill_qualified_path_still_required(self, tmp_path: Path) -> None:
        """A fully-qualified reference to THIS skill's own scripts/ IS a claim."""
        repo = _make_fake_repo(tmp_path)
        _make_skill(
            repo,
            "mover",
            "---\nname: mover\ndescription: a mover\n---\n\n"
            "Run `bash .claude/skills/mover/scripts/go.sh`.\n",
            scripts=None,  # go.sh deliberately missing
        )
        mod = _skill_check()
        results = mod.run(repo)
        missing = [c for c in results if c["severity"] == "error" and "go" in c["id"]]
        assert missing, "own fully-qualified script path should still be required"

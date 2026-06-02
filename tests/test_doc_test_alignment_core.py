"""Tests for the doc-test-alignment skill spine.

TDD: tests are written first, then the implementation is added.

Uses importlib to load skill scripts (not on sys.path as a package) and
subprocess to exercise the CLI via check.sh.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "doc-test-alignment"
SCRIPTS_DIR = SKILL_ROOT / "scripts"
CHECKS_DIR = SCRIPTS_DIR / "checks"
ENTRY_SH = SCRIPTS_DIR / "check.sh"
ENTRY_PY = SCRIPTS_DIR / "check.py"
REPORT_PY = SCRIPTS_DIR / "_report.py"
MD_PY = SCRIPTS_DIR / "_md.py"
CHECKS_INIT = CHECKS_DIR / "__init__.py"

# repo root (contains pyproject.toml)
REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Module-loading helpers (importlib, not package import)
# ---------------------------------------------------------------------------


def _load_module(path: Path, name: str) -> ModuleType:
    """Load a .py file as a module without it being on sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None, f"Could not create spec for {path}"
    mod = importlib.util.module_from_spec(spec)
    # Ensure the scripts dir is on sys.path so intra-skill imports work.
    scripts_str = str(SCRIPTS_DIR)
    if scripts_str not in sys.path:
        sys.path.insert(0, scripts_str)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _report() -> ModuleType:
    return _load_module(REPORT_PY, "_report")


def _md() -> ModuleType:
    return _load_module(MD_PY, "_md")


def _checks_registry() -> ModuleType:
    return _load_module(CHECKS_INIT, "checks")


# ---------------------------------------------------------------------------
# _report.py tests
# ---------------------------------------------------------------------------


class TestMakeCheck:
    def test_shape(self) -> None:
        r = _report()
        c = r.make_check("my_id", True, "info", "all good")
        assert set(c.keys()) == {"id", "passed", "severity", "message", "remediation"}
        assert c["id"] == "my_id"
        assert c["passed"] is True
        assert c["severity"] == "info"
        assert c["message"] == "all good"
        assert c["remediation"] == ""

    def test_remediation_default_empty(self) -> None:
        r = _report()
        c = r.make_check("x", True, "info", "msg")
        assert c["remediation"] == ""

    def test_explicit_remediation(self) -> None:
        r = _report()
        c = r.make_check("x", False, "error", "bad", "fix it")
        assert c["remediation"] == "fix it"

    def test_invalid_severity_raises(self) -> None:
        r = _report()
        with pytest.raises(ValueError, match="severity"):
            r.make_check("x", True, "critical", "msg")

    def test_all_valid_severities(self) -> None:
        r = _report()
        for sev in ("error", "warning", "info"):
            c = r.make_check("x", True, sev, "m")
            assert c["severity"] == sev


class TestAggregate:
    def test_all_passing_is_aligned(self) -> None:
        r = _report()
        checks = [
            r.make_check("a", True, "info", "ok"),
            r.make_check("b", True, "warning", "ok"),
        ]
        agg = r.aggregate(checks)
        assert agg["aligned"] is True
        assert agg["checks"] == checks

    def test_failed_error_is_not_aligned(self) -> None:
        r = _report()
        checks = [r.make_check("a", False, "error", "bad", "fix")]
        agg = r.aggregate(checks)
        assert agg["aligned"] is False

    def test_failed_warning_still_aligned(self) -> None:
        r = _report()
        checks = [r.make_check("a", False, "warning", "mismatch", "optional")]
        agg = r.aggregate(checks)
        assert agg["aligned"] is True

    def test_failed_info_still_aligned(self) -> None:
        r = _report()
        checks = [r.make_check("a", False, "info", "note", "optional")]
        agg = r.aggregate(checks)
        assert agg["aligned"] is True

    def test_mixed_error_and_warning_not_aligned(self) -> None:
        r = _report()
        checks = [
            r.make_check("a", False, "warning", "w", "hint"),
            r.make_check("b", False, "error", "e", "fix"),
        ]
        agg = r.aggregate(checks)
        assert agg["aligned"] is False

    def test_empty_checks_is_aligned(self) -> None:
        r = _report()
        agg = r.aggregate([])
        assert agg["aligned"] is True
        assert agg["checks"] == []

    def test_passed_error_is_aligned(self) -> None:
        """A passed error check (the invariant holds) should keep aligned=True."""
        r = _report()
        checks = [r.make_check("a", True, "error", "invariant holds")]
        agg = r.aggregate(checks)
        assert agg["aligned"] is True


# ---------------------------------------------------------------------------
# _md.py tests
# ---------------------------------------------------------------------------


class TestIterFencedBlocks:
    def test_bash_block(self) -> None:
        m = _md()
        text = "line1\n```bash\necho hi\n```\nline4\n"
        blocks = list(m.iter_fenced_blocks(text, "bash"))
        assert len(blocks) == 1
        lineno, body = blocks[0]
        assert lineno == 2
        assert "echo hi" in body

    def test_sh_block_accepted_when_lang_bash(self) -> None:
        """```sh blocks must be accepted when lang='bash'."""
        m = _md()
        text = "```sh\nls\n```\n"
        blocks = list(m.iter_fenced_blocks(text, "bash"))
        assert len(blocks) == 1
        _, body = blocks[0]
        assert "ls" in body

    def test_other_lang_ignored(self) -> None:
        m = _md()
        text = "```python\nprint(1)\n```\n"
        blocks = list(m.iter_fenced_blocks(text, "bash"))
        assert len(blocks) == 0

    def test_multiple_blocks(self) -> None:
        m = _md()
        text = "intro\n" "```bash\nfoo\n```\n" "middle\n" "```bash\nbar\n```\n"
        blocks = list(m.iter_fenced_blocks(text, "bash"))
        assert len(blocks) == 2
        assert blocks[0][0] == 2
        assert blocks[1][0] == 6

    def test_line_number_is_1based(self) -> None:
        m = _md()
        text = "```bash\nhello\n```\n"
        lineno, _ = list(m.iter_fenced_blocks(text, "bash"))[0]
        assert lineno == 1

    def test_body_does_not_include_fence_lines(self) -> None:
        m = _md()
        text = "```bash\nmy command\n```\n"
        _, body = list(m.iter_fenced_blocks(text, "bash"))[0]
        assert "```" not in body

    def test_arbitrary_lang(self) -> None:
        m = _md()
        text = "```toml\nkey=val\n```\n"
        blocks = list(m.iter_fenced_blocks(text, "toml"))
        assert len(blocks) == 1

    def test_empty_text(self) -> None:
        m = _md()
        blocks = list(m.iter_fenced_blocks("", "bash"))
        assert blocks == []


class TestParseFrontmatter:
    def test_no_frontmatter(self) -> None:
        m = _md()
        result = m.parse_frontmatter("# Title\ncontent\n")
        assert result == {}

    def test_plain_scalar(self) -> None:
        m = _md()
        text = "---\nname: foo\ndescription: a simple desc\n---\n# content\n"
        result = m.parse_frontmatter(text)
        assert result["name"] == "foo"
        assert result["description"] == "a simple desc"

    def test_quoted_scalar(self) -> None:
        m = _md()
        text = '---\ndescription: "quoted value"\n---\n'
        result = m.parse_frontmatter(text)
        assert result["description"] == "quoted value"

    def test_single_quoted_scalar(self) -> None:
        m = _md()
        text = "---\ndescription: 'single quoted'\n---\n"
        result = m.parse_frontmatter(text)
        assert result["description"] == "single quoted"

    def test_folded_scalar_gt(self) -> None:
        """description: > followed by indented lines — joined with spaces."""
        m = _md()
        text = "---\ndescription: >\n  line one\n  line two\n---\n"
        result = m.parse_frontmatter(text)
        # folded: lines joined with spaces
        assert "line one" in result["description"]
        assert "line two" in result["description"]
        # folded = joined with space, not newline
        assert "\n" not in result["description"].strip()

    def test_folded_scalar_literal(self) -> None:
        """description: | followed by indented lines — joined with newlines."""
        m = _md()
        text = "---\ndescription: |\n  line one\n  line two\n---\n"
        result = m.parse_frontmatter(text)
        assert "line one" in result["description"]
        assert "line two" in result["description"]

    def test_folded_scalar_gt_dash(self) -> None:
        """description: >- strip final newlines."""
        m = _md()
        text = "---\ndescription: >-\n  only line\n---\n"
        result = m.parse_frontmatter(text)
        assert "only line" in result["description"]

    def test_skill_md_frontmatter(self) -> None:
        """Parse the real SKILL.md frontmatter (has folded description with >)."""
        m = _md()
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        result = m.parse_frontmatter(text)
        assert "description" in result
        assert len(result["description"]) > 10


# ---------------------------------------------------------------------------
# checks/__init__.py (registry) tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_canonical_list(self) -> None:
        reg = _checks_registry()
        assert hasattr(reg, "CANONICAL")
        assert set(reg.CANONICAL) == {"readme", "claude", "skills", "tests"}

    def test_name_to_module_keys(self) -> None:
        reg = _checks_registry()
        assert set(reg.NAME_TO_MODULE.keys()) == {"readme", "claude", "skills", "tests"}

    def test_run_check_pending_fallback(self) -> None:
        """With no check modules present, run_check returns a pending info check."""
        reg = _checks_registry()
        result = reg.run_check("readme", REPO_ROOT)
        assert isinstance(result, list)
        assert len(result) >= 1
        # all pending checks are info + passed
        for c in result:
            assert c["passed"] is True
            assert c["severity"] == "info"
            assert "pending" in c["id"] or "pending" in c["message"].lower()

    def test_run_checks_all_pending(self) -> None:
        """run_checks over all CANONICAL returns pending info for each."""
        reg = _checks_registry()
        results = reg.run_checks(reg.CANONICAL, REPO_ROOT)
        assert isinstance(results, list)
        # Should have at least one per canonical name (pending)
        assert len(results) >= len(reg.CANONICAL)
        for c in results:
            assert c["severity"] == "info"
            assert c["passed"] is True

    def test_run_checks_order_matches_canonical(self) -> None:
        """run_checks returns results in CANONICAL order."""
        reg = _checks_registry()
        results = reg.run_checks(reg.CANONICAL, REPO_ROOT)
        # IDs should embed the canonical names in order
        canonical = reg.CANONICAL
        # Each canonical name should appear in the result ids in order
        seen_order = []
        for c in results:
            for name in canonical:
                if name in c["id"]:
                    if not seen_order or seen_order[-1] != name:
                        seen_order.append(name)
                    break
        assert seen_order == canonical


# ---------------------------------------------------------------------------
# CLI tests (subprocess via check.sh)
# ---------------------------------------------------------------------------


def _run_check(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ENTRY_SH), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


class TestCLI:
    def test_json_output_shape(self) -> None:
        """--json emits valid JSON with aligned + checks keys."""
        result = _run_check("--json", "--repo", str(REPO_ROOT))
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "aligned" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_all_pending_json(self) -> None:
        """With no check modules, all four canonicals report pending info checks."""
        result = _run_check("--json", "--repo", str(REPO_ROOT))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["aligned"] is True
        # At least 4 checks (one per canonical)
        assert len(data["checks"]) >= 4
        for c in data["checks"]:
            assert c["severity"] == "info"
            assert c["passed"] is True

    def test_bogus_only_exits_2(self) -> None:
        """--only with an unknown check name exits 2 and prints a stderr hint."""
        result = _run_check("--only", "bogus", "--repo", str(REPO_ROOT))
        assert result.returncode == 2
        assert result.stderr.strip() != ""  # hint on stderr

    def test_only_single_check(self) -> None:
        """--only skills runs just the skills check (1 pending info check)."""
        result = _run_check("--only", "skills", "--json", "--repo", str(REPO_ROOT))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["aligned"] is True
        assert len(data["checks"]) == 1
        assert "skills" in data["checks"][0]["id"]

    def test_only_comma_split(self) -> None:
        """--only readme,tests is equivalent to --only readme --only tests."""
        result = _run_check("--only", "readme,tests", "--json", "--repo", str(REPO_ROOT))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["checks"]) == 2

    def test_repo_autodetect_from_nested_cwd(self) -> None:
        """Repo root autodetect walks up from a nested subdirectory."""
        nested = REPO_ROOT / "tests"
        result = _run_check("--json", cwd=nested)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "aligned" in data

    def test_human_output_header(self) -> None:
        """Human output includes the alignment header."""
        result = _run_check("--repo", str(REPO_ROOT))
        assert result.returncode == 0
        assert "doc-test-alignment" in result.stdout

    def test_human_output_pass_markers(self) -> None:
        """Human output includes [PASS] markers for pending info checks."""
        result = _run_check("--repo", str(REPO_ROOT))
        assert result.returncode == 0
        assert "[PASS]" in result.stdout

    def test_exit_0_when_aligned(self) -> None:
        result = _run_check("--json", "--repo", str(REPO_ROOT))
        assert result.returncode == 0

    def test_no_stdout_stderr_mix(self) -> None:
        """Diagnostics go to stderr, result to stdout — they are not mixed."""
        result = _run_check("--json", "--repo", str(REPO_ROOT))
        # stdout should be valid JSON, stderr can be empty
        data = json.loads(result.stdout)
        assert "aligned" in data

    def test_only_repeatable(self) -> None:
        """--only can be repeated: --only readme --only claude."""
        result = _run_check(
            "--only", "readme", "--only", "claude", "--json", "--repo", str(REPO_ROOT)
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["checks"]) == 2


# ---------------------------------------------------------------------------
# Portability guard
# ---------------------------------------------------------------------------


class TestPortabilityGuard:
    def test_no_import_convertible(self) -> None:
        """No skill script file may import convertible (portability)."""
        py_files = list(SCRIPTS_DIR.rglob("*.py"))
        assert py_files, "Expected at least one .py file under scripts/"
        violations: list[str] = []
        for pyfile in py_files:
            text = pyfile.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                # Skip comments and docstring prose (lines inside triple-quoted strings
                # or starting with backtick-code in docstrings are prose, not real imports)
                if stripped.startswith("#"):
                    continue
                # Only flag actual import statements (import/from at start of statement)
                if stripped.startswith("import convertible") or stripped.startswith(
                    "from convertible"
                ):
                    violations.append(f"{pyfile.relative_to(SCRIPTS_DIR)}: {line!r}")
        assert not violations, "Portability violations:\n" + "\n".join(violations)

    def test_no_third_party_imports(self) -> None:
        """Skill scripts must only use stdlib (no third-party imports like requests, pydantic)."""
        # Known stdlib + internal modules only — we just check a few known third-party names
        third_party_suspects = ["requests", "pydantic", "httpx", "attrs", "click"]
        py_files = list(SCRIPTS_DIR.rglob("*.py"))
        violations: list[str] = []
        for pyfile in py_files:
            text = pyfile.read_text(encoding="utf-8")
            for lib in third_party_suspects:
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if f"import {lib}" in stripped or f"from {lib}" in stripped:
                        violations.append(f"{pyfile.name}: {line!r}")
        assert not violations, "Third-party import violations:\n" + "\n".join(violations)

    def test_scripts_dir_has_expected_files(self) -> None:
        """Key spine files must exist."""
        assert REPORT_PY.is_file(), "_report.py missing"
        assert MD_PY.is_file(), "_md.py missing"
        assert CHECKS_INIT.is_file(), "checks/__init__.py missing"
        assert ENTRY_PY.is_file(), "check.py missing"
        assert ENTRY_SH.is_file(), "check.sh missing"

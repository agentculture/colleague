"""Tests for the doc-test-alignment skill spine.

TDD: tests are written first, then the implementation is added.

Uses importlib to load skill scripts (not on sys.path as a package) and
subprocess to exercise the CLI via check.sh.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
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
# Hermetic fixture repo — a minimal tree where each of the four checks yields
# exactly one aligned `info` check, so the spine mechanics (dispatch, order,
# --only selection, exit codes, rendering) can be exercised fast and
# deterministically without depending on the real repo's content.
# ---------------------------------------------------------------------------


def _build_fixture_repo(root: Path) -> Path:
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    # No colleague commands → checks (a)/(b) run no subprocess (fast + hermetic).
    (root / "README.md").write_text("# Demo\n\nNo commands here.\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(
        "# Demo\n\n## Commands\n\n```bash\necho hello\n```\n", encoding="utf-8"
    )
    skill = root / ".claude" / "skills" / "demo" / "scripts"
    skill.mkdir(parents=True)
    (skill.parent / "SKILL.md").write_text(
        "---\nname: demo\ndescription: a demo skill\n---\n\n# Demo\n\nRun `scripts/run.sh`.\n",
        encoding="utf-8",
    )
    run_sh = skill / "run.sh"
    run_sh.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
    run_sh.chmod(0o755)
    tdir = root / "tests"
    tdir.mkdir()
    # Name tokens (value/target) appear in the body → not flagged by check (d).
    (tdir / "test_demo.py").write_text(
        "def test_value_equals_target():\n"
        "    target = 5\n"
        "    value = 5\n"
        "    assert value == target\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    return _build_fixture_repo(tmp_path)


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

    def test_run_check_pending_fallback(
        self, monkeypatch: pytest.MonkeyPatch, fixture_repo: Path
    ) -> None:
        """A canonical name whose module is missing falls back to a pending info check.

        All four checks are implemented now, so the fallback is exercised by
        pointing one canonical name at a non-existent module.
        """
        reg = _checks_registry()
        patched = dict(reg.NAME_TO_MODULE)
        patched["readme"] = "no_such_module_xyz"
        monkeypatch.setattr(reg, "NAME_TO_MODULE", patched)
        result = reg.run_check("readme", fixture_repo)
        assert isinstance(result, list) and len(result) >= 1
        for c in result:
            assert c["passed"] is True
            assert c["severity"] == "info"
            assert "pending" in c["id"] or "pending" in c["message"].lower()

    def test_run_checks_returns_valid_check_dicts(self, fixture_repo: Path) -> None:
        """run_checks over all CANONICAL returns well-formed check dicts."""
        reg = _checks_registry()
        results = reg.run_checks(reg.CANONICAL, fixture_repo)
        assert len(results) >= len(reg.CANONICAL)
        for c in results:
            assert set(c.keys()) == {"id", "passed", "severity", "message", "remediation"}
            assert c["severity"] in ("error", "warning", "info")

    def test_run_checks_orders_by_canonical(self, fixture_repo: Path) -> None:
        """run_checks concatenates results in CANONICAL order, regardless of input order."""
        reg = _checks_registry()
        expected = reg.run_check("skills", fixture_repo) + reg.run_check("tests", fixture_repo)
        assert reg.run_checks(["skills", "tests"], fixture_repo) == expected
        # Reversed input still yields CANONICAL (skills before tests) order.
        assert reg.run_checks(["tests", "skills"], fixture_repo) == expected


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
    def test_json_output_shape(self, fixture_repo: Path) -> None:
        """--json emits valid JSON with aligned + checks keys and five-key dicts."""
        result = _run_check("--json", "--repo", str(fixture_repo))
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "aligned" in data
        assert isinstance(data["checks"], list)
        for c in data["checks"]:
            assert set(c.keys()) == {"id", "passed", "severity", "message", "remediation"}

    def test_aligned_fixture_exits_0(self, fixture_repo: Path) -> None:
        """A fully aligned fixture repo reports aligned and exits 0."""
        result = _run_check("--json", "--repo", str(fixture_repo))
        assert result.returncode == 0
        assert json.loads(result.stdout)["aligned"] is True

    def test_bogus_only_exits_2(self) -> None:
        """--only with an unknown check name exits 2 and prints a stderr hint."""
        result = _run_check("--only", "bogus", "--repo", str(REPO_ROOT))
        assert result.returncode == 2
        assert result.stderr.strip() != ""  # hint on stderr

    def test_only_single_check(self, fixture_repo: Path) -> None:
        """--only skills runs only the skills check (every result id is a skills check)."""
        result = _run_check("--only", "skills", "--json", "--repo", str(fixture_repo))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["checks"]
        assert all("skills" in c["id"] for c in data["checks"])

    def test_only_comma_split(self, fixture_repo: Path) -> None:
        """--only readme,tests == running readme then tests (CANONICAL order)."""
        combined = json.loads(
            _run_check("--only", "readme,tests", "--json", "--repo", str(fixture_repo)).stdout
        )["checks"]
        readme = json.loads(
            _run_check("--only", "readme", "--json", "--repo", str(fixture_repo)).stdout
        )["checks"]
        tests = json.loads(
            _run_check("--only", "tests", "--json", "--repo", str(fixture_repo)).stdout
        )["checks"]
        assert combined == readme + tests

    def test_only_repeatable(self, fixture_repo: Path) -> None:
        """--only readme --only claude == running readme then claude."""
        combined = json.loads(
            _run_check(
                "--only", "readme", "--only", "claude", "--json", "--repo", str(fixture_repo)
            ).stdout
        )["checks"]
        readme = json.loads(
            _run_check("--only", "readme", "--json", "--repo", str(fixture_repo)).stdout
        )["checks"]
        claude = json.loads(
            _run_check("--only", "claude", "--json", "--repo", str(fixture_repo)).stdout
        )["checks"]
        assert combined == readme + claude

    def test_repo_autodetect_from_nested_cwd(self, fixture_repo: Path) -> None:
        """Repo root autodetect walks up from a nested subdirectory."""
        result = _run_check("--json", cwd=fixture_repo / "tests")
        assert result.returncode == 0
        assert "aligned" in json.loads(result.stdout)

    def test_human_output_header(self, fixture_repo: Path) -> None:
        """Human output includes the alignment header."""
        result = _run_check("--repo", str(fixture_repo))
        assert result.returncode == 0
        assert "doc-test-alignment" in result.stdout

    def test_human_output_pass_markers(self, fixture_repo: Path) -> None:
        """Human output includes [PASS] markers for passing checks."""
        result = _run_check("--repo", str(fixture_repo))
        assert result.returncode == 0
        assert "[PASS]" in result.stdout

    def test_no_stdout_stderr_mix(self, fixture_repo: Path) -> None:
        """Diagnostics go to stderr, result (JSON) to stdout — not mixed."""
        result = _run_check("--json", "--repo", str(fixture_repo))
        assert "aligned" in json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Portability guard
# ---------------------------------------------------------------------------


class TestPortabilityGuard:
    def test_no_import_colleague(self) -> None:
        """No skill script file may import colleague (portability)."""
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
                if stripped.startswith("import colleague") or stripped.startswith("from colleague"):
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


class TestPython3Guard:
    def test_clear_error_without_python3(self, tmp_path: Path) -> None:
        """check.sh exits 2 with a clear message when python3 is not on PATH."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        # Provide the tools the wrapper itself needs (bash + dirname) but NOT python3.
        needed = {tool: shutil.which(tool) for tool in ("bash", "dirname")}
        if not all(needed.values()):
            pytest.skip("bash/dirname not resolvable for a restricted-PATH test")
        for tool, src in needed.items():
            (bindir / tool).symlink_to(src)
        result = subprocess.run(
            ["bash", str(ENTRY_SH), "--only", "skills", "--repo", str(REPO_ROOT)],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": str(bindir)},
        )
        assert result.returncode == 2
        assert "python3" in result.stderr

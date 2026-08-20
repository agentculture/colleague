"""Tests proving the Gemma4 staged (not flipped) per-model configuration.

This module validates that the existing per-model profiles overlay seam
(``.colleague/<sanitize_model(model)>/profiles.json``) can carry a
Gemma4-specific context budget without touching any default or source code.

Covers:
1. A per-model overlay for ``coolthor/gemma-4-12B-it-NVFP4A16`` setting
   ``context_budget_tokens: 96000`` yields that budget after
   ``apply_mode_profile``.
2. A bare default resolve (no overlay) still yields the default 131072 budget.
3. No file under ``colleague/`` contains the string ``gemma`` in source code
   (only in comments/docstrings is acceptable).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from colleague.config import _DEFAULT_CONTEXT_BUDGET, EngineConfig, apply_mode_profile
from colleague.layers import sanitize_model

_GEMMA_MODEL = "coolthor/gemma-4-12B-it-NVFP4A16"
_GEMMA_SAFE = sanitize_model(_GEMMA_MODEL)  # "coolthor-gemma-4-12B-it-NVFP4A16"
_GEMMA_BUDGET = 96000

# The overlay keys REAL mode names (session_modes.MODES minus "auto") — the
# profile layer is consulted only when a mode is selected, and
# ``apply_mode_profile`` looks the overlay up by that mode name.  A made-up
# key (e.g. "default") would satisfy a test that passes the same made-up mode
# but can never fire on a real run — the exact mirror-shape the
# test-integrity gate exists to catch.  explore/review carry 0.75 of the
# window, matching the built-in profiles' fraction for those modes.
_GEMMA_OVERLAY = {
    "work": {"context_budget_tokens": _GEMMA_BUDGET},
    "plan": {"context_budget_tokens": _GEMMA_BUDGET},
    "explore": {"context_budget_tokens": 72000},
    "review": {"context_budget_tokens": 72000},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gemma_repo(tmp_path: Path) -> Path:
    """Create a temp repo with a per-model overlay for the Gemma model."""
    overlay_dir = tmp_path / ".colleague" / _GEMMA_SAFE
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "profiles.json").write_text(
        json.dumps(_GEMMA_OVERLAY),
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: Per-model overlay yields the expected budget
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("work", _GEMMA_BUDGET),
        ("plan", _GEMMA_BUDGET),
        ("explore", 72000),
        ("review", 72000),
    ],
)
def test_per_model_overlay_sets_gemma_budget(gemma_repo: Path, mode: str, expected: int) -> None:
    """A per-model overlay for the Gemma model id sets context_budget_tokens.

    Uses the REAL mode names — the only names a live run ever passes.
    """
    config = EngineConfig(model=_GEMMA_MODEL)
    applied = apply_mode_profile(
        config,
        mode=mode,
        repo_path=gemma_repo,
    )
    assert applied.context_budget_tokens == expected


def test_per_model_overlay_is_exact_path(gemma_repo: Path) -> None:
    """The overlay only applies to the exact sanitized model id."""
    # A different model should NOT pick up the Gemma overlay; the built-in
    # work profile is behavior-neutral (fraction 1.0), so the default holds.
    config = EngineConfig(model="other/model")
    applied = apply_mode_profile(
        config,
        mode="work",
        repo_path=gemma_repo,
    )
    # Falls back to default since no overlay for "other-model"
    assert applied.context_budget_tokens == _DEFAULT_CONTEXT_BUDGET


def test_modeless_run_ignores_overlay(gemma_repo: Path) -> None:
    """A bare modeless run keeps the default even WITH the overlay present.

    This is the staged-not-flipped pin: profiles fire only when a mode is
    selected (``apply_mode_profile`` is a strict no-op for ``mode=None``), so
    staging Gemma via the overlay can never drift a bare run's budget.
    """
    config = EngineConfig(model=_GEMMA_MODEL)
    applied = apply_mode_profile(config, mode=None, repo_path=gemma_repo)
    assert applied.context_budget_tokens == _DEFAULT_CONTEXT_BUDGET


# ---------------------------------------------------------------------------
# Test 2: Default resolve without overlay stays at 131072
# ---------------------------------------------------------------------------


def test_default_budget_without_overlay(tmp_path: Path) -> None:
    """Bare default resolve yields the built-in 131072 budget (no drift)."""
    # No .colleague/ directory at all
    config = EngineConfig()
    applied = apply_mode_profile(config, mode=None)
    assert applied.context_budget_tokens == _DEFAULT_CONTEXT_BUDGET
    assert _DEFAULT_CONTEXT_BUDGET == 131072


def test_default_budget_with_empty_repo(tmp_path: Path) -> None:
    """Even with an empty .colleague/ directory, default budget holds."""
    (tmp_path / ".colleague").mkdir()
    config = EngineConfig()
    applied = apply_mode_profile(
        config,
        mode=None,
        repo_path=tmp_path,
    )
    assert applied.context_budget_tokens == _DEFAULT_CONTEXT_BUDGET


# ---------------------------------------------------------------------------
# Test 3: No "gemma" string in colleague/ source code
# ---------------------------------------------------------------------------


def test_no_gemma_in_source_code() -> None:
    """No file under colleague/ contains 'gemma' in executable source code.

    The string is allowed in comments and docstrings (where it documents the
    staged-but-not-flipped status), but must not appear as an identifier,
    string literal, or other code token.
    """
    colleague_root = Path(__file__).resolve().parent.parent / "colleague"
    violations: list[tuple[str, int, str]] = []

    for py_file in sorted(list(colleague_root.glob("*.py")) + list(colleague_root.glob("**/*.py"))):
        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            continue

        tree = ast.parse(source)
        lines = source.splitlines()

        for node in ast.walk(tree):
            # Check string constants in the AST (not comments/docstrings)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "gemma" in node.value.lower():
                    # Found in a string literal — record it
                    line_text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    violations.append(
                        (str(py_file.relative_to(colleague_root)), node.lineno, line_text.strip())
                    )
            # Check names (identifiers)
            elif isinstance(node, ast.Name) and "gemma" in node.id.lower():
                line_text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                violations.append(
                    (str(py_file.relative_to(colleague_root)), node.lineno, line_text.strip())
                )
            # Check attribute access targets
            elif isinstance(node, ast.Attribute) and isinstance(node.attr, str):
                if "gemma" in node.attr.lower():
                    line_text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    violations.append(
                        (str(py_file.relative_to(colleague_root)), node.lineno, line_text.strip())
                    )

    assert not violations, "Found 'gemma' in source code (not comments/docstrings):\n" + "\n".join(
        f"  {f}:{l}: {t}" for f, l, t in violations
    )


def test_gemma_safe_dir_name() -> None:
    """Verify the sanitized model directory name for the Gemma model."""
    assert _GEMMA_SAFE == "coolthor-gemma-4-12B-it-NVFP4A16"


def test_gemma_overlay_json_structure(gemma_repo: Path) -> None:
    """The overlay JSON keys real mode names for the profiles seam."""
    overlay_file = gemma_repo / ".colleague" / _GEMMA_SAFE / "profiles.json"
    data = json.loads(overlay_file.read_text(encoding="utf-8"))
    assert "work" in data
    assert data["work"]["context_budget_tokens"] == _GEMMA_BUDGET
    # Guard against the vacuous key returning: no real run passes a
    # "default" mode, so the recipe must never document one.
    assert "default" not in data

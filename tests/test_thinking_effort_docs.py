"""Doc pins for the per-seat thinking-effort feature doc (#416 t10).

Covers spec targets c12, h7, c16, h12, c19, h15, c18, h14, c17, h13.

The v3 default table is written ONCE in docs/features/thinking-effort.md and
referenced (pointer, not duplicate) from CLAUDE.md and the sibling feature
docs. These tests pin that the feature doc renders the table row-for-row with
tests/test_effort.py, that the honest limits are recorded, and that the
pointer edits landed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from colleague import effort

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURE_DOC = REPO_ROOT / "docs" / "features" / "thinking-effort.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
ENGINES_MD = REPO_ROOT / "docs" / "features" / "engines.md"
DEEPTHINK_MD = REPO_ROOT / "docs" / "features" / "deepthink.md"
CONFIG_RESOLUTION_MD = REPO_ROOT / "docs" / "features" / "config-resolution.md"
SUBAGENT_ROLES_MD = REPO_ROOT / "docs" / "features" / "subagent-roles.md"


def _read(path: Path) -> str:
    assert path.exists(), f"missing doc: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# c12/h7 — the feature doc exists and names both readers (operator + seat table)
# ---------------------------------------------------------------------------


def test_feature_doc_exists_and_names_both_readers() -> None:
    text = _read(FEATURE_DOC)
    assert "operator" in text.lower()
    assert "seat" in text.lower()


# ---------------------------------------------------------------------------
# c16/h12 — the v3 table renders row-for-row with tests/test_effort.py
# ---------------------------------------------------------------------------


def _table_rows() -> list[tuple[str, str]]:
    """Every (key, rung) row the parametrized pin asserts, in one flat list."""
    rows: list[tuple[str, str]] = []
    for table in (
        effort.SEAT_TABLE,
        effort.ROLE_TABLE,
        effort.TOP_LEVEL_ROLE_TABLE,
        effort.TOP_LEVEL_MODE_TABLE,
        effort.DESIGN_SITE_TABLE,
    ):
        for key, rung in table.items():
            rows.append((key, rung))
    return rows


@pytest.mark.parametrize("key,rung", _table_rows())
def test_feature_doc_renders_every_table_row(key: str, rung: str) -> None:
    text = _read(FEATURE_DOC)
    # The row must appear as a markdown table cell pair: | `key` | `rung` |
    # (design call-sites use dotted keys, which are also backticked).
    pattern = re.compile(r"\|\s*`" + re.escape(key) + r"`\s*\|\s*`" + re.escape(rung) + r"`\s*\|")
    assert pattern.search(text), f"feature doc does not render the row | `{key}` | `{rung}` |"


def test_feature_doc_table_is_not_a_duplicate_elsewhere() -> None:
    # CLAUDE.md trim discipline: pointer, not duplicate. The full seat table
    # (all six persistent seats as backticked rows) must NOT be re-rendered in
    # CLAUDE.md — it points at thinking-effort.md instead.
    claude = _read(CLAUDE_MD)
    assert "thinking-effort.md" in claude
    # No CLAUDE.md line renders a seat-table row like | `cortex` | `medium` |.
    assert not re.search(r"\|\s*`cortex`\s*\|\s*`medium`\s*\|", claude)


# ---------------------------------------------------------------------------
# c18/h14 — precedence order + kill-switch are documented
# ---------------------------------------------------------------------------


def test_feature_doc_documents_precedence_order() -> None:
    text = _read(FEATURE_DOC)
    # The six precedence rungs, in order.
    for token in (
        "kill-switch",
        "parent override",
        "per-seat",
        "role table",
        "seat table",
        "unset",
    ):
        assert token in text.lower(), f"precedence rung missing: {token}"
    # The order is one documented function.
    assert "resolve_effort" in text


def test_feature_doc_documents_kill_switch() -> None:
    text = _read(FEATURE_DOC)
    assert "COLLEAGUE_REASONING_EFFORT=default" in text
    assert "reasoning_effort" in text
    # The kill switch forces every seat to unset / byte-identical.
    assert "byte-identical" in text


# ---------------------------------------------------------------------------
# c19/h15 — ladder-400 degrade is documented
# ---------------------------------------------------------------------------


def test_feature_doc_documents_ladder_400_degrade() -> None:
    text = _read(FEATURE_DOC)
    assert "400" in text
    assert "retried" in text.lower() or "retry" in text.lower()
    # The degrade names the seat + the server's supported ladder.
    assert "warning" in text.lower()
    # Disjoint from the stale-pin 404 refresh.
    assert "404" in text


# ---------------------------------------------------------------------------
# h13 — the probe record + #417 scope limits under 'Honest limits'
# ---------------------------------------------------------------------------


def test_feature_doc_honest_limits_records_probe_and_417() -> None:
    text = _read(FEATURE_DOC)
    assert "Honest limits" in text
    # The probe is recorded with its n=1 limit.
    assert "n=1" in text
    # #417 scope limits are cited.
    assert "#417" in text
    # 'high' == 'xhigh' on Qwen3.8 is recorded honestly.
    assert "Qwen3.8" in text
    assert "verbatim" in text.lower()
    # effort x tool-calling rests on the t11 arm.
    assert "t11" in text
    # #415 is cited.
    assert "#415" in text


# ---------------------------------------------------------------------------
# c17/h13 — CLAUDE.md: THREE carve-outs + a new architecture bullet
# ---------------------------------------------------------------------------


def test_claude_md_reads_three_carve_outs() -> None:
    text = _read(CLAUDE_MD)
    # The convention sentence now reads THREE carve-outs.
    assert "THREE" in text
    # All three carve-outs are named.
    assert "/tokenize" in text
    assert "stale-pin" in text
    assert "chat_template_kwargs" in text


def test_claude_md_has_thinking_effort_architecture_bullet() -> None:
    text = _read(CLAUDE_MD)
    # A new architecture bullet points at thinking-effort.md.
    assert "thinking-effort.md" in text
    # The bullet names the feature.
    assert "Thinking effort" in text or "thinking effort" in text


# ---------------------------------------------------------------------------
# c16/h12 — the sibling docs are updated (pointer, not duplicate)
# ---------------------------------------------------------------------------


def test_engines_md_mentions_third_carve_out() -> None:
    text = _read(ENGINES_MD)
    assert "chat_template_kwargs" in text
    assert "thinking-effort.md" in text


def test_deepthink_md_notes_xhigh_default() -> None:
    text = _read(DEEPTHINK_MD)
    # The four-point surface notes the xhigh default.
    assert "xhigh" in text
    assert "thinking-effort.md" in text


def test_config_resolution_md_documents_new_knobs() -> None:
    text = _read(CONFIG_RESOLUTION_MD)
    assert "COLLEAGUE_REASONING_EFFORT" in text
    assert "reasoning_effort_seats" in text
    assert "thinking-effort.md" in text


def test_subagent_roles_md_documents_role_effort() -> None:
    text = _read(SUBAGENT_ROLES_MD)
    assert "effort" in text.lower()
    assert "thinking-effort.md" in text

"""The P3 size-trigger arm's two staged overlays (plan t3).

``docs/plans/2026-08-30-delegation-follow-ups-a7-p3-hire.md`` task t3 (covers
c7, h4).

The P3 arm asks one question: does an explicit SIZE TRIGGER move delegation on
a clean control? The two overlays are the manipulated variable and nothing
else:

* **P2-0** (control) — P2's ``effort: medium`` line + P2's FIRST paragraph
  (the true peer-seat framing on this rig), byte-for-byte, and no instruction
  at all. It is the clean control for the large-surface brief: P2's first
  paragraph alone.
* **P3** (trigger) — P2-0 plus EXACTLY ONE added sentence carrying an explicit
  size trigger that names ``code_survey``.

So ``diff -u P2-0 P3`` is exactly one ``+`` content line — the trigger
sentence. Anything else in that diff would be a confound and would invalidate
the arm.

**Staged, never shipped.** Both files live under ``docs/live-testing/overlays/``
— NOT under ``.colleague/agents/`` — so their presence cannot change a default
run here. The trigger sentence must not leak into the shipped writer fragment
(``BUILTIN_ROLES['writer'].prompt_fragment``) or the prompt snapshot
(``tests/snapshots/prompttext_v1.txt``); until promotion it lives ONLY in the
overlay.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from colleague.roles import BUILTIN_ROLES

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_DIR = REPO_ROOT / "docs" / "live-testing" / "overlays"

#: The trigger sentence, verbatim from spec c7.
TRIGGER = (
    "When the survey does not fit in one pass, hand parts of it to "
    "`code_survey` and review the digests before you act."
)


def _read(arm: str) -> str:
    path = OVERLAY_DIR / arm / "writer.md"
    assert path.is_file(), f"missing overlay: {path}"
    return path.read_text(encoding="utf-8")


def _effort_and_body(text: str) -> "tuple[str, str]":
    """Split an overlay into its leading ``effort: <rung>`` line and body."""
    lines = text.split("\n")
    assert lines[0].startswith("effort: "), "overlay must lead with an 'effort:' line"
    return lines[0], "\n".join(lines[1:])


# ---------------------------------------------------------------------------
# (a) P2-0 is P2's head, byte-for-byte: the effort line + first paragraph
# ---------------------------------------------------------------------------


def test_p2_0_is_p2s_head_byte_for_byte() -> None:
    p2 = _read("P2")
    p2_0 = _read("P2-0")
    # P2-0 is a strict prefix of P2 (the head), and P2 continues past it.
    assert p2.startswith(p2_0)
    assert p2 != p2_0
    # P2-0 is exactly the effort line + P2's first paragraph, nothing more.
    p2_parts = p2.split("\n\n")
    first_para = p2_parts[1]
    # v4 (#475): the acting default the staged arms pin moved medium -> low.
    assert p2_0 == "effort: low\n\n" + first_para + "\n"


def test_p2_0_carries_no_instruction_paragraph() -> None:
    """The control is the framing ALONE — no imperative paragraph, or the arm
    is confounded against P3."""
    _, body = _effort_and_body(_read("P2-0"))
    paragraphs = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    assert len(paragraphs) == 1


def test_p2_0_pins_the_acting_seat_default_rung() -> None:
    effort, _ = _effort_and_body(_read("P2-0"))
    # v4 (#475): the acting default the staged arms pin moved medium -> low.
    assert effort == "effort: low"


# ---------------------------------------------------------------------------
# (b) P3 diffs against P2-0 by exactly one added trigger sentence
# ---------------------------------------------------------------------------


def test_p3_diffs_against_p2_0_by_exactly_one_plus_line() -> None:
    p2_0 = _read("P2-0")
    p3 = _read("P3")
    diff = list(
        difflib.unified_diff(
            p2_0.splitlines(keepends=True),
            p3.splitlines(keepends=True),
            fromfile="P2-0/writer.md",
            tofile="P3/writer.md",
        )
    )
    plus_lines = [line for line in diff if line.startswith("+") and not line.startswith("+++")]
    assert len(plus_lines) == 1, f"expected exactly one '+' content line, got: {plus_lines}"
    # No deletions or changes — P3 is P2-0 with one line appended.
    minus_lines = [line for line in diff if line.startswith("-") and not line.startswith("---")]
    assert minus_lines == []


def test_p3_added_line_is_the_verbatim_trigger() -> None:
    p2_0 = _read("P2-0")
    p3 = _read("P3")
    diff = list(
        difflib.unified_diff(
            p2_0.splitlines(keepends=True),
            p3.splitlines(keepends=True),
        )
    )
    plus_lines = [line for line in diff if line.startswith("+") and not line.startswith("+++")]
    assert len(plus_lines) == 1
    assert plus_lines[0][1:].rstrip("\n") == TRIGGER


def test_p3_trigger_names_code_survey_and_carries_a_size_trigger() -> None:
    p3 = _read("P3")
    assert "code_survey" in p3
    # The explicit size trigger: the survey not fitting in one pass.
    assert "does not fit in one pass" in p3


def test_p3_is_p2_0_plus_the_trigger() -> None:
    p2_0 = _read("P2-0")
    p3 = _read("P3")
    assert p3.startswith(p2_0)
    assert p3 == p2_0 + TRIGGER + "\n"


# ---------------------------------------------------------------------------
# (c) staged, never shipped: the trigger does not leak into the defaults
# ---------------------------------------------------------------------------


def test_trigger_is_not_in_the_builtin_writer_fragment() -> None:
    fragment = BUILTIN_ROLES["writer"].prompt_fragment
    assert TRIGGER not in fragment
    assert "does not fit in one pass" not in fragment


def test_trigger_is_not_in_the_prompt_snapshot() -> None:
    snapshot = (REPO_ROOT / "tests" / "snapshots" / "prompttext_v1.txt").read_text(encoding="utf-8")
    assert TRIGGER not in snapshot
    assert "does not fit in one pass" not in snapshot


def test_overlays_are_staged_not_shipped() -> None:
    """Both files live under ``docs/``, not ``.colleague/agents/`` — so a bare
    run at this repo composes the pre-arm prompt, not one byte of either."""
    assert not (REPO_ROOT / ".colleague" / "agents" / "writer.md").exists()
    for arm in ("P2-0", "P3"):
        assert (OVERLAY_DIR / arm / "writer.md").is_file()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

"""Tests for :mod:`colleague.truncation` (task t11, decisions c10/h8/c50).

adapted-from: qwen-code packages/core/src/tools/truncation.ts:22,200-296, tools/shell.ts:91-112

Each test proves one acceptance criterion from the plan verbatim:

* head+tail truncation + spill-to-disk, 0o600, spilled content == original;
* the c50 per-tool-default-beneath-ceiling knob precedence, including the
  exact case ``COLLEAGUE_MAX_OUTPUT_CHARS=100000`` leaving ``read_file`` at
  25000;
* the 500 MB session spill cap (a recorded ``RuntimeWarning`` + a head+tail
  fallback) and the ``COLLEAGUE_TOOL_SPILL=0`` disable switch.

``tests/conftest.py`` scrubs every ``COLLEAGUE_*`` env var before each test
(autouse); this file uses ``monkeypatch.setenv`` for anything it needs set,
per repo convention. The module-level session spill counter is reset before
and after every test via an autouse fixture so tests never see each other's
spilled bytes.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from colleague import truncation


@pytest.fixture(autouse=True)
def _reset_spill_counter():
    truncation.reset_session_spill_bytes()
    yield
    truncation.reset_session_spill_bytes()


def _make_lines(n: int) -> str:
    return "\n".join(f"L{i}" for i in range(n))


# --------------------------------------------------------------------------
# truncate_output: head+tail + spill-to-disk
# --------------------------------------------------------------------------


def test_within_budget_returns_unchanged_and_spills_nothing(tmp_path: Path):
    text = "short output\nline two"
    spill_dir = tmp_path / "tool-output"

    result = truncation.truncate_output(text, max_chars=1000, max_lines=100, spill_dir=spill_dir)

    assert result == text
    assert not spill_dir.exists()


def test_truncate_output_keeps_head_and_tail(tmp_path: Path):
    text = _make_lines(200)  # "L0" .. "L199"
    spill_dir = tmp_path / "tool-output"

    result = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    # Head and tail survive; a middle line does not.
    assert "L0" in result
    assert "L1" in result
    assert "L199" in result
    assert "L192" in result
    assert "L100" not in result
    assert "CONTENT TRUNCATED" in result
    # finding #441-9 / B: the returned string (trailer + preview) itself
    # respects both budgets — not just the internal preview.
    assert len(result) <= 2000
    assert result.count("\n") + 1 <= 30


def test_truncate_output_spills_full_text_with_0o600(tmp_path: Path):
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    result = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    # The result names the spilled file's absolute path.
    files = list(spill_dir.glob("*.txt"))
    assert len(files) == 1
    spilled = files[0]
    assert str(spilled.resolve()) in result
    assert spilled.is_absolute()

    # Spilled content is byte-for-byte the original, untouched text.
    assert spilled.read_text(encoding="utf-8") == text

    # Mode is owner-only (0o600).
    mode = stat.S_IMODE(spilled.stat().st_mode)
    assert mode == 0o600

    # finding #441-9 / B: the trailer (with the spilled path) + preview
    # together still respect both budgets.
    assert len(result) <= 2000
    assert result.count("\n") + 1 <= 30


def test_spilled_file_named_by_content_hash(tmp_path: Path):
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    files = list(spill_dir.glob("*.txt"))
    assert len(files) == 1
    import hashlib

    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert files[0].name == f"{expected}.txt"


# --------------------------------------------------------------------------
# c50: per-tool defaults + COLLEAGUE_MAX_OUTPUT_CHARS as a ceiling
# --------------------------------------------------------------------------


def test_default_budgets_with_no_env_set():
    assert truncation.resolve_max_chars("read_file") == 25_000
    assert truncation.resolve_max_chars("write_file") == 25_000
    assert truncation.resolve_max_chars("run_command") == 30_000
    assert truncation.resolve_max_lines() == 1_000


def test_c50_ceiling_leaves_read_file_at_its_default(monkeypatch):
    """Decision c50, verbatim case: a large ceiling does not raise the
    per-tool default — it can only lower it."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "100000")

    assert truncation.resolve_max_chars("read_file") == 25_000
    # run_command's own 30000 default is likewise untouched by the looser ceiling.
    assert truncation.resolve_max_chars("run_command") == 30_000


def test_ceiling_does_lower_an_oversized_per_tool_value(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "10000")

    assert truncation.resolve_max_chars("read_file") == 10_000
    assert truncation.resolve_max_chars("run_command") == 10_000


def test_per_tool_override_beneath_ceiling(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "100000")
    monkeypatch.setenv("COLLEAGUE_READ_MAX_CHARS", "5000")

    assert truncation.resolve_max_chars("read_file") == 5_000
    # Unrelated tool (run_command) is unaffected by the read-only override.
    assert truncation.resolve_max_chars("run_command") == 30_000


def test_per_tool_override_still_bounded_by_a_tighter_ceiling(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "20000")
    monkeypatch.setenv("COLLEAGUE_SHELL_MAX_CHARS", "50000")

    # The override raises run_command's budget, but the ceiling still wins.
    assert truncation.resolve_max_chars("run_command") == 20_000


def test_shell_max_chars_env_only_affects_run_command(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_SHELL_MAX_CHARS", "12345")

    assert truncation.resolve_max_chars("run_command") == 12_345
    assert truncation.resolve_max_chars("read_file") == 25_000


# --------------------------------------------------------------------------
# session cap (500 MB) + COLLEAGUE_TOOL_SPILL=0
# --------------------------------------------------------------------------


def test_session_cap_stops_spilling_with_recorded_warning(tmp_path: Path, monkeypatch):
    # Shrink the cap so a small payload already exceeds it, without needing
    # to actually allocate/write 500 MB in a test.
    monkeypatch.setattr(truncation, "MAX_SESSION_SPILL_BYTES", 10)
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    with pytest.warns(RuntimeWarning, match="session tool-output spill budget"):
        result = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    # Fell back to head+tail only: nothing written, no path named.
    assert not spill_dir.exists() or not list(spill_dir.glob("*.txt"))
    assert "L0" in result
    assert "L199" in result
    assert "saved to:" not in result
    assert truncation.session_bytes_spilled() == 0


def test_session_cap_is_tracked_across_calls(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        truncation, "MAX_SESSION_SPILL_BYTES", len(_make_lines(200).encode("utf-8")) + 5
    )
    spill_dir = tmp_path / "tool-output"
    text = _make_lines(200)

    first = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)
    assert "saved to:" in first
    spent_after_first = truncation.session_bytes_spilled()
    assert spent_after_first > 0

    # A second spill of the same size now exceeds the (small) remaining budget.
    with pytest.warns(RuntimeWarning):
        second = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)
    assert "saved to:" not in second
    assert truncation.session_bytes_spilled() == spent_after_first


def test_reset_session_spill_bytes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(truncation, "MAX_SESSION_SPILL_BYTES", 10)
    truncation._session_bytes_spilled = 999
    truncation.reset_session_spill_bytes()
    assert truncation.session_bytes_spilled() == 0


def test_tool_spill_disabled_falls_back_to_head_and_tail_only(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COLLEAGUE_TOOL_SPILL", "0")
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    result = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    assert not spill_dir.exists()
    assert "L0" in result
    assert "L199" in result
    assert "L100" not in result
    assert "saved to:" not in result
    assert truncation.session_bytes_spilled() == 0
    # finding #441-9 / B
    assert len(result) <= 2000
    assert result.count("\n") + 1 <= 30


def test_tool_spill_env_other_values_leave_spilling_enabled(tmp_path: Path, monkeypatch):
    # Only the literal "0"/"false"/"False" strings disable; anything else
    # (e.g. "1") leaves spilling on.
    monkeypatch.setenv("COLLEAGUE_TOOL_SPILL", "1")
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    result = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    assert "saved to:" in result
    assert list(spill_dir.glob("*.txt"))


# --------------------------------------------------------------------------
# finding #441-9 / B: the returned string (trailer + preview), not just the
# internal preview, must respect max_chars/max_lines — on every branch.
# --------------------------------------------------------------------------


def test_truncation_respects_small_budget_when_spill_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COLLEAGUE_TOOL_SPILL", "0")
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    result = truncation.truncate_output(text, max_chars=200, max_lines=15, spill_dir=spill_dir)

    assert len(result) <= 200
    assert result.count("\n") + 1 <= 15
    assert "saved to:" not in result


def test_truncation_respects_small_budget_when_session_cap_exceeded(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(truncation, "MAX_SESSION_SPILL_BYTES", 10)
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    with pytest.warns(RuntimeWarning):
        result = truncation.truncate_output(text, max_chars=200, max_lines=15, spill_dir=spill_dir)

    assert len(result) <= 200
    assert result.count("\n") + 1 <= 15
    assert "saved to:" not in result


def test_truncation_respects_small_budget_when_spilled_to_disk(tmp_path: Path):
    text = _make_lines(200)
    spill_dir = tmp_path / "tool-output"

    result = truncation.truncate_output(text, max_chars=500, max_lines=20, spill_dir=spill_dir)

    assert "saved to:" in result
    assert len(result) <= 500
    assert result.count("\n") + 1 <= 20


# --------------------------------------------------------------------------
# finding #441-5 / A: a pre-planted symlink at the predictable digest path
# must never be written through or chmod-ed.
# --------------------------------------------------------------------------


def test_spill_refuses_to_follow_a_preplanted_symlink(tmp_path: Path):
    import hashlib

    text = _make_lines(200)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spill_dir = tmp_path / "tool-output"
    spill_dir.mkdir(parents=True)

    # A file OUTSIDE the spill dir the attacker wants overwritten/chmod-ed.
    victim = tmp_path / "victim.txt"
    victim.write_text("do not touch me", encoding="utf-8")
    victim_mode_before = stat.S_IMODE(victim.stat().st_mode)

    # Pre-plant a symlink at the exact predictable digest path.
    planted = spill_dir / f"{digest}.txt"
    planted.symlink_to(victim)

    result = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    # The victim file is completely untouched: same content, same mode.
    assert victim.read_text(encoding="utf-8") == "do not touch me"
    assert stat.S_IMODE(victim.stat().st_mode) == victim_mode_before

    # The planted symlink itself is left alone (never written through).
    assert planted.is_symlink()

    # colleague wrote its spill content under a FRESH, non-symlink name
    # instead, and that file — not the symlink — is what the result names.
    real_files = [p for p in spill_dir.glob("*.txt") if not p.is_symlink()]
    assert len(real_files) == 1
    fresh = real_files[0]
    assert fresh.name != planted.name
    assert str(fresh.resolve()) in result
    assert fresh.read_text(encoding="utf-8") == text
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o600


def test_spill_reuses_existing_regular_file_with_matching_content(tmp_path: Path):
    """A same-content collision on the digest path (two tools spilling
    byte-identical output) is reused rather than duplicated — only a
    symlink (or mismatched content) forces a fresh name."""
    import hashlib

    text = _make_lines(200)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spill_dir = tmp_path / "tool-output"
    spill_dir.mkdir(parents=True)

    existing = spill_dir / f"{digest}.txt"
    existing.write_bytes(text.encode("utf-8"))
    os.chmod(existing, 0o600)

    result = truncation.truncate_output(text, max_chars=2000, max_lines=30, spill_dir=spill_dir)

    files = list(spill_dir.glob("*.txt"))
    assert len(files) == 1
    assert files[0] == existing
    assert str(existing.resolve()) in result

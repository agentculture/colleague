"""Tests for colleague/editmatch.py (t6, c9/h7).

adapted-from: qwen-code packages/core/src/utils/editHelper.ts:313-380,
tools/priorReadEnforcement.ts
"""

from __future__ import annotations

import sys

import pytest

from colleague.editmatch import AmbiguousEditMatch, ReadSet, normalize_edit_strings

# --------------------------------------------------------------------------
# normalize_edit_strings
# --------------------------------------------------------------------------


def test_exact_match_already_succeeds_returns_none() -> None:
    text = "line one\nline two\nline three\n"
    # old_string is found verbatim -> the caller's exact path already
    # succeeds; normalize_edit_strings must not do any work here.
    assert normalize_edit_strings(text, "line two", "replaced") is None


def test_empty_old_string_returns_none() -> None:
    assert normalize_edit_strings("some text", "", "new") is None


def test_smart_quotes_relax_to_ascii_and_return_ondisk_slice() -> None:
    # On-disk file uses straight ASCII quotes; the proposed old_string uses
    # curly/smart quotes an LLM might emit instead.
    text = 'greeting = "hello there"\nfarewell = "goodbye"\n'
    old = "greeting = “hello there”"
    result = normalize_edit_strings(text, old, "greeting = 'hi'")
    assert result is not None
    canonical_old, new = result
    # The canonical slice returned is the literal ASCII text from disk, not
    # the smart-quoted string the caller proposed.
    assert canonical_old == 'greeting = "hello there"'
    # new_string is returned completely untouched.
    assert new == "greeting = 'hi'"


def test_new_string_is_never_rewritten() -> None:
    text = "value = ‘straight’\n"
    old = "value = 'straight'"
    # Disk has smart quotes, old_string (proposed) uses ASCII quotes ->
    # still a relaxed match, and new_string (itself containing trailing
    # whitespace) must come back byte-for-byte.
    new_with_trailing_ws = "value = 'updated'   \n"
    result = normalize_edit_strings(text, old, new_with_trailing_ws)
    assert result is not None
    canonical_old, new = result
    assert canonical_old == "value = ‘straight’"
    assert new == new_with_trailing_ws  # untouched, including trailing spaces


def test_per_line_leading_and_trailing_whitespace_trim_indent_drifted() -> None:
    text = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"
    # old_string has different (drifted) indentation than the file.
    old = "def foo():\n  return 1"
    result = normalize_edit_strings(text, old, "def foo():\n    return 42")
    assert result is not None
    canonical_old, new = result
    assert canonical_old == "def foo():\n    return 1"
    assert new == "def foo():\n    return 42"


def test_trailing_whitespace_only_drift_lands() -> None:
    text = "alpha\nbeta   \ngamma\n"
    old = "alpha\nbeta\ngamma"
    result = normalize_edit_strings(text, old, "alpha\nBETA\ngamma")
    assert result is not None
    canonical_old, _new = result
    assert canonical_old == "alpha\nbeta   \ngamma"


def test_crlf_drifted_old_string_lands() -> None:
    # File on disk uses CRLF line endings; the proposed old_string uses
    # plain LF.
    text = "first line\r\nsecond line\r\nthird line\r\n"
    old = "second line\nthird line"
    result = normalize_edit_strings(text, old, "SECOND\nTHIRD")
    assert result is not None
    canonical_old, new = result
    # The canonical slice preserves the file's real CRLF endings.
    assert canonical_old == "second line\r\nthird line"
    assert new == "SECOND\nTHIRD"


def test_crlf_old_string_matches_lf_disk_content() -> None:
    text = "first line\nsecond line\nthird line\n"
    old = "second line\r\nthird line"
    result = normalize_edit_strings(text, old, "replacement")
    assert result is not None
    canonical_old, _new = result
    assert canonical_old == "second line\nthird line"


def test_two_relaxed_matches_raise_ambiguity_error() -> None:
    # Two identical indent-drifted blocks: the exact substring check fails
    # (disk uses 4-space indent, old_string uses 2-space), and the relaxed
    # per-line-trim pass finds the SAME snippet at two separate locations.
    text = "if True:\n    do_something()\n\nif True:\n    do_something()\n"
    old = "if True:\n  do_something()"
    with pytest.raises(AmbiguousEditMatch) as excinfo:
        normalize_edit_strings(text, old, "new-body")
    assert excinfo.value.count == 2
    # The error message names the count, echoing colleague's existing
    # exact-match ambiguity message style in colleague/tools.py.
    assert "2" in str(excinfo.value)


def test_no_relaxed_match_returns_none() -> None:
    text = "alpha\nbeta\ngamma\n"
    old = "this text does not exist anywhere in the file"
    assert normalize_edit_strings(text, old, "new") is None


def test_no_relaxed_match_when_old_longer_than_haystack() -> None:
    text = "one line\n"
    old = "line one\nline two\nline three\nline four\n"
    assert normalize_edit_strings(text, old, "new") is None


def test_single_line_no_trailing_newline_slice_excludes_terminator() -> None:
    text = "keep this\nEDIT ME\nkeep that\n"
    old = "  EDIT ME  "  # whitespace-drifted, no trailing newline
    result = normalize_edit_strings(text, old, "replacement")
    assert result is not None
    canonical_old, _new = result
    assert canonical_old == "EDIT ME"


def test_old_string_with_trailing_newline_includes_terminator_in_slice() -> None:
    text = "keep this\nEDIT ME\nkeep that\n"
    old = "  EDIT ME  \n"  # whitespace-drifted, WITH trailing newline
    result = normalize_edit_strings(text, old, "replacement\n")
    assert result is not None
    canonical_old, _new = result
    assert canonical_old == "EDIT ME\n"


def test_last_line_of_file_with_no_trailing_newline() -> None:
    text = "keep this\nEDIT ME"  # no trailing newline at EOF
    old = "  EDIT ME  "
    result = normalize_edit_strings(text, old, "replacement")
    assert result is not None
    canonical_old, _new = result
    assert canonical_old == "EDIT ME"


def test_ambiguity_error_is_a_value_error() -> None:
    # So a caller that only catches ValueError still gets it.
    assert issubclass(AmbiguousEditMatch, ValueError)


def test_no_llm_or_engine_import_in_module() -> None:
    """Guards the acceptance criterion: no LLM call, no import of an engine."""
    import colleague.editmatch as mod

    src_path = mod.__file__
    assert src_path is not None
    source = open(src_path, encoding="utf-8").read()
    forbidden = ["colleague.engines", "colleague.engine", "openai", "anthropic"]
    lowered = source.lower()
    for token in forbidden:
        assert token.lower() not in lowered, f"unexpected import/reference: {token}"


def test_module_has_no_third_party_imports() -> None:
    """stdlib only — the module must not pull in anything beyond the stdlib."""
    import colleague.editmatch as mod

    assert "colleague.editmatch" in sys.modules
    # A crude but effective guard: everything imported at module scope maps
    # to a stdlib name (dataclasses, typing) plus nothing else.
    import dis

    src_path = mod.__file__
    assert src_path is not None
    source = open(src_path, encoding="utf-8").read()
    assert "import" in source  # sanity: file does import something (dataclasses/typing)
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert stripped.split()[1].split(".")[0] in {
                "dataclasses",
                "typing",
                "__future__",
            }, f"non-stdlib import found: {stripped}"
    del dis  # imported only to demonstrate stdlib-only introspection is fine


# --------------------------------------------------------------------------
# ReadSet
# --------------------------------------------------------------------------


def test_readset_full_read_covers_any_span() -> None:
    rs = ReadSet()
    rs.record_full("colleague/tools.py", total_lines=1508)
    assert rs.is_read_for_edit("colleague/tools.py", 1, 1508) is True
    assert rs.is_read_for_edit("colleague/tools.py", 500, 501) is True


def test_readset_record_whole_file_range_counts_as_full() -> None:
    rs = ReadSet()
    rs.record("foo.py", start_line=1, end_line=42, total_lines=42)
    assert rs.is_read_for_edit("foo.py", 10, 20) is True
    # Even a span the recorded range technically starts before/ends after
    # is fine since it was a full-file read.
    assert rs.is_read_for_edit("foo.py", 1, 42) is True


def test_readset_paged_read_covers_only_shown_lines() -> None:
    rs = ReadSet()
    # A paged/truncated read only showed lines 1-50 of a 200-line file.
    rs.record("big.py", start_line=1, end_line=50, total_lines=200)
    assert rs.is_read_for_edit("big.py", 10, 30) is True
    # A span outside the shown window was NOT read.
    assert rs.is_read_for_edit("big.py", 60, 70) is False
    assert rs.is_read_for_edit("big.py", 40, 60) is False  # partially outside


def test_readset_unread_path_is_false() -> None:
    rs = ReadSet()
    assert rs.is_read_for_edit("never/touched.py", 1, 1) is False


def test_readset_disjoint_partial_reads_do_not_combine() -> None:
    rs = ReadSet()
    rs.record("f.py", start_line=1, end_line=10, total_lines=100)
    rs.record("f.py", start_line=20, end_line=30, total_lines=100)
    # Span straddling the gap between the two reads was never actually shown
    # in one contiguous read.
    assert rs.is_read_for_edit("f.py", 5, 25) is False
    # But a span fully inside either individual read is covered.
    assert rs.is_read_for_edit("f.py", 2, 8) is True
    assert rs.is_read_for_edit("f.py", 22, 28) is True


def test_readset_middle_paged_read_excludes_earlier_and_later_lines() -> None:
    rs = ReadSet()
    rs.record("mid.py", start_line=51, end_line=100, total_lines=200)
    assert rs.is_read_for_edit("mid.py", 60, 90) is True
    assert rs.is_read_for_edit("mid.py", 1, 50) is False
    assert rs.is_read_for_edit("mid.py", 101, 150) is False


def test_readset_multiple_paths_are_independent() -> None:
    rs = ReadSet()
    rs.record_full("a.py", total_lines=10)
    assert rs.is_read_for_edit("a.py", 1, 10) is True
    assert rs.is_read_for_edit("b.py", 1, 10) is False


def test_readset_record_promote_full_false_does_not_grant_blanket_full_read() -> None:
    """finding #441-9(readpage) / D: a caller that can't vouch the recorded
    span's CONTENT (not just its line numbers) was completely shown passes
    ``promote_full=False`` — the exact span is still recorded (so a repeat
    check of the SAME span still passes), but the coincidence of the span
    numerically covering ``[1, total_lines]`` must not grant blanket
    authorization for the rest of the path (in particular, content added to
    the file after this record call)."""
    rs = ReadSet()
    rs.record("one_liner.py", start_line=1, end_line=1, total_lines=1, promote_full=False)

    # The exact span that was recorded is still a legitimate match.
    assert rs.is_read_for_edit("one_liner.py", 1, 1) is True

    # But the path was NOT promoted to `_full` — a span beyond what was
    # recorded (e.g. a line appended to the file afterwards) is refused.
    assert rs.is_read_for_edit("one_liner.py", 2, 2) is False

    # The default (promote_full=True, unchanged) still auto-promotes an
    # equivalent whole-range span — this is the pre-existing, still-correct
    # behavior for a read that genuinely vouches for the whole file.
    rs2 = ReadSet()
    rs2.record("full.py", start_line=1, end_line=1, total_lines=1)
    assert rs2.is_read_for_edit("full.py", 1, 1) is True

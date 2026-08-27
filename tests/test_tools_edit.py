"""t13 — edit_file tolerant tier + prior-read enforcement (plan adopt-from-qwen-code, c9/h7).

Exact match first, then :func:`colleague.editmatch.normalize_edit_strings`; a file
(or span) never shown by ``read_file`` in this work item is refused with a typed
error that says how to recover; ``write_file`` of a NEW file is unaffected; no
LLM call anywhere in ``colleague/tools.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from colleague import editgate
from colleague.tools import ToolError, ToolExecutor

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "mod.py").write_text(
        "def f():\n    x = 1\n    return x\n\n\ndef g():\n    y = 2\n    return y\n",
        encoding="utf-8",
    )
    return tmp_path


def _exec(repo: Path) -> ToolExecutor:
    return ToolExecutor(repo)


def test_exact_match_lands_after_read(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("read_file", {"path": "mod.py"})
    out = ex.execute("edit_file", {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 3"})
    assert "replaced 1 occurrence" in out.result
    assert "x = 3" in (repo / "mod.py").read_text()


def test_whitespace_drifted_old_string_lands_in_one_step(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("read_file", {"path": "mod.py"})
    # indent drift (2 spaces instead of 4) + a trailing space on the second line
    out = ex.execute(
        "edit_file",
        {
            "path": "mod.py",
            "old_string": "  y = 2 \n  return y",
            "new_string": "    y = 20\n    return y",
        },
    )
    assert "replaced 1 occurrence" in out.result
    text = (repo / "mod.py").read_text()
    assert "    y = 20\n    return y" in text
    assert "y = 2\n" not in text


def test_smart_quote_drift_lands(repo: Path) -> None:
    (repo / "s.py").write_text('msg = "hello"\n', encoding="utf-8")
    ex = _exec(repo)
    ex.execute("read_file", {"path": "s.py"})
    out = ex.execute(
        "edit_file", {"path": "s.py", "old_string": "msg = “hello”", "new_string": 'msg = "bye"'}
    )
    assert "replaced 1" in out.result
    assert (repo / "s.py").read_text() == 'msg = "bye"\n'


def test_exact_ambiguity_still_errors_naming_the_count(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("read_file", {"path": "mod.py"})
    with pytest.raises(ToolError, match=r"2 matches"):
        ex.execute(
            "edit_file", {"path": "mod.py", "old_string": "    return", "new_string": "    yield"}
        )


def test_relaxed_ambiguity_errors_naming_the_count(repo: Path) -> None:
    (repo / "q.py").write_text('x = "q"\ny = 1\nx = "q"\n', encoding="utf-8")
    ex = _exec(repo)
    ex.execute("read_file", {"path": "q.py"})
    with pytest.raises(ToolError, match=r"matches 2 places"):
        ex.execute("edit_file", {"path": "q.py", "old_string": "x = “q”", "new_string": 'x = "z"'})


def test_not_found_at_all_is_a_clear_error(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("read_file", {"path": "mod.py"})
    with pytest.raises(ToolError, match=r"old_string not found"):
        ex.execute("edit_file", {"path": "mod.py", "old_string": "nope", "new_string": "yes"})


def test_edit_without_prior_read_is_refused_with_recovery_hint(repo: Path) -> None:
    ex = _exec(repo)
    with pytest.raises(ToolError, match=r"read the file \(or that span\) first") as info:
        ex.execute("edit_file", {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 3"})
    assert "prior-read rule" in str(info.value)
    assert (repo / "mod.py").read_text().count("x = 1") == 1  # untouched


def test_edit_of_span_outside_a_paged_read_is_refused(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("read_file", {"path": "mod.py", "offset": 1, "limit": 3})  # shows lines 1-3 only
    with pytest.raises(ToolError, match=r"read the file \(or that span\) first"):
        ex.execute("edit_file", {"path": "mod.py", "old_string": "y = 2", "new_string": "y = 9"})
    out = ex.execute("edit_file", {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 9"})
    assert "replaced 1" in out.result


def test_paged_read_then_read_of_the_rest_covers_the_span(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("read_file", {"path": "mod.py", "offset": 1, "limit": 3})
    ex.execute("read_file", {"path": "mod.py", "offset": 4, "limit": 10})
    out = ex.execute("edit_file", {"path": "mod.py", "old_string": "y = 2", "new_string": "y = 9"})
    assert "replaced 1" in out.result


def test_truncated_read_only_covers_shown_lines(tmp_path: Path) -> None:
    big = "\n".join(f"line {i} " + "x" * 60 for i in range(1, 2001)) + "\n"
    (tmp_path / "big.txt").write_text(big, encoding="utf-8")
    ex = ToolExecutor(tmp_path)
    out = ex.execute("read_file", {"path": "big.txt"})
    assert re.search(r"Read lines 1-\d+ of 2000$", out.result)
    with pytest.raises(ToolError, match=r"read the file \(or that span\) first"):
        ex.execute("edit_file", {"path": "big.txt", "old_string": "line 1999 ", "new_string": "L "})
    assert (
        "replaced 1"
        in ex.execute(
            "edit_file", {"path": "big.txt", "old_string": "line 2 ", "new_string": "L "}
        ).result
    )


def test_write_file_new_file_is_unaffected(repo: Path) -> None:
    ex = _exec(repo)
    out = ex.execute("write_file", {"path": "new.txt", "content": "hi\n"})
    assert "wrote 3 bytes" in out.result


def test_write_file_over_existing_file_is_not_gated(repo: Path) -> None:
    ex = _exec(repo)  # overwriting is a whole-file act the model authors (mock rerun determinism)
    assert "wrote" in ex.execute("write_file", {"path": "mod.py", "content": "gone\n"}).result


def test_prior_read_knob_disables_the_rule(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_PRIOR_READ", "0")
    ex = _exec(repo)
    out = ex.execute("edit_file", {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 3"})
    assert "replaced 1" in out.result


def test_replace_all_requires_every_occurrence_shown(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("read_file", {"path": "mod.py", "offset": 1, "limit": 3})
    with pytest.raises(ToolError, match=r"read the file \(or that span\) first"):
        ex.execute(
            "edit_file",
            {
                "path": "mod.py",
                "old_string": "    return",
                "new_string": "    yield",
                "replace_all": True,
            },
        )


def test_write_then_edit_needs_no_read(repo: Path) -> None:
    ex = _exec(repo)
    ex.execute("write_file", {"path": "w.txt", "content": "alpha beta\n"})
    assert (
        "replaced 1"
        in ex.execute(
            "edit_file", {"path": "w.txt", "old_string": "beta", "new_string": "gamma"}
        ).result
    )


def test_read_set_is_per_executor(repo: Path) -> None:
    ex1, ex2 = _exec(repo), _exec(repo)
    ex1.execute("read_file", {"path": "mod.py"})
    with pytest.raises(ToolError):
        ex2.execute("edit_file", {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 3"})


def test_span_lines_of_first_occurrence() -> None:
    text = "a\nb\nc\nd\n"
    assert editgate.occurrence_spans(text, "b\nc") == [(2, 3)]
    assert editgate.occurrence_spans("x\nx\n", "x") == [(1, 1), (2, 2)]


def test_no_llm_or_engine_import_in_tools_py() -> None:
    src = (REPO_ROOT / "colleague" / "tools.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
    forbidden = ("engine", "engines", "vllm", "openai", "urllib", "http", "socket", "deepthink_run")
    assert not [n for n in names if any(tok in n for tok in forbidden)], names
    assert "urlopen" not in src
    assert "chat/completions" not in src

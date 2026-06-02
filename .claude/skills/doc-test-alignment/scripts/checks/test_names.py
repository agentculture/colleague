"""test_names.py — check (d): test NAME vs the assertions the test makes.

Canonical check name: ``tests``.

For each ``test_*`` function under ``<repo>/tests/test_*.py`` (including methods
in ``Test*`` classes), apply two HEURISTIC signals — both advisory, all findings
``severity="warning"`` so this check NEVER flips a green exit / gates CI in v1:

Signal 1 — zero-assertion test (real bug class)
    The body contains no ``assert`` statement, no ``with pytest.raises(...)`` /
    ``pytest.warns(...)``, no call whose function name starts with
    ``assert``/``check``/``expect``/``verify`` (local assertion helpers — this
    prefix whitelist avoids false positives), and no ``self.assert*`` method
    call. → flagged "test has no assertions".

Signal 2 — name/body token drift (tuned heuristic)
    Tokenize the function name (split on ``_``, drop leading ``test``, drop
    STOPWORDS, singularize trivially). Collect the body's SALIENT tokens
    (identifiers inside ``assert`` test expressions, all called function/method
    names, attribute names, words from string-literal constants). Overlap =
    fraction of (non-stopword) name tokens present in the body token set. When
    overlap is below ``MIN_NAME_TOKEN_OVERLAP`` (just above 0 → zero matched
    flags, ≥1 matched passes) the test is flagged, naming the unmatched name
    tokens. Tests with no salient name tokens are skipped.

Suppression (escape hatch — a 982-test repo needs one):
  * Inline ``# doc-test-alignment: ok`` on (or just above) the ``def`` line
    suppresses both signals → an info "suppressed (inline)" check.
  * File ``<repo>/.claude/skills/doc-test-alignment/suppressions.txt``, one
    ``relpath::test_name`` per line (``#`` comments allowed) → suppressed.

Output shape:
  * ONE summary ``info`` check (passed=True): "scanned N test functions in M
    files; flagged K".
  * one ``warning`` check per FLAGGED test (id ``test_drift::<relpath>::<name>``
    or ``test_noassert::<relpath>::<name>``).
  * NO check per passing test (the suite has ~982).

``run`` never raises: any internal failure returns a single ``error`` check.

Portable, stdlib-only (``ast``); never imports ``convertible``.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from typing import List

NAME = "tests"

# --- Tunables --------------------------------------------------------------

# Overlap threshold for signal 2. Set just above 0 so a test with ZERO matched
# name tokens is flagged, while ≥1 matched token passes. With name-token counts
# typically 1–4, any positive overlap clears this.
MIN_NAME_TOKEN_OVERLAP: float = 0.01

# Name tokens dropped before computing overlap (structural + generic words that
# carry no feature meaning). Tunable module-level set.
STOPWORDS: frozenset = frozenset(
    {
        # structural / grammatical
        "test",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "is",
        "are",
        "was",
        "with",
        "without",
        "when",
        "then",
        "for",
        "in",
        "on",
        "by",
        "no",
        "not",
        "it",
        "its",
        "that",
        "this",
        "from",
        "into",
        "as",
        "at",
        # generic test-name filler
        "should",
        "works",
        "work",
        "handles",
        "handle",
        "returns",
        "return",
        "given",
        "case",
        "basic",
        "simple",
    }
)

# Local-assertion-helper call prefixes that count as assertions (signal 1).
_ASSERT_CALL_PREFIXES = ("assert", "check", "expect", "verify")

# Inline suppression marker.
_SUPPRESS_MARKER = "doc-test-alignment: ok"

# Splits string-literal constants into word tokens.
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _make_check_import():
    """Put scripts/ on sys.path and return _report.make_check (mirrors __init__)."""
    scripts_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from _report import make_check  # type: ignore[import]

    return make_check


def _singular(token: str) -> str:
    """Trivially singularize: strip a trailing 's' (len>1 only)."""
    if len(token) > 1 and token.endswith("s"):
        return token[:-1]
    return token


def _name_tokens(func_name: str) -> List[str]:
    """Tokenize a test function name into salient (non-stopword) tokens."""
    parts = [p for p in func_name.split("_") if p]
    # Drop a single leading "test" segment.
    if parts and parts[0].lower() == "test":
        parts = parts[1:]
    out: List[str] = []
    for p in parts:
        low = p.lower()
        if low in STOPWORDS:
            continue
        sing = _singular(low)
        if sing in STOPWORDS:
            continue
        out.append(sing)
    return out


def _is_assertion_node(node: ast.AST) -> bool:
    """True if *node* is itself an assertion-bearing construct (signal 1)."""
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.With):
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Call):
                fn = _call_func_name(ctx)
                if fn in {"raises", "warns"}:
                    return True
    if isinstance(node, ast.Call):
        fn = _call_func_name(node)
        if fn is None:
            return False
        low = fn.lower()
        if low.startswith(_ASSERT_CALL_PREFIXES):
            return True
    return False


def _call_func_name(call: ast.Call) -> "str | None":
    """Return the simple function/method name of a Call node, or None."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _has_assertion(fn: ast.AST) -> bool:
    """Walk the function body — True if any assertion construct is present."""
    for node in ast.walk(fn):
        if node is fn:
            continue
        if _is_assertion_node(node):
            return True
    return False


def _body_tokens(fn: ast.AST) -> set:
    """Collect SALIENT body tokens: assert-expr names, call/attr names, string words."""
    tokens: set = set()
    for node in ast.walk(fn):
        # identifiers used inside assert test expressions
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Name):
                    tokens.add(_singular(sub.id.lower()))
                elif isinstance(sub, ast.Attribute):
                    tokens.add(_singular(sub.attr.lower()))
        # all called function/method names
        elif isinstance(node, ast.Call):
            fn_name = _call_func_name(node)
            if fn_name:
                tokens.add(_singular(fn_name.lower()))
        # attribute names anywhere
        elif isinstance(node, ast.Attribute):
            tokens.add(_singular(node.attr.lower()))
        # words from string-literal constants
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for word in _WORD_RE.findall(node.value):
                tokens.add(_singular(word.lower()))
    return tokens


def _iter_test_functions(tree: ast.AST):
    """Yield (func_node, qualifier) for every test_* function and Test*-class method."""
    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                yield node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("test_"):
                        yield sub


def _inline_suppressed(fn: ast.AST, source_lines: List[str]) -> bool:
    """True if the suppression marker is on the def line or just above it."""
    lineno = getattr(fn, "lineno", None)
    if not lineno:
        return False
    # ast lineno is 1-based; for decorated functions, decorators sit above and
    # the def line itself is `lineno`. Check the def line and the line above.
    idx = lineno - 1  # 0-based index of the def line
    candidates = []
    if 0 <= idx < len(source_lines):
        candidates.append(source_lines[idx])
    if 0 <= idx - 1 < len(source_lines):
        candidates.append(source_lines[idx - 1])
    return any(_SUPPRESS_MARKER in line for line in candidates)


def _load_file_suppressions(repo: pathlib.Path) -> set:
    """Load relpath::test_name entries from suppressions.txt (if present)."""
    supp = repo / ".claude" / "skills" / "doc-test-alignment" / "suppressions.txt"
    out: set = set()
    if not supp.is_file():
        return out
    try:
        text = supp.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out


def run(repo: pathlib.Path) -> List[dict]:
    """Scan <repo>/tests/test_*.py for test-name-vs-assertion drift.

    Returns a single summary info check plus one warning check per flagged test.
    Never raises — internal failures are returned as a single error check.
    """
    make_check = _make_check_import()
    try:
        return _run(repo, make_check)
    except Exception as exc:  # noqa: BLE001 - contract: run() must not raise
        return [
            make_check(
                "tests_internal_error",
                False,
                "error",
                f"test-names check failed internally: {exc!r}",
                "This is a bug in the doc-test-alignment 'tests' check.",
            )
        ]


def _run(repo: pathlib.Path, make_check) -> List[dict]:
    tests_dir = repo / "tests"
    file_suppressions = _load_file_suppressions(repo)

    checks: List[dict] = []
    scanned = 0
    files_with_tests = 0
    flagged = 0
    suppressed_infos: List[dict] = []

    test_files = sorted(tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []

    for path in test_files:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Unparseable test file — skip it (run() must not crash on bad syntax).
            continue

        source_lines = source.splitlines()
        relpath = path.relative_to(repo).as_posix()
        file_had_test = False

        for fn in _iter_test_functions(tree):
            scanned += 1
            file_had_test = True
            key = f"{relpath}::{fn.name}"

            # --- suppression --------------------------------------------------
            if key in file_suppressions or _inline_suppressed(fn, source_lines):
                suppressed_infos.append(
                    make_check(
                        f"test_suppressed::{key}",
                        True,
                        "info",
                        (
                            f"{fn.name} suppressed (inline)"
                            if _inline_suppressed(fn, source_lines)
                            else f"{fn.name} suppressed (file)"
                        ),
                        "",
                    )
                )
                continue

            # --- Signal 1: zero-assertion ------------------------------------
            if not _has_assertion(fn):
                flagged += 1
                checks.append(
                    make_check(
                        f"test_noassert::{key}",
                        False,
                        "warning",
                        f"{fn.name} has no assertions",
                        "Add an assert (or pytest.raises / a check_*/verify_* "
                        "helper), or suppress with '# doc-test-alignment: ok'.",
                    )
                )
                # A zero-assertion test gives no signal for drift; move on.
                continue

            # --- Signal 2: name/body token drift -----------------------------
            name_toks = _name_tokens(fn.name)
            if not name_toks:
                # Nothing salient to check (all-stopword name) → skip.
                continue
            body_toks = _body_tokens(fn)
            matched = [t for t in name_toks if t in body_toks]
            overlap = len(matched) / len(name_toks)
            if overlap < MIN_NAME_TOKEN_OVERLAP:
                unmatched = [t for t in name_toks if t not in body_toks]
                flagged += 1
                checks.append(
                    make_check(
                        f"test_drift::{key}",
                        False,
                        "warning",
                        f"{fn.name} name advertises {unmatched!r} but its "
                        "assertions touch none of those tokens",
                        "Rename the test to match what it asserts, or suppress "
                        "with '# doc-test-alignment: ok'.",
                    )
                )

        if file_had_test:
            files_with_tests += 1

    summary = make_check(
        "tests_summary",
        True,
        "info",
        f"scanned {scanned} test functions in {files_with_tests} files; " f"flagged {flagged}",
        "",
    )

    # Summary first, then suppressed infos, then per-flag warnings.
    return [summary, *suppressed_infos, *checks]

#!/usr/bin/env python3
"""Pin audit: which tests are coupled to a module file, and how?

A read-only helper that answers one question for a given module path::

    python scripts/pin_audit.py colleague/loop.py

It reports five sections:

1. PATH LITERALS — every file under ``tests/`` containing the module path as a
   string literal (e.g. ``"colleague/loop.py"``).
1b. MODULE-OBJECT SOURCE READS — every file under ``tests/`` that reaches the
   module object (``import <path> as <alias>`` / ``from <parent> import
   <modname>``) and then reads its source via ``<alias>.__file__`` /
   ``getsource(<alias>)`` / ``Path(<alias>.__file__).read_text(...)``.
2. MONKEYPATCH TARGETS — every ``monkeypatch.setattr`` / ``mock.patch`` target
   string under ``tests/`` that names the module's import path
   (e.g. ``"colleague.loop."``).
3. ALLOW-LIST MEMBERSHIP — whether the module path appears in
   ``tests/test_boundary.py``'s ``_SUBPROCESS_ALLOWED`` or ``_THREADS_ALLOWED``.
4. MONKEYPATCH-EFFECTIVENESS CHECKLIST — one line per section-2 target and per
   section-1b source read, warning that a monkeypatch whose target moves to
   another module STAYS GREEN while silently testing nothing, and that a
   source-text assertion on a module that gets split silently changes meaning.

Pure stdlib only (the repo has a zero-deps rule). READ-ONLY: this script never
writes or edits any file. Exit 0 when a module path is given; exit 2 with a
usage message when called with no argument.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# A quoted string literal (single or double) — used to confirm a match is a
# literal, not a bare comment mention.
_QUOTED = re.compile(r"['\"]([^'\"]*)['\"]")
# A call that takes a target string: monkeypatch.setattr / mock.patch / patch.
_PATCH_CALL = re.compile(r"\b(monkeypatch\.setattr|mock\.patch|patch)\s*\(")
# A source-read idiom on a module object: <name>.__file__ or getsource(<name>).
_SOURCE_READ = re.compile(r"\.__file__\b|getsource\s*\(")


def _import_path(module_path: str) -> str:
    """``colleague/loop.py`` -> ``colleague.loop`` (the dotted import path)."""
    stem = module_path[:-3] if module_path.endswith(".py") else module_path
    return stem.replace("/", ".")


def _iter_test_files(repo_root: Path):
    """Yield (relative_path, lines) for every ``.py`` file under ``tests/``."""
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return
    for path in sorted(tests_dir.rglob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield rel, text.splitlines()


def _section_path_literals(repo_root: Path, module_path: str) -> int:
    """Section 1: the module path as a quoted string literal under tests/."""
    print("1. PATH LITERALS")
    print(f"   module path: {module_path!r}")
    needle = f"['\"]{re.escape(module_path)}['\"]"
    rx = re.compile(needle)
    count = 0
    for rel, lines in _iter_test_files(repo_root):
        for i, line in enumerate(lines, start=1):
            if rx.search(line):
                count += 1
                print(f"   {rel}:{i}: {line.strip()}")
    if count == 0:
        print("   (none)")
    print(f"   -> {count} path literal(s)")
    return count


def _section_module_source_reads(repo_root: Path, module_path: str) -> list[tuple[str, int, str]]:
    """Section 1b: tests that reach the module object and read its source.

    Detects, per test file, an import that binds the module's import path to a
    name (``import <path> as <alias>`` or ``from <parent> import <modname>``)
    followed by a source-read idiom on that name (``<alias>.__file__``,
    ``getsource(<alias>)``, ``Path(<alias>.__file__).read_text(...)``).

    Returns the (rel, lineno, line) tuples so section 4 can reuse them.
    """
    print("\n1b. MODULE-OBJECT SOURCE READS")
    import_path = _import_path(module_path)
    print(f"   import path: {import_path!r}")
    # import <import.path> as <alias>
    as_rx = re.compile(r"\bimport\s+" + re.escape(import_path) + r"\s+as\s+([A-Za-z_]\w*)")
    # from <parent> import <modname>
    parent, _, modname = import_path.rpartition(".")
    from_rx = re.compile(
        r"\bfrom\s+" + re.escape(parent) + r"\s+import\s+[^#\n]*\b" + re.escape(modname) + r"\b"
    )
    found: list[tuple[str, int, str]] = []
    for rel, lines in _iter_test_files(repo_root):
        aliases: set[str] = set()
        for i, line in enumerate(lines, start=1):
            m = as_rx.search(line)
            if m:
                aliases.add(m.group(1))
            if from_rx.search(line):
                aliases.add(modname)
            if aliases and _SOURCE_READ.search(line):
                # Only count a read that names one of this module's aliases as a
                # whole word (so ``loop`` does not match ``toolbatch_loop``).
                if any(re.search(r"\b" + re.escape(a) + r"\b", line) for a in aliases):
                    found.append((rel, i, line.strip()))
    for rel, i, line in found:
        print(f"   {rel}:{i}: {line}")
    if not found:
        print("   (none)")
    print(f"   -> {len(found)} module-object source read(s)")
    return found


def _section_monkeypatch_targets(repo_root: Path, module_path: str) -> list[tuple[str, int, str]]:
    """Section 2: patch target strings naming the module's import path.

    Returns the (rel, lineno, target) tuples so section 4 can reuse them.
    """
    print("\n2. MONKEYPATCH TARGETS")
    prefix = _import_path(module_path) + "."
    print(f"   import-path prefix: {prefix!r}")
    found: list[tuple[str, int, str]] = []
    for rel, lines in _iter_test_files(repo_root):
        for i, line in enumerate(lines, start=1):
            if not _PATCH_CALL.search(line):
                continue
            for target in _QUOTED.findall(line):
                if target.startswith(prefix):
                    found.append((rel, i, target))
    for rel, i, target in found:
        print(f"   {rel}:{i}: {target!r}")
    if not found:
        print("   (none)")
    print(f"   -> {len(found)} target(s)")
    return found


def _set_span(text: str, name: str) -> str:
    """Return the text of a ``name = frozenset(...)`` block, or '' if absent."""
    m = re.search(re.escape(name) + r"\s*(?::\s*[^=\n]+)?=\s*frozenset\s*\(", text)
    if not m:
        return ""
    start = m.end()
    depth = 1
    for j in range(start, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[start:j]
    return text[start:]


def _section_allowlist(repo_root: Path, module_path: str) -> None:
    """Section 3: membership in test_boundary.py's allow-list sets."""
    print("\n3. ALLOW-LIST MEMBERSHIP")
    boundary = repo_root / "tests" / "test_boundary.py"
    if not boundary.is_file():
        print(f"   {boundary.as_posix()} not found")
        return
    text = boundary.read_text(encoding="utf-8")
    for name in ("_SUBPROCESS_ALLOWED", "_THREADS_ALLOWED"):
        span = _set_span(text, name)
        present = bool(re.search(r"['\"]" + re.escape(module_path) + r"['\"]", span))
        status = "PRESENT" if present else "absent"
        print(f"   {name}: {status}")


def _module_aliases(lines: list[str], import_path: str) -> set[str]:
    """Every local name bound to ``import_path`` in one test file.

    Shared by sections 1b and 2b: both need "what does this file call the
    module object?" before they can spot a use of it.
    """
    as_rx = re.compile(r"\bimport\s+" + re.escape(import_path) + r"\s+as\s+([A-Za-z_]\w*)")
    parent, _, modname = import_path.rpartition(".")
    from_rx = re.compile(
        r"\bfrom\s+" + re.escape(parent) + r"\s+import\s+[^#\n]*\b" + re.escape(modname) + r"\b"
    )
    from_as_rx = re.compile(
        r"\bfrom\s+"
        + re.escape(parent)
        + r"\s+import\s+"
        + re.escape(modname)
        + r"\s+as\s+([A-Za-z_]\w*)"
    )
    aliases: set[str] = set()
    for line in lines:
        m = as_rx.search(line)
        if m:
            aliases.add(m.group(1))
        m = from_as_rx.search(line)
        if m:
            aliases.add(m.group(1))
        elif from_rx.search(line):
            aliases.add(modname)
    return aliases


def _section_alias_patches(repo_root: Path, module_path: str) -> list[tuple[str, int, str]]:
    """Section 2b: OBJECT-form patches — ``monkeypatch.setattr(<alias>, "name")``.

    Section 2 only sees string targets (``"colleague.loop.thing"``). Tests far
    more often hold the module object and patch an attribute on it::

        from colleague.engines import vllm_openai
        monkeypatch.setattr(vllm_openai, "_post", fake)

    That form is invisible to a string-prefix grep, and it is the dangerous
    one: re-exporting a moved symbol does NOT keep such a patch effective,
    because a bare-name call resolves through the ``__globals__`` of the module
    the calling function is TEXTUALLY DEFINED in. Missing these is how a split
    leaves a green suite that tests nothing (found against appserver.py and
    vllm_openai.py during the file-length arc).
    """
    print("\n2b. OBJECT-FORM PATCHES (module alias)")
    import_path = _import_path(module_path)
    found: list[tuple[str, int, str]] = []
    for rel, lines in _iter_test_files(repo_root):
        aliases = _module_aliases(lines, import_path)
        if not aliases:
            continue
        alias_rx = re.compile(
            r"\b(?:monkeypatch\.setattr|setattr)\s*\(\s*("
            + "|".join(re.escape(a) for a in sorted(aliases))
            + r")\s*,\s*['\"]([^'\"]+)['\"]"
        )
        for i, line in enumerate(lines, start=1):
            m = alias_rx.search(line)
            if m:
                found.append((rel, i, f"{m.group(1)}.{m.group(2)}"))
    for rel, i, target in found:
        print(f"   {rel}:{i}: {target}")
    if not found:
        print("   (none)")
    print(f"   -> {len(found)} object-form patch(es)")
    return found


def _section_checklist(
    found: list[tuple[str, int, str]],
    source_reads: list[tuple[str, int, str]],
) -> None:
    """Section 4: one effectiveness-warning line per section-2 target and per
    section-1b source read."""
    print("\n4. MONKEYPATCH-EFFECTIVENESS CHECKLIST")
    for rel, i, target in found:
        print(f"   {rel}:{i} patches {target!r}")
        print(
            "     WARNING: a monkeypatch whose target moves to another module "
            "STAYS GREEN while silently testing nothing — prove this patch is "
            "still effective."
        )
    for rel, i, line in source_reads:
        print(f"   {rel}:{i} reads module source: {line}")
        print(
            "     WARNING: a source-text assertion on a module that gets split "
            "silently changes meaning — re-verify it after any refactor."
        )
    if not found and not source_reads:
        print("   (nothing to check)")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/pin_audit.py <module-path>", file=sys.stderr)
        print("       e.g. python scripts/pin_audit.py colleague/loop.py", file=sys.stderr)
        return 2

    module_path = argv[1]
    repo_root = Path(__file__).resolve().parent.parent
    print(f"pin audit for {module_path!r} (repo root: {repo_root.as_posix()})")
    _section_path_literals(repo_root, module_path)
    source_reads = _section_module_source_reads(repo_root, module_path)
    found = _section_monkeypatch_targets(repo_root, module_path)
    found += _section_alias_patches(repo_root, module_path)
    _section_allowlist(repo_root, module_path)
    _section_checklist(found, source_reads)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

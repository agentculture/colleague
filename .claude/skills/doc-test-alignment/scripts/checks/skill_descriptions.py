"""skill_descriptions.py — check (c): SKILL.md script claims vs actual scripts/.

NAME = "skills"

For each `<repo>/.claude/skills/<name>/` directory this check:

1. Reads SKILL.md (if present) and extracts ALL `scripts/<path>` literals
   found ANYWHERE in the file (frontmatter + body), using a conservative
   regex that only matches the literal pattern ``scripts/<relative-path>``.
   It does NOT mine natural-language capability prose (e.g., "bumps the
   version") — only unambiguous path references.  This keeps false-positives
   to zero.

2. For each claimed path, verifies the file exists under the skill directory.
   Missing file → ``severity="error"``, ``passed=False``.

3. Verifies that any claimed path that appears inside a fenced bash/sh
   ``## How to run`` / ``## Usage`` block (the skill's entry-point call) is
   also executable.  Non-executable but present → ``severity="error"``.

4. Emits a per-skill summary ``info``/``passed=True`` check:
   - If there are no ``scripts/`` directory AND no ``scripts/<path>`` claims
     → "no scripts, no script claims; nothing to align" (pure-doc skill).
   - If there are claims that all resolve correctly
     → "N script claim(s) resolve".

Honest scope
------------
This check only flags **concrete, unambiguous missing-artifact disagreements**:
 - ``scripts/<path>`` literals that appear in SKILL.md but whose files are absent.
 - Entry-point scripts that exist but are not executable.

It does NOT mine natural-language capability prose such as "bump the version"
or "opens a PR".  Those are subjective and would false-positive on descriptive
wording.  Precision over recall: only flag things that are unambiguously wrong.

Contract
--------
- NAME = "skills"
- run(repo: pathlib.Path) -> list[dict]
- MUST NOT raise — all exceptions caught, returned as a single error check.
- Read-only, no network, no daemon, stdlib-only, no ``import convertible``.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

__all__ = ["NAME", "run"]

NAME = "skills"

# Ensure the scripts/ directory is on sys.path for sibling imports.
_SCRIPTS_DIR = str(pathlib.Path(__file__).resolve().parents[1])
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _md import iter_fenced_blocks, parse_frontmatter  # type: ignore[import]  # noqa: E402
from _report import make_check  # type: ignore[import]  # noqa: E402

# Regex: match ``scripts/<path>`` — the path segment is one or more non-whitespace,
# non-backtick, non-quote chars that don't start with a dot (avoids matching
# directory sentinel files like scripts/.gitkeep) and contain at least one dot or
# slash (looks like a real file reference).  Conservative by design.
# Optionally capture a fully-qualified ``.claude/skills/<name>/`` prefix so a
# cross-skill reference (e.g. the assign-to-workforce SKILL.md mentioning
# ``.claude/skills/cicd/scripts/workflow.sh``) is attributed to the OTHER skill,
# not the one being checked — otherwise every skill that documents a sibling's
# command would false-positive.
_SCRIPT_PATH_RE = re.compile(
    r"(?:\.claude/skills/(?P<skill>[^/\s]+)/)?\bscripts/(?P<rel>[^\s`'\"<>\[\]()]+)"
)

# Minimum dot-in-basename guard: a referenced scripts/<path> must look like a
# real file (contains a dot somewhere OR has a typical script name without extension
# — we allow both; the important thing is that pure-dot-only paths like
# ``scripts/.gitkeep`` are excluded by the leading-dot guard above).
_DOTKEEP_RE = re.compile(r"^\.")


def _extract_script_claims(text: str, skill_name: str) -> list[str]:
    """Return all unique ``scripts/<relpath>`` literals *claimed by this skill*.

    A match prefixed by ``.claude/skills/<other>/`` is a cross-skill reference
    and is attributed to ``<other>``, so it is excluded unless ``<other>`` is
    *skill_name* itself. Bare ``scripts/<path>`` references (and ones prefixed by
    this skill's own path) are this skill's claims. Excludes dotfiles
    (e.g. .gitkeep), which are sentinel/hidden files, not real script claims.
    """
    seen: set[str] = set()
    result: list[str] = []
    for m in _SCRIPT_PATH_RE.finditer(text):
        owner = m.group("skill")
        if owner is not None and owner != skill_name:
            continue  # a sibling skill's script — not this skill's claim
        rel = m.group("rel")
        # Exclude dotfiles and paths that are just punctuation
        basename = rel.split("/")[-1]
        if _DOTKEEP_RE.match(basename):
            continue
        full = f"scripts/{rel}"
        if full not in seen:
            seen.add(full)
            result.append(full)
    return result


def _is_entry_point_claim(skill_text: str, script_rel: str) -> bool:
    """Return True if *script_rel* (e.g. ``scripts/check.sh``) appears in a
    fenced bash/sh block — indicating it is the skill's invocation entry point
    and should be executable.
    """
    for _lineno, body in iter_fenced_blocks(skill_text, "bash"):
        if script_rel in body:
            return True
    return False


def _check_skill(skill_dir: pathlib.Path) -> list[dict]:
    """Check one skill directory and return its check dicts."""
    skill_name = skill_dir.name
    id_prefix = f"skills_{skill_name}"

    skill_md = skill_dir / "SKILL.md"
    scripts_dir = skill_dir / "scripts"

    # --- No SKILL.md at all: emit a minimal info/passed and move on ---
    if not skill_md.exists():
        return [
            make_check(
                f"{id_prefix}_no_skill_md",
                True,
                "info",
                f"skill '{skill_name}': no SKILL.md found; nothing to align",
                "",
            )
        ]

    text = skill_md.read_text(encoding="utf-8")

    # Parse frontmatter (handles folded scalars)
    fm = parse_frontmatter(text)
    description = fm.get("description", "")

    # Build the full text to scan: frontmatter description + body
    full_text = description + "\n" + text

    # Extract all scripts/<path> claims from the full text
    claims = _extract_script_claims(full_text, skill_name)

    # Determine if a scripts/ directory is present
    has_scripts_dir = scripts_dir.is_dir()

    # --- Pure-doc skill: no scripts/ dir and no script claims ---
    if not claims and not has_scripts_dir:
        return [
            make_check(
                f"{id_prefix}_pure_doc",
                True,
                "info",
                (f"skill '{skill_name}': no scripts, no script claims; " "nothing to align"),
                "",
            )
        ]

    checks: list[dict] = []
    errors: int = 0

    for claim in claims:
        full_path = skill_dir / claim
        if not full_path.exists():
            checks.append(
                make_check(
                    f"{id_prefix}_missing_{claim.replace('/', '_').replace('.', '_')}",
                    False,
                    "error",
                    (
                        f"skill '{skill_name}': SKILL.md claims '{claim}' "
                        "but the file does not exist"
                    ),
                    "add the script or correct SKILL.md",
                )
            )
            errors += 1
        else:
            # File exists — check executability for entry-point scripts
            if _is_entry_point_claim(text, claim):
                if not os.access(str(full_path), os.X_OK):
                    safe_claim = claim.replace("/", "_").replace(".", "_")
                    checks.append(
                        make_check(
                            f"{id_prefix}_not_executable_{safe_claim}",
                            False,
                            "error",
                            (
                                f"skill '{skill_name}': entry-point script "
                                f"'{claim}' exists but is not executable"
                            ),
                            f"chmod +x {claim}",
                        )
                    )
                    errors += 1

    # Summary info check
    if errors == 0:
        n = len(claims)
        if n == 0:
            # scripts/ dir exists but SKILL.md has no claims — that's fine
            summary_msg = (
                f"skill '{skill_name}': scripts/ dir present, "
                "no explicit script claims in SKILL.md; nothing to align"
            )
        else:
            summary_msg = f"skill '{skill_name}': {n} script claim(s) resolve"
        checks.append(
            make_check(
                f"{id_prefix}_ok",
                True,
                "info",
                summary_msg,
                "",
            )
        )

    return checks


def run(repo: pathlib.Path) -> list[dict]:
    """Run the skills check against *repo*.

    Iterates every ``.claude/skills/<name>/`` directory and checks that
    SKILL.md script-path claims match the actual files on disk.

    Never raises — all exceptions are caught and returned as a single error check.
    """
    try:
        skills_root = repo / ".claude" / "skills"
        if not skills_root.is_dir():
            return [
                make_check(
                    "skills_no_skills_dir",
                    True,
                    "info",
                    "no .claude/skills/ directory; nothing to check",
                    "",
                )
            ]

        skill_dirs = sorted(p for p in skills_root.iterdir() if p.is_dir())

        if not skill_dirs:
            return [
                make_check(
                    "skills_empty_dir",
                    True,
                    "info",
                    ".claude/skills/ is empty; nothing to check",
                    "",
                )
            ]

        results: list[dict] = []
        for skill_dir in skill_dirs:
            results.extend(_check_skill(skill_dir))
        return results

    except Exception as exc:  # noqa: BLE001
        return [
            make_check(
                "skills_internal_error",
                False,
                "error",
                f"skills check internal error: {exc}",
                "report this as a bug in skill_descriptions.py",
            )
        ]

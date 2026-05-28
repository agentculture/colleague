"""Identity check-group — the agent-identity invariants.

Ported verbatim (in behaviour) from the original ``doctor`` verb's
``_diagnose()``. Mirrors the invariants ``steward doctor`` verifies for a mesh
agent:

* **prompt-file-present** / **backend-consistency** — the repo declares an agent
  in ``culture.yaml`` and has the matching prompt file on disk for the declared
  backend (``claude`` → ``CLAUDE.md``, ``acp`` → ``AGENTS.md``, ``gemini`` →
  ``GEMINI.md``);
* **skills-present** — the vendored ``.claude/skills/`` kit is on disk.

Read-only: touches only the agent's own ``culture.yaml`` (located by walking up
from the package) and the repo files it points at. When run from a wheel install
(no ``culture.yaml`` alongside the package) it reports a single ``source_checkout``
info check and nothing else — there is nothing to diagnose.
"""

from __future__ import annotations

from convertible.cli._commands.whoami import find_culture_yaml, read_agent_fields
from convertible.oilcheck import make_check

# backend → required prompt file (the backend-consistency mapping).
_PROMPT_FILE = {
    "claude": "CLAUDE.md",
    "acp": "AGENTS.md",
    "gemini": "GEMINI.md",
}


def checks() -> list[dict]:
    """Return the agent-identity checks (see module docstring)."""
    cfg = find_culture_yaml()
    if cfg is None:
        return [
            make_check(
                "source_checkout",
                True,
                "info",
                "no culture.yaml found alongside the package; identity checks skipped",
            )
        ]

    root = cfg.parent
    fields = read_agent_fields()
    backend = fields["backend"]
    out: list[dict] = []

    # 1. backend-consistency: the prompt file for the declared backend exists.
    expected = _PROMPT_FILE.get(backend)
    if expected is None:
        out.append(
            make_check(
                "backend_consistency",
                False,
                "error",
                f"unknown backend '{backend}' in culture.yaml",
                remediation=f"set backend to one of: {', '.join(sorted(_PROMPT_FILE))}",
            )
        )
    else:
        present = (root / expected).is_file()
        out.append(
            make_check(
                "prompt_file_present",
                present,
                "error",
                (
                    f"backend '{backend}' requires {expected} — "
                    + ("present" if present else "missing")
                ),
                remediation="" if present else f"create {expected} at the repo root",
            )
        )

    # 2. skills-present: the vendored skill kit is on disk.
    skills_dir = root / ".claude" / "skills"
    has_skills = skills_dir.is_dir() and any(skills_dir.iterdir())
    out.append(
        make_check(
            "skills_present",
            has_skills,
            "warning",
            (".claude/skills/ vendored" if has_skills else ".claude/skills/ missing or empty"),
            remediation=("" if has_skills else "vendor the skill kit (see docs/skill-sources.md)"),
        )
    )

    return out

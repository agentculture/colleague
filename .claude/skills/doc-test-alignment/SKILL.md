---
name: doc-test-alignment
type: command
description: >
  Verify that committed docs (README.md, CLAUDE.md, SKILL.md descriptions) still
  describe what the code and tests actually do. Use at the end of a plan, before
  PR creation, or when the user says "check doc-test alignment", "verify docs",
  or "do the docs still match the code".
---

# doc-test-alignment

Verifies that committed documentation (README.md, CLAUDE.md, SKILL.md skill
descriptions) and test names still accurately reflect what the code and tests
actually do. The skill runs four independent checks and reports alignment status.

## The four checks

**(a) readme** — README.md command examples. Scans every bash block and validates
each `convertible` / `uv run convertible` invocation. Safe introspection commands
(e.g., `convertible wheels list`, `convertible commands overview`) are executed;
networked/side-effecting commands (e.g., `convertible drive`, `--base-url` flags)
are statically validated against `convertible --help`. Findings are **advisory
(warning)**, never gating.

**(b) claude** — CLAUDE.md "build/test/publish" command examples. Validates
the same way as (a): execute safe introspection, statically validate networked
commands against `convertible --help`. Findings are **advisory (warning)**.

**(c) skills** — SKILL.md descriptions vs. actual scripts. For each
`.claude/skills/<name>/` directory, extracts any `scripts/<path>` literals
from SKILL.md (frontmatter and body), verifies files exist, and checks that
entry-point scripts are executable. This is the **only check that gates CI**
(`severity="error"`); the four-check spine here passes only when (c) is clean.

**(d) tests** — Test name vs. assertion content. Uses an AST heuristic to
flag zero-assertion tests and name/body token drift. Tests can be suppressed
inline with `# doc-test-alignment: ok` or in `.claude/skills/doc-test-alignment/
suppressions.txt`. Findings are **advisory (warning)**, never gating.

## How to run

```bash
bash .claude/skills/doc-test-alignment/scripts/check.sh [OPTIONS]

Options:
  --only readme|claude|skills|tests   Run only the named check(s) (repeatable,
                                      comma-splittable; default: all four).
  --repo PATH                         Repository root (default: walk up from
                                      cwd to find pyproject.toml).
  --json                              Emit aggregate result as JSON.

Exit codes:
  0  aligned (no failed error-severity checks, i.e., check (c) passed)
  1  drift found (at least one error-severity check failed)
  2  usage or operational error
```

JSON output shape (when `--json` is passed):
```json
{
  "aligned": bool,
  "checks": [
    {
      "id": "string",           // e.g. "skills_doc-test-alignment_ok"
      "passed": bool,
      "severity": "info|warning|error",
      "message": "string",
      "remediation": "string"   // optional
    }
  ]
}
```

## Honest limits

**(a)/(b) command introspection** — These checks execute ONLY networkless
introspection subcommands (e.g., `--help`, `overview`, `wheels list`, `doctor`).
Networked or side-effecting commands (anything with `drive`, `--base-url`,
`--model`, or filesystem mutation) are NEVER executed. Instead, they are
statically validated: each command is parsed for its verb and flags, then
validated against `convertible --help` output (verb exists, flag names are valid).
Prose assertions (what the command's output *says*) are checked only via
exit-code hints (`# 0` or `# 1` in adjacent comments); "matches the prose"
means exit-code class, not literal string matching. This means the checks can
detect malformed commands and renamed verbs, but NOT subtle output changes.

**(c) skill descriptions** — Determines "what the script does" by ONLY
inspecting the literal `scripts/<path>` references in SKILL.md; it does NOT
mine natural-language capability claims like "bumps the version". This keeps
false-positives to zero but means it only catches unambiguous file-existence
disagreements. It is **deterministic and gates CI** (the gating check).

**(d) test names** — Uses a tuned token-overlap heuristic between the function
name (split on `_`, stopword-filtered, singularized) and the body's salient
tokens (identifiers in assertions, called function/method names, string-literal
content). Overlap ≥1 matched name tokens passes; below that is flagged. This is
an **advisory check with built-in suppression** (`# doc-test-alignment: ok`
inline, or `suppressions.txt` file entries). In a 1000-test repo, the heuristic
is tuned to be pragmatic; every finding is a warning, never blocking.

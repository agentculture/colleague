Verify that committed docs (README.md, CLAUDE.md, skill descriptions) still describe what the code and tests actually do. Use at the end of a plan, before PR creation, or when the user says "check doc-test alignment", "verify docs", or "do the docs still match the code".

<!-- learned-from: claude; source: .claude/skills/doc-test-alignment/SKILL.md; scripts: .claude/skills/doc-test-alignment/scripts; adapt: claude->colleague -->

# doc-test-alignment

Verifies that committed documentation (README.md, CLAUDE.md, `.colleague/skills/`
skill descriptions) and test names still accurately reflect what the code and
tests actually do. The skill runs four independent checks and reports alignment
status.

## The four checks

**(a) readme** — README.md command examples. Read README.md with `read_file`,
scan every bash block, and validate each `colleague` / `uv run colleague`
invocation. Safe introspection commands (e.g., `colleague wheels list`,
`colleague commands overview`) can be executed via `run_command`;
networked/side-effecting commands (e.g., `colleague drive`, `--base-url` flags)
are statically validated against `run_command "colleague --help"`. Findings are
**advisory (warning)**, never gating.

**(b) claude** — CLAUDE.md "build/test/publish" command examples. Read
CLAUDE.md with `read_file`, validate the same way as (a): execute safe
introspection via `run_command`, statically validate networked commands against
`colleague --help`. Findings are **advisory (warning)**.

**(c) skills** — Skill descriptions vs. actual files. For each
`.colleague/skills/<name>.md` file, extract any file-path or tool references
from the skill doc, verify referenced files exist via `list_dir` and
`read_file`, and check that any scripts mentioned are present. This is the
**only check that gates CI** (`severity="error"`); the four-check spine here
passes only when (c) is clean.

**(d) tests** — Test name vs. assertion content. Read test files with
`read_file`, use an AST heuristic (via `run_command "python -c 'import ast; ...'"`
or inline reasoning) to flag zero-assertion tests and name/body token drift.
Tests can be suppressed inline with `# doc-test-alignment: ok`. Findings are
**advisory (warning)**, never gating.

## How to run

Colleague does not execute skills; follow these steps using your available tools:

1. **Read the docs.** Use `read_file` on `README.md` and `CLAUDE.md`.
2. **Validate commands.** For each `colleague` or `uv run colleague` command
   found in bash blocks, run `run_command "colleague --help"` to get the
   canonical verb/flag list, then check each command's verb and flags against
   it. Execute safe introspection commands directly via `run_command`; skip
   networked/side-effecting ones and note them as statically validated.
3. **Check skill files.** Use `list_dir ".colleague/skills"` to enumerate
   skills, then `read_file` each `.md` to verify any referenced paths or
   scripts actually exist.
4. **Check tests.** Use `read_file` on test files, inspect function names and
   assertion bodies for drift. Flag tests with no assertions or significant
   name/body mismatch.
5. **Report.** Summarise findings as aligned / warning / error.

## Honest limits

**(a)/(b) command introspection** — These checks execute ONLY networkless
introspection subcommands (e.g., `--help`, `overview`, `wheels list`, `doctor`).
Networked or side-effecting commands (anything with `drive`, `--base-url`,
`--model`, or filesystem mutation) are NEVER executed. Instead, they are
statically validated: each command is parsed for its verb and flags, then
validated against `colleague --help` output (verb exists, flag names are valid).
Prose assertions (what the command's output *says*) are checked only via
exit-code hints (`# 0` or `# 1` in adjacent comments); "matches the prose"
means exit-code class, not literal string matching. This means the checks can
detect malformed commands and renamed verbs, but NOT subtle output changes.

**(c) skill descriptions** — Determines "what the skill references" by ONLY
inspecting the literal file-path references in `.colleague/skills/<name>.md`;
it does NOT mine natural-language capability claims. This keeps false-positives
to zero but means it only catches unambiguous file-existence disagreements. It
is **deterministic and gates CI** (the gating check).

**(d) test names** — Uses a tuned token-overlap heuristic between the function
name (split on `_`, stopword-filtered, singularized) and the body's salient
tokens (identifiers in assertions, called function/method names, string-literal
content). Overlap ≥1 matched name tokens passes; below that is flagged. This is
an **advisory check with built-in suppression** (`# doc-test-alignment: ok`
inline). In a large repo, the heuristic is tuned to be pragmatic; every finding
is a warning, never blocking.

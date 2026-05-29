# Build Plan — Convertible only runs the executables you've approved: a declarative policy allow/deny-lists run_command CLIs by name and pins lifecycle hook scripts and command templates to an approved version or checksum, while declarative skills and AGENTS instructions keep loading freely — and with no policy file present, behaviour is byte-identical to today.

slug: `convertible-only-runs-the-executables-you-ve-appro` · status: `exported` · from frame: `convertible-only-runs-the-executables-you-ve-appro`

> Convertible only runs the executables you've approved: a declarative policy allow/deny-lists run_command CLIs by name and pins lifecycle hook scripts and command templates to an approved version or checksum, while declarative skills and AGENTS instructions keep loading freely — and with no policy file present, behaviour is byte-identical to today.

## Tasks

### t1 — Policy core module convertible/policy.py: load .convertible/<policy>.json (repo+user via configdir, per-model overlay via layers.sanitize_model, exact-path isolation); data model for run_command allow/deny + hooks/commands content-approvals; check functions (shlex program-token gate; hashlib checksum verify, algo-prefixed sha256-default + md5; version match). Stdlib only.

- covers: c10, h3, c11, h4, c13, h6, c16, h9, c23, h10, c4, h16
- acceptance:
  - with no policy file present, the loader returns an empty policy and all check functions are pass-through no-ops (byte-identical behavior)
  - checksum verification uses hashlib over file bytes; values are algorithm-prefixed ('sha256:<hex>' default, 'md5:<hex>' honored); a changed file fails to match
  - run_command check: shlex extracts the program token; allow-list denies a token not listed, deny-list blocks a listed token
  - per-model overlay path built by exact construction via layers.sanitize_model; a test proves model X never loads model Y's policy (no sibling glob)
  - module imports stdlib only (json/shlex/hashlib/pathlib); no third-party import

### t2 — run_command name-gate enforcement in convertible/loop.py: in the pre_tool control path, extract the program token (shlex) of a run_command call and consult the policy; a denied token skips execution, feeds the reason back as the tool result, and is recorded as a non-ok Step (mirrors the pre_tool deny path).

- depends on: t1
- covers: c25, h12, c15, h8, c9, h2
- acceptance:
  - a run_command whose program token is denied is not executed; the reason is fed back as the tool result and recorded as a non-ok Step; the drive continues
  - behavior is identical on mock and vllm-openai for the same policy (all-engines rule); no engine module imports the policy
  - with no run_command section in the policy, run_command is ungated (strict no-op)

### t3 — Hook approval enforcement in convertible/hooks.py: consult the policy when loading/firing hooks; a hook whose referenced script's checksum/version does not match its approval is denied (skipped) and recorded; chassis-owned.

- depends on: t1
- covers: c11, h4, c25, c23
- acceptance:
  - an approved hook fires; a hook whose referenced script is tampered/unapproved is denied (skipped) and recorded; with no hooks-approval section all hooks fire as today
  - the approval check is consulted in the chassis hook path; no engine module touches it

### t4 — Command-template approval enforcement in convertible/commands.py: expand_command consults the policy and refuses (CliError) a template whose checksum/version does not match its approval, before expansion / before the drive starts.

- depends on: t1
- covers: c11, c25, h12, c23
- acceptance:
  - an approved command template expands; a drifted/unapproved template is refused with a CliError at expand time, before any engine runs
  - with no commands-approval section, templates expand exactly as today (strict no-op)

### t5 — CLI surface on existing nouns: add 'approve <name>' write-verb to the commands + hooks nouns (records a version/checksum approval into the policy file); extend commands/hooks/skills 'list' with approval+accessibility status; 'hooks list' also shows the run_command allow/deny policy; add an explain catalog entry for 'approve'.

- depends on: t1
- covers: c26, h13
- acceptance:
  - 'commands approve <name>' and 'hooks approve <name>' write a version/checksum approval into the policy file
  - 'commands|hooks|skills list' shows approval/accessibility status; 'hooks list' also shows run_command allow/deny
  - every verb supports --json, failures raise CliError, each noun retains 'overview', an 'explain' entry exists for 'approve'; teken cli doctor . --strict stays green

### t6 — Declarative carve-out test (tests/): assert skills + AGENTS still load and fold into the system prompt while a policy is active, and that the gate code path is never reached for declarative config (resolve_skills/resolve_agents unchanged).

- depends on: t1
- covers: c12, h5
- acceptance:
  - with a policy active, resolve_skills and resolve_agents are unchanged and skills + AGENTS still fold into the system prompt; the gate code path is never reached for declarative config

### t7 — Cross-cutting guards (tests/): e2e shape no-op + zero-deps + all-engines deny parity. Update tests/test_e2e_mock.py (no-policy byte-identical) and tests/test_zero_deps.py (import the policy module, assert no third-party leak); add an all-engines parity test (mock + vllm-openai identical run_command + hook denials for the same policy).

- depends on: t2, t3, t4
- covers: c9, h2, c16, h9, c1, h11, c7, h19, c2, h14, c25, h12
- acceptance:
  - e2e shape: with no policy file the JSON artifact is byte-identical to a policy-free run
  - zero-deps guard imports the new policy module and asserts no third-party import leak, even with the [otel] extra installed
  - all-engines parity: mock and vllm-openai produce identical run_command + hook denials for the same policy
  - announcement honesty: with a policy an unapproved/tampered CLI or hook is refused and recorded, skills+AGENTS still load, and no-policy changes nothing

### t8 — Documentation (README.md + CLAUDE.md): document the approval gate, the policy-file shape, the new noun verbs, and the honest limits; align the before->after framing with what ships.

- depends on: t5
- covers: c3, h15, c5, h17, c6, h18, c4
- acceptance:
  - README + CLAUDE.md document the approval gate, the policy-file shape, and the new noun verbs (commands/hooks approve, list status)
  - honest limits documented: policy gate not a sandbox (bypassable by sh -c/pipes), md5 = accidental-drift-only, no daemon/socket/runtime-dep/MCP
  - the before->after framing in docs matches what ships

### t9 — Version bump + CHANGELOG (pyproject.toml + convertible/__init__.py + CHANGELOG.md): minor bump for the new feature, Keep-a-Changelog entry (satisfies the version-check CI gate before PR).

- depends on: t8
- acceptance:
  - version bumped (minor) in pyproject.toml and convertible/__init__.py; CHANGELOG.md gets a Keep-a-Changelog entry; the version-check CI job passes

## Risks

- [unknown_nonblocking] What exactly is hashed for a hook? hooks.json entries are shell command strings; the spec config example keys hooks by a script filename (lint.sh), implying the referenced script *file* is checksummed. Inline hooks (echo done) have no file. Build decision: checksum the referenced repo-relative script file; inline/no-file hooks fall back to command-string hashing or name-only. (task t3)
- [unknown_nonblocking] Version-pinning needs a version source: command templates have no 'version:' frontmatter key today (commands.py metadata = description/engine/constraints/arg-hint), and hooks have none either. Build decision: ship checksum-only for v0 with 'version:' as a documented follow-up, OR add a version metadata key. (task t4)
- [unknown_nonblocking] Concrete policy filename/location under .convertible/ (spec uses a generic <policy>.json placeholder): pick the filename in build (e.g. approvals.json), composed via configdir (repo+user) and layers (per-model overlay), consistent with hooks.json. (task t1)

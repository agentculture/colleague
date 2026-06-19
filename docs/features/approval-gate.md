# approval-gate — colleague only runs the executables you've approved

> An operator-declared allow-list (`.colleague/approvals.json`) controls what the
> harness *executes*: `run_command` CLIs by program token, and hook/command
> template files by content checksum. Absent or malformed config is a strict
> no-op — byte-identical to pre-gate behavior.

The approval gate (`colleague/policy.py`) is the landed increment of the planned
per-repo hook trust gate. It is a **policy gate, not a sandbox** — read the
honest limits below before relying on it.

## Where the policy lives

`.colleague/approvals.json` (repo-level, resolved via `configdir`). A per-model
overlay at `.colleague/<sanitized-model>/approvals.json` is composed ahead via
exact-path construction (no sibling globbing).

## Three gated categories (each opt-in via presence of its section)

- **`run_command`** — gates CLI invocations by program token (the `shlex` first
  token). Allow/deny lists; an absent section is a strict no-op.
- **`hooks`** — gates lifecycle hook script files by content checksum. A section
  present but listing no entry is **still a gate** (allow-list semantics:
  unlisted = denied).
- **`commands`** — gates command-template files by content checksum at
  expansion time.

Skills and AGENTS instructions are **never gated** — they are declarative and
load freely.

## Checksums

Approval values are algorithm-prefixed strings: `"sha256:<hex>"` (default) or
`"md5:<hex>"` (honored). `approve` records the file's current checksum; a
subsequent content change voids the approval (checksum mismatch → denied).

```bash
colleague hooks approve <script> --repo .       # record a hook-script checksum
colleague commands approve <name> --repo .      # record a command-template checksum
# both accept --algo sha256|md5 (default sha256) and --json
```

## Where it is consulted (runtime-owned, all-engines)

`load_policy(task.repo_path, model=model)` is loaded once in `colleague/loop.py`
and consulted at `_deny_by_policy` (for `run_command`) and `_fire_hooks` (for
hook scripts before they run); `colleague/commands.py` consults it at template
expansion. No backend module touches `policy.py`.

## Honest limits

- **Not a sandbox.** The token check is bypassable by `sh -c`, pipelines, and
  shell expansion.
- `md5` detects accidental drift, not a malicious editor — use `sha256` for
  integrity.
- **Checksum-only in v0.** `version` pinning is a documented follow-up, **not
  built** — do not document it as existing.
- There is still **no `--no-hooks` flag** (see [hooks.md](hooks.md)).

## Key files

- `colleague/policy.py` — load + the gate checks.
- `colleague/loop.py` — `_deny_by_policy`, `_fire_hooks`.

## Spec + plan

- [`docs/specs/2026-05-29-convertible-only-runs-the-executables-you-ve-appro.md`](../specs/2026-05-29-convertible-only-runs-the-executables-you-ve-appro.md)
  (historical specs keep the pre-rename `convertible` name)
- [`docs/plans/2026-05-29-convertible-only-runs-the-executables-you-ve-appro.md`](../plans/2026-05-29-convertible-only-runs-the-executables-you-ve-appro.md)
